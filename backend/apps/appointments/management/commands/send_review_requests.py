"""Management command — send post-appointment review-request SMS.

Invoked by an external scheduler (EventBridge → ECS RunTask, or a
plain cron). Recommended cadence: every 30 minutes, same as the
reminder runner.

For each tenant that has `review_request_enabled = True` AND a
`google_review_url` set, finds completed appointments whose
`completed_at` is between `(hours_after - slop)` and
`(hours_after + slop)` ago and that haven't yet had a review-request
SMS sent. Per-tenant gating means a tenant can't accidentally send
reviews before they've configured the destination URL.

Output: same structured log shape as `send_appointment_reminders`.

Usage:

    python manage.py send_review_requests
    python manage.py send_review_requests --slop-hours 2
    python manage.py send_review_requests --dry-run
"""

from __future__ import annotations

import datetime as dt
import logging

from django.core.management.base import BaseCommand
from django.utils import timezone as djtz

from apps.appointments.models import Appointment
from apps.appointments.sms import SMSDispatchError, send_review_request_sms
from apps.tenants.models import Tenant

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Send post-appointment review-request SMS for completed appointments.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--slop-hours', type=int, default=1,
            help=(
                'Tolerance ± around the tenant\'s '
                '`review_request_hours_after`. Wider slop catches '
                'appointments missed by a delayed cron run.'
            ),
        )
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Log which appointments would be sent without calling Twilio.',
        )

    def handle(self, *args, slop_hours, dry_run, **opts):
        now = djtz.now()

        # The hours-after window is per-tenant (each spa decides how
        # long after completion to ask). Iterate tenants, then their
        # eligible appointments, so the window math reads cleanly.
        enabled_tenants = (
            Tenant.objects
            .filter(review_request_enabled=True)
            .exclude(google_review_url='')
        )
        total_candidates = 0
        sent = 0
        skipped = 0
        failed = 0

        for tenant in enabled_tenants:
            hours_after = tenant.review_request_hours_after or 24
            target = now - dt.timedelta(hours=hours_after)
            window_start = target - dt.timedelta(hours=slop_hours)
            window_end = target + dt.timedelta(hours=slop_hours)

            qs = (
                Appointment.objects
                .filter(
                    tenant=tenant,
                    status=Appointment.Status.COMPLETED,
                    review_request_sms_sent_at__isnull=True,
                    completed_at__gte=window_start,
                    completed_at__lte=window_end,
                )
                # Skip migration-imported appointments — see
                # signals.py + send_appointment_reminders. Imports
                # land thousands of "completed" rows in bulk; a
                # review-request blast against years-old visits is
                # spammy + TCPA-risky.
                .exclude(source__endswith='_import')
                .select_related('customer', 'tenant', 'location')
            )

            tenant_count = qs.count()
            total_candidates += tenant_count
            self.stdout.write(self.style.NOTICE(
                f'review.run: tenant={tenant.slug} '
                f'window={window_start:%Y-%m-%d %H:%M} to {window_end:%Y-%m-%d %H:%M}, '
                f'candidates={tenant_count}, dry_run={dry_run}'
            ))

            for appointment in qs.iterator():
                if dry_run:
                    self.stdout.write(
                        f'  would send #{appointment.pk} → tenant={tenant.slug} '
                        f'completed={appointment.completed_at:%Y-%m-%d %H:%M}'
                    )
                    continue

                try:
                    fired = send_review_request_sms(appointment)
                    if fired:
                        sent += 1
                    else:
                        skipped += 1
                except SMSDispatchError:
                    logger.exception(
                        'review.send.twilio_error',
                        extra={'appointment_id': appointment.pk},
                    )
                    failed += 1
                except Exception:
                    logger.exception(
                        'review.send.unexpected',
                        extra={'appointment_id': appointment.pk},
                    )
                    failed += 1

        self.stdout.write(self.style.SUCCESS(
            f'review.done: sent={sent}, skipped={skipped}, failed={failed}, '
            f'total_candidates={total_candidates}'
        ))
