"""Backfill consent-form submissions on appointments that missed them.

Before the multi-service consent-assignment fix, ``assign_forms_for_appointment``
only looked at ``appointment.service`` (the primary). Any extra services
on a multi-service visit silently skipped their consent forms — so the
customer's profile and the appointment popover both came up empty even
though the operator had wired the templates to the right services.

This command reconciles the historical data. For every appointment in
the database (or the slice you scope with flags), it re-runs the
"which consent forms should be on this appointment" calculation using
the corrected primary-plus-extras loop and creates any missing pending
submissions. The submission service is itself idempotent — a
recurrence='once' template that the customer already signed, or a
per-visit template that already has a pending submission on this
appointment, will be skipped. So a second run is safe.

Usage:

    # Default: every tenant, every active (non-cancelled) appointment.
    python manage.py backfill_appointment_consent_forms

    # Narrow to one tenant by slug.
    python manage.py backfill_appointment_consent_forms --tenant tenant-slug

    # Narrow to a date window (start_time inclusive on both ends, local
    # to the appointment's stored UTC value).
    python manage.py backfill_appointment_consent_forms \
        --since 2026-01-01 --until 2026-12-31

    # Plan only — print what WOULD be created without writing anything.
    python manage.py backfill_appointment_consent_forms --dry-run

Output: per-appointment summary + a totals line at the end. Designed to
be safe to run from a deploy step or one-off ECS task.
"""

from __future__ import annotations

import datetime as dt
import logging

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.dateparse import parse_date

from apps.appointments.models import Appointment
from apps.forms.services import _assign_consent_for_service
from apps.tenants.models import Tenant

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        'Create any missing pending consent FormSubmissions on existing '
        'appointments. Use after the multi-service consent fix to '
        'reconcile historical data.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--tenant',
            help='Limit to a single tenant by slug.',
        )
        parser.add_argument(
            '--since',
            help='Only process appointments with start_time >= this date '
                 '(YYYY-MM-DD).',
        )
        parser.add_argument(
            '--until',
            help='Only process appointments with start_time <= this date '
                 '(YYYY-MM-DD).',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Report what would be created without writing.',
        )

    def handle(self, *args, **options):
        tenant_slug = options.get('tenant')
        since_str = options.get('since')
        until_str = options.get('until')
        dry_run = options.get('dry_run', False)

        qs = (
            Appointment.objects
            .select_related('tenant', 'customer', 'service')
            .prefetch_related('extra_services__service')
            # Exclude cancelled — no point assigning consents to an
            # appointment that won't happen. No-shows DO stay in scope
            # because the consent record is still part of the history
            # the operator may want for "this customer agreed to X."
            .exclude(status=Appointment.Status.CANCELLED)
            .order_by('start_time')
        )

        if tenant_slug:
            try:
                tenant = Tenant.objects.get(slug=tenant_slug)
            except Tenant.DoesNotExist as e:
                raise CommandError(
                    f'No tenant with slug "{tenant_slug}".'
                ) from e
            qs = qs.filter(tenant=tenant)

        if since_str:
            since = parse_date(since_str)
            if since is None:
                raise CommandError(f'Bad --since (use YYYY-MM-DD): {since_str}')
            qs = qs.filter(
                start_time__gte=dt.datetime.combine(
                    since, dt.time.min, tzinfo=dt.timezone.utc,
                ),
            )
        if until_str:
            until = parse_date(until_str)
            if until is None:
                raise CommandError(f'Bad --until (use YYYY-MM-DD): {until_str}')
            qs = qs.filter(
                start_time__lte=dt.datetime.combine(
                    until, dt.time.max, tzinfo=dt.timezone.utc,
                ),
            )

        total_appts = 0
        total_created = 0
        total_touched_appts = 0

        # chunk_size is required when iterator() is paired with
        # prefetch_related (Django 4.2+). 500 is comfortable for ~25 KB
        # per row of memory and avoids the per-row overhead of a tiny
        # window without holding the whole table in memory.
        for appt in qs.iterator(chunk_size=500):
            total_appts += 1
            # Build the same de-duped primary + extras list as
            # `assign_forms_for_appointment`. Iterate this here (rather
            # than calling `assign_forms_for_appointment` whole) because
            # the public entry point also re-runs the intake check,
            # and a backfill shouldn't surprise-issue an intake form
            # that wasn't issued at booking time.
            service_ids: list[int] = []
            seen: set[int] = set()
            if appt.service_id is not None and appt.service_id not in seen:
                service_ids.append(appt.service_id)
                seen.add(appt.service_id)
            for extra in appt.extra_services.all():
                if extra.service_id is not None and extra.service_id not in seen:
                    service_ids.append(extra.service_id)
                    seen.add(extra.service_id)

            created_for_appt = []
            if dry_run:
                # Simulate inside a transaction we then roll back, so the
                # idempotency checks inside _assign_consent_for_service
                # see the true current state without persisting writes.
                sid = transaction.savepoint()
                try:
                    for service_id in service_ids:
                        created_for_appt.extend(
                            _assign_consent_for_service(
                                tenant=appt.tenant,
                                customer=appt.customer,
                                appointment=appt,
                                service_id=service_id,
                            )
                        )
                finally:
                    transaction.savepoint_rollback(sid)
            else:
                with transaction.atomic():
                    for service_id in service_ids:
                        created_for_appt.extend(
                            _assign_consent_for_service(
                                tenant=appt.tenant,
                                customer=appt.customer,
                                appointment=appt,
                                service_id=service_id,
                            )
                        )

            if created_for_appt:
                total_touched_appts += 1
                total_created += len(created_for_appt)
                self.stdout.write(
                    f'  appt #{appt.pk} ({appt.tenant.slug}): '
                    f'+{len(created_for_appt)} pending consent(s)'
                )

        verb = 'would create' if dry_run else 'created'
        self.stdout.write(self.style.SUCCESS(
            f'\nBackfill complete: scanned {total_appts} appointment(s); '
            f'{verb} {total_created} pending submission(s) across '
            f'{total_touched_appts} appointment(s).'
        ))
