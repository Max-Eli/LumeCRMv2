"""Seed AIConfig for one tenant + (optionally) flip enabled=True.

Default behavior: creates AIConfig with the safe defaults (test_mode=True,
enabled=False) so the tenant can be configured via the Settings UI
before going live.

For ops + smoke testing: pass --enable to flip enabled=True immediately,
and --test-mode-number to set the only phone that can interact in
sandbox.

Refuses to enable for a tenant whose `twilio_from_number` is empty
— the dispatch layer would block it anyway but this fails fast so
the operator notices.

Examples:

    # Seed defaults only (safe — does NOT enable):
    python manage.py enable_ai_for_tenant --tenant demo

    # Enable + sandbox test mode tied to my cell:
    python manage.py enable_ai_for_tenant --tenant demo --enable \\
        --test-mode-number +14155551234 \\
        --persona "You're Avery, the front-desk assistant for the demo medspa."
"""

from __future__ import annotations

import json
import re

from django.core.management.base import BaseCommand, CommandError

from apps.ai_inbox.models import AIConfig
from apps.tenants.models import Tenant


_E164_RE = re.compile(r'^\+\d{8,15}$')


class Command(BaseCommand):
    help = 'Create / update AIConfig for one tenant. Safe by default — does NOT enable.'

    def add_arguments(self, parser):
        parser.add_argument('--tenant', required=True, help='Tenant slug.')
        parser.add_argument(
            '--enable', action='store_true',
            help='Flip enabled=True. Requires --test-mode-number unless --no-test-mode is also passed.',
        )
        parser.add_argument(
            '--no-test-mode', action='store_true',
            help='Flip test_mode=False. Only allowed with --enable + an explicit confirmation prompt.',
        )
        parser.add_argument('--test-mode-number', help='E.164 phone allowed in sandbox.')
        parser.add_argument('--persona', help='Free-text persona for the system prompt.')
        parser.add_argument('--daily-send-cap', type=int)
        parser.add_argument('--monthly-exchange-cap', type=int)
        parser.add_argument('--booking-lead-minutes', type=int)

    def handle(self, *args, **options):
        slug = options['tenant']
        try:
            tenant = Tenant.objects.get(slug=slug)
        except Tenant.DoesNotExist as exc:
            raise CommandError(f'No tenant with slug={slug!r}.') from exc

        enabling = options['enable']
        no_test_mode = options['no_test_mode']
        test_mode_number = options.get('test_mode_number') or ''

        if enabling and not (tenant.twilio_from_number or '').strip():
            raise CommandError(
                f"Refusing to enable AI on tenant {tenant.slug!r}: "
                f"twilio_from_number is empty. Provision a TFN first."
            )
        if test_mode_number and not _E164_RE.match(test_mode_number):
            raise CommandError(
                f"test-mode-number {test_mode_number!r} is not E.164 "
                f"(expected +<digits>).",
            )

        config, created = AIConfig.objects.get_or_create(tenant=tenant)

        fields_changed = []
        if test_mode_number:
            config.test_mode_number = test_mode_number
            fields_changed.append('test_mode_number')
        if options.get('persona'):
            config.persona = options['persona']
            fields_changed.append('persona')
        if options.get('daily_send_cap') is not None:
            config.daily_send_cap = options['daily_send_cap']
            fields_changed.append('daily_send_cap')
        if options.get('monthly_exchange_cap') is not None:
            config.monthly_exchange_cap = options['monthly_exchange_cap']
            fields_changed.append('monthly_exchange_cap')
        if options.get('booking_lead_minutes') is not None:
            config.booking_lead_minutes = options['booking_lead_minutes']
            fields_changed.append('booking_lead_minutes')
        if no_test_mode and enabling:
            config.test_mode = False
            fields_changed.append('test_mode')
        if enabling:
            if not config.test_mode and not no_test_mode:
                # test_mode was already off and we're not explicitly
                # leaving it off — that's fine, just record it.
                pass
            if config.test_mode and not config.test_mode_number:
                raise CommandError(
                    'Cannot enable in test mode without test_mode_number. '
                    'Pass --test-mode-number +1<digits>.',
                )
            config.enabled = True
            fields_changed.append('enabled')
        if fields_changed:
            fields_changed.append('updated_at')
            config.save(update_fields=fields_changed)

        # Pretty output.
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            f'AIConfig {"created" if created else "updated"} for {tenant.slug}:'
        ))
        for k in (
            'enabled', 'test_mode', 'test_mode_number', 'persona',
            'daily_send_cap', 'monthly_exchange_cap', 'booking_lead_minutes',
            'platform_disabled_at',
        ):
            val = getattr(config, k)
            if k == 'persona' and val:
                val = (val[:60] + '…') if len(val) > 60 else val
            self.stdout.write(f'  {k:24s} {val}')

        if config.enabled and config.test_mode:
            self.stdout.write('')
            self.stdout.write(self.style.WARNING(
                'AI is ENABLED in test mode. Only inbound SMS from '
                f'{config.test_mode_number} will be answered. All '
                'other inbound numbers are audit-logged + dropped.'
            ))
        elif config.enabled and not config.test_mode:
            self.stdout.write('')
            self.stdout.write(self.style.WARNING(
                'AI is ENABLED in LIVE mode — every inbound SMS to '
                f'{tenant.twilio_from_number} will be answered by the AI. '
                'Use --no-test-mode only after sandbox testing.'
            ))
