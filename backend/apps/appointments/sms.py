"""Appointment SMS — confirmations + reminders.

Two transactional flows here, both calling the same low-level
`send_sms()` helper that wraps the Twilio SDK:

  - `send_confirmation_sms(appointment)` — fires from the
    `post_save` signal when a new appointment is created with a
    customer who has `sms_opt_in=True` + a phone number on file.
    Idempotent on `Appointment.confirmation_sms_sent_at`.

  - `send_reminder_sms(appointment)` — invoked by the
    `manage.py send_appointment_reminders` command for cron use.
    Idempotent on `Appointment.reminder_sms_sent_at`.

Why a separate path from `apps.marketing.sender._dispatch_one`:

  - Transactional SMS uses `Customer.sms_opt_in` (booking-flow
    consent), not `sms_marketing_opt_in` (promotional). Operators
    expect appointment SMS to ride alongside booking even if the
    client has unsubscribed from marketing.
  - No quiet-hours window (TCPA exempts appointment reminders).
  - No unsubscribe token (the customer can't opt out of their own
    appointment confirmation).
  - No `MarketingSendLog` row (this isn't marketing data).
  - Audit trail lives on the Appointment row itself (`*_sent_at` +
    `*_provider_id`) plus an `AuditLog` entry per send.

HIPAA: Twilio BAA covers this surface. The SMS body unavoidably
carries PHI (customer first name + appointment time + spa
identity). All within the TPO (Treatment / Payment / Operations)
exception per 45 CFR 164.506.

See ADR 0021 for the design rationale.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.utils import timezone as djtz

logger = logging.getLogger(__name__)


# ── Low-level Twilio send ────────────────────────────────────────────


class SMSDispatchError(Exception):
    """Raised when an SMS dispatch fails for a non-business reason
    (Twilio API rejection, provider unavailable). Business-reason
    skips (no consent, no phone, already sent) return False from the
    caller-facing functions instead."""


def _twilio_creds_ready() -> bool:
    """SID + auth token present in env. The from-number is resolved
    per-tenant now (see `_resolve_from_number`), so it isn't part of
    the global-readiness check anymore."""
    return all([
        getattr(settings, 'TWILIO_ACCOUNT_SID', None),
        getattr(settings, 'TWILIO_AUTH_TOKEN', None),
    ])


def _resolve_from_number(tenant) -> str:
    """Resolve the From: TFN for `tenant`. Per-tenant assignment first
    (so each spa carries its own number for reputation isolation +
    branded local-area identity), falling back to the platform-
    default `settings.TWILIO_FROM_NUMBER` for tenants whose number
    hasn't been provisioned yet. Empty string when neither is set —
    caller treats that as a "skip, no sender available" state."""
    per_tenant = (getattr(tenant, 'twilio_from_number', '') or '').strip()
    if per_tenant:
        return per_tenant
    return (getattr(settings, 'TWILIO_FROM_NUMBER', '') or '').strip()


def send_sms(*, tenant, to: str, body: str) -> str:
    """Send a single SMS via Twilio and return the provider Message
    SID. Raises `SMSDispatchError` if the Twilio call fails.

    The From: number is resolved per-tenant via
    `tenant.twilio_from_number` with fallback to
    `settings.TWILIO_FROM_NUMBER`. When neither is set the call
    is skipped (returns `''`) — same posture as missing SID/token.

    Returns `''` (empty SID) and logs a warning when Twilio isn't
    configured. Lets the rest of the system run end-to-end in dev
    without TWILIO_* set.
    """
    if not _twilio_creds_ready():
        logger.warning(
            'sms.send.skipped: TWILIO_ACCOUNT_SID/AUTH_TOKEN not set; would have sent to %s',
            _phone_redact(to),
        )
        return ''

    from_number = _resolve_from_number(tenant)
    if not from_number:
        logger.warning(
            'sms.send.skipped: tenant=%s has no twilio_from_number and no platform default; recipient %s',
            tenant.slug, _phone_redact(to),
        )
        return ''

    from twilio.base.exceptions import TwilioRestException
    from twilio.rest import Client

    client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
    kwargs = {
        'from_': from_number,
        'to': to,
        'body': body,
    }
    if getattr(settings, 'TWILIO_STATUS_CALLBACK_URL', ''):
        kwargs['status_callback'] = settings.TWILIO_STATUS_CALLBACK_URL

    try:
        tw_msg = client.messages.create(**kwargs)
    except TwilioRestException as e:
        raise SMSDispatchError(f'twilio:{e.code} {e.msg}') from e

    # Bump the tenant's current-period SMS counter so /org/billing's
    # usage display + the Stripe metered-overage report at period
    # roll reflect this send. Best-effort: never raises (a counter
    # miss is preferred to a Twilio call that succeeded but recorded
    # as a failed send). See apps.tenants.usage.
    from apps.tenants.usage import increment_sms_count
    increment_sms_count(tenant)

    return tw_msg.sid


def _phone_redact(phone: str) -> str:
    """Show only the last 4 digits when logging — full numbers in
    application logs would land in CloudWatch + index a PII surface
    that's expensive to redact later."""
    digits = ''.join(ch for ch in (phone or '') if ch.isdigit())
    return f'***-***-{digits[-4:]}' if len(digits) >= 4 else '***'


def _mirror_automated_to_inbox(*, appointment, kind: str, body: str, sid: str) -> None:
    """Write a `messaging.Message` row mirroring an automated send.

    The transactional-SMS path lives in this module because it has
    distinct consent / quiet-hours / template semantics from manual
    sends. But the customer experiences ALL these messages as one
    thread on their phone — there's no separation at the SMS layer.
    Mirroring into the inbox keeps the operator's view of the thread
    truthful: they can scroll up and see the confirmation that went
    out, then the customer's reply, then the reminder, all in one
    chronological flow.

    Idempotency is already enforced by the caller (won't be invoked
    twice for the same appointment-kind combination), so this just
    writes the row.
    """
    from apps.messaging.models import Direction, Message, MessageKind, MessageStatus

    customer = appointment.customer
    tenant = appointment.tenant
    from_number = _resolve_from_number(tenant)
    Message.objects.create(
        tenant=tenant,
        customer=customer,
        direction=Direction.OUTBOUND,
        kind=kind,
        body=body,
        status=MessageStatus.SENT if sid else MessageStatus.QUEUED,
        provider_message_id=sid,
        from_number=from_number,
        to_number=(customer.phone or '').strip(),
        sent_at=djtz.now() if sid else None,
    )


# Map from internal `kind` strings (used in audit logs + this module)
# to the public MessageKind values mirrored into the inbox.
_AUDIT_KIND_TO_MESSAGE_KIND = {
    'confirmation': 'confirmation',
    'reminder': 'reminder',
    'review_request': 'review_request',
}


# ── Body renderers ───────────────────────────────────────────────────


def _format_appt_time(appointment) -> str:
    """Render the appointment's start_time in the appointment's
    location's timezone. Falls back to UTC if no tz is set — better
    a slightly-off time string than a crash on send."""
    import zoneinfo

    tz_name = (
        appointment.location.timezone
        if appointment.location_id and appointment.location.timezone
        else 'UTC'
    )
    try:
        tz = zoneinfo.ZoneInfo(tz_name)
    except zoneinfo.ZoneInfoNotFoundError:
        tz = zoneinfo.ZoneInfo('UTC')

    local = appointment.start_time.astimezone(tz)
    # "Mon, May 15 at 2:00 PM"
    return local.strftime('%a, %b %-d at %-I:%M %p')


# Default bodies — shipped when the tenant hasn't customized.
#
# Bodies are intentionally short. Twilio segments at 160 chars (GSM-7)
# or 70 chars (UCS-2); over-length texts split into multiple billable
# segments + are more likely to be filtered by carriers. Keep it tight.

DEFAULT_CONFIRMATION_BODY = (
    'Hi {{first_name}}, your appointment at {{spa_name}} is '
    'confirmed for {{appointment_time}}. Reply STOP to opt out.'
)
DEFAULT_REMINDER_BODY = (
    'Hi {{first_name}}, reminder: your appointment at {{spa_name}} '
    'is tomorrow ({{appointment_time}}). Reply STOP to opt out.'
)
DEFAULT_REVIEW_REQUEST_BODY = (
    'Hi {{first_name}}, thanks for visiting {{spa_name}}! Would you '
    'mind leaving us a review? {{review_url}} Reply STOP to opt out.'
)

# Tokens recognised at render time. Anything not in this set is left
# as-is (so a tenant who pastes "{{my_typo}}" sees their typo in the
# message and can fix it). Token substitution is a literal
# `str.replace` — never call any Python expression from operator text.


def render_template(template: str, *, appointment, review_url: str = '') -> str:
    """Substitute appointment context into `template`. Used by all
    three automated-SMS surfaces (confirmation + reminder + review
    request). The `review_url` token is review-only; pass empty
    string from the other two paths."""
    customer = appointment.customer
    spa = appointment.tenant.name
    when = _format_appt_time(appointment)
    return (
        template
        .replace('{{first_name}}', customer.first_name)
        .replace('{{spa_name}}', spa)
        .replace('{{appointment_time}}', when)
        .replace('{{review_url}}', review_url)
    )


def render_confirmation_body(appointment) -> str:
    """Resolve the tenant's confirmation template (empty falls back
    to the platform default) and substitute tokens."""
    template = (appointment.tenant.confirmation_sms_template or '').strip() or DEFAULT_CONFIRMATION_BODY
    return render_template(template, appointment=appointment)


def render_reminder_body(appointment) -> str:
    """Resolve the tenant's 24h reminder template and substitute
    tokens."""
    template = (appointment.tenant.reminder_sms_template or '').strip() or DEFAULT_REMINDER_BODY
    return render_template(template, appointment=appointment)


def render_review_request_body(appointment) -> str:
    """Resolve the tenant's review-request template, substituting
    `{{review_url}}` with the tenant's Google review URL."""
    template = (appointment.tenant.review_request_sms_template or '').strip() or DEFAULT_REVIEW_REQUEST_BODY
    review_url = (appointment.tenant.google_review_url or '').strip()
    return render_template(template, appointment=appointment, review_url=review_url)


# ── Caller-facing entry points ───────────────────────────────────────


def _can_send_appointment_sms(appointment) -> tuple[bool, str | None]:
    """Common consent + reachability check.

    Returns `(can_send, skip_reason)`. `skip_reason` is None when
    sendable; otherwise a short identifier the audit log records.
    """
    customer = appointment.customer
    if customer is None:
        return False, 'no_customer'
    if not (customer.phone or '').strip():
        return False, 'no_phone'
    if not customer.sms_opt_in:
        return False, 'no_consent_transactional'
    if getattr(customer, 'sms_marketing_suppressed_at', None) is not None:
        # Hard-bounce or complaint on this number — don't keep sending.
        return False, 'suppressed'
    return True, None


def send_confirmation_sms(appointment) -> bool:
    """Send the just-booked confirmation SMS for `appointment`.
    Returns True if a Twilio call was made + the row was updated;
    False if skipped (no consent, no phone, already sent).

    Idempotent: a row with `confirmation_sms_sent_at IS NOT NULL`
    is a no-op return. Exceptions from Twilio propagate as
    `SMSDispatchError` — the signal handler's job to decide
    whether to swallow them so a Twilio outage doesn't fail an
    appointment booking.
    """
    from apps.audit.models import AuditLog
    from apps.audit.services import record

    if appointment.confirmation_sms_sent_at is not None:
        return False

    can_send, reason = _can_send_appointment_sms(appointment)
    if not can_send:
        record(
            action=AuditLog.Action.UPDATE,
            resource_type='appointment_sms',
            resource_id=appointment.id,
            metadata={
                'kind': 'confirmation',
                'outcome': 'skipped',
                'reason': reason,
            },
        )
        return False

    body = render_confirmation_body(appointment)
    sid = send_sms(tenant=appointment.tenant, to=appointment.customer.phone, body=body)

    # Stamp the audit row even when Twilio wasn't wired up (sid='') —
    # we want to know the SEND ATTEMPT happened so a redeploy with
    # creds doesn't double-send.
    appointment.confirmation_sms_sent_at = djtz.now()
    appointment.confirmation_sms_provider_id = sid
    appointment.save(update_fields=['confirmation_sms_sent_at', 'confirmation_sms_provider_id'])

    # Mirror into the customer's inbox thread so the operator can see
    # exactly what the customer saw, interleaved with any manual
    # replies. See `_mirror_automated_to_inbox` for the rationale.
    _mirror_automated_to_inbox(
        appointment=appointment, kind='confirmation', body=body, sid=sid,
    )

    record(
        action=AuditLog.Action.UPDATE,
        resource_type='appointment_sms',
        resource_id=appointment.id,
        metadata={
            'kind': 'confirmation',
            'outcome': 'sent' if sid else 'stub_no_provider',
            'recipient_last4': _phone_redact(appointment.customer.phone)[-4:],
            'provider_message_id': sid,
        },
    )
    return True


def send_reminder_sms(appointment) -> bool:
    """Send the 24h reminder for `appointment`. Same idempotency +
    consent posture as the confirmation path; tracked under
    `reminder_sms_*` fields instead."""
    from apps.audit.models import AuditLog
    from apps.audit.services import record

    if appointment.reminder_sms_sent_at is not None:
        return False

    can_send, reason = _can_send_appointment_sms(appointment)
    if not can_send:
        record(
            action=AuditLog.Action.UPDATE,
            resource_type='appointment_sms',
            resource_id=appointment.id,
            metadata={
                'kind': 'reminder',
                'outcome': 'skipped',
                'reason': reason,
            },
        )
        return False

    body = render_reminder_body(appointment)
    sid = send_sms(tenant=appointment.tenant, to=appointment.customer.phone, body=body)

    appointment.reminder_sms_sent_at = djtz.now()
    appointment.reminder_sms_provider_id = sid
    appointment.save(update_fields=['reminder_sms_sent_at', 'reminder_sms_provider_id'])

    _mirror_automated_to_inbox(
        appointment=appointment, kind='reminder', body=body, sid=sid,
    )

    record(
        action=AuditLog.Action.UPDATE,
        resource_type='appointment_sms',
        resource_id=appointment.id,
        metadata={
            'kind': 'reminder',
            'outcome': 'sent' if sid else 'stub_no_provider',
            'recipient_last4': _phone_redact(appointment.customer.phone)[-4:],
            'provider_message_id': sid,
        },
    )
    return True


def send_review_request_sms(appointment) -> bool:
    """Send the post-appointment review-request SMS.

    Gates beyond the shared consent check:

    - Tenant must have `review_request_enabled = True` (explicit
      opt-in — defaults False so tenants don't accidentally send
      reviews requests on day one).
    - Tenant must have `google_review_url` set (a review request
      with a broken/missing link is worse than no request at all —
      we'd train the customer to ignore the spa's texts).
    - Appointment must be in `completed` status (not cancelled, not
      no-show, not pending).

    Idempotency: `review_request_sms_sent_at` is the boundary.
    """
    from apps.audit.models import AuditLog
    from apps.audit.services import record
    from .models import Appointment

    if appointment.review_request_sms_sent_at is not None:
        return False

    tenant = appointment.tenant
    if not getattr(tenant, 'review_request_enabled', False):
        record(
            action=AuditLog.Action.UPDATE,
            resource_type='appointment_sms',
            resource_id=appointment.id,
            metadata={'kind': 'review_request', 'outcome': 'skipped', 'reason': 'tenant_disabled'},
        )
        return False
    if not (tenant.google_review_url or '').strip():
        record(
            action=AuditLog.Action.UPDATE,
            resource_type='appointment_sms',
            resource_id=appointment.id,
            metadata={'kind': 'review_request', 'outcome': 'skipped', 'reason': 'no_review_url'},
        )
        return False
    if appointment.status != Appointment.Status.COMPLETED:
        record(
            action=AuditLog.Action.UPDATE,
            resource_type='appointment_sms',
            resource_id=appointment.id,
            metadata={'kind': 'review_request', 'outcome': 'skipped', 'reason': 'not_completed'},
        )
        return False

    can_send, reason = _can_send_appointment_sms(appointment)
    if not can_send:
        record(
            action=AuditLog.Action.UPDATE,
            resource_type='appointment_sms',
            resource_id=appointment.id,
            metadata={'kind': 'review_request', 'outcome': 'skipped', 'reason': reason},
        )
        return False

    body = render_review_request_body(appointment)
    sid = send_sms(tenant=tenant, to=appointment.customer.phone, body=body)

    appointment.review_request_sms_sent_at = djtz.now()
    appointment.review_request_sms_provider_id = sid
    appointment.save(update_fields=[
        'review_request_sms_sent_at', 'review_request_sms_provider_id',
    ])

    _mirror_automated_to_inbox(
        appointment=appointment, kind='review_request', body=body, sid=sid,
    )

    record(
        action=AuditLog.Action.UPDATE,
        resource_type='appointment_sms',
        resource_id=appointment.id,
        metadata={
            'kind': 'review_request',
            'outcome': 'sent' if sid else 'stub_no_provider',
            'recipient_last4': _phone_redact(appointment.customer.phone)[-4:],
            'provider_message_id': sid,
        },
    )
    return True
