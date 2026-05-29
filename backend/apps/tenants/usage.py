"""Per-tenant usage counters for SMS + email.

Phase 1f of the self-serve pricing rollout. Counters live on the
``Tenant`` row (``current_period_sms_count`` /
``current_period_email_count``) and are mutated atomically here.
Reset on the billing period roll by ``apps.billing.services.sync_from_stripe``
when ``customer.subscription.updated`` fires with a new
``current_period_end``.

Why a dedicated module:

  - Single atomic-increment surface so every send path uses the
    same race-safe ``UPDATE … SET count = count + 1`` shape.
  - Single quota-check surface so the policy ("block emails past
    quota; meter SMS overage to Stripe") is defined exactly once.
  - Grandfathered + Enterprise tenants short-circuit at this layer,
    so callers don't have to know whether usage limits apply —
    everything just records, and quota helpers say "allowed."

The increment helpers are best-effort: they NEVER raise. A counter
miss is preferred to a failed send. Quota-check helpers return a
bool; the send wrapper decides whether to block.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from django.db import models

from apps.tenants.plans import (
    effective_monthly_email_quota,
    effective_monthly_sms_quota,
)

if TYPE_CHECKING:
    from apps.tenants.models import Tenant

logger = logging.getLogger(__name__)


__all__ = [
    'increment_sms_count',
    'increment_email_count',
    'check_email_quota',
    'check_sms_quota',
    'EmailQuotaExceeded',
]


class EmailQuotaExceeded(Exception):
    """Raised by ``check_email_quota`` callers (Phase 1g) when a send
    must be blocked because the tenant has used their full
    period quota + the next pack hasn't been purchased.

    Carries the tenant + quota numbers in the message so the
    operator-facing copy can quote actuals."""

    def __init__(self, tenant_slug: str, quota: int, used: int):
        self.tenant_slug = tenant_slug
        self.quota = quota
        self.used = used
        super().__init__(
            f'Email quota exceeded for tenant {tenant_slug}: '
            f'{used}/{quota} emails used in current period. '
            f'Buy an email pack on /org/billing to send more.'
        )


# ── Increment helpers ───────────────────────────────────────────────


def increment_sms_count(tenant: 'Tenant', *, n: int = 1) -> None:
    """Atomically add ``n`` to the tenant's current-period SMS count.

    Never raises — a counter miss is preferred to a failed send.
    A logged warning is enough for ops to spot if this ever stops
    working in prod.

    Idempotency: not enforced here. Each send path calls once per
    sent message; double-call would double-count. The Twilio /
    SES wrappers are the only callers + each is single-call.
    """
    if not getattr(tenant, 'pk', None):
        return
    try:
        from apps.tenants.models import Tenant as TenantModel
        TenantModel.objects.filter(pk=tenant.pk).update(
            current_period_sms_count=models.F('current_period_sms_count') + n,
        )
    except Exception:
        logger.exception(
            'usage.increment_sms_count failed for tenant=%s (continuing)',
            getattr(tenant, 'slug', tenant.pk),
        )


def increment_email_count(tenant: 'Tenant', *, n: int = 1) -> None:
    """Atomically add ``n`` to the tenant's current-period email count.

    Same best-effort posture as ``increment_sms_count``. Marketing
    campaign sends call once per recipient (NOT once per campaign)
    so the counter accurately reflects "messages out."
    """
    if not getattr(tenant, 'pk', None):
        return
    try:
        from apps.tenants.models import Tenant as TenantModel
        TenantModel.objects.filter(pk=tenant.pk).update(
            current_period_email_count=models.F('current_period_email_count') + n,
        )
    except Exception:
        logger.exception(
            'usage.increment_email_count failed for tenant=%s (continuing)',
            getattr(tenant, 'slug', tenant.pk),
        )


# ── Quota checks ────────────────────────────────────────────────────


def check_email_quota(tenant: 'Tenant') -> tuple[bool, int | None, int]:
    """Return ``(allowed, quota, used)`` for the tenant's current-period
    email quota.

    ``allowed`` is True when the tenant can send another email right
    now without exceeding quota. ``quota`` is the inclusive cap or
    ``None`` for unlimited (grandfathered / Enterprise). ``used`` is
    the current-period count.

    Senders block when ``allowed`` is False. Quota is computed via
    ``effective_monthly_email_quota`` which already accounts for
    add-ons (5k or 10k email packs).
    """
    quota = effective_monthly_email_quota(tenant)
    used = int(getattr(tenant, 'current_period_email_count', 0) or 0)
    if quota is None:
        return True, None, used
    return (used < quota), quota, used


def check_sms_quota(tenant: 'Tenant') -> tuple[bool, int | None, int]:
    """Return ``(within_quota, quota, used)`` for SMS.

    SMS uses **pay-as-you-go overage** rather than a hard block —
    sends past quota succeed locally + are reported to Stripe as
    metered usage at period roll. Callers use this helper to decide
    whether the upcoming send is "included" (within quota) or
    "overage" (past quota); the actual send happens in both cases.

    Grandfathered / Enterprise tenants always return True / None /
    used.
    """
    quota = effective_monthly_sms_quota(tenant)
    used = int(getattr(tenant, 'current_period_sms_count', 0) or 0)
    if quota is None:
        return True, None, used
    return (used < quota), quota, used
