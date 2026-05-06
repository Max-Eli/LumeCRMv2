"""Fire all active marketing automations whose triggers are
currently eligible.

Designed to run on a daily schedule. In production this becomes a
Celery beat task (Phase 1L session 4); for v1 the command is the
single canonical entry point — invoke via cron, GitHub Actions,
or manually for testing.

Idempotency: each automation has a per-customer dedup window
(default 365 days). Re-running this command on the same day is a
no-op for any customer who already received a given automation
this year. Safe to re-run if anything fails midway.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.marketing.models import Automation
from apps.marketing.sender import fire_automation


class Command(BaseCommand):
    help = 'Fire all active automations whose triggers are eligible right now.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--tenant',
            type=str,
            default=None,
            help='Limit to a single tenant by slug (default: all tenants).',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Print what would fire; do not write SendLog rows.',
        )

    def handle(self, *args, **options):
        qs = Automation.objects.filter(is_active=True).select_related('tenant', 'template', 'audience')
        if options['tenant']:
            qs = qs.filter(tenant__slug=options['tenant'])

        total = qs.count()
        if total == 0:
            self.stdout.write(self.style.WARNING('No active automations.'))
            return

        if options['dry_run']:
            for a in qs:
                from apps.marketing.automations import preview_automation
                preview = preview_automation(a)
                self.stdout.write(
                    f'[dry-run] {a.tenant.slug} · {a.name} → would fire to '
                    f'{preview["final_count"]} customer(s)',
                )
            return

        for a in qs:
            try:
                result = fire_automation(a)
                if result['sent_count'] > 0:
                    self.stdout.write(self.style.SUCCESS(
                        f'{a.tenant.slug} · {a.name}: '
                        f'{result["sent_count"]}/{result["eligible_count"]} sent',
                    ))
                else:
                    self.stdout.write(
                        f'{a.tenant.slug} · {a.name}: 0 eligible (dedup or no consent)',
                    )
            except Exception as e:  # noqa: BLE001
                self.stdout.write(self.style.ERROR(
                    f'{a.tenant.slug} · {a.name}: FAILED — {e}',
                ))
