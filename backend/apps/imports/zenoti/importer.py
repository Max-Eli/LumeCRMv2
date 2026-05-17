"""Zenoti customer import orchestration.

Two-pass design (per ADR 0030):

  Pass 1 — VALIDATE
    Read the entire CSV. Validate header. Map every row. Detect
    internal duplicates. Produce a reconciliation report and a
    per-row error log. NO database writes.

  Pass 2 — WRITE (only when not dry-run)
    Iterate the validated rows. Upsert each on (tenant,
    external_source='zenoti', external_id). Write an AuditLog entry
    per row tagged metadata.source='zenoti_import'.

Idempotency: every customer carries a stable external_id (Zenoti
Code prefixed `zenoti-code:`, or a synthetic hash prefixed
`zenoti-syn:` when Code is blank). Re-running the import is safe;
duplicates are skipped on existence, and updated rows have their
non-external fields refreshed.

Atomicity: each customer write is its own transaction, so a failing
row doesn't roll back the whole import. The reconciliation report
surfaces what wrote vs what skipped vs what errored.
"""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass, field
from typing import IO

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.audit.services import record as audit_record
from apps.customers.models import Customer
from apps.tenants.models import Tenant

from .mappers import (
    EXPECTED_HEADER,
    PREAMBLE_LINES,
    MapError,
    MappedCustomer,
    detect_internal_duplicates,
    map_row,
    validate_header,
)

logger = logging.getLogger(__name__)


@dataclass
class ImportReport:
    """End-to-end reconciliation. Logged + printed by the CLI."""
    rows_read: int = 0
    rows_mapped: int = 0
    rows_failed_mapping: int = 0
    rows_created: int = 0
    rows_updated: int = 0
    rows_skipped_duplicate_in_export: int = 0
    rows_skipped_db_error: int = 0
    header_errors: list[str] = field(default_factory=list)
    mapping_errors: list[MapError] = field(default_factory=list)
    db_errors: list[str] = field(default_factory=list)
    duplicate_external_ids: list[str] = field(default_factory=list)

    def to_summary_dict(self) -> dict:
        """Minimal version for the audit log — no PHI, just counts."""
        return {
            'rows_read': self.rows_read,
            'rows_mapped': self.rows_mapped,
            'rows_failed_mapping': self.rows_failed_mapping,
            'rows_created': self.rows_created,
            'rows_updated': self.rows_updated,
            'rows_skipped_duplicate_in_export': self.rows_skipped_duplicate_in_export,
            'rows_skipped_db_error': self.rows_skipped_db_error,
            'header_error_count': len(self.header_errors),
            'mapping_error_count': len(self.mapping_errors),
            'db_error_count': len(self.db_errors),
            'duplicate_external_id_count': len(self.duplicate_external_ids),
        }


def import_zenoti_guests(
    *,
    tenant: Tenant,
    file_obj: IO,
    dry_run: bool = True,
    actor=None,
) -> ImportReport:
    """Run a Zenoti customer import.

    Args:
        tenant: target Lumè tenant; every imported Customer is scoped
            to this tenant.
        file_obj: an open file-like object positioned at the start of
            the Zenoti CSV (any of the project's standard CSV-reading
            wrappers fine).
        dry_run: when True, validate + report only. No DB writes, no
            audit log. Use this against a sandbox tenant first.
        actor: optional User performing the import. Recorded on the
            audit log entries; can be None for cron / shell invocations.

    Returns the full ImportReport.
    """
    report = ImportReport()

    # ── Skip the 5-line metadata preamble ──────────────────────────
    for _ in range(PREAMBLE_LINES):
        next(file_obj, None)

    reader = csv.DictReader(file_obj, fieldnames=EXPECTED_HEADER, restkey='_extra')
    # DictReader treats the FIRST line as the header by default. We've
    # overridden `fieldnames` so the next line IS the actual header;
    # validate it explicitly and then advance past it.
    header_row = next(reader, None)
    if header_row is None:
        report.header_errors.append('CSV is empty after the preamble.')
        return report
    header_list = [header_row.get(col, '') for col in EXPECTED_HEADER]
    report.header_errors.extend(validate_header(header_list))
    if report.header_errors:
        # Hard-fail on header drift — better than blind-mapping into
        # wrong columns.
        return report

    # ── Pass 1: map every row ──────────────────────────────────────
    mapped_rows: list[MappedCustomer] = []
    for line_number, row in enumerate(reader, start=PREAMBLE_LINES + 2):
        report.rows_read += 1
        mapped, err = map_row(row, line_number=line_number)
        if err is not None:
            report.rows_failed_mapping += 1
            report.mapping_errors.append(err)
        if mapped is not None:
            mapped_rows.append(mapped)
    report.rows_mapped = len(mapped_rows)

    # Detect duplicates inside the export itself.
    dupes = detect_internal_duplicates(mapped_rows)
    report.duplicate_external_ids = list(dupes.keys())

    if dry_run:
        # Don't write; report is enough for the operator to decide
        # whether to proceed.
        return report

    # ── Pass 2: write ──────────────────────────────────────────────
    seen_external_ids: set[str] = set()
    now = timezone.now()
    for mapped in mapped_rows:
        if mapped.external_id in seen_external_ids:
            report.rows_skipped_duplicate_in_export += 1
            continue
        seen_external_ids.add(mapped.external_id)

        mapped.imported_at = now
        try:
            customer, created = _upsert_one(tenant=tenant, mapped=mapped)
        except IntegrityError as e:
            report.rows_skipped_db_error += 1
            report.db_errors.append(f'{mapped.external_id}: {e}'[:300])
            logger.warning(
                'imports.zenoti.row_db_error',
                extra={'external_id': mapped.external_id, 'error': str(e)[:200]},
            )
            continue
        except Exception as e:  # noqa: BLE001
            report.rows_skipped_db_error += 1
            report.db_errors.append(f'{mapped.external_id}: {type(e).__name__}: {e}'[:300])
            logger.exception(
                'imports.zenoti.row_unexpected_error',
                extra={'external_id': mapped.external_id},
            )
            continue

        if created:
            report.rows_created += 1
        else:
            report.rows_updated += 1

        # Per-row audit. Metadata is PHI-light: no body fields, just
        # the external_id + base_center + create/update verb.
        audit_record(
            action=(
                AuditLog.Action.CREATE if created
                else AuditLog.Action.UPDATE
            ),
            resource_type='customer',
            resource_id=customer.id,
            user=actor,
            tenant=tenant,
            metadata={
                'source': 'zenoti_import',
                'external_id': mapped.external_id,
                'base_center': mapped.base_center,
                'verb': 'create' if created else 'update',
            },
        )

    # Aggregate audit entry for the whole run.
    audit_record(
        action=AuditLog.Action.CREATE,
        resource_type='zenoti_import_run',
        user=actor,
        tenant=tenant,
        metadata=report.to_summary_dict(),
    )

    return report


def _upsert_one(*, tenant: Tenant, mapped: MappedCustomer) -> tuple[Customer, bool]:
    """Find-or-create + update. Wrapped in atomic to roll back on
    integrity failures (e.g. unique referral_code race).
    """
    with transaction.atomic():
        defaults = mapped.write_kwargs()
        existing = Customer.objects.filter(
            tenant=tenant,
            external_source=mapped.external_source,
            external_id=mapped.external_id,
        ).first()
        if existing is not None:
            # Update non-external fields. Don't touch acquisition_source
            # (immutable post-create) or referral_code (auto-managed).
            for k, v in defaults.items():
                setattr(existing, k, v)
            existing.save()
            return existing, False
        # Brand-new row. Set acquisition_source on create.
        defaults.update({
            'tenant': tenant,
            'external_source': mapped.external_source,
            'external_id': mapped.external_id,
            'acquisition_source': Customer.AcquisitionSource.ZENOTI_IMPORT,
        })
        customer = Customer.objects.create(**defaults)
        return customer, True
