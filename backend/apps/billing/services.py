"""Stripe Billing integration — SaaS subscription management.

Owns the round-trip between Lumè's ``Tenant`` model and Stripe's
``Customer`` + ``Subscription`` objects. All Stripe API calls go through
this module so the webhook handler + signup endpoint + /settings/billing
view stay focused on their own concerns.

Mirrors-not-stores: every authoritative billing state (status, period
end, add-on quantities) lives in Stripe. We mirror it onto ``Tenant``
on every webhook so capacity / feature gating can run synchronously
against the local DB. If Stripe and local DB ever diverge, Stripe wins
— ``sync_from_stripe`` reconciles.

Legal entity: Voxtro LLC. Stripe Customer descriptions, statement
descriptors, and email "from" addresses identify Voxtro LLC as the
merchant. Lumè CRM is the product name. See ``BILLING_LEGAL_NAME``
in settings.

Soft-fail in dev: when ``STRIPE_SECRET_KEY`` isn't configured, every
function in this module raises ``StripeNotConfigured`` (caught by the
view layer + turned into a clear 503). The signup endpoint short-
circuits before reaching here when Stripe isn't ready, so dev work
on tenant onboarding can proceed without a Stripe account.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import TYPE_CHECKING, Any

from django.conf import settings

if TYPE_CHECKING:
    from apps.tenants.models import Tenant

logger = logging.getLogger(__name__)


class StripeNotConfigured(RuntimeError):
    """Raised when a billing call lands but the Stripe SDK / keys
    haven't been wired up. View layer maps this to a 503 with a
    clear "Stripe billing not configured for this environment"
    message — not an opaque 500."""


class StripeBillingError(RuntimeError):
    """Raised when Stripe returns an error we can't recover from at
    this layer (rate limited, network error, etc.). The view layer
    surfaces a 502 with a sanitized message."""


def _stripe():
    """Lazy import + configure the Stripe SDK.

    Returns the configured ``stripe`` module. Raises
    ``StripeNotConfigured`` when ``STRIPE_SECRET_KEY`` is empty —
    we never partially-init the SDK with no key (the SDK will
    silently send to the public API and you'd get a confusing
    auth error later).
    """
    secret = getattr(settings, 'STRIPE_SECRET_KEY', '') or ''
    if not secret:
        raise StripeNotConfigured(
            'STRIPE_SECRET_KEY is not set. Configure the Stripe '
            'integration in environment variables before calling '
            'billing endpoints.'
        )
    try:
        import stripe
    except ImportError as e:
        raise StripeNotConfigured(
            'The `stripe` package is not installed. Add it to '
            'requirements.txt and reinstall.'
        ) from e
    stripe.api_key = secret
    return stripe


def is_configured() -> bool:
    """Cheap check used by views + the signup endpoint to decide
    whether to attempt a Stripe call at all. Doesn't import the SDK
    so it stays safe to call during settings load."""
    return bool(getattr(settings, 'STRIPE_SECRET_KEY', ''))


# ── Customer + Subscription create (signup) ─────────────────────────


def create_customer_for_tenant(
    tenant: 'Tenant',
    *,
    billing_email: str,
    payment_method_id: str | None = None,
) -> str:
    """Create a Stripe Customer keyed by the tenant + return the ID.

    Attaches ``payment_method_id`` as the default if supplied (signup
    flow passes the PaymentMethod the operator entered via Stripe
    Elements). Stamps the Customer with metadata pointing back at our
    tenant row so the Stripe dashboard makes sense to an operator.

    Idempotency: if ``tenant.stripe_customer_id`` is already set, we
    return it without creating a duplicate.
    """
    if tenant.stripe_customer_id:
        return tenant.stripe_customer_id

    stripe = _stripe()
    legal_name = getattr(settings, 'BILLING_LEGAL_NAME', 'Voxtro LLC')
    try:
        customer = stripe.Customer.create(
            email=billing_email,
            description=f'{tenant.name} (Lumè CRM tenant #{tenant.id})',
            metadata={
                'lume_tenant_id': str(tenant.id),
                'lume_tenant_slug': tenant.slug,
                'billed_by': legal_name,
            },
        )
        if payment_method_id:
            stripe.PaymentMethod.attach(
                payment_method_id, customer=customer.id,
            )
            stripe.Customer.modify(
                customer.id,
                invoice_settings={'default_payment_method': payment_method_id},
            )
    except Exception as e:
        logger.exception('Stripe Customer create failed for tenant %s', tenant.id)
        raise StripeBillingError(f'Stripe Customer create failed: {e}') from e

    tenant.stripe_customer_id = customer.id
    tenant.billing_email = billing_email
    tenant.save(update_fields=['stripe_customer_id', 'billing_email'])
    return customer.id


def create_trial_subscription(
    tenant: 'Tenant',
    *,
    plan: str,
    billing_cycle: str,
    trial_days: int = 14,
) -> str:
    """Create a Stripe Subscription with a built-in trial period.

    The trial period is Stripe-native (no charge until day 15). When
    the trial ends, Stripe automatically attempts the first charge —
    we don't need a separate cron. ``customer.subscription.updated``
    webhook fires on both the trial-end transition and the charge
    success / failure.

    Args:
        tenant: must already have ``stripe_customer_id`` set.
        plan: one of ``starter`` / ``pro``. Trial signups pick a
            target tier at checkout; the subscription is created
            against that tier's price, with a 14-day trial.
        billing_cycle: ``monthly`` or ``annual``. Determines which
            Stripe Price ID we pull from settings.
        trial_days: defaults to 14; tests pass 0 for immediate-charge
            scenarios.
    """
    if not tenant.stripe_customer_id:
        raise StripeBillingError(
            'Tenant has no Stripe Customer ID. Call '
            'create_customer_for_tenant first.'
        )
    if plan not in {'starter', 'pro'}:
        raise StripeBillingError(
            f'Cannot create a subscription for plan="{plan}". Only '
            f'starter + pro have self-serve prices; enterprise is '
            f'manual / custom.'
        )

    price_id = _price_id_for(plan, billing_cycle)

    stripe = _stripe()
    try:
        subscription = stripe.Subscription.create(
            customer=tenant.stripe_customer_id,
            items=[{'price': price_id}],
            trial_period_days=trial_days,
            metadata={
                'lume_tenant_id': str(tenant.id),
                'lume_tenant_slug': tenant.slug,
                'lume_plan': plan,
                'lume_billing_cycle': billing_cycle,
            },
            # Bill the first invoice automatically when the trial ends.
            payment_behavior='default_incomplete',
        )
    except Exception as e:
        logger.exception(
            'Stripe Subscription create failed for tenant %s plan=%s cycle=%s',
            tenant.id, plan, billing_cycle,
        )
        raise StripeBillingError(f'Stripe Subscription create failed: {e}') from e

    # Mirror initial state.
    tenant.stripe_subscription_id = subscription.id
    tenant.plan = 'trial'  # trial-period flag; flips to plan on first charge
    tenant.billing_cycle = billing_cycle
    if trial_days:
        tenant.trial_ends_at = dt.datetime.fromtimestamp(
            subscription.trial_end, tz=dt.timezone.utc,
        )
    if subscription.current_period_end:
        tenant.current_period_end = dt.datetime.fromtimestamp(
            subscription.current_period_end, tz=dt.timezone.utc,
        )
    tenant.save(update_fields=[
        'stripe_subscription_id', 'plan', 'billing_cycle',
        'trial_ends_at', 'current_period_end',
    ])
    return subscription.id


def _price_id_for(plan: str, billing_cycle: str) -> str:
    """Look up the Stripe Price ID configured in settings.

    Prices are created in the Stripe dashboard (one Product per tier,
    two Prices per product — monthly + annual). Their IDs land in
    env vars per environment. Returns ``STRIPE_PRICE_<plan>_<cycle>``.
    """
    key = f'STRIPE_PRICE_{plan.upper()}_{billing_cycle.upper()}'
    price_id = getattr(settings, key, '') or ''
    if not price_id:
        raise StripeBillingError(
            f'No Stripe Price configured for {plan} {billing_cycle}. '
            f'Set {key} in environment variables.'
        )
    return price_id


# ── Webhook-side sync ───────────────────────────────────────────────


def sync_from_stripe(stripe_subscription_obj: Any) -> 'Tenant':
    """Reconcile local ``Tenant`` from a Stripe Subscription event.

    Driven by the webhook handler on ``customer.subscription.updated``
    / ``.deleted`` / ``invoice.paid`` / ``invoice.payment_failed``.
    Resolves the tenant from the subscription's metadata (we stamp
    ``lume_tenant_id`` at create time so we don't have to rely on
    Stripe Customer → Tenant lookups).

    Updates ``plan`` (from the subscription's metadata or the price
    nickname), ``status`` (trial / active / past_due / cancelled per
    the Stripe status), ``current_period_end``, ``addon_quantities``
    (computed from the subscription's items), and resets the period
    usage counters when ``current_period_end`` moves forward.

    Idempotent: re-applying the same Stripe event leaves the tenant
    in the same state.
    """
    from apps.tenants.models import Tenant

    metadata = getattr(stripe_subscription_obj, 'metadata', {}) or {}
    tenant_id = metadata.get('lume_tenant_id')
    if not tenant_id:
        # Defensive — every subscription we create stamps the metadata.
        # If we receive one without it, something has gone wrong (likely
        # a subscription created manually in the dashboard).
        raise StripeBillingError(
            'Stripe subscription missing lume_tenant_id in metadata; '
            'cannot sync.'
        )

    try:
        tenant = Tenant.objects.get(id=int(tenant_id))
    except (Tenant.DoesNotExist, ValueError) as e:
        raise StripeBillingError(
            f'Stripe subscription metadata.lume_tenant_id={tenant_id!r} '
            f'does not match a known tenant.'
        ) from e

    if tenant.grandfathered:
        # Grandfathered tenants must never be touched by the billing
        # sync. If a webhook arrives for one (shouldn't), log + skip.
        logger.warning(
            'Ignoring Stripe subscription sync for grandfathered '
            'tenant %s', tenant.slug,
        )
        return tenant

    # Status: Stripe → local status enum.
    # Stripe states: incomplete / incomplete_expired / trialing / active
    #                / past_due / canceled / unpaid / paused
    stripe_status = getattr(stripe_subscription_obj, 'status', '')
    if stripe_status == 'trialing':
        tenant.status = Tenant.Status.TRIAL
    elif stripe_status == 'active':
        tenant.status = Tenant.Status.ACTIVE
    elif stripe_status in {'past_due', 'unpaid'}:
        tenant.status = Tenant.Status.PAST_DUE
    elif stripe_status in {'canceled', 'incomplete_expired'}:
        tenant.status = Tenant.Status.CANCELLED

    # Plan: pull from metadata (set at create) — most reliable signal.
    # On a plan change, we re-set metadata in the change_plan flow.
    plan_from_metadata = metadata.get('lume_plan')
    if plan_from_metadata and plan_from_metadata in {
        Tenant.Plan.STARTER, Tenant.Plan.PRO, Tenant.Plan.ENTERPRISE,
    }:
        # If still trialing, keep plan='trial' (the trial-period preview
        # flag). Flip to the target tier on the active transition.
        if stripe_status == 'trialing':
            tenant.plan = Tenant.Plan.TRIAL
        else:
            tenant.plan = plan_from_metadata

    # Period end: move + reset counters if forward.
    new_period_end = getattr(stripe_subscription_obj, 'current_period_end', None)
    if new_period_end:
        new_period_end_dt = dt.datetime.fromtimestamp(
            new_period_end, tz=dt.timezone.utc,
        )
        if (
            tenant.current_period_end is None
            or new_period_end_dt > tenant.current_period_end
        ):
            tenant.current_period_end = new_period_end_dt
            # Period rolled forward — reset usage counters so the new
            # period starts at 0 against the new included quota.
            tenant.current_period_sms_count = 0
            tenant.current_period_email_count = 0

    # Add-on quantities: rebuild from the subscription's items.
    new_addons = _addons_from_subscription_items(stripe_subscription_obj)
    if new_addons is not None:
        tenant.addon_quantities = new_addons

    tenant.save()
    return tenant


def _addons_from_subscription_items(stripe_subscription_obj: Any) -> dict | None:
    """Walk the subscription's items + return a {addon_key: quantity}
    dict matching ``Tenant.addon_quantities`` shape.

    Each add-on Price in Stripe has a metadata key
    ``lume_addon_key`` set to the canonical add-on identifier
    (``staff`` / ``location`` / ``email_5k`` / ``email_10k``). The base
    plan Price doesn't have that metadata, so it gets skipped.

    Returns None when the subscription has no items expanded (a
    partial webhook payload) so the caller knows to leave the
    existing addon_quantities alone rather than blanking them.
    """
    items_data = getattr(getattr(stripe_subscription_obj, 'items', None), 'data', None)
    if items_data is None:
        return None

    result: dict[str, int] = {}
    for item in items_data:
        price = getattr(item, 'price', None)
        if price is None:
            continue
        price_metadata = getattr(price, 'metadata', {}) or {}
        addon_key = price_metadata.get('lume_addon_key')
        if not addon_key:
            continue
        try:
            qty = int(getattr(item, 'quantity', 0) or 0)
        except (TypeError, ValueError):
            qty = 0
        if qty > 0:
            result[addon_key] = qty
    return result


# ── Customer-driven flows ───────────────────────────────────────────


def create_portal_session(tenant: 'Tenant', return_url: str) -> str:
    """Stripe-hosted billing portal session URL.

    The customer (owner / billing contact) lands at Stripe's hosted
    UI for updating their card, downloading invoices, or cancelling
    the subscription. We don't allow self-serve plan change in the
    portal — that flows through /settings/billing with sales
    involvement for upgrades.

    Returns the absolute URL the operator should be redirected to.
    """
    if not tenant.stripe_customer_id:
        raise StripeBillingError(
            'Tenant has no Stripe Customer — cannot open billing portal.'
        )
    stripe = _stripe()
    try:
        session = stripe.billing_portal.Session.create(
            customer=tenant.stripe_customer_id,
            return_url=return_url,
        )
    except Exception as e:
        logger.exception(
            'Stripe billing portal session create failed for tenant %s',
            tenant.id,
        )
        raise StripeBillingError(
            f'Could not open billing portal: {e}',
        ) from e
    return session.url


def set_addon_quantity(
    tenant: 'Tenant',
    *,
    addon_key: str,
    quantity: int,
) -> None:
    """Set the quantity of an add-on on the tenant's Stripe Subscription.

    Three cases handled symmetrically:

      - Quantity > 0 and the subscription already has an item for this
        addon's Price → modify the item's quantity.
      - Quantity > 0 and there's no item yet → create one against the
        addon's configured Price ID. Stripe stamps the new item with
        ``metadata.lume_addon_key`` so the next webhook sync picks it
        up cleanly.
      - Quantity == 0 → delete the existing item if any. Stripe
        prorates the credit back to the customer.

    The local ``Tenant.addon_quantities`` row is updated optimistically
    so the UI reflects the new state immediately. The webhook reconciles
    on the next ``customer.subscription.updated`` event — if a discrepancy
    sneaks in we self-heal on the next webhook.
    """
    if not tenant.stripe_subscription_id:
        raise StripeBillingError(
            'Tenant has no active Stripe Subscription. Sign up + complete '
            'first charge before adding add-ons.',
        )
    price_id = _price_id_for_addon(addon_key)
    stripe = _stripe()
    try:
        subscription = stripe.Subscription.retrieve(
            tenant.stripe_subscription_id,
            expand=['items'],
        )
        existing_item = None
        for item in (subscription.get('items', {}).get('data', []) or []):
            item_price_id = (item.get('price') or {}).get('id')
            if item_price_id == price_id:
                existing_item = item
                break

        if quantity > 0 and existing_item is None:
            stripe.SubscriptionItem.create(
                subscription=tenant.stripe_subscription_id,
                price=price_id,
                quantity=quantity,
                metadata={'lume_addon_key': addon_key},
                proration_behavior='create_prorations',
            )
        elif quantity > 0 and existing_item is not None:
            stripe.SubscriptionItem.modify(
                existing_item['id'],
                quantity=quantity,
                proration_behavior='create_prorations',
            )
        elif quantity == 0 and existing_item is not None:
            stripe.SubscriptionItem.delete(
                existing_item['id'],
                proration_behavior='create_prorations',
            )
        # else: quantity 0 + no existing item = no-op
    except Exception as e:
        logger.exception(
            'Stripe set_addon_quantity failed: tenant=%s addon=%s qty=%s',
            tenant.id, addon_key, quantity,
        )
        raise StripeBillingError(f'Could not update add-on: {e}') from e

    # Local mirror — optimistic. Webhook reconciles authoritative state.
    new_quantities = dict(tenant.addon_quantities or {})
    if quantity > 0:
        new_quantities[addon_key] = quantity
    else:
        new_quantities.pop(addon_key, None)
    tenant.addon_quantities = new_quantities
    tenant.save(update_fields=['addon_quantities'])


def _price_id_for_addon(addon_key: str) -> str:
    """Resolve the Stripe Price ID for an add-on key from settings."""
    mapping = {
        'staff': 'STRIPE_PRICE_ADDON_STAFF',
        'location': 'STRIPE_PRICE_ADDON_LOCATION',
        'email_5k': 'STRIPE_PRICE_ADDON_EMAIL_5K',
        'email_10k': 'STRIPE_PRICE_ADDON_EMAIL_10K',
    }
    setting_name = mapping.get(addon_key)
    if not setting_name:
        raise StripeBillingError(f'Unknown add-on key: {addon_key!r}')
    price_id = getattr(settings, setting_name, '') or ''
    if not price_id:
        raise StripeBillingError(
            f'No Stripe Price configured for add-on "{addon_key}". '
            f'Set {setting_name} in environment variables.'
        )
    return price_id


def cancel_subscription(tenant: 'Tenant', *, reason: str = '') -> None:
    """Cancel the tenant's subscription at the end of the current
    period (NOT immediately — they paid for the time, they keep it).
    Sets ``cancel_at_period_end=True`` on Stripe; the
    ``customer.subscription.updated`` webhook fires when the period
    actually ends and we flip status to CANCELLED.
    """
    if not tenant.stripe_subscription_id:
        return  # nothing to do
    stripe = _stripe()
    try:
        stripe.Subscription.modify(
            tenant.stripe_subscription_id,
            cancel_at_period_end=True,
            metadata={'lume_cancel_reason': reason},
        )
    except Exception as e:
        logger.exception(
            'Stripe Subscription cancel failed for tenant %s', tenant.id,
        )
        raise StripeBillingError(f'Cancel failed: {e}') from e
