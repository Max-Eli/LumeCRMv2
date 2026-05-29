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
    sync_from_stripe_account,
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
