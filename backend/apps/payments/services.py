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
