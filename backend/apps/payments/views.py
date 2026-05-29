"""Payments endpoints — Stripe Connect onboarding + status.

This first chunk of Phase 2 ships only the connect-account flow:
  - GET /api/payments/summary/ — connect status for /org/payments
  - POST /api/payments/onboarding-link/ — start (or continue) the
    Stripe-hosted onboarding flow

The charge-card + refund endpoints land in the next chunk along
with the Charge / Refund models.

Permission: ``MANAGE_BILLING`` (owner-only, locked against per-user
override). Same gate as the SaaS billing endpoints — taking payments
is a billing-adjacent operation, not a front-desk operation.
"""

from __future__ import annotations

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.payments.services import (
    StripeAPIError,
    StripeNotConfigured,
    create_onboarding_link,
    ensure_merchant_account,
    is_configured,
    refresh_account_status,
)
from apps.tenants.permissions import P


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def payments_summary(request: Request) -> Response:
    """Connect status snapshot for /org/payments.

    Always returns useful data — even for grandfathered tenants or
    when Stripe Connect isn't configured in the environment. The
    frontend uses the flags to decide which UI state to render
    (connect button, in-progress banner, ready-to-charge confirmation).

    Optional query param ?refresh=1 forces a pull from Stripe before
    returning. Used by the manual "Refresh status" button on the
    settings page. Without it we serve the locally-mirrored state
    (which the webhook keeps current).
    """
    membership = getattr(request, 'tenant_membership', None)
    if not membership or not membership.has(P.MANAGE_BILLING):
        return Response(
            {'detail': 'Manage Billing permission required.'},
            status=status.HTTP_403_FORBIDDEN,
        )

    tenant = membership.tenant

    if request.query_params.get('refresh') == '1' and is_configured():
        try:
            account = refresh_account_status(tenant)
        except (StripeAPIError, StripeNotConfigured):
            # Fall through to the locally-stored state on a refresh
            # failure — the operator still sees something useful even
            # when Stripe is down or the secret isn't set.
            account = ensure_merchant_account(tenant)
    else:
        account = ensure_merchant_account(tenant)

    return Response({
        'provider': account.provider,
        'stripe_account_id': account.stripe_account_id or '',
        'charges_enabled': account.charges_enabled,
        'payouts_enabled': account.payouts_enabled,
        'details_submitted': account.details_submitted,
        'connected_at': (
            account.connected_at.isoformat() if account.connected_at else None
        ),
        'disabled_at': (
            account.disabled_at.isoformat() if account.disabled_at else None
        ),
        'is_ready_to_charge': account.is_ready_to_charge,
        # Flags the frontend reads to enable/disable controls + show
        # the right copy. `stripe_configured` is the platform-wide
        # check (any STRIPE_SECRET_KEY at all); `connect_ready_to_use`
        # composes that with the account-level readiness flags so the
        # UI has a single "show the Charge button" predicate.
        'stripe_configured': is_configured(),
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def payments_onboarding_link(request: Request) -> Response:
    """Generate (or regenerate) the Stripe-hosted onboarding URL.

    The frontend redirects the spa to the returned URL. Stripe
    collects business details + bank account + KYC, then redirects
    back to the configured return URL on /org/payments.

    AccountLinks are single-use and expire quickly — always call
    this fresh per click, never cache.
    """
    membership = getattr(request, 'tenant_membership', None)
    if not membership or not membership.has(P.MANAGE_BILLING):
        return Response(
            {'detail': 'Manage Billing permission required.'},
            status=status.HTTP_403_FORBIDDEN,
        )

    tenant = membership.tenant
    if not is_configured():
        return Response(
            {
                'detail': (
                    'Stripe is not configured in this environment. '
                    'Cannot start Connect onboarding.'
                ),
                'code': 'stripe_not_configured',
            },
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    try:
        url = create_onboarding_link(tenant)
    except StripeNotConfigured as e:
        return Response(
            {'detail': str(e), 'code': 'stripe_not_configured'},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    except StripeAPIError as e:
        return Response(
            {'detail': str(e), 'code': 'stripe_error'},
            status=status.HTTP_502_BAD_GATEWAY,
        )

    return Response({'url': url})
