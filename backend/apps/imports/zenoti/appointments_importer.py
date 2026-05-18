"""Zenoti appointments import orchestration.

Per-appointment workflow:
  1. Match Customer (by Guest Name, case-insensitive on first+last).
  2. Match Service (by Service Name, case-insensitive normalized).
  3. Match Provider (by Provider name → TenantMembership where
     User.first_name + User.last_name match, scoped to tenant).
  4. Create the Appointment row.
     - This fires `invoices.signals.create_invoice_for_appointment`
       which auto-creates an OPEN invoice + one snapshot line.
  5. Apply the invoice action derived in the mapper:
     - `close_invoice=True` → invoice.close(by_user=tenant_owner,
       payment_method='other') — transitions OPEN → PAID AND flips
       the Appointment to COMPLETED.
     - `void_invoice=True` → invoice.void(by_user=tenant_owner,
       reason='Zenoti import: ...').
     - Otherwise leave the invoice OPEN.
  6. If a non-cancelled appointment, transition the Appointment to
     its target Lume status (booked / confirmed / checked_in).
     COMPLETED is set by close() above so we don't double-flip.

Two PRE-passes run before per-appointment writes:
  - Pre-pass A: validate all headers across all files, map every
    row, dedupe across files.
  - Pre-pass B: Walk every mapped appointment, build the per-
    provider weekly_hours set (8am-8pm on every weekday they have
    appointments), upsert ProviderSchedule for each provider's
    MembershipLocation. This is what makes the calendar's provider
    columns light up on the right days.

Multi-file aware (same as packages): Zenoti caps appointment
exports at ~11 months. Operator passes all files in one
invocation; later file wins on Invoice No collision.

Customer / Service / Provider misses are SKIPPED with a counter
(distinct from mapping failures). The operator triages via the
error log post-run.
"""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass, field
from typing import IO

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.appointments.models import Appointment
from apps.audit.models import AuditLog
from apps.audit.services import record as audit_record
from apps.customers.models import Customer
from apps.invoices.models import Invoice
from apps.services.models import Service
from apps.tenants.models import (
    Location, MembershipLocation, ProviderSchedule, Tenant, TenantMembership,
)

from .appointments_mapper import (
    EXPECTED_HEADER,
    AppointmentMapError,
    MappedAppointment,
    infer_provider_weekly_hours,
    map_row,
    merge_appointment_files,
    validate_header,
)

logger = logging.getLogger(__name__)


@dataclass
class AppointmentsImportReport:
    files_read: int = 0
    rows_read: int = 0
    rows_mapped: int = 0
    rows_failed_mapping: int = 0
    rows_skipped_filtered_status: int = 0  # 'Deleted'
    rows_deduped_across_files: int = 0
    rows_skipped_no_customer: int = 0  # dry-run only; live auto-creates instead
    rows_skipped_no_service: int = 0
    rows_skipped_no_provider: int = 0
    rows_skipped_db_error: int = 0
    rows_created: int = 0
    rows_updated: int = 0
    invoices_closed: int = 0
    invoices_voided: int = 0
    schedules_set: int = 0
    placeholder_customers_created: int = 0  # live only
    header_errors: list[str] = field(default_factory=list)
    mapping_errors: list[AppointmentMapError] = field(default_factory=list)
    db_errors: list[str] = field(default_factory=list)
    customer_misses: list[str] = field(default_factory=list)
    service_misses: list[str] = field(default_factory=list)
    provider_misses: list[str] = field(default_factory=list)

    def to_summary_dict(self) -> dict:
        return {
            'files_read': self.files_read,
            'rows_read': self.rows_read,
            'rows_mapped': self.rows_mapped,
            'rows_failed_mapping': self.rows_failed_mapping,
            'rows_skipped_filtered_status': self.rows_skipped_filtered_status,
            'rows_deduped_across_files': self.rows_deduped_across_files,
            'rows_skipped_no_customer': self.rows_skipped_no_customer,
            'rows_skipped_no_service': self.rows_skipped_no_service,
            'rows_skipped_no_provider': self.rows_skipped_no_provider,
            'rows_skipped_db_error': self.rows_skipped_db_error,
            'rows_created': self.rows_created,
            'rows_updated': self.rows_updated,
            'invoices_closed': self.invoices_closed,
            'invoices_voided': self.invoices_voided,
            'schedules_set': self.schedules_set,
            'placeholder_customers_created': self.placeholder_customers_created,
            'header_error_count': len(self.header_errors),
            'mapping_error_count': len(self.mapping_errors),
            'db_error_count': len(self.db_errors),
            'customer_miss_count': len(self.customer_misses),
            'service_miss_count': len(self.service_misses),
            'provider_miss_count': len(self.provider_misses),
        }


def import_zenoti_appointments(
    *,
    tenant: Tenant,
    file_objs: list[IO],
    dry_run: bool = True,
    actor=None,
) -> AppointmentsImportReport:
    """Import one or more Zenoti appointment CSVs."""
    report = AppointmentsImportReport(files_read=len(file_objs))
    now = timezone.now()

    # ── Pass 1: parse + map every file ──────────────────────────────
    per_file: list[list[MappedAppointment]] = []
    for f in file_objs:
        reader = csv.DictReader(f)
        header_errs = validate_header(reader.fieldnames or [])
        if header_errs:
            report.header_errors.extend(header_errs)
            continue
        batch: list[MappedAppointment] = []
        for line_number, row in enumerate(reader, start=2):
            report.rows_read += 1
            mapped, err = map_row(row, line_number=line_number, now=now)
            if err is not None:
                if err.reason.startswith('Skipped'):
                    report.rows_skipped_filtered_status += 1
                else:
                    report.rows_failed_mapping += 1
                    report.mapping_errors.append(err)
            if mapped is not None:
                batch.append(mapped)
        per_file.append(batch)

    if report.header_errors:
        return report

    deduped, dupes = merge_appointment_files(per_file)
    report.rows_deduped_across_files = len(dupes)
    report.rows_mapped = len(deduped)

    # ── Pre-flight: collect match caches + provider schedule ────────
    customer_cache: dict[tuple[str, str], Customer | None] = {}
    service_catalog = _build_service_catalog(tenant=tenant)
    provider_lookup = _build_provider_lookup(tenant=tenant)

    default_location = (
        Location.objects.filter(tenant=tenant, is_default=True).first()
        or Location.objects.filter(tenant=tenant).order_by('id').first()
    )

    inferred_schedules = infer_provider_weekly_hours(deduped)

    if dry_run:
        # Pre-count match misses for the dry-run reconciliation.
        for m in deduped:
            if _match_customer(tenant=tenant, mapped=m, cache=customer_cache) is None:
                report.rows_skipped_no_customer += 1
                report.customer_misses.append(
                    f'{m.customer_first} {m.customer_last} (invoice {m.external_invoice_no})'
                )
            if _match_service(m.service_name, service_catalog) is None:
                report.service_misses.append(m.service_name)
                report.rows_skipped_no_service += 1
            if _match_provider(m.provider_name, provider_lookup) is None:
                report.provider_misses.append(m.provider_name)
                report.rows_skipped_no_provider += 1
        # Distinct unmatched names rather than per-row noise.
        report.service_misses = sorted(set(report.service_misses))
        report.provider_misses = sorted(set(report.provider_misses))
        return report

    # ── Pre-pass B: write inferred provider schedules ──────────────
    if default_location is not None:
        for provider_name, weekly in inferred_schedules.items():
            membership = _match_provider(provider_name, provider_lookup)
            if membership is None:
                continue
            ml = MembershipLocation.objects.filter(
                membership=membership, location=default_location, is_active=True,
            ).first()
            if ml is None:
                continue
            ProviderSchedule.objects.update_or_create(
                membership_location=ml,
                defaults={'weekly_hours': weekly},
            )
            report.schedules_set += 1

    # ── Pass 2: per-appointment write ──────────────────────────────
    owner_user = _resolve_owner_actor(tenant=tenant, actor=actor)
    seen_external_ids: set[str] = set()
    write_now = timezone.now()
    placeholder_count = [0]  # mutable ref for the auto-create helper

    for mapped in deduped:
        if mapped.external_id in seen_external_ids:
            continue
        seen_external_ids.add(mapped.external_id)

        # Per operator instruction: customers not in our catalog get
        # auto-created as name-only placeholders so the appointment
        # lands. Returns the matched or freshly-created Customer.
        customer = _match_or_create_customer(
            tenant=tenant, mapped=mapped, cache=customer_cache,
            placeholder_count_ref=placeholder_count,
        )
        service = _match_service(mapped.service_name, service_catalog)
        if service is None:
            report.rows_skipped_no_service += 1
            report.service_misses.append(mapped.service_name)
            continue
        provider = _match_provider(mapped.provider_name, provider_lookup)
        if provider is None:
            report.rows_skipped_no_provider += 1
            report.provider_misses.append(mapped.provider_name)
            continue
        if default_location is None:
            report.rows_skipped_db_error += 1
            report.db_errors.append(
                f'{mapped.external_id}: tenant has no default location'
            )
            continue

        try:
            appt, created = _upsert_appointment(
                tenant=tenant, mapped=mapped, customer=customer, service=service,
                provider=provider, location=default_location, write_now=write_now,
            )
        except IntegrityError as e:
            report.rows_skipped_db_error += 1
            report.db_errors.append(f'{mapped.external_id}: {e}'[:300])
            logger.warning(
                'imports.zenoti.appointments.row_db_error',
                extra={'external_id': mapped.external_id, 'error': str(e)[:200]},
            )
            continue
        except Exception as e:  # noqa: BLE001
            report.rows_skipped_db_error += 1
            report.db_errors.append(f'{mapped.external_id}: {type(e).__name__}: {e}'[:300])
            logger.exception(
                'imports.zenoti.appointments.row_unexpected_error',
                extra={'external_id': mapped.external_id},
            )
            continue

        # Apply invoice state per the mapper's resolution. Each branch
        # is wrapped in try/except so an invoice failure doesn't block
        # the appointment write — operator can triage post-import.
        if created:
            try:
                if mapped.close_invoice:
                    _close_imported_invoice(
                        appt=appt, by_user=owner_user, mapped=mapped,
                    )
                    report.invoices_closed += 1
                elif mapped.void_invoice:
                    _void_imported_invoice(
                        appt=appt, by_user=owner_user, mapped=mapped,
                    )
                    report.invoices_voided += 1
                else:
                    # OPEN appointment in the future — set Lumè status
                    # explicitly since the auto-invoice path didn't
                    # flip it (close() is what transitions to COMPLETED).
                    if mapped.lume_status not in (None, '', 'completed'):
                        appt.status = mapped.lume_status
                        appt.save(update_fields=['status', 'updated_at'])
            except Exception as e:  # noqa: BLE001
                report.db_errors.append(
                    f'{mapped.external_id} (invoice transition): '
                    f'{type(e).__name__}: {e}'[:300]
                )
                logger.exception(
                    'imports.zenoti.appointments.invoice_action_error',
                    extra={'external_id': mapped.external_id, 'lume_status': mapped.lume_status},
                )

        if created:
            report.rows_created += 1
        else:
            report.rows_updated += 1

        audit_record(
            action=AuditLog.Action.CREATE if created else AuditLog.Action.UPDATE,
            resource_type='appointment',
            resource_id=appt.id,
            user=actor, tenant=tenant,
            metadata={
                'source': 'zenoti_import',
                'external_id': mapped.external_id,
                'external_invoice_no': mapped.external_invoice_no,
                'customer_id': customer.id,
                'service_id': service.id,
                'provider_id': provider.id,
                'lume_status': mapped.lume_status,
                'upstream_status': mapped.upstream_status,
            },
        )

    audit_record(
        action=AuditLog.Action.CREATE,
        resource_type='zenoti_appointments_import_run',
        user=actor, tenant=tenant,
        metadata=report.to_summary_dict(),
    )

    report.service_misses = sorted(set(report.service_misses))
    report.provider_misses = sorted(set(report.provider_misses))
    report.placeholder_customers_created = placeholder_count[0]
    return report


# ── Match helpers ──────────────────────────────────────────────────


def _match_customer(
    *, tenant: Tenant, mapped: MappedAppointment,
    cache: dict[tuple[str, str], Customer | None],
) -> Customer | None:
    """Same fallback logic as packages: exact (first, last) first,
    then last-name-only when unambiguous.

    Used by the dry-run pre-flight to count misses without writes.
    The live pass uses `_match_or_create_customer` which auto-creates
    a placeholder Customer for misses (per operator instruction).
    """
    key = (mapped.customer_first.lower(), mapped.customer_last.lower())
    if key in cache:
        return cache[key]
    qs = Customer.objects.filter(tenant=tenant)
    customer = qs.filter(
        first_name__iexact=mapped.customer_first,
        last_name__iexact=mapped.customer_last,
    ).first()
    if customer is None and mapped.customer_last:
        candidates = list(qs.filter(last_name__iexact=mapped.customer_last)[:2])
        if len(candidates) == 1:
            customer = candidates[0]
    cache[key] = customer
    return customer


def _match_or_create_customer(
    *, tenant: Tenant, mapped: MappedAppointment,
    cache: dict[tuple[str, str], Customer | None],
    placeholder_count_ref: list[int],
) -> Customer:
    """Find an existing customer or auto-create a placeholder.

    Per operator instruction: appointments for customers we don't
    have in the catalog (because they weren't in the active-guest
    export) should land anyway — auto-create a stub Customer with
    just name. Operator manually cleans up duplicates / fills in
    contact info later.

    Idempotent via external_id: re-runs find the previously-created
    placeholder rather than spawning a new one. Uses the
    `zenoti-appt-placeholder:<name-slug>` prefix so these rows are
    visibly distinct from the customer-importer-generated rows
    (`zenoti-code:` or `zenoti-syn:`).

    `placeholder_count_ref` is a single-element list mutated as the
    counter — Python's lack of `nonlocal` parameter sharing is the
    only reason it isn't an int.
    """
    matched = _match_customer(tenant=tenant, mapped=mapped, cache=cache)
    if matched is not None:
        return matched

    import re
    name_slug = re.sub(
        r'[^a-z0-9]+', '-',
        f'{mapped.customer_first} {mapped.customer_last}'.lower(),
    ).strip('-') or 'unknown'
    eid = f'zenoti-appt-placeholder:{name_slug}'[:100]

    existing = Customer.objects.filter(
        tenant=tenant,
        external_source='zenoti',
        external_id=eid,
    ).first()
    if existing is not None:
        # Cache the lookup so subsequent rows for the same person
        # don't hit the DB again.
        key = (mapped.customer_first.lower(), mapped.customer_last.lower())
        cache[key] = existing
        return existing

    placeholder = Customer.objects.create(
        tenant=tenant,
        first_name=mapped.customer_first[:100] or 'Unknown',
        last_name=mapped.customer_last[:100],
        external_source='zenoti',
        external_id=eid,
        acquisition_source=Customer.AcquisitionSource.ZENOTI_IMPORT,
        imported_at=timezone.now(),
        notes=(
            'Auto-created by Zenoti appointment import — original '
            'guest record was not present in ZenotiActiveGuest.csv '
            '(likely an inactive / departed client). No contact info '
            'on file. Operator should review + merge or fill in if '
            'this person becomes active again.'
        ),
    )
    placeholder_count_ref[0] += 1
    key = (mapped.customer_first.lower(), mapped.customer_last.lower())
    cache[key] = placeholder
    return placeholder


def _build_service_catalog(*, tenant: Tenant) -> dict[str, Service]:
    catalog: dict[str, Service] = {}
    for s in Service.objects.filter(tenant=tenant).only('id', 'name', 'price_cents', 'tax_rate_percent'):
        catalog[_norm_name(s.name)] = s
    return catalog


def _build_provider_lookup(*, tenant: Tenant) -> dict[str, TenantMembership]:
    """Map 'firstname lastname' (normalized) → TenantMembership.

    Limited to bookable + active memberships so a deactivated
    technician isn't accidentally re-bound to a new appointment.
    """
    lookup: dict[str, TenantMembership] = {}
    qs = TenantMembership.objects.filter(
        tenant=tenant, is_active=True, is_bookable=True,
    ).select_related('user')
    for m in qs:
        full = f'{m.user.first_name} {m.user.last_name}'.strip()
        if full:
            lookup[_norm_name(full)] = m
    return lookup


def _norm_name(name: str) -> str:
    import re
    return re.sub(r'\s+', ' ', (name or '').lower()).strip()


def _match_service(name: str, catalog: dict[str, Service]) -> Service | None:
    return catalog.get(_norm_name(name))


def _match_provider(name: str, lookup: dict[str, TenantMembership]) -> TenantMembership | None:
    return lookup.get(_norm_name(name))


def _resolve_owner_actor(*, tenant: Tenant, actor):
    """The Invoice.close() + Invoice.void() paths require a User as
    `by_user`. When invoked from a CLI / cron there's no request.user
    so we use the tenant's first owner membership."""
    if actor is not None:
        return actor
    owner_membership = (
        TenantMembership.objects
        .filter(tenant=tenant, role=TenantMembership.Role.OWNER, is_active=True)
        .select_related('user')
        .first()
    )
    return owner_membership.user if owner_membership is not None else None


# ── Appointment + invoice writers ──────────────────────────────────


def _upsert_appointment(
    *, tenant: Tenant, mapped: MappedAppointment,
    customer: Customer, service: Service,
    provider: TenantMembership, location: Location, write_now,
) -> tuple[Appointment, bool]:
    """Find-or-create by (tenant, external_source, external_id).

    Re-runs update mutable fields (status / times) but keep the
    auto-created invoice intact. Schedule changes from Zenoti
    re-imports flow through.
    """
    with transaction.atomic():
        existing = Appointment.objects.filter(
            tenant=tenant,
            external_source=mapped.external_source,
            external_id=mapped.external_id,
        ).first()
        if existing is not None:
            existing.start_time = mapped.start_time
            existing.end_time = mapped.end_time
            existing.customer = customer
            existing.service = service
            existing.provider = provider
            existing.location = location
            existing.imported_at = write_now
            # Don't clobber operator's manual status edits on re-import
            # — only refresh the times + assignment.
            existing.save()
            return existing, False
        appt = Appointment.objects.create(
            tenant=tenant,
            customer=customer,
            service=service,
            provider=provider,
            location=location,
            start_time=mapped.start_time,
            end_time=mapped.end_time,
            status=Appointment.Status.BOOKED,  # close() flips to COMPLETED when needed
            source='zenoti_import',
            external_source=mapped.external_source,
            external_id=mapped.external_id,
            imported_at=write_now,
            quoted_price_cents=service.price_cents,
        )
        return appt, True


def _close_imported_invoice(*, appt: Appointment, by_user, mapped: MappedAppointment):
    """Close the auto-created OPEN invoice with payment_method=OTHER.

    Operator's explicit instruction: imported past appointments are
    paid via OTHER so reports + provider revenue stitch together
    cleanly. The invoice carries a `notes` line that names the import
    so audits can distinguish migrated payments from live ones.
    """
    invoice = Invoice.objects.filter(appointment=appt).first()
    if invoice is None:
        return
    if invoice.status != Invoice.Status.OPEN:
        return  # already finalized; importer is idempotent
    invoice.close(
        by_user=by_user,
        payment_method=Invoice.PaymentMethod.OTHER,
        payment_reference=f'zenoti:{mapped.external_invoice_no}',
        notes='Closed by Zenoti import (payment method = other; original receipt in Zenoti).',
    )


def _void_imported_invoice(*, appt: Appointment, by_user, mapped: MappedAppointment):
    """Void the auto-created OPEN invoice for cancelled / no-show
    imported appointments."""
    invoice = Invoice.objects.filter(appointment=appt).first()
    if invoice is None:
        return
    if invoice.status != Invoice.Status.OPEN:
        return
    invoice.void(
        by_user=by_user,
        reason=(
            f'Voided by Zenoti import — '
            f'upstream status {mapped.upstream_status!r}.'
        ),
    )
    # void() doesn't auto-set appointment status; do it here.
    if mapped.lume_status in (Appointment.Status.CANCELLED, Appointment.Status.NO_SHOW):
        appt.status = mapped.lume_status
        if mapped.lume_status == Appointment.Status.CANCELLED:
            appt.cancelled_at = timezone.now()
            appt.cancelled_reason = 'Zenoti import (cancelled upstream)'
            appt.save(update_fields=['status', 'cancelled_at', 'cancelled_reason', 'updated_at'])
        else:
            appt.save(update_fields=['status', 'updated_at'])
