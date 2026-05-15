"""Management command — send 24h-out appointment reminders.

Invoked by an external scheduler (EventBridge → ECS RunTask, or a
plain cron). Idempotent: runs every 30 minutes and only sends to
appointments that:

  - Haven't already had a reminder sent (`reminder_sms_sent_at IS NULL`)
  - Are still in a sendable status (not cancelled / completed / no-show)
  - Start within the next 23–25 hour window (the ±1h slop lets the
    cron be late or early without missing anyone)

Outputs structured logs so ECS CloudWatch + the audit log together
form the operational record.

Usage:

    python manage.py send_appointment_reminders
    python manage.py send_appointment_reminders --window-hours 24 --slop-hours 1
    python manage.py send_appointment_reminders --dry-run
"""

from __future__ import annotations

import datetime as dt
import logging

from django.core.management.base import BaseCommand
from django.utils import timezone as djtz

from apps.appointments.models import Appointment
from apps.appointments.sms import SMSDispatchError, send_reminder_sms

logger = logging.getLogger(__name__)


# Statuses that mean "still a real upcoming appointment." Cancelled
# + no-show + completed all skip the reminder (the operator already
# either knows or doesn't care).
_SENDABLE_STATUSES = (
    Appointment.Status.BOOKED,
    Appointment.Status.CONFIRMED,
    Appointment.Status.CHECKED_IN,
)


class Command(BaseCommand):
    help = 'Send 24h-out SMS reminders for appointments starting within the window.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--window-hours', type=int, default=24,
            help='Target lead time before appointment start (default 24).',
        )
        parser.add_argument(
            '--slop-hours', type=int, default=1,
            help=(
                'Tolerance ± around `window_hours`. With the default 1, a 24h '
                'reminder fires for any appointment 23–25 hours out. Wider '
                'slop catches appointments missed by a delayed cron run.'
            ),
        )
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Log which appointments would be sent without calling Twilio.',
        )

    def handle(self, *args, window_hours, slop_hours, dry_run, **opts):
        now = djtz.now()
        target = now + dt.timedelta(hours=window_hours)
        window_start = target - dt.timedelta(hours=slop_hours)
        window_end = target + dt.timedelta(hours=slop_hours)

        qs = (
            Appointment.objects
            .filter(
                reminder_sms_sent_at__isnull=True,
                status__in=_SENDABLE_STATUSES,
                start_time__gte=window_start,
                start_time__lte=window_end,
            )
            .select_related('customer', 'tenant', 'location')
        )

        total = qs.count()
        self.stdout.write(
            self.style.NOTICE(
                f'reminder.run: window={window_start:%Y-%m-%d %H:%M}'
                f' to {window_end:%Y-%m-%d %H:%M}, candidates={total}, '
                f'dry_run={dry_run}'
            ),
        )

        sent = 0
        skipped = 0
        failed = 0

        for appointment in qs.iterator():
            if dry_run:
                self.stdout.write(
                    f'  would send #{appointment.pk} → tenant={appointment.tenant.slug} '
                    f'start={appointment.start_time:%Y-%m-%d %H:%M}'
                )
                continue

            try:
                fired = send_reminder_sms(appointment)
                if fired:
                    sent += 1
                else:
                    # No-consent / no-phone / already-sent skip — the
                    # underlying helper writes the audit-log entry
                    # with the reason. Don't double-log here.
                    skipped += 1
            except SMSDispatchError:
                # Logged inside send_reminder_sms via Twilio exception
                # handling. Counting at this level for the summary.
                logger.exception(
                    'reminder.send.twilio_error',
                    extra={'appointment_id': appointment.pk},
                )
                failed += 1
            except Exception:
                # Anything else: keep iterating so one busted row
                # doesn't stop the rest of the batch.
                logger.exception(
                    'reminder.send.unexpected',
                    extra={'appointment_id': appointment.pk},
                )
                failed += 1

        self.stdout.write(self.style.SUCCESS(
            f'reminder.done: sent={sent}, skipped={skipped}, failed={failed}, '
            f'total_candidates={total}'
        ))
