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

    from .sms import SMSDispatchError, send_confirmation_sms

    try:
        send_confirmation_sms(instance)
    except SMSDispatchError as e:
        logger.exception(
            'appointment_sms.confirmation.failed',
            extra={'appointment_id': instance.pk, 'twilio_error': str(e)},
        )
    except Exception:
        # Belt + suspenders — anything we didn't anticipate also
        # gets swallowed so the appointment commit isn't reverted.
        logger.exception(
            'appointment_sms.confirmation.unexpected',
            extra={'appointment_id': instance.pk},
        )
