"""Daily cron — send trial-ending reminder emails (7d / 3d / 1d).

Invoked by EventBridge → ECS RunTask (or any cron). Matches the
established pattern from ``apps.appointments.management.commands.send_appointment_reminders``.

For each tenant in TRIAL status, check whether ``trial_ends_at``
falls within a 7-day / 3-day / 1-day window from "now." If so AND
we haven't already sent the matching reminder, dispatch it via
``apps.billing.notifications.send_notification``.

Idempotency:

  Each notification kind ('trial_7d', 'trial_3d', 'trial_1d') is
  tracked on ``Tenant.notifications_sent``. ``send_notification``
  skips when the key is already set, so a daily cron firing multiple
  times within the window won't duplicate. The ±1-day slop on each
  window means cron lateness up to 24 hours won't miss a tenant.

HIPAA + audit:

  Emails sent contain NO PHI (see notifications.py docstring). Every
  send writes an ``apps.audit.AuditLog`` row. Failures are logged
  but don't halt the batch — one bad email doesn't take down the
  cron run.

Usage:

    python manage.py send_trial_reminders
    python manage.py send_trial_reminders --dry-run
    python manage.py send_trial_reminders --tenant <slug>   # one tenant only
"""

from __future__ import annotations

import datetime as dt
import logging

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone as djtz

from apps.billing.notifications import send_notification
from apps.tenants.models import Tenant

logger = logging.getLogger(__name__)


# Each entry: (notification_kind, days_to_end, slop_hours). The window
# is [days_to_end - slop, days_to_end + slop] so cron lateness up to
# ±12h doesn't miss a tenant. 12h slop is wider than the daily
# cadence (24h), guaranteeing each tenant hits each window at least
# once.
_REMINDER_WINDOWS = (
    ('trial_7d', 7, 12),
    ('trial_3d', 3, 12),
    ('trial_1d', 1, 12),
)


class Command(BaseCommand):
    help = 'Send trial-ending reminder emails (7d / 3d / 1d before trial_ends_at).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help="Report what would be sent without actually sending.",
        )
        parser.add_argument(
            '--tenant',
            help='Limit to one tenant slug. Useful for ops re-issues.',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        single_slug = options.get('tenant')

        qs = Tenant.objects.filter(
            status=Tenant.Status.TRIAL,
            grandfathered=False,
            trial_ends_at__isnull=False,
        )
        if single_slug:
            qs = qs.filter(slug=single_slug)
            if not qs.exists():
                raise CommandError(f'No trial tenant with slug={single_slug!r}.')

        now = djtz.now()
        counts = {kind: 0 for kind, _, _ in _REMINDER_WINDOWS}
        counts['skipped'] = 0
        counts['failed'] = 0

        for tenant in qs.iterator():
            kind = _matching_window(tenant.trial_ends_at, now)
            if kind is None:
                counts['skipped'] += 1
                continue
            if dry_run:
                self.stdout.write(
                    f'[dry-run] would send {kind} to {tenant.slug} '
                    f'(trial_ends_at={tenant.trial_ends_at.isoformat()})'
                )
                counts[kind] += 1
                continue
            try:
                sent = send_notification(tenant=tenant, kind=kind)
            except Exception:  # noqa: BLE001
                logger.exception(
                    'send_trial_reminders.send_failed tenant=%s kind=%s',
                    tenant.slug, kind,
                )
                counts['failed'] += 1
                continue
            if sent:
                counts[kind] += 1
            else:
                # send_notification returned False — already-sent
                # idempotency check OR transport failure (logged
                # inside the function).
                counts['skipped'] += 1

        verb = 'would send' if dry_run else 'sent'
        self.stdout.write(self.style.SUCCESS(
            f'Trial reminders complete: {verb} '
            f'{counts["trial_7d"]}x 7d + {counts["trial_3d"]}x 3d + '
            f'{counts["trial_1d"]}x 1d (skipped {counts["skipped"]}, '
            f'failed {counts["failed"]}).'
        ))


def _matching_window(
    trial_ends_at: dt.datetime,
    now: dt.datetime,
) -> str | None:
    """Which reminder kind matches the current distance to
    ``trial_ends_at``? Returns the kind, or None if no window
    matches. Uses ±slop_hours so cron lateness doesn't miss anyone.

    Order matters: we prefer the LATEST applicable window (the
    closer-to-end one). That way a tenant 7d 6h out gets the trial_7d
    reminder; a tenant 7d 1h out still gets trial_7d; a tenant
    3d 13h out gets trial_3d (not trial_7d) because the 3d window
    is closer.
    """
    delta = trial_ends_at - now
    hours_left = delta.total_seconds() / 3600.0
    for kind, days, slop in _REMINDER_WINDOWS:
        center = days * 24.0
        if abs(hours_left - center) <= slop:
            return kind
    return None
