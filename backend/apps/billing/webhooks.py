"""Stripe webhook receiver for SaaS billing events.

Receives POSTs from Stripe at ``/api/billing/stripe-webhook/`` after
we register the endpoint URL in the Stripe Dashboard. Stripe signs
every request with a header derived from the endpoint's signing
secret; we MUST verify that signature before trusting the payload —
the public webhook URL is otherwise unauthenticated.

Event routing:

  - ``customer.subscription.updated`` → ``sync_from_stripe`` reconciles
    plan / status / period end / add-on quantities. The most important
    event — fires on trial end, plan change, add-on quantity change,
    payment success, and renewal.
  - ``customer.subscription.deleted`` → ``sync_from_stripe`` sets the
    local status to CANCELLED.
  - ``invoice.payment_failed`` → status → PAST_DUE. We rely on the
    next ``subscription.updated`` to handle the recovery transition;
    this event just kicks off the dunning email (Phase 4 work).
  - ``customer.subscription.trial_will_end`` → fire the 3-day trial
    reminder email (Phase 4 work — for now we just log).

Idempotency: Stripe retries failed deliveries with the same event ID.
We don't dedupe here because ``sync_from_stripe`` is itself idempotent
(reading the latest state from Stripe and re-writing it is safe). If
we add side effects that aren't idempotent (firing an email twice),
we'll add an ``ProcessedStripeEvent`` model + uniqueness check.

Auth: this endpoint is unauthenticated by design. The signature
verification IS the auth.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.billing.services import StripeBillingError, sync_from_stripe

logger = logging.getLogger(__name__)


@csrf_exempt
@require_POST
def stripe_webhook(request: HttpRequest) -> JsonResponse:
    """Handle Stripe-signed webhook deliveries.

    Returns 200 on successful processing; 400 on bad payload / bad
    signature; 503 when Stripe isn't configured (test mode etc.); 500
    on internal error (which will trigger a Stripe retry).
    """
    secret = getattr(settings, 'STRIPE_WEBHOOK_SECRET', '') or ''
    if not secret:
        # We received a webhook but we have no signing secret. This is
        # safer to log + drop than to attempt a no-signature parse.
        logger.warning(
            'Stripe webhook received but STRIPE_WEBHOOK_SECRET is empty; '
            'rejecting. Configure the webhook secret in env vars.'
        )
        return JsonResponse(
            {'detail': 'Webhook receiver not configured.'},
            status=503,
        )

    payload = request.body
    sig_header = request.headers.get('Stripe-Signature', '')

    try:
        import stripe
    except ImportError:
        logger.exception('stripe SDK not installed; cannot process webhook')
        return JsonResponse(
            {'detail': 'Stripe SDK not installed.'},
            status=503,
        )

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, secret,
        )
    except ValueError:
        # Malformed payload (not JSON, etc.). Don't reveal details.
        logger.warning('Stripe webhook payload is malformed JSON')
        return JsonResponse({'detail': 'Invalid payload.'}, status=400)
    except stripe.error.SignatureVerificationError:
        logger.warning(
            'Stripe webhook signature verification failed (signature: %s)',
            sig_header[:40],
        )
        return JsonResponse({'detail': 'Invalid signature.'}, status=400)

    event_type = event.get('type', '')
    data_object = event.get('data', {}).get('object', {})
    logger.info(
        'Stripe webhook received: type=%s id=%s', event_type, event.get('id'),
    )

    try:
        if event_type in {
            'customer.subscription.created',
            'customer.subscription.updated',
            'customer.subscription.deleted',
        }:
            sync_from_stripe(data_object)

        elif event_type == 'invoice.payment_failed':
            # The subscription side fires its own .updated event with
            # status='past_due'; we just log here. Phase 4 lands the
            # dunning email.
            logger.info(
                'invoice.payment_failed for subscription %s — '
                'dunning email handled in Phase 4',
                data_object.get('subscription'),
            )

        elif event_type == 'customer.subscription.trial_will_end':
            # Stripe fires this 3 days before trial end. Phase 4 will
            # send the reminder email; for now log so we can confirm
            # it's arriving.
            logger.info(
                'Trial-end reminder for subscription %s — email handled '
                'in Phase 4',
                data_object.get('id'),
            )

        else:
            logger.info('Stripe webhook unhandled: %s', event_type)

    except StripeBillingError as e:
        # A predictable error from our own services — log + 200 (Stripe
        # shouldn't retry these because they reflect a state mismatch
        # we can't recover from automatically).
        logger.exception('Stripe webhook sync failed: %s', e)
        return JsonResponse(
            {'detail': 'Sync failed; logged for ops.'},
            status=200,
        )
    except Exception:  # noqa: BLE001 — webhook errors must not 500
        # Anything else is unexpected. Return 500 so Stripe retries —
        # gives us a window to fix + replay without losing the event.
        logger.exception('Stripe webhook processing crashed')
        return JsonResponse(
            {'detail': 'Internal error processing webhook.'},
            status=500,
        )

    return JsonResponse({'received': True}, status=200)
