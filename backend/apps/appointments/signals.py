"""Post-save signals on Appointment.

The invoice-creation signal lives in `apps.invoices.signals` (cross-
app); this module hosts the appointment-side cascades:

  - Transactional SMS confirmation when a new appointment is
    scheduled (gated by customer SMS opt-in + phone). Synchronous
    so the audit log captures the send before the API response;
    Twilio errors are swallowed + logged so a Twilio outage
    doesn't fail an appointment booking.

Future hooks belong here: email-confirmation fallback signal,
calendar-rebroadcast events, etc.
"""

from __future__ import annotations

import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Appointment

logger = logging.getLogger(__name__)


_TERMINAL_STATUSES = frozenset({
    Appointment.Status.CANCELLED,
    Appointment.Status.NO_SHOW,
    Appointment.Status.COMPLETED,
})


@receiver(post_save, sender=Appointment, dispatch_uid='appointments.send_confirmation_sms')
def send_confirmation_sms_on_create(sender, instance: Appointment, created: bool, **kwargs):
    """Fire the SMS confirmation for a newly-created appointment.

    Only on CREATE — status transitions later (e.g. reschedule)
    aren't a new confirmation event. Terminal-status creates
    (someone seeding cancelled / completed historical data) skip
    too.

    Errors are caught + logged. A Twilio outage taking down
    appointment booking would be worse than the SMS not going out;
    operators can resend manually from the appointment detail page
    (UI follow-up).
    """
    if not created:
        return
    if instance.status in _TERMINAL_STATUSES:
        return
    # Critical: NEVER fire confirmation SMS for migration-imported
    # appointments. Imports create thousands of historical / future
    # rows in one shot; texting every customer about appointments
    # they made years ago (or appointments they already attended) is
    # a TCPA + customer-trust disaster. The importer also pre-fills
    # confirmation_sms_sent_at as a belt-and-suspenders backstop;
    # this check is the primary gate.
    if (instance.source or '').endswith('_import'):
        return

    # AI-driven bookings: send the formal confirmation with a 60-second
    # delay so the customer perceives the AI's instant "got it" ack
    # and the platform's official confirmation as two clean touches
    # rather than one duplicate. See apps/ai_inbox/agents/sms_agent.py
    # for the in-flow ack.
    #
    # Implementation: threading.Timer fires after transaction commits
    # so we don't send before the DB row is visible to other readers.
    # Failure mode: if the gunicorn worker is recycled within the 60s
    # window (deploy, scale-down), the timer dies and the customer
    # doesn't get the formal confirmation. Acceptable for v1 —
    # operators can resend manually from the appointment detail page.
    # v2 fix: persist to a delayed-jobs table + reap via an
    # EventBridge cron.
    if instance.source == 'sms_ai':
        import threading
        from django.db import transaction

        appt_id = instance.pk

        def _send_delayed():
            _safe_send_by_id(appt_id)

        def _arm_timer():
            timer = threading.Timer(60.0, _send_delayed)
            timer.daemon = True   # don't block worker shutdown
            timer.start()

        transaction.on_commit(_arm_timer)
        return

    _safe_send(instance)


def _safe_send(appointment: Appointment) -> None:
    """Send the confirmation, swallowing transport + unexpected errors."""
    from .sms import SMSDispatchError, send_confirmation_sms
    try:
        send_confirmation_sms(appointment)
    except SMSDispatchError as e:
        logger.exception(
            'appointment_sms.confirmation.failed',
            extra={'appointment_id': appointment.pk, 'twilio_error': str(e)},
        )
    except Exception:
        # Belt + suspenders — anything we didn't anticipate also
        # gets swallowed so the appointment commit isn't reverted.
        logger.exception(
            'appointment_sms.confirmation.unexpected',
            extra={'appointment_id': appointment.pk},
        )


def _safe_send_by_id(appointment_id: int) -> None:
    """Re-fetch + send. Used by the 60-second delayed branch — by the
    time the Timer fires, the in-memory `instance` may be stale
    (someone could have cancelled the appointment), so re-fetch from
    the DB to guarantee we don't send confirmations for already-cancelled
    rows.
    """
    try:
        appt = Appointment.objects.get(pk=appointment_id)
    except Appointment.DoesNotExist:
        logger.warning(
            'appointment_sms.delayed_send.appointment_gone',
            extra={'appointment_id': appointment_id},
        )
        return
    if appt.status in _TERMINAL_STATUSES:
        logger.info(
            'appointment_sms.delayed_send.skipped_terminal',
            extra={'appointment_id': appointment_id, 'status': appt.status},
        )
        return
    _safe_send(appt)
