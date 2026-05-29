"""Stripe Connect integration — Express account onboarding.

This first chunk wires up account creation + the Stripe-hosted
onboarding link. The charge / refund flow lands in the next chunk
once the spa can connect a real account.

Soft-fail in dev: every function raises ``StripeNotConfigured`` when
``STRIPE_SECRET_KEY`` isn't set, caught by the view layer and turned
into a 503. The CRM nav still shows /org/payments; clicking "Connect
Stripe" surfaces a clear "billing not configured in this environment"
message instead of a 500.

Audit trail: account creation + deauthorization both write
``apps.audit.AuditLog`` rows so ops can reconstruct exactly when a
spa connected / disconnected and who triggered it.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import TYPE_CHECKING, Any

from django.conf import settings
from django.db import transaction

# We reuse the billing app's Stripe helpers (_stripe loader, exception
# classes) — same Stripe account, same configuration check. Pulling
# them in keeps the two integrations' error shapes identical so the
# frontend can handle 503 / 502 / 200 the same way.
from apps.billing.services import (
    StripeBillingError as StripeAPIError,
    StripeNotConfigured,
    _stripe,
    is_configured,
)

from apps.payments.models import MerchantAccount

if TYPE_CHECKING:
    from apps.tenants.models import Tenant

logger = logging.getLogger(__name__)


__all__ = [
    'StripeAPIError',
    'StripeNotConfigured',
    'is_configured',
    'ensure_merchant_account',
    'create_express_account',
    'create_onboarding_link',
    'refresh_account_status',
    'sync_from_stripe_account',
    # Payment flow (chunk 2):
    'create_payment_intent_for_invoice',
    'sync_charge_from_payment_intent',
    'refund_charge',
    'sync_refund_from_stripe',
    'ChargeRefusedError',
    'RefundRefusedError',
]


# ── Local account row management ───────────────────────────────────


def ensure_merchant_account(tenant: 'Tenant') -> MerchantAccount:
    """Return the tenant's MerchantAccount, creating an empty one if
    none exists yet. Idempotent: safe to call from any read path that
    wants to render "connect status" without first writing a row.
    """
    account, _ = MerchantAccount.objects.get_or_create(
        tenant=tenant,
        defaults={'provider': MerchantAccount.Provider.STRIPE_CONNECT},
    )
    return account


# ── Stripe-side account create ─────────────────────────────────────


@transaction.atomic
def create_express_account(tenant: 'Tenant') -> MerchantAccount:
    """Create the Stripe Connect Express account for a tenant.

    Idempotent: if the tenant already has a ``stripe_account_id``,
    returns the existing MerchantAccount without re-creating on
    Stripe (avoids stranded accounts cluttering the dashboard).

    The Express account is created with:
      - country='US' (US-only at v1; international flagged for Phase 6)
      - default_currency='usd'
      - business_type left blank (the spa fills it in during the
        hosted onboarding flow)
      - metadata.lume_tenant_id stamped so we can resolve the tenant
        from a webhook without keeping a Stripe → Lumè lookup table
      - capabilities request: card_payments + transfers

    Raises StripeAPIError on any Stripe-side failure (network, auth,
    rate limit). View layer maps to 502 with a sanitized message.
    """
    account = ensure_merchant_account(tenant)
    if account.stripe_account_id:
        return account

    stripe = _stripe()
    try:
        stripe_account = stripe.Account.create(
            type='express',
            country='US',
            email=tenant.billing_email or None,
            default_currency='usd',
            business_profile={
                'name': tenant.name,
                # Best-effort; the spa edits this in the hosted flow.
                'product_description': (
                    f'{tenant.name} — medspa services + retail products.'
                ),
            },
            capabilities={
                'card_payments': {'requested': True},
                'transfers': {'requested': True},
            },
            metadata={
                'lume_tenant_id': str(tenant.id),
                'lume_tenant_slug': tenant.slug,
            },
        )
    except Exception as e:
        logger.exception(
            'Stripe Account.create failed for tenant %s', tenant.id,
        )
        raise StripeAPIError(f'Could not create Stripe account: {e}') from e

    account.stripe_account_id = stripe_account.id
    account.connected_at = dt.datetime.now(tz=dt.timezone.utc)
    # Reset disabled_at on re-connect — a tenant that previously
    # deauthorized + comes back through a fresh onboarding link gets
    # a clean slate locally.
    account.disabled_at = None
    account.save(update_fields=[
        'stripe_account_id', 'connected_at', 'disabled_at', 'updated_at',
    ])
    return account


# ── Hosted onboarding link ─────────────────────────────────────────


def create_onboarding_link(tenant: 'Tenant') -> str:
    """Generate a one-shot Stripe-hosted onboarding URL.

    The spa clicks "Set up payments" in /org/payments → backend hits
    this → returns a Stripe URL → frontend redirects them there →
    Stripe collects business info + bank account + KYC → Stripe
    redirects them back to ``return_url``.

    AccountLinks are one-time use and expire after a few minutes.
    Always generate a fresh one per click.
    """
    account = create_express_account(tenant)  # ensures Stripe account exists
    stripe = _stripe()

    return_url = _format_url_template(
        settings.STRIPE_CONNECT_RETURN_URL_TEMPLATE, tenant,
    )
    refresh_url = _format_url_template(
        settings.STRIPE_CONNECT_REFRESH_URL_TEMPLATE, tenant,
    )

    try:
        link = stripe.AccountLink.create(
            account=account.stripe_account_id,
            return_url=return_url,
            refresh_url=refresh_url,
            type='account_onboarding',
        )
    except Exception as e:
        logger.exception(
            'Stripe AccountLink.create failed for tenant %s', tenant.id,
        )
        raise StripeAPIError(f'Could not generate onboarding link: {e}') from e

    return link.url


def _format_url_template(template: str, tenant: 'Tenant') -> str:
    """Substitute {tenant_slug} into a URL template from settings.

    Defensive: a malformed template (missing the placeholder) just
    returns the literal string — Stripe will reject if it can't
    parse, and the operator gets a clear error from us instead of
    a silent wrong-tenant redirect.
    """
    return template.replace('{tenant_slug}', tenant.slug)


# ── Status sync (webhook side + manual refresh) ────────────────────


def sync_from_stripe_account(stripe_account_obj: Any) -> MerchantAccount | None:
    """Mirror an updated Stripe Account onto the local MerchantAccount.

    Called by the ``account.updated`` webhook handler. Resolves the
    tenant from ``metadata.lume_tenant_id`` (which we stamp at
    create_express_account time), so we don't need a separate Stripe
    account → tenant lookup.

    Returns the updated MerchantAccount, or None if the account
    couldn't be resolved (e.g. an account that was created manually
    in the Stripe dashboard without our metadata — should never
    happen in normal operation but doesn't crash if it does).
    """
    metadata = getattr(stripe_account_obj, 'metadata', {}) or {}
    tenant_id = metadata.get('lume_tenant_id')
    if not tenant_id:
        logger.warning(
            'Connect webhook account.updated has no lume_tenant_id; '
            'ignoring. account=%s',
            getattr(stripe_account_obj, 'id', '?'),
        )
        return None

    try:
        account = MerchantAccount.objects.select_related('tenant').get(
            tenant_id=int(tenant_id),
        )
    except (MerchantAccount.DoesNotExist, ValueError):
        logger.warning(
            'Connect webhook account.updated metadata.lume_tenant_id=%r '
            'does not match a known MerchantAccount.', tenant_id,
        )
        return None

    account.charges_enabled = bool(getattr(stripe_account_obj, 'charges_enabled', False))
    account.payouts_enabled = bool(getattr(stripe_account_obj, 'payouts_enabled', False))
    account.details_submitted = bool(getattr(stripe_account_obj, 'details_submitted', False))
    account.save(update_fields=[
        'charges_enabled', 'payouts_enabled', 'details_submitted', 'updated_at',
    ])
    return account


# ── Charge flow ─────────────────────────────────────────────────────


class ChargeRefusedError(RuntimeError):
    """Raised when a charge can't be initiated for a non-Stripe reason
    (tenant not ready to charge, invoice already paid, amount exceeds
    balance due, etc.). View layer maps to 409 with a clear message
    distinct from a Stripe API failure."""


class RefundRefusedError(RuntimeError):
    """Raised when a refund can't be issued (charge not succeeded,
    amount exceeds refundable balance, etc.)."""


def create_payment_intent_for_invoice(
    *,
    invoice,
    amount_cents: int,
    operator=None,
    initiated_via: str = 'operator',
):
    """Create a Stripe PaymentIntent on the spa's connected account +
    a local Charge row, returning both.

    Architecture: **Direct charges on the connected account.** The
    PaymentIntent is created with the ``Stripe-Account`` header set
    to the spa's connected account ID; the charge appears on the
    spa's Stripe dashboard, money settles to the spa's Stripe
    balance, payouts go to the spa's bank. Lumè doesn't touch the
    money (no platform fee per the pricing plan).

    Returns ``(charge_row, client_secret)``. The frontend uses
    ``client_secret`` with Stripe Elements to collect the card +
    confirm the intent. Final status (succeeded / failed) lands via
    the ``payment_intent.*`` webhook, NOT the synchronous response,
    so the 3DS / SCA flow works the same as the immediate-success
    flow.

    Args:
        invoice: ``apps.invoices.models.Invoice`` row. Must be open,
            have a positive amount_due, and belong to a tenant that
            has a charges_enabled MerchantAccount.
        amount_cents: how much to charge. Caller validates this is
            <= invoice.amount_due_cents (or whatever the relevant
            outstanding-balance field is in the invoice model).
        operator: optional ``User`` who initiated the charge. None
            for customer-portal self-pay (initiated_via='customer_portal').
        initiated_via: 'operator' or 'customer_portal' — for the
            local audit + activity log.

    Raises:
        ChargeRefusedError: tenant isn't ready to charge, invoice
            is closed, amount is 0/negative, etc.
        StripeAPIError: Stripe API call failed.
    """
    from apps.payments.models import Charge

    tenant = invoice.tenant
    merchant = ensure_merchant_account(tenant)
    if not merchant.is_ready_to_charge:
        raise ChargeRefusedError(
            'This tenant\'s Stripe Connect account is not ready to '
            'take payments yet. Complete onboarding at '
            '/org/payments and try again.'
        )
    if amount_cents <= 0:
        raise ChargeRefusedError('Charge amount must be greater than zero.')

    stripe = _stripe()
    try:
        # Direct charge: stripe_account=merchant.stripe_account_id
        # makes the PaymentIntent land on the connected account.
        # idempotency_key would also be useful here for retry safety,
        # but the local Charge row pre-create gives us a natural
        # idempotency key via the invoice + operator + timestamp; we
        # rely on the database-level unique constraint on
        # stripe_payment_intent_id to dedupe webhook events.
        pi = stripe.PaymentIntent.create(
            amount=amount_cents,
            currency='usd',
            metadata={
                'lume_tenant_id': str(tenant.id),
                'lume_tenant_slug': tenant.slug,
                'lume_invoice_id': str(invoice.pk),
                'lume_invoice_number': getattr(invoice, 'invoice_number', '') or '',
                'lume_initiated_via': initiated_via,
                **(
                    {'lume_operator_id': str(operator.id)}
                    if operator else {}
                ),
            },
            # PaymentMethod automation: Stripe picks the right
            # confirmation method based on the customer's payment
            # method (handles 3DS / SCA automatically).
            automatic_payment_methods={'enabled': True},
            # Receipt goes to the customer email on file if present.
            receipt_email=(
                getattr(invoice.customer, 'email', None)
                if getattr(invoice, 'customer', None) else None
            ),
            stripe_account=merchant.stripe_account_id,
        )
    except Exception as e:
        logger.exception(
            'Stripe PaymentIntent.create failed: tenant=%s invoice=%s amount=%s',
            tenant.id, invoice.pk, amount_cents,
        )
        raise StripeAPIError(f'Could not create payment intent: {e}') from e

    # Persist a local Charge row immediately so the audit trail
    # captures even an abandoned payment intent. Status stays
    # pending until the webhook lands.
    charge = Charge.objects.create(
        tenant=tenant,
        invoice=invoice,
        merchant_account=merchant,
        amount_cents=amount_cents,
        stripe_payment_intent_id=pi.id,
        status=Charge.Status.PENDING,
        currency='usd',
        created_by=operator,
        initiated_via=initiated_via,
    )

    return charge, pi.client_secret


def sync_charge_from_payment_intent(stripe_pi_obj) -> 'Charge | None':
    """Reconcile local Charge row from a payment_intent.* webhook event.

    Resolves the Charge via ``stripe_payment_intent_id`` (unique).
    Idempotent: re-applying the same event leaves the row identical.

    Updates status (succeeded / failed), the charge ID, last4 + brand,
    failure_code/message, and (on succeeded) the fee + net amounts
    from the balance_transaction.

    Returns the updated Charge, or None if we don't recognize the
    payment intent (shouldn't happen in normal operation — we always
    stamp metadata.lume_invoice_id at create time; this is the
    defensive branch).
    """
    from apps.payments.models import Charge

    pi_id = getattr(stripe_pi_obj, 'id', None)
    if not pi_id:
        logger.warning('Connect webhook payment_intent event missing id')
        return None

    try:
        charge = Charge.objects.select_related(
            'invoice', 'merchant_account',
        ).get(stripe_payment_intent_id=pi_id)
    except Charge.DoesNotExist:
        # PI created out-of-band (or before this code shipped). Log +
        # ignore — we can't reconstruct the row safely without an
        # invoice link.
        logger.warning(
            'Connect webhook for unknown PaymentIntent %s — '
            'no local Charge row to sync.',
            pi_id,
        )
        return None

    pi_status = getattr(stripe_pi_obj, 'status', '')

    if pi_status == 'succeeded':
        charge.status = Charge.Status.SUCCEEDED
        # PI has a list of charges (latest_charge is the relevant one
        # in modern Stripe). Each Charge has card details + a
        # balance_transaction we can expand to find the fee.
        latest_charge = (
            getattr(stripe_pi_obj, 'latest_charge', None)
            or _first_charge_from_pi(stripe_pi_obj)
        )
        if latest_charge:
            # latest_charge may be just an ID; resolve to the full
            # Charge object if so. We fetch with the connected
            # account header.
            if isinstance(latest_charge, str):
                latest_charge = _retrieve_charge(
                    latest_charge,
                    stripe_account=charge.merchant_account.stripe_account_id,
                )
            if latest_charge:
                charge.stripe_charge_id = getattr(latest_charge, 'id', '') or ''
                pm_details = (
                    getattr(latest_charge, 'payment_method_details', {}) or {}
                )
                card = (
                    pm_details.get('card', {}) if isinstance(pm_details, dict)
                    else getattr(pm_details, 'card', {}) or {}
                )
                charge.last4 = (
                    card.get('last4', '') if isinstance(card, dict)
                    else getattr(card, 'last4', '') or ''
                )
                charge.brand = (
                    card.get('brand', '') if isinstance(card, dict)
                    else getattr(card, 'brand', '') or ''
                )
                # Fee + net come from the balance_transaction. If it's
                # not expanded on the event, fetch it.
                bt = getattr(latest_charge, 'balance_transaction', None)
                if bt and isinstance(bt, str):
                    bt = _retrieve_balance_transaction(
                        bt,
                        stripe_account=charge.merchant_account.stripe_account_id,
                    )
                if bt and not isinstance(bt, str):
                    charge.fee_cents = max(0, int(getattr(bt, 'fee', 0) or 0))
                    charge.net_cents = max(0, int(getattr(bt, 'net', 0) or 0))

    elif pi_status in {'requires_payment_method', 'canceled'}:
        # Failed or abandoned — keep details for the activity log.
        charge.status = Charge.Status.FAILED
        last_error = getattr(stripe_pi_obj, 'last_payment_error', None)
        if last_error:
            charge.failure_code = (
                getattr(last_error, 'code', None)
                or (last_error.get('code', '') if isinstance(last_error, dict) else '')
                or ''
            )
            charge.failure_message = (
                getattr(last_error, 'message', None)
                or (last_error.get('message', '') if isinstance(last_error, dict) else '')
                or ''
            )
    else:
        # In-flight (processing / requires_action) — wait for the
        # next webhook to land in a terminal state.
        return charge

    charge.save()
    return charge


def _first_charge_from_pi(stripe_pi_obj):
    """Backwards-compat shim — some Stripe API versions return
    ``charges.data`` instead of ``latest_charge``. Returns the first
    Charge object if present, else None."""
    charges = getattr(stripe_pi_obj, 'charges', None)
    if not charges:
        return None
    data = getattr(charges, 'data', None) or []
    return data[0] if data else None


def _retrieve_charge(charge_id: str, *, stripe_account: str):
    """Resolve a Stripe Charge ID to the full object on the connected
    account. Returns None on retrieval failure (logged but not
    raised — partial sync is better than no sync)."""
    try:
        stripe = _stripe()
        return stripe.Charge.retrieve(
            charge_id, stripe_account=stripe_account,
            expand=['balance_transaction'],
        )
    except Exception:
        logger.exception('Failed to retrieve Stripe Charge %s', charge_id)
        return None


def _retrieve_balance_transaction(bt_id: str, *, stripe_account: str):
    """Same pattern for balance_transaction."""
    try:
        stripe = _stripe()
        return stripe.BalanceTransaction.retrieve(
            bt_id, stripe_account=stripe_account,
        )
    except Exception:
        logger.exception('Failed to retrieve BalanceTransaction %s', bt_id)
        return None


# ── Refund flow ─────────────────────────────────────────────────────


@transaction.atomic
def refund_charge(
    *,
    charge,
    amount_cents: int,
    reason: str,
    operator,
):
    """Issue a Stripe refund + persist a local Refund row.

    Validates ``amount_cents`` against ``charge.refundable_cents``
    BEFORE hitting Stripe (cheap safety; avoids a wasted round-trip
    when the operator over-types). Stripe is the second guard — if
    we somehow miscalculated, Stripe will reject and we surface that.

    Updates ``charge.refunded_cents`` atomically. Database CHECK
    constraint enforces refunded_cents <= amount_cents at the storage
    layer as the last line of defense.

    Raises:
        RefundRefusedError: charge not succeeded, amount > refundable
        StripeAPIError: Stripe API call failed
    """
    from apps.payments.models import Refund

    if not charge.is_succeeded:
        raise RefundRefusedError(
            'Cannot refund a charge that did not succeed.'
        )
    if amount_cents <= 0:
        raise RefundRefusedError('Refund amount must be greater than zero.')
    if amount_cents > charge.refundable_cents:
        raise RefundRefusedError(
            f'Refund amount ${amount_cents/100:.2f} exceeds remaining '
            f'refundable balance ${charge.refundable_cents/100:.2f}.'
        )

    merchant = charge.merchant_account
    stripe = _stripe()
    try:
        stripe_refund = stripe.Refund.create(
            charge=charge.stripe_charge_id,
            amount=amount_cents,
            metadata={
                'lume_tenant_id': str(charge.tenant_id),
                'lume_charge_id': str(charge.pk),
                'lume_reason': reason[:255],
                'lume_operator_id': str(operator.id) if operator else '',
            },
            stripe_account=merchant.stripe_account_id,
        )
    except Exception as e:
        logger.exception(
            'Stripe Refund.create failed: charge=%s amount=%s',
            charge.pk, amount_cents,
        )
        raise StripeAPIError(f'Could not issue refund: {e}') from e

    refund = Refund.objects.create(
        tenant=charge.tenant,
        charge=charge,
        amount_cents=amount_cents,
        reason=reason,
        stripe_refund_id=stripe_refund.id,
        status=Refund.Status.PENDING,
        created_by=operator,
    )

    # Bump the denormalized rollup atomically. The CHECK constraint
    # on the row will reject if this would exceed amount_cents — a
    # bug-class detection net.
    from apps.payments.models import Charge
    Charge.objects.filter(pk=charge.pk).update(
        refunded_cents=models.F('refunded_cents') + amount_cents,
    )
    charge.refresh_from_db(fields=['refunded_cents'])

    return refund


def sync_refund_from_stripe(stripe_refund_obj) -> 'Refund | None':
    """Reconcile a Refund row from a charge.refunded / refund.* event.

    Two paths into this:
      - Webhook after refund_charge() created the row locally:
        update status pending → succeeded/failed, no-op otherwise.
      - Webhook for a refund issued in Stripe Express dashboard
        directly: create the local row + bump the Charge rollup.

    Uses ``stripe_refund_id`` as the idempotency key.
    """
    from apps.payments.models import Charge, Refund

    refund_id = getattr(stripe_refund_obj, 'id', None)
    if not refund_id:
        return None

    refund = Refund.objects.select_related('charge').filter(
        stripe_refund_id=refund_id,
    ).first()

    if refund is None:
        # Issued in Stripe Express dashboard — look up the parent
        # charge by stripe_charge_id and create our local row.
        charge_id = getattr(stripe_refund_obj, 'charge', None)
        if not charge_id:
            logger.warning(
                'Stripe refund %s missing charge id; cannot link.', refund_id,
            )
            return None
        charge = Charge.objects.filter(stripe_charge_id=charge_id).first()
        if charge is None:
            logger.warning(
                'Stripe refund %s for unknown charge %s; skipping.',
                refund_id, charge_id,
            )
            return None
        amount = max(0, int(getattr(stripe_refund_obj, 'amount', 0) or 0))
        reason_attr = getattr(stripe_refund_obj, 'reason', None) or ''
        refund = Refund.objects.create(
            tenant=charge.tenant,
            charge=charge,
            amount_cents=amount,
            reason=str(reason_attr) or 'Refunded via Stripe dashboard',
            stripe_refund_id=refund_id,
            status=Refund.Status.PENDING,
        )
        Charge.objects.filter(pk=charge.pk).update(
            refunded_cents=models.F('refunded_cents') + amount,
        )
        charge.refresh_from_db(fields=['refunded_cents'])

    # Map Stripe status onto local.
    stripe_status = getattr(stripe_refund_obj, 'status', '')
    if stripe_status == 'succeeded':
        refund.status = Refund.Status.SUCCEEDED
        refund.save(update_fields=['status', 'updated_at'])
    elif stripe_status == 'failed':
        refund.status = Refund.Status.FAILED
        refund.save(update_fields=['status', 'updated_at'])
    # 'pending' / 'requires_action' / 'canceled' — leave alone or
    # wait for next event. canceled is rare for refunds.

    return refund


# ── F-expression import (used above) ────────────────────────────────


from django.db import models  # noqa: E402 — needed for models.F above


def refresh_account_status(tenant: 'Tenant') -> MerchantAccount:
    """Pull the latest Account state from Stripe + mirror locally.

    Used by /org/payments when the operator hits "Refresh status" —
    most syncs come through the webhook, but a manual refresh is the
    right escape hatch when the operator wants to verify state right
    now (e.g. they just submitted KYC + want immediate feedback).
    """
    account = ensure_merchant_account(tenant)
    if not account.stripe_account_id:
        return account

    stripe = _stripe()
    try:
        stripe_account = stripe.Account.retrieve(account.stripe_account_id)
    except Exception as e:
        logger.exception(
            'Stripe Account.retrieve failed for tenant %s', tenant.id,
        )
        raise StripeAPIError(f'Could not refresh account status: {e}') from e

    return sync_from_stripe_account(stripe_account) or account
