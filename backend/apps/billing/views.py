"""Billing endpoints exposed to the CRM frontend.

Just one endpoint for now: ``portal-session`` opens the Stripe-hosted
billing portal so the owner can update their card, view invoices, or
cancel. Self-serve plan change is intentionally NOT supported through
the portal — upgrades flow through /settings/billing in the CRM (with
a sales conversation gating Pro/Enterprise).

Add-on quantity changes will get their own endpoints in Phase 1e
(/settings/billing UI), routed through this app's services.
"""

from __future__ import annotations

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.billing.services import (
    StripeBillingError,
    StripeNotConfigured,
    create_portal_session,
    is_configured,
    set_addon_quantity,
)
from apps.tenants.permissions import P
from apps.tenants.plans import (
    allowed_addons_for_plan,
    effective_max_locations,
    effective_max_staff,
    effective_monthly_email_quota,
    effective_monthly_sms_quota,
    is_addon_quantity_valid,
)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def stripe_portal_session(request: Request) -> Response:
    """Create a Stripe-hosted billing portal session + return its URL.

    Caller must hold ``MANAGE_BILLING`` (owner-only by default — locked
    against per-user override per the existing permission catalog).
    Grandfathered tenants get a clear 409 explaining they're not
    enrolled in Stripe Billing.
    """
    membership = getattr(request, 'tenant_membership', None)
    if not membership or not membership.has(P.MANAGE_BILLING):
        return Response(
            {'detail': 'Manage Billing permission required.'},
            status=status.HTTP_403_FORBIDDEN,
        )

    tenant = membership.tenant

    if tenant.grandfathered:
        return Response(
            {
                'detail': (
                    'This account is on a legacy plan and isn\'t '
                    'managed through self-serve billing. Contact '
                    'support@lume-crm.com to make billing changes.'
                ),
                'code': 'grandfathered_no_self_serve_billing',
            },
            status=status.HTTP_409_CONFLICT,
        )

    if not is_configured():
        return Response(
            {
                'detail': (
                    'Stripe billing is not configured in this '
                    'environment. Set STRIPE_SECRET_KEY before '
                    'opening the billing portal.'
                ),
                'code': 'stripe_not_configured',
            },
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    return_url = request.data.get('return_url') or _default_return_url(tenant)

    try:
        portal_url = create_portal_session(tenant, return_url=return_url)
    except StripeNotConfigured as e:
        return Response(
            {'detail': str(e), 'code': 'stripe_not_configured'},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    except StripeBillingError as e:
        return Response(
            {'detail': str(e), 'code': 'stripe_error'},
            status=status.HTTP_502_BAD_GATEWAY,
        )

    return Response({'url': portal_url})


def _default_return_url(tenant) -> str:
    """Where Stripe sends the customer back after they close the
    billing portal. The frontend can override via ``return_url`` in
    the POST body."""
    from django.conf import settings as dj_settings
    base = getattr(dj_settings, 'PUBLIC_BASE_URL', 'http://localhost:3000')
    # Strip trailing slash so we don't end up with `//settings`.
    return f"{base.rstrip('/')}/settings/billing"


# ── Billing summary (drives /settings/billing) ──────────────────


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def billing_summary(request: Request) -> Response:
    """The billing snapshot that drives /settings/billing.

    Readable by any owner/manager (they see their own tenant's plan +
    add-ons + usage). The endpoint never requires Stripe to be
    configured — even grandfathered tenants need to see "you're on
    Pro, contact support for billing changes" rather than a stack
    trace. Stripe-side details (subscription_id) are emitted only
    when present.
    """
    membership = getattr(request, 'tenant_membership', None)
    if not membership or not membership.has(P.MANAGE_BILLING):
        return Response(
            {'detail': 'Manage Billing permission required.'},
            status=status.HTTP_403_FORBIDDEN,
        )

    tenant = membership.tenant
    # Live counts of what they're using against their caps.
    from apps.tenants.models import Location, TenantMembership
    staff_count = (
        TenantMembership.objects
        .filter(tenant=tenant, is_active=True).count()
    )
    location_count = Location.objects.filter(tenant=tenant, is_active=True).count()

    return Response({
        'plan': tenant.plan,
        'billing_cycle': tenant.billing_cycle,
        'status': tenant.status,
        'grandfathered': tenant.grandfathered,
        'trial_ends_at': (
            tenant.trial_ends_at.isoformat() if tenant.trial_ends_at else None
        ),
        'current_period_end': (
            tenant.current_period_end.isoformat()
            if tenant.current_period_end else None
        ),
        'billing_email': tenant.billing_email or '',
        # Capacity = plan baseline + add-ons. None means "unlimited"
        # (grandfathered or enterprise). The frontend treats null as
        # "no cap — show ∞".
        'capacity': {
            'max_staff': effective_max_staff(tenant),
            'max_locations': effective_max_locations(tenant),
            'sms_quota': effective_monthly_sms_quota(tenant),
            'email_quota': effective_monthly_email_quota(tenant),
        },
        'usage': {
            'staff_count': staff_count,
            'location_count': location_count,
            'sms_used': tenant.current_period_sms_count,
            'email_used': tenant.current_period_email_count,
        },
        # Current add-on quantities. Keyed by addon identifier; values
        # are integers. Empty dict if no add-ons purchased.
        'addons': tenant.addon_quantities or {},
        # Add-ons the tenant's plan is allowed to buy. The frontend
        # renders one row of controls per allowed addon. Grandfathered
        # tenants get an empty allowed list — they can't self-serve
        # add-ons (call support).
        'allowed_addons': (
            allowed_addons_for_plan(tenant.plan)
            if not tenant.grandfathered else {}
        ),
        # Frontend uses this to decide whether to enable the "Open
        # billing portal" button + the addon quantity buttons.
        'stripe_configured': is_configured(),
        'has_stripe_subscription': bool(tenant.stripe_subscription_id),
    })


# ── Update add-on quantity ──────────────────────────────────────


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def update_addon_quantity(request: Request) -> Response:
    """Owner-only endpoint to set the quantity of a single add-on on
    the tenant's subscription.

    Validates the (plan, addon_key, quantity) combination against the
    catalog, then talks to Stripe. The local ``addon_quantities`` row
    is updated optimistically inside ``set_addon_quantity``; the
    next webhook reconciles authoritative state.
    """
    membership = getattr(request, 'tenant_membership', None)
    if not membership or not membership.has(P.MANAGE_BILLING):
        return Response(
            {'detail': 'Manage Billing permission required.'},
            status=status.HTTP_403_FORBIDDEN,
        )

    tenant = membership.tenant
    if tenant.grandfathered:
        return Response(
            {
                'detail': (
                    'Add-on quantities for legacy accounts are managed '
                    'by support. Contact support@lume-crm.com.'
                ),
                'code': 'grandfathered_no_self_serve_billing',
            },
            status=status.HTTP_409_CONFLICT,
        )

    addon_key = request.data.get('addon_key')
    raw_qty = request.data.get('quantity')
    if not isinstance(addon_key, str) or not addon_key:
        return Response(
            {'detail': 'addon_key is required.'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    try:
        quantity = int(raw_qty)
    except (TypeError, ValueError):
        return Response(
            {'detail': 'quantity must be an integer.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    ok, err = is_addon_quantity_valid(tenant.plan, addon_key, quantity)
    if not ok:
        return Response(
            {'detail': err, 'code': 'invalid_addon_request'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if not is_configured():
        return Response(
            {
                'detail': (
                    'Stripe billing is not configured in this '
                    'environment. Cannot change add-ons.'
                ),
                'code': 'stripe_not_configured',
            },
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    try:
        set_addon_quantity(tenant, addon_key=addon_key, quantity=quantity)
    except StripeNotConfigured as e:
        return Response(
            {'detail': str(e), 'code': 'stripe_not_configured'},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    except StripeBillingError as e:
        return Response(
            {'detail': str(e), 'code': 'stripe_error'},
            status=status.HTTP_502_BAD_GATEWAY,
        )

    return Response({
        'addon_key': addon_key,
        'quantity': quantity,
        'addons': tenant.addon_quantities,
    })
