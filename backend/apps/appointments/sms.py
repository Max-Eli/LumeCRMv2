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


def _twilio_ready() -> bool:
    """Mirror of `apps.marketing.sender._sms_provider_ready` — we
    can't import directly because the marketing path's import graph
    is heavier than we need here, and inlining a 3-line check is
    cheaper than coupling the two modules."""
    return all([
        getattr(settings, 'TWILIO_ACCOUNT_SID', None),
        getattr(settings, 'TWILIO_AUTH_TOKEN', None),
        getattr(settings, 'TWILIO_FROM_NUMBER', None),
    ])


def send_sms(*, to: str, body: str) -> str:
    """Send a single SMS via Twilio and return the provider Message
    SID. Raises `SMSDispatchError` if the Twilio call fails.

    Returns `''` (empty SID) and logs a warning when Twilio isn't
    configured — caller treats that as a "skipped, env not wired
    yet" state. Lets the rest of the system run end-to-end in dev
    without TWILIO_* set.
    """
    if not _twilio_ready():
        logger.warning(
            'sms.send.skipped: TWILIO_* env not set; would have sent to %s',
            _phone_redact(to),
        )
        return ''

    from twilio.base.exceptions import TwilioRestException
    from twilio.rest import Client

    client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
    kwargs = {
        'from_': settings.TWILIO_FROM_NUMBER,
        'to': to,
        'body': body,
    }
    if getattr(settings, 'TWILIO_STATUS_CALLBACK_URL', ''):
        kwargs['status_callback'] = settings.TWILIO_STATUS_CALLBACK_URL

    try:
        tw_msg = client.messages.create(**kwargs)
    except TwilioRestException as e:
        raise SMSDispatchError(f'twilio:{e.code} {e.msg}') from e

    return tw_msg.sid


def _phone_redact(phone: str) -> str:
    """Show only the last 4 digits when logging — full numbers in
    application logs would land in CloudWatch + index a PII surface
    that's expensive to redact later."""
    digits = ''.join(ch for ch in (phone or '') if ch.isdigit())
    return f'***-***-{digits[-4:]}' if len(digits) >= 4 else '***'


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


def render_confirmation_body(appointment) -> str:
    """Render the appointment confirmation SMS body. Hardcoded for
    v1 — tenant-customizable templates land later (Phase 1H
    notification templates).

    Body is intentionally short. Twilio segments at 160 chars (GSM-7)
    or 70 chars (UCS-2 / Unicode); over-length texts split into
    multiple billable segments + are more likely to be filtered by
    carriers. Keep it tight.
    """
    customer = appointment.customer
    when = _format_appt_time(appointment)
    spa = appointment.tenant.name
    return (
        f'Hi {customer.first_name}, your appointment at {spa} is '
        f'confirmed for {when}. Reply STOP to opt out.'
    )


def render_reminder_body(appointment) -> str:
    """Render the 24h-out appointment reminder body."""
    customer = appointment.customer
    when = _format_appt_time(appointment)
    spa = appointment.tenant.name
    return (
        f'Hi {customer.first_name}, reminder: your appointment at '
        f'{spa} is tomorrow ({when}). Reply STOP to opt out.'
    )


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
    sid = send_sms(to=appointment.customer.phone, body=body)

    # Stamp the audit row even when Twilio wasn't wired up (sid='') —
    # we want to know the SEND ATTEMPT happened so a redeploy with
    # creds doesn't double-send.
    appointment.confirmation_sms_sent_at = djtz.now()
    appointment.confirmation_sms_provider_id = sid
    appointment.save(update_fields=['confirmation_sms_sent_at', 'confirmation_sms_provider_id'])

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
    sid = send_sms(to=appointment.customer.phone, body=body)

    appointment.reminder_sms_sent_at = djtz.now()
    appointment.reminder_sms_provider_id = sid
    appointment.save(update_fields=['reminder_sms_sent_at', 'reminder_sms_provider_id'])

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
