"""Stripe Connect webhook receiver.

Distinct from the Billing webhook (``apps.billing.webhooks``) by
design — same Stripe account but different webhook endpoints in the
Stripe dashboard, different signing secrets. Mixing them on one
endpoint would couple their failure modes; isolating them lets us
fix one without restarting the other.

Events handled this chunk (account-lifecycle only):
  - ``account.updated`` → sync charges_enabled / payouts_enabled /
    details_submitted onto MerchantAccount.
  - ``account.application.deauthorized`` → spa disconnected the
    application from their Stripe account; mark disabled_at.

Events handled in the next chunk (payment-flow):
  - ``payment_intent.succeeded`` → create Charge row, mark invoice paid
  - ``payment_intent.payment_failed`` → log + surface to operator
  - ``charge.refunded`` → ensure Refund row exists (idempotency)
"""

from __future__ import annotations

import datetime as dt
import logging

from django.conf import settings
from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.payments.models import MerchantAccount
from apps.payments.services import (
    StripeAPIError,
    sync_charge_from_payment_intent,
    sync_from_stripe_account,
    sync_refund_from_stripe,
)

logger = logging.getLogger(__name__)


@csrf_exempt
@require_POST
def stripe_connect_webhook(request: HttpRequest) -> JsonResponse:
    """Handle Stripe-signed Connect webhook deliveries.

    Same status-code conventions as the billing webhook:
      200 — processed
      400 — bad payload / bad signature
      503 — STRIPE_CONNECT_WEBHOOK_SECRET not configured
      500 — unexpected error (triggers Stripe retry)

    The signature header for Connect events is ``Stripe-Signature``
    (same name as Billing, but verified against a different secret).
    """
    secret = getattr(settings, 'STRIPE_CONNECT_WEBHOOK_SECRET', '') or ''
    if not secret:
        logger.warning(
            'Stripe Connect webhook received but '
            'STRIPE_CONNECT_WEBHOOK_SECRET is empty; rejecting.'
        )
        return JsonResponse(
            {'detail': 'Connect webhook receiver not configured.'},
            status=503,
        )

    payload = request.body
    sig_header = request.headers.get('Stripe-Signature', '')

    try:
        import stripe
    except ImportError:
        logger.exception('stripe SDK not installed; cannot process Connect webhook')
        return JsonResponse({'detail': 'Stripe SDK not installed.'}, status=503)

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, secret)
    except ValueError:
        logger.warning('Connect webhook payload is malformed JSON')
        return JsonResponse({'detail': 'Invalid payload.'}, status=400)
    except stripe.error.SignatureVerificationError:
        logger.warning(
            'Connect webhook signature verification failed (sig: %s)',
            sig_header[:40],
        )
        return JsonResponse({'detail': 'Invalid signature.'}, status=400)

    event_type = event.get('type', '')
    data_object = event.get('data', {}).get('object', {})
    logger.info(
        'Stripe Connect webhook received: type=%s id=%s',
        event_type, event.get('id'),
    )

    try:
        if event_type == 'account.updated':
            sync_from_stripe_account(data_object)
        elif event_type == 'account.application.deauthorized':
            _handle_deauthorization(data_object)
        # ── Payment flow events ──────────────────────────────────
        # These arrive on the SAME Connect webhook endpoint because
        # we use direct charges on the connected account; Stripe
        # routes them to the platform's Connect endpoint by default.
        elif event_type in {
            'payment_intent.succeeded',
            'payment_intent.payment_failed',
            'payment_intent.canceled',
        }:
            sync_charge_from_payment_intent(data_object)
        elif event_type in {
            'charge.refunded',
            # Modern Stripe also emits refund.* events for
            # finer-grained status updates (esp. ACH refunds that
            # settle days later). Both event shapes carry the refund
            # object as data.object, so sync_refund_from_stripe
            # handles them identically.
            'refund.created',
            'refund.updated',
        }:
            # charge.refunded's data.object is the Charge (with
            # refunds.data inside); refund.* events have the Refund
            # itself. Normalize to the Refund(s) before syncing.
            for refund_obj in _refunds_from_event(event_type, data_object):
                sync_refund_from_stripe(refund_obj)
        else:
            logger.info('Connect webhook unhandled: %s', event_type)
    except StripeAPIError as e:
        # Predictable sync issue — log + 200 so Stripe doesn't retry.
        logger.exception('Connect webhook sync failed: %s', e)
        return JsonResponse(
            {'detail': 'Sync failed; logged for ops.'},
            status=200,
        )
    except Exception:  # noqa: BLE001 — webhook errors must not 500
        logger.exception('Connect webhook processing crashed')
        return JsonResponse(
            {'detail': 'Internal error processing webhook.'},
            status=500,
        )

    return JsonResponse({'received': True}, status=200)


def _refunds_from_event(event_type: str, data_object):
    """Normalize charge.refunded vs refund.* event shapes into an
    iterable of Refund-shaped objects.

    ``charge.refunded`` data.object is a Charge with a nested
    ``refunds.data`` list (Stripe sends the latest snapshot of all
    refunds against that charge). ``refund.*`` data.object IS the
    Refund itself. We yield Refund objects in both cases so the
    caller can sync uniformly.
    """
    if event_type in {'refund.created', 'refund.updated'}:
        yield data_object
        return
    # charge.refunded path:
    refunds = getattr(data_object, 'refunds', None)
    if refunds is None and isinstance(data_object, dict):
        refunds = data_object.get('refunds')
    data = getattr(refunds, 'data', None) if refunds else None
    if data is None and isinstance(refunds, dict):
        data = refunds.get('data')
    yield from (data or [])


def _handle_deauthorization(data_object) -> None:
    """A spa disconnected the Lumè application from their Stripe
    account (via Stripe's own dashboard). Mark the MerchantAccount as
    disabled so the UI hides the "Charge card" button + prompts the
    spa to reconnect.

    The data object on this event is the Connected Account itself
    (not an Application object). It has the account ID we use to
    look up our local row.
    """
    account_id = getattr(data_object, 'id', None) or data_object.get('id')
    if not account_id:
        logger.warning('Deauthorization event has no account id')
        return

    try:
        account = MerchantAccount.objects.get(stripe_account_id=account_id)
    except MerchantAccount.DoesNotExist:
        # Could happen if a Stripe-side dashboard test triggered this
        # for an account we never created. Safe to ignore.
        logger.info(
            'Deauthorization for unknown account_id=%s; nothing to do.',
            account_id,
        )
        return

    account.disabled_at = dt.datetime.now(tz=dt.timezone.utc)
    account.charges_enabled = False
    account.payouts_enabled = False
    account.save(update_fields=[
        'disabled_at', 'charges_enabled', 'payouts_enabled', 'updated_at',
    ])
    logger.info(
        'Marked MerchantAccount for tenant %s as deauthorized.',
        account.tenant_id,
    )
