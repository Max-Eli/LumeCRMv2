"""Daily cron — payment-failure dunning + lifecycle transitions.

Three responsibilities, all idempotent:

  1. **payment_failed reminder** — for every tenant currently in
     PAST_DUE, send a "card declined, update payment" email if we
     haven't already (per the notifications_sent tracker). Stripe's
     own webhook lands the first ``invoice.payment_failed`` event;
     this cron re-arms the reminder if the tenant stays past_due
     longer than expected.

  2. **past_due → suspended** — tenants in PAST_DUE for more than
     7 days flip to SUSPENDED. Workspace becomes read-only (the
     LifecycleBanner shifts to the rose tone; future work locks
     write endpoints in middleware). Stripe-side, the subscription
     remains active until Stripe itself cancels at its retry
     schedule's end.

  3. **suspended_warning at 45 days** — tenants in SUSPENDED for 45
     days get a "data will be deleted in 15 days" notice. Final
     deletion at day 60 is intentionally NOT in this cron — that's
     a manual ops action with a human checkpoint until we have
     enough volume to justify automating it.

Invoked daily by EventBridge → ECS RunTask. Matches the established
management-command pattern (no Celery — same shape as
``send_appointment_reminders``).

HIPAA: emails contain NO PHI; status transitions touch only the
Tenant row (no PHI). See ``apps.billing.notifications`` docstring
for the full framing.

Usage:

    python manage.py process_dunning
    python manage.py process_dunning --dry-run
    python manage.py process_dunning --tenant <slug>
"""

from __future__ import annotations

import datetime as dt
import logging

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone as djtz

from apps.audit.models import AuditLog
from apps.audit.services import record
from apps.billing.notifications import send_notification
from apps.tenants.models import Tenant

logger = logging.getLogger(__name__)


# Days in PAST_DUE before workspace is suspended. Tight enough that
# a real customer feels real pressure; loose enough that a bank-
# verification call has time to clear before we lock them out.
PAST_DUE_GRACE_DAYS = 7

# Days in SUSPENDED before the data-deletion warning email goes out.
# 45 of 60 means the customer has 15 days to react after we warn —
# enough time to take action (or accept deletion).
SUSPENDED_WARNING_DAYS = 45


class Command(BaseCommand):
    help = (
        'Daily dunning + lifecycle transitions: send payment_failed '
        'reminders, transition past_due → suspended at 7d, send '
        'suspended_warning at 45d.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help="Report what would happen without writing or sending.",
        )
        parser.add_argument(
            '--tenant',
            help='Limit to one tenant slug. Useful for ops re-issues.',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        single_slug = options.get('tenant')

        counts = {
            'payment_failed_sent': 0,
            'suspended_warning_sent': 0,
            'transitioned_to_suspended': 0,
            'skipped': 0,
            'failed': 0,
        }
        now = djtz.now()

        # ── 1. PAST_DUE: send payment_failed reminder + maybe transition ──
        past_due_qs = Tenant.objects.filter(
            status=Tenant.Status.PAST_DUE,
            grandfathered=False,
        )
        if single_slug:
            past_due_qs = past_due_qs.filter(slug=single_slug)

        for tenant in past_due_qs.iterator():
            try:
                # CAPTURE past_due age BEFORE we send any notifications —
                # send_notification() saves the tenant row, which
                # bumps updated_at and would zero out our age check.
                # The past-due transition timestamp lives in the audit
                # log (most recent AuditLog with resource=tenant +
                # metadata.event=past_due); for v1 we use updated_at as
                # a proxy because it reflects when the Stripe webhook
                # last set status=PAST_DUE. An incremental refinement
                # could add an explicit `past_due_started_at` field;
                # deferred until needed.
                past_due_age = now - tenant.updated_at

                # Send the reminder if we haven't yet.
                if 'payment_failed' not in (tenant.notifications_sent or {}):
                    if dry_run:
                        self.stdout.write(
                            f'[dry-run] would send payment_failed to {tenant.slug}'
                        )
                        counts['payment_failed_sent'] += 1
                    elif send_notification(tenant=tenant, kind='payment_failed'):
                        counts['payment_failed_sent'] += 1
                    else:
                        counts['skipped'] += 1

                # Now consult the pre-send age for the transition.
                if past_due_age >= dt.timedelta(days=PAST_DUE_GRACE_DAYS):
                    if dry_run:
                        self.stdout.write(
                            f'[dry-run] would suspend {tenant.slug} '
                            f'(past_due for {past_due_age.days}d)'
                        )
                    else:
                        tenant.status = Tenant.Status.SUSPENDED
                        tenant.save(update_fields=['status', 'updated_at'])
                        record(
                            action=AuditLog.Action.UPDATE,
                            resource_type='tenant',
                            resource_id=tenant.id,
                            tenant=tenant,
                            metadata={
                                'transition': 'past_due→suspended',
                                'reason': f'past_due {past_due_age.days} days',
                            },
                        )
                    counts['transitioned_to_suspended'] += 1
            except Exception:  # noqa: BLE001
                logger.exception(
                    'process_dunning.past_due_handling_failed tenant=%s',
                    tenant.slug,
                )
                counts['failed'] += 1

        # ── 2. SUSPENDED: send 45d data-deletion warning ──
        suspended_qs = Tenant.objects.filter(
            status=Tenant.Status.SUSPENDED,
            grandfathered=False,
        )
        if single_slug:
            suspended_qs = suspended_qs.filter(slug=single_slug)

        for tenant in suspended_qs.iterator():
            try:
                # Same "capture-before-mutate" pattern as the past_due
                # branch: any save bumps updated_at + would falsely
                # reset the age clock on the next cron run.
                suspended_age = now - tenant.updated_at
                if 'suspended_warning' in (tenant.notifications_sent or {}):
                    counts['skipped'] += 1
                    continue
                if suspended_age < dt.timedelta(days=SUSPENDED_WARNING_DAYS):
                    counts['skipped'] += 1
                    continue
                if dry_run:
                    self.stdout.write(
                        f'[dry-run] would send suspended_warning to {tenant.slug} '
                        f'(suspended for {suspended_age.days}d)'
                    )
                    counts['suspended_warning_sent'] += 1
                elif send_notification(tenant=tenant, kind='suspended_warning'):
                    counts['suspended_warning_sent'] += 1
                else:
                    counts['skipped'] += 1
            except Exception:  # noqa: BLE001
                logger.exception(
                    'process_dunning.suspended_warning_failed tenant=%s',
                    tenant.slug,
                )
                counts['failed'] += 1

        verb = 'would do' if dry_run else 'did'
        self.stdout.write(self.style.SUCCESS(
            f'Dunning complete: {verb} '
            f'{counts["payment_failed_sent"]} payment_failed sends, '
            f'{counts["transitioned_to_suspended"]} past_due→suspended transitions, '
            f'{counts["suspended_warning_sent"]} suspended_warning sends '
            f'(skipped {counts["skipped"]}, failed {counts["failed"]}).'
        ))
