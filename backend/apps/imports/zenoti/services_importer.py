"""Zenoti services import orchestration.

Mirrors `importer.py` (customer migration) for shape + safety
guarantees:

  - Two-pass: validate everything, then write only when not dry-run.
  - Idempotent on (tenant, external_source='zenoti', external_id).
  - Per-row atomic transactions — one bad row doesn't roll back
    the other ~350.
  - Per-row audit + aggregate run-level audit for SOC 2 trace.
  - ServiceCategory rows are created lazily via `get_or_create`
    so the operator gets the Zenoti category taxonomy as a side
    effect of the first import.
  - `service_type` and `is_bookable_online` are NEVER overwritten
    on re-runs — operator's later classifications stay sticky.

See [ADR 0030] for the broader migration rationale; this importer
shares the same idempotency + audit posture as the customer one.
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
from apps.services.models import Service, ServiceCategory
from apps.tenants.models import Tenant

from .services_mapper import (
    EXPECTED_HEADER,
    PREAMBLE_LINES,
    MappedService,
    ServiceMapError,
    detect_duplicate_external_ids,
    map_row,
    validate_header,
)

logger = logging.getLogger(__name__)


@dataclass
class ServicesImportReport:
    rows_read: int = 0
    rows_mapped: int = 0
    rows_skipped_filtered: int = 0      # Nails + 'category' junk rows
    rows_failed_mapping: int = 0        # blank names, etc.
    rows_created: int = 0
    rows_updated: int = 0
    rows_skipped_duplicate_in_export: int = 0
    rows_skipped_db_error: int = 0
    categories_created: int = 0
    header_errors: list[str] = field(default_factory=list)
    mapping_errors: list[ServiceMapError] = field(default_factory=list)
    db_errors: list[str] = field(default_factory=list)
    duplicate_external_ids: list[str] = field(default_factory=list)

    def to_summary_dict(self) -> dict:
        return {
            'rows_read': self.rows_read,
            'rows_mapped': self.rows_mapped,
            'rows_skipped_filtered': self.rows_skipped_filtered,
            'rows_failed_mapping': self.rows_failed_mapping,
            'rows_created': self.rows_created,
            'rows_updated': self.rows_updated,
            'rows_skipped_duplicate_in_export': self.rows_skipped_duplicate_in_export,
            'rows_skipped_db_error': self.rows_skipped_db_error,
            'categories_created': self.categories_created,
            'header_error_count': len(self.header_errors),
            'mapping_error_count': len(self.mapping_errors),
            'db_error_count': len(self.db_errors),
            'duplicate_external_id_count': len(self.duplicate_external_ids),
        }


def import_zenoti_services(
    *,
    tenant: Tenant,
    file_obj: IO,
    dry_run: bool = True,
    actor=None,
) -> ServicesImportReport:
    """Run a Zenoti services-with-prices CSV import against the tenant.

    Filtered rows (Nails category, junk 'category' rows) are
    counted as `rows_skipped_filtered` — distinct from mapping
    failures (blank names etc.) so the operator can tell intentional
    skips from real problems.
    """
    report = ServicesImportReport()

    for _ in range(PREAMBLE_LINES):
        next(file_obj, None)

    reader = csv.DictReader(file_obj, fieldnames=EXPECTED_HEADER, restkey='_extra')
    header_row = next(reader, None)
    if header_row is None:
        report.header_errors.append('CSV is empty after the preamble.')
        return report

    header_list = [header_row.get(col, '') for col in EXPECTED_HEADER]
    report.header_errors.extend(validate_header(header_list))
    if report.header_errors:
        return report

    # ── Pass 1 ─────────────────────────────────────────────────────
    mapped_rows: list[MappedService] = []
    for line_number, row in enumerate(reader, start=PREAMBLE_LINES + 2):
        report.rows_read += 1
        mapped, err = map_row(row, line_number=line_number)
        if err is not None:
            if err.reason.startswith('Skipped'):
                report.rows_skipped_filtered += 1
            else:
                report.rows_failed_mapping += 1
                report.mapping_errors.append(err)
        if mapped is not None:
            mapped_rows.append(mapped)
    report.rows_mapped = len(mapped_rows)

    dupes = detect_duplicate_external_ids(mapped_rows)
    report.duplicate_external_ids = list(dupes.keys())

    if dry_run:
        return report

    # ── Pass 2 ─────────────────────────────────────────────────────
    seen_external_ids: set[str] = set()
    category_cache: dict[str, ServiceCategory] = {}
    now = timezone.now()

    for mapped in mapped_rows:
        if mapped.external_id in seen_external_ids:
            report.rows_skipped_duplicate_in_export += 1
            continue
        seen_external_ids.add(mapped.external_id)

        mapped.imported_at = now
        try:
            category = _resolve_category(
                tenant=tenant, name=mapped.category_name,
                cache=category_cache, report=report,
            )
            service, created = _upsert_one(
                tenant=tenant, mapped=mapped, category=category,
            )
        except IntegrityError as e:
            report.rows_skipped_db_error += 1
            report.db_errors.append(f'{mapped.external_id}: {e}'[:300])
            logger.warning(
                'imports.zenoti.services.row_db_error',
                extra={'external_id': mapped.external_id, 'error': str(e)[:200]},
            )
            continue
        except Exception as e:  # noqa: BLE001
            report.rows_skipped_db_error += 1
            report.db_errors.append(f'{mapped.external_id}: {type(e).__name__}: {e}'[:300])
            logger.exception(
                'imports.zenoti.services.row_unexpected_error',
                extra={'external_id': mapped.external_id},
            )
            continue

        if created:
            report.rows_created += 1
        else:
            report.rows_updated += 1

        audit_record(
            action=(
                AuditLog.Action.CREATE if created
                else AuditLog.Action.UPDATE
            ),
            resource_type='service',
            resource_id=service.id,
            user=actor,
            tenant=tenant,
            metadata={
                'source': 'zenoti_import',
                'external_id': mapped.external_id,
                'category': mapped.category_name,
                'verb': 'create' if created else 'update',
            },
        )

    audit_record(
        action=AuditLog.Action.CREATE,
        resource_type='zenoti_services_import_run',
        user=actor,
        tenant=tenant,
        metadata=report.to_summary_dict(),
    )

    return report


def _resolve_category(
    *, tenant: Tenant, name: str,
    cache: dict[str, ServiceCategory], report: ServicesImportReport,
) -> ServiceCategory | None:
    """Find-or-create a ServiceCategory for this tenant.

    `name` may be blank (some Zenoti services are uncategorised) —
    in that case return None and let the Service row have a null
    category FK.
    """
    if not name:
        return None
    cached = cache.get(name)
    if cached is not None:
        return cached
    cat, created = ServiceCategory.objects.get_or_create(
        tenant=tenant, name=name,
    )
    if created:
        report.categories_created += 1
    cache[name] = cat
    return cat


def _upsert_one(
    *, tenant: Tenant, mapped: MappedService, category: ServiceCategory | None,
) -> tuple[Service, bool]:
    """Find-or-create by (tenant, external_source, external_id).

    Updates only the safe-to-overwrite fields (name, code,
    description, duration, price, tax, imported_at). `service_type`
    + `is_bookable_online` are intentionally NOT in `write_kwargs`
    so operator classifications survive re-imports.

    The `category` FK is set on both create + update so re-categorising
    in Zenoti propagates to Lumè.
    """
    with transaction.atomic():
        defaults = mapped.write_kwargs()
        existing = Service.objects.filter(
            tenant=tenant,
            external_source=mapped.external_source,
            external_id=mapped.external_id,
        ).first()
        if existing is not None:
            for k, v in defaults.items():
                setattr(existing, k, v)
            existing.category = category
            existing.save()
            return existing, False
        defaults.update({
            'tenant': tenant,
            'external_source': mapped.external_source,
            'external_id': mapped.external_id,
            'category': category,
        })
        service = Service.objects.create(**defaults)
        return service, True
