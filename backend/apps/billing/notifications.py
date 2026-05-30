"""Billing-lifecycle email notifications (Phase 5).

Five kinds of email this module sends to the tenant OWNER (the
account holder, NOT the spa's customers):

  - trial_7d        — 7 days before trial_ends_at
  - trial_3d        — 3 days before trial_ends_at
  - trial_1d        — 1 day  before trial_ends_at
  - payment_failed  — when a Stripe invoice fails to charge
  - suspended_warning — 45 days into SUSPENDED state, before data deletion

HIPAA compliance posture:

  - **No PHI in these emails.** The body references only account-
    level data (tenant name, plan tier, dates, login URL, billing
    portal URL). No patient names, no service names, no clinical
    information. The send_signed_copy email in apps.forms is the
    only path that handles PHI in mail — see ADR 0012.
  - **Recipient is the OWNER's email**, which is operator PII but
    NOT PHI (it's a business contact for the spa, not a patient).
  - **Transport is AWS SES under our BAA-covered account.** Even
    with no PHI involved, we route through the BAA-covered backend
    by default so a future template addition can't accidentally
    bypass.
  - **Audit-logged.** Every send writes an ``apps.audit.AuditLog``
    row with resource_type=tenant_notification, resource_id=tenant.id,
    metadata.kind=notification_kind. Recipient email is logged via
    the standard mechanism (operator PII, not PHI; same posture as
    SES bounce webhooks).

Idempotency:

  Every send checks ``Tenant.notifications_sent`` first — a JSONField
  keyed by notification_kind ('trial_7d' / 'trial_3d' / etc.). If
  the key is present, the send is skipped. After a successful send,
  the key is set to ``djtz.now().isoformat()`` so a re-run of the
  daily cron 24 hours later doesn't duplicate.

  Recovery scenarios reset the relevant keys:
    - When payment SUCCEEDS after a past_due cycle, the billing
      webhook clears ``payment_failed`` so a future failure gets
      a fresh email.
    - When a trial is extended (rare; manual sales action), ops
      can clear the trial_*d keys to re-arm the reminders.

Resilience:

  ``send_notification`` NEVER raises on email failure. SES errors
  are caught + logged + the notification flag is NOT set (so the
  next cron run retries). The dunning + reminder commands wrap
  every per-tenant call in its own try/except so one bad recipient
  doesn't take down the whole batch.

Test seam:

  In test settings (``EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend'``)
  the mail is captured in ``django.core.mail.outbox`` instead of
  being sent. Tests assert on outbox contents + verify
  ``notifications_sent`` is updated atomically.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import TYPE_CHECKING, Literal

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.utils import timezone as djtz

from apps.audit.models import AuditLog
from apps.audit.services import record

if TYPE_CHECKING:
    from apps.tenants.models import Tenant

logger = logging.getLogger(__name__)


__all__ = [
    'NotificationKind',
    'send_notification',
    'clear_notification',
]


NotificationKind = Literal[
    'trial_7d', 'trial_3d', 'trial_1d',
    'payment_failed', 'suspended_warning',
]

_ALL_KINDS: frozenset[str] = frozenset({
    'trial_7d', 'trial_3d', 'trial_1d',
    'payment_failed', 'suspended_warning',
})


def send_notification(
    *,
    tenant: 'Tenant',
    kind: NotificationKind,
    owner_email: str | None = None,
    force: bool = False,
) -> bool:
    """Send a billing-lifecycle email to the tenant's owner.

    Args:
        tenant: the Tenant to notify. Used for body interpolation
            (name, slug, plan, trial dates) + recipient lookup.
        kind: which template to render. One of the NotificationKind
            string literals above.
        owner_email: optional explicit recipient. When omitted, the
            owner's email is resolved from the first active
            membership with role='owner'. Tests pass an explicit
            value to skip the lookup.
        force: bypass the ``notifications_sent`` idempotency check.
            Used for manual re-send actions; never set True in the
            cron jobs themselves.

    Returns:
        True if an email was queued for sending; False if skipped
        (already sent, no recipient, transport failure). NEVER
        raises — callers can iterate batches without guarding
        every call.

    HIPAA: emails dispatched by this function contain NO PHI. See
    module docstring for the full compliance framing.
    """
    if kind not in _ALL_KINDS:
        logger.error('send_notification called with unknown kind=%r', kind)
        return False

    sent_log = tenant.notifications_sent or {}
    if not force and kind in sent_log:
        logger.info(
            'notification.skip_already_sent tenant=%s kind=%s sent_at=%s',
            tenant.slug, kind, sent_log[kind],
        )
        return False

    recipient = owner_email or _resolve_owner_email(tenant)
    if not recipient:
        logger.warning(
            'notification.skip_no_owner_email tenant=%s kind=%s',
            tenant.slug, kind,
        )
        return False

    subject, body_text = _render(kind, tenant)
    if not subject:
        return False

    try:
        msg = EmailMultiAlternatives(
            subject=subject,
            body=body_text,
            from_email=_from_email(),
            to=[recipient],
        )
        msg.send(fail_silently=False)
    except Exception:  # noqa: BLE001 — never break the batch on one bad email
        logger.exception(
            'notification.send_failed tenant=%s kind=%s',
            tenant.slug, kind,
        )
        return False

    # Mark sent — atomic enough for daily-cron idempotency. The
    # JSONField rewrite is a single UPDATE on a single row.
    sent_log = dict(tenant.notifications_sent or {})
    sent_log[kind] = djtz.now().isoformat()
    tenant.notifications_sent = sent_log
    tenant.save(update_fields=['notifications_sent', 'updated_at'])

    record(
        action=AuditLog.Action.UPDATE,
        resource_type='tenant_notification',
        resource_id=tenant.id,
        tenant=tenant,
        metadata={
            'kind': kind,
            # Recipient domain only — same posture as SES bounce-
            # webhook audit logging. Full recipient address is in
            # SES delivery logs (also BAA-covered).
            'recipient_domain': recipient.split('@')[-1],
        },
    )
    return True


def clear_notification(*, tenant: 'Tenant', kind: NotificationKind) -> None:
    """Remove ``kind`` from ``tenant.notifications_sent`` so the next
    cron run will re-send. Called by the Stripe webhook handler when:

      - ``invoice.paid`` after a past_due → clears ``payment_failed``
      - Subscription period rolls (renewal) → clears all trial_* keys
        (defensive — should already be irrelevant by then)

    Always safe to call; no-op when the key isn't present.
    """
    sent_log = dict(tenant.notifications_sent or {})
    if kind in sent_log:
        del sent_log[kind]
        tenant.notifications_sent = sent_log
        tenant.save(update_fields=['notifications_sent', 'updated_at'])


# ── Template rendering ──────────────────────────────────────────────


def _render(kind: NotificationKind, tenant: 'Tenant') -> tuple[str, str]:
    """Pick the matching subject + body for ``kind``. Returns
    ``('', '')`` if anything goes wrong so the caller can skip the
    send cleanly. Inline templates (string literals) for v1 — when
    we add HTML versions + tenant-branded headers in a follow-up,
    extract into ``backend/templates/billing/<kind>.{txt,html}``."""
    product = _product_name()
    legal = _legal_name()
    subdomain = tenant.slug
    base_host = _crm_host()
    login_url = f'https://{subdomain}.{base_host}/login'
    billing_url = f'https://{subdomain}.{base_host}/org/billing'
    owner_first_name = _owner_first_name(tenant) or 'there'
    trial_date_str = _format_date(tenant.trial_ends_at)

    if kind == 'trial_7d':
        subject = f'Your {product} trial ends in 7 days'
        body = (
            f'Hi {owner_first_name},\n\n'
            f'Your 30-day free trial of {product} ends on {trial_date_str}.\n\n'
            f'On that date, your card will be charged for the plan you selected.\n'
            f'No action is needed to continue — your spa keeps running uninterrupted.\n\n'
            f'If you want to cancel, you can do so anytime in your billing\n'
            f'settings — no charge if you cancel before {trial_date_str}.\n\n'
            f'Manage billing: {billing_url}\n'
            f'Open workspace: {login_url}\n\n'
            f'Questions? Reply to this email or write support@lume-crm.com.\n\n'
            f'— The {product} team\n'
            f'({product} is a product of {legal}.)\n'
        )
        return subject, body

    if kind == 'trial_3d':
        subject = f'3 days left in your {product} trial'
        body = (
            f'Hi {owner_first_name},\n\n'
            f'Your free trial ends on {trial_date_str}. Three days from now,\n'
            f'your card on file will be charged for the plan you selected.\n\n'
            f'Nothing to do if you want to keep using {product} — your spa\n'
            f'continues seamlessly.\n\n'
            f'To cancel before the charge, visit billing: {billing_url}\n\n'
            f'— The {product} team\n'
            f'({product} is a product of {legal}.)\n'
        )
        return subject, body

    if kind == 'trial_1d':
        subject = f'Your {product} trial ends tomorrow'
        body = (
            f'Hi {owner_first_name},\n\n'
            f'Last reminder — your free trial ends tomorrow ({trial_date_str}).\n'
            f'Your card on file will be charged at that time.\n\n'
            f'Keep going: nothing to do.\n'
            f'Cancel: {billing_url} (before the charge clears).\n\n'
            f'Thanks for trying {product}.\n\n'
            f'— The {product} team\n'
            f'({product} is a product of {legal}.)\n'
        )
        return subject, body

    if kind == 'payment_failed':
        subject = f'Action needed: {product} payment failed'
        body = (
            f'Hi {owner_first_name},\n\n'
            f'We weren\'t able to charge your card on file for your {product}\n'
            f'subscription. Your workspace remains active for now, but will be\n'
            f'suspended in 7 days if payment isn\'t resolved.\n\n'
            f'Update your payment method here: {billing_url}\n\n'
            f'Common reasons charges fail:\n'
            f'  - Card expired\n'
            f'  - Insufficient funds\n'
            f'  - Bank flagged the charge as unusual (call the number on the\n'
            f'    back of your card to authorize)\n\n'
            f'Questions? Reply to this email.\n\n'
            f'— The {product} team\n'
            f'({product} is a product of {legal}.)\n'
        )
        return subject, body

    if kind == 'suspended_warning':
        subject = f'Final notice: your {product} workspace data will be deleted'
        body = (
            f'Hi {owner_first_name},\n\n'
            f'Your {product} workspace has been suspended for 45 days due to\n'
            f'a billing issue. Per our data-retention policy, if billing isn\'t\n'
            f'resolved in the next 15 days, your workspace data will be\n'
            f'permanently deleted.\n\n'
            f'This includes customer records, appointments, invoices, forms,\n'
            f'and clinical notes. Once deleted, this data cannot be recovered.\n\n'
            f'To restore your workspace immediately and preserve your data,\n'
            f'update your payment method: {billing_url}\n\n'
            f'If you intentionally cancelled and want to confirm deletion now,\n'
            f'reply to this email and we\'ll process it.\n\n'
            f'— The {product} team\n'
            f'({product} is a product of {legal}.)\n'
        )
        return subject, body

    return '', ''


# ── Helpers ─────────────────────────────────────────────────────────


def _resolve_owner_email(tenant: 'Tenant') -> str:
    """First active owner's email, or empty string. Falls back to
    tenant.billing_email if no owner found (rare edge case)."""
    owner_membership = (
        tenant.memberships
        .filter(role='owner', is_active=True)
        .select_related('user')
        .first()
    )
    if owner_membership and owner_membership.user.email:
        return owner_membership.user.email
    return (tenant.billing_email or '').strip()


def _owner_first_name(tenant: 'Tenant') -> str:
    owner_membership = (
        tenant.memberships
        .filter(role='owner', is_active=True)
        .select_related('user')
        .first()
    )
    if owner_membership:
        name = (owner_membership.user.first_name or '').strip()
        if name:
            return name
    return ''


def _format_date(value: dt.datetime | None) -> str:
    if value is None:
        return '(date not set)'
    # Tenant-agnostic format — "May 30, 2026". Locale-aware
    # formatting isn't worth the dependency for a transactional
    # email; English-only is acceptable for v1.
    return value.strftime('%B %-d, %Y')


def _product_name() -> str:
    return getattr(settings, 'BILLING_PRODUCT_NAME', 'Lumè CRM')


def _legal_name() -> str:
    return getattr(settings, 'BILLING_LEGAL_NAME', 'Voxtro LLC')


def _crm_host() -> str:
    """Bare host (no protocol) used to assemble subdomain URLs. The
    punycode form is what Stripe + email clients reliably handle;
    browsers display the accented form to users."""
    return getattr(settings, 'CRM_BASE_HOST', 'xn--lumcrm-5ua.com')


def _from_email() -> str:
    return getattr(
        settings, 'DEFAULT_FROM_EMAIL',
        'noreply@xn--lumcrm-5ua.com',
    )
