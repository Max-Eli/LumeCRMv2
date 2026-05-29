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
    ChargeRefusedError,
    RefundRefusedError,
    StripeAPIError,
    StripeNotConfigured,
    create_onboarding_link,
    create_payment_intent_for_invoice,
    ensure_merchant_account,
    is_configured,
    refresh_account_status,
    refund_charge,
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


# ── Charge card flow (invoice page + customer portal) ──────────────


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def charge_invoice_card(request: Request, invoice_id: int) -> Response:
    """Create a PaymentIntent for the operator to confirm via Stripe Elements.

    Body: ``{amount_cents: int}``. Amount is validated client-side
    against ``invoice.amount_due_cents``; the backend re-validates as
    "must be positive" — if the operator tries to charge more than
    due, Stripe will succeed (over-payment is legal) but the spa is
    on the hook for refunding the difference. Operator UI prevents
    this; we trust it here.

    Returns ``{charge_id, client_secret, publishable_key}``. The
    frontend uses ``client_secret`` with Stripe Elements to mount the
    Payment Element + confirm. Final status flips via the
    payment_intent.* webhook (not the synchronous response).

    Permission: PROCESS_PAYMENT (front-desk default).
    """
    from apps.invoices.models import Invoice
    from django.conf import settings as dj_settings

    membership = getattr(request, 'tenant_membership', None)
    if not membership or not membership.has(P.PROCESS_PAYMENT):
        return Response(
            {'detail': 'Process Payment permission required.'},
            status=status.HTTP_403_FORBIDDEN,
        )

    try:
        invoice = Invoice.objects.get(
            pk=invoice_id, tenant=membership.tenant,
        )
    except Invoice.DoesNotExist:
        return Response(
            {'detail': 'Invoice not found.'},
            status=status.HTTP_404_NOT_FOUND,
        )

    if invoice.status != Invoice.Status.OPEN:
        return Response(
            {
                'detail': f'Cannot charge a {invoice.status} invoice.',
                'code': 'invoice_not_open',
            },
            status=status.HTTP_409_CONFLICT,
        )

    raw_amount = request.data.get('amount_cents')
    try:
        amount_cents = int(raw_amount)
    except (TypeError, ValueError):
        return Response(
            {'detail': 'amount_cents must be an integer.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if not is_configured():
        return Response(
            {
                'detail': (
                    'Stripe is not configured in this environment. '
                    'Cannot take card payments.'
                ),
                'code': 'stripe_not_configured',
            },
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    try:
        charge, client_secret = create_payment_intent_for_invoice(
            invoice=invoice,
            amount_cents=amount_cents,
            operator=request.user,
            initiated_via='operator',
        )
    except ChargeRefusedError as e:
        return Response(
            {'detail': str(e), 'code': 'charge_refused'},
            status=status.HTTP_409_CONFLICT,
        )
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

    return Response({
        'charge_id': charge.pk,
        'client_secret': client_secret,
        # Frontend Stripe Elements needs the publishable key to
        # initialize. Echo it back so the client doesn't have to
        # store it separately + risk a stale value when keys rotate.
        'publishable_key': getattr(dj_settings, 'STRIPE_PUBLISHABLE_KEY', ''),
        # Stripe Elements needs the connected account ID to mount
        # against the right Stripe account.
        'stripe_account_id': charge.merchant_account.stripe_account_id,
    }, status=status.HTTP_201_CREATED)


# ── Refund flow ────────────────────────────────────────────────────


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def refund_card_charge(request: Request, charge_id: int) -> Response:
    """Issue a Stripe refund + persist a local Refund row.

    Body: ``{amount_cents: int, reason: str}``. Amount must be > 0
    and <= the charge's remaining refundable balance. Reason is
    operator-typed (mostly for the audit log + Stripe metadata; not
    surfaced to the customer).

    Permission: ISSUE_REFUND (front-desk default within limit;
    ISSUE_REFUND_UNLIMITED for manager+). We don't enforce the
    front-desk dollar limit here at the API layer — that's a
    follow-up. For v1, any holder of ISSUE_REFUND can issue any
    amount within the charge's refundable balance.
    """
    from apps.payments.models import Charge

    membership = getattr(request, 'tenant_membership', None)
    if not membership or not membership.has(P.ISSUE_REFUND):
        return Response(
            {'detail': 'Issue Refund permission required.'},
            status=status.HTTP_403_FORBIDDEN,
        )

    try:
        charge = Charge.objects.select_related('merchant_account', 'tenant').get(
            pk=charge_id, tenant=membership.tenant,
        )
    except Charge.DoesNotExist:
        return Response(
            {'detail': 'Charge not found.'},
            status=status.HTTP_404_NOT_FOUND,
        )

    raw_amount = request.data.get('amount_cents')
    try:
        amount_cents = int(raw_amount)
    except (TypeError, ValueError):
        return Response(
            {'detail': 'amount_cents must be an integer.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    reason = (request.data.get('reason') or '').strip()
    if not reason:
        return Response(
            {'detail': 'A reason is required for every refund (audit trail).'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if len(reason) > 255:
        return Response(
            {'detail': 'Reason cannot exceed 255 characters.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if not is_configured():
        return Response(
            {
                'detail': (
                    'Stripe is not configured in this environment. '
                    'Cannot issue card refunds.'
                ),
                'code': 'stripe_not_configured',
            },
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    try:
        refund = refund_charge(
            charge=charge,
            amount_cents=amount_cents,
            reason=reason,
            operator=request.user,
        )
    except RefundRefusedError as e:
        return Response(
            {'detail': str(e), 'code': 'refund_refused'},
            status=status.HTTP_409_CONFLICT,
        )
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

    return Response({
        'refund_id': refund.pk,
        'status': refund.status,
        'amount_cents': refund.amount_cents,
        'charge_refunded_cents': charge.refunded_cents,
    }, status=status.HTTP_201_CREATED)
