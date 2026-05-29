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
)
from apps.tenants.permissions import P


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
