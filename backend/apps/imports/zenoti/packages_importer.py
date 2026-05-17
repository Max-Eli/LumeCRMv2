"""Zenoti packages import orchestration.

Multi-file aware — Zenoti caps the Package Status report at ~11
months, so a real spa migration ships 3-4 CSVs to cover several
years. The importer accepts an arbitrary list of file objects and
merges them by Invoice No (latest occurrence wins).

Two-pass shape mirrors the customer + services importers:

  Pass 1: validate all headers, map all rows, dedupe across files,
          report counts + per-row errors. NO DB writes.
  Pass 2: for each deduped mapped package:
            - match the customer by case-insensitive (first, last)
            - upsert PurchasedPackage on (tenant, external_source,
              external_id)
            - upsert PurchasedPackageItem rows per benefit (matched
              against Service catalog by name; unmatched leaves
              `service=NULL` with the snapshot name preserved)
          Each package is atomic; one failed row doesn't roll back
          the others. Audit-logged per-row + one aggregate run.

Customer-match misses: counted as `rows_skipped_no_customer` and
listed in the error log so the operator can manually triage
(typos, recent name changes, departed clients).

Service-match misses: NOT counted as failures — the package still
imports with `service=NULL` per [ADR 0030] decision recorded with
the user.
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
from apps.packages.models import PurchasedPackage, PurchasedPackageItem
from apps.services.models import Service
from apps.tenants.models import Tenant

from .packages_mapper import (
    EXPECTED_HEADER,
    MappedPackage,
    PackageMapError,
    map_row,
    merge_files,
    validate_header,
)

logger = logging.getLogger(__name__)


@dataclass
class PackagesImportReport:
    files_read: int = 0
    rows_read: int = 0
    rows_mapped: int = 0
    rows_failed_mapping: int = 0
    rows_deduped_across_files: int = 0
    rows_skipped_no_customer: int = 0
    rows_skipped_db_error: int = 0
    rows_created: int = 0
    rows_updated: int = 0
    items_created: int = 0
    items_matched_service: int = 0
    items_unmatched_service: int = 0
    header_errors: list[str] = field(default_factory=list)
    mapping_errors: list[PackageMapError] = field(default_factory=list)
    db_errors: list[str] = field(default_factory=list)
    customer_misses: list[str] = field(default_factory=list)
    unmatched_service_names: set[str] = field(default_factory=set)

    def to_summary_dict(self) -> dict:
        return {
            'files_read': self.files_read,
            'rows_read': self.rows_read,
            'rows_mapped': self.rows_mapped,
            'rows_failed_mapping': self.rows_failed_mapping,
            'rows_deduped_across_files': self.rows_deduped_across_files,
            'rows_skipped_no_customer': self.rows_skipped_no_customer,
            'rows_skipped_db_error': self.rows_skipped_db_error,
            'rows_created': self.rows_created,
            'rows_updated': self.rows_updated,
            'items_created': self.items_created,
            'items_matched_service': self.items_matched_service,
            'items_unmatched_service': self.items_unmatched_service,
            'header_error_count': len(self.header_errors),
            'mapping_error_count': len(self.mapping_errors),
            'db_error_count': len(self.db_errors),
            'customer_miss_count': len(self.customer_misses),
            'unmatched_service_name_count': len(self.unmatched_service_names),
        }


def import_zenoti_packages(
    *,
    tenant: Tenant,
    file_objs: list[IO],
    dry_run: bool = True,
    actor=None,
) -> PackagesImportReport:
    """Run an import across one or more Zenoti Package Status CSVs."""
    report = PackagesImportReport(files_read=len(file_objs))

    # ── Pass 1: parse + map every file ──────────────────────────────
    per_file: list[list[MappedPackage]] = []
    for f in file_objs:
        reader = csv.DictReader(f)  # Zenoti packages CSVs have NO preamble
        header_list = reader.fieldnames or []
        header_errors = validate_header(header_list)
        if header_errors:
            report.header_errors.extend(header_errors)
            continue

        batch: list[MappedPackage] = []
        for line_number, row in enumerate(reader, start=2):
            report.rows_read += 1
            mapped, err = map_row(row, line_number=line_number)
            if err is not None:
                report.rows_failed_mapping += 1
                report.mapping_errors.append(err)
            if mapped is not None:
                batch.append(mapped)
        per_file.append(batch)

    if report.header_errors:
        return report

    deduped, duplicate_invoice_nos = merge_files(per_file)
    report.rows_deduped_across_files = len(duplicate_invoice_nos)
    report.rows_mapped = len(deduped)

    if dry_run:
        # Still surface unmatched service names + customer misses in
        # the dry-run output so the operator can fix the data first.
        customer_cache: dict[tuple[str, str], Customer | None] = {}
        for mapped in deduped:
            if _match_customer(tenant=tenant, mapped=mapped, cache=customer_cache) is None:
                report.rows_skipped_no_customer += 1
                report.customer_misses.append(
                    f'{mapped.customer_first} {mapped.customer_last} (invoice {mapped.external_invoice_no})'
                )
        # Service-name pre-flight.
        catalog = _build_service_catalog(tenant=tenant)
        for mapped in deduped:
            for item in mapped.items:
                if _match_service(item.service_name, catalog) is None:
                    report.unmatched_service_names.add(item.service_name)
        return report

    # ── Pass 2: write ──────────────────────────────────────────────
    customer_cache: dict[tuple[str, str], Customer | None] = {}
    service_catalog = _build_service_catalog(tenant=tenant)
    now = timezone.now()

    for mapped in deduped:
        customer = _match_customer(tenant=tenant, mapped=mapped, cache=customer_cache)
        if customer is None:
            report.rows_skipped_no_customer += 1
            report.customer_misses.append(
                f'{mapped.customer_first} {mapped.customer_last} (invoice {mapped.external_invoice_no})'
            )
            continue

        mapped_imported_at = now
        try:
            pkg, created, item_stats = _upsert_one(
                tenant=tenant, mapped=mapped, customer=customer,
                service_catalog=service_catalog, now=mapped_imported_at,
            )
        except IntegrityError as e:
            report.rows_skipped_db_error += 1
            report.db_errors.append(f'{mapped.external_id}: {e}'[:300])
            logger.warning(
                'imports.zenoti.packages.row_db_error',
                extra={'external_id': mapped.external_id, 'error': str(e)[:200]},
            )
            continue
        except Exception as e:  # noqa: BLE001
            report.rows_skipped_db_error += 1
            report.db_errors.append(f'{mapped.external_id}: {type(e).__name__}: {e}'[:300])
            logger.exception(
                'imports.zenoti.packages.row_unexpected_error',
                extra={'external_id': mapped.external_id},
            )
            continue

        if created:
            report.rows_created += 1
        else:
            report.rows_updated += 1
        report.items_created += item_stats['items_created']
        report.items_matched_service += item_stats['items_matched']
        report.items_unmatched_service += item_stats['items_unmatched']
        for n in item_stats['unmatched_names']:
            report.unmatched_service_names.add(n)

        audit_record(
            action=AuditLog.Action.CREATE if created else AuditLog.Action.UPDATE,
            resource_type='purchased_package',
            resource_id=pkg.id,
            user=actor, tenant=tenant,
            metadata={
                'source': 'zenoti_import',
                'external_id': mapped.external_id,
                'external_invoice_no': mapped.external_invoice_no,
                'verb': 'create' if created else 'update',
                'customer_id': customer.id,
                'item_count': item_stats['items_created'],
            },
        )

    audit_record(
        action=AuditLog.Action.CREATE,
        resource_type='zenoti_packages_import_run',
        user=actor, tenant=tenant,
        metadata=report.to_summary_dict(),
    )

    return report


# ── Helpers ────────────────────────────────────────────────────────


def _match_customer(
    *, tenant: Tenant, mapped: MappedPackage,
    cache: dict[tuple[str, str], Customer | None],
) -> Customer | None:
    """Case-insensitive (first, last) lookup, cached per (first, last).

    Strategy:
      1. Exact case-insensitive match on (first_name, last_name).
      2. Fallback: just last_name (first matches a different field?).
      3. Give up → None.

    Returns the Customer or None. Cache prevents N²-ish queries
    when the same customer has many packages in the file.
    """
    key = (mapped.customer_first.lower(), mapped.customer_last.lower())
    if key in cache:
        return cache[key]

    qs = Customer.objects.filter(tenant=tenant)
    # Step 1: exact-ish.
    customer = qs.filter(
        first_name__iexact=mapped.customer_first,
        last_name__iexact=mapped.customer_last,
    ).first()

    # Step 2: last name only if exact missed (Zenoti sometimes has
    # nicknames in first; "Bobby" vs "Robert"). Only use this when
    # exactly one customer with that last name exists — multiple
    # matches are ambiguous.
    if customer is None and mapped.customer_last:
        candidates = list(qs.filter(last_name__iexact=mapped.customer_last)[:2])
        if len(candidates) == 1:
            customer = candidates[0]

    cache[key] = customer
    return customer


def _build_service_catalog(*, tenant: Tenant) -> dict[str, Service]:
    """Map normalized service name → Service for fast lookup.

    Case-insensitive + whitespace-collapsed so minor name drift
    between Zenoti and Lumè still matches.
    """
    catalog: dict[str, Service] = {}
    for s in Service.objects.filter(tenant=tenant).only('id', 'name'):
        catalog[_norm_name(s.name)] = s
    return catalog


def _norm_name(name: str) -> str:
    import re
    return re.sub(r'\s+', ' ', (name or '').lower()).strip()


def _match_service(name: str, catalog: dict[str, Service]) -> Service | None:
    return catalog.get(_norm_name(name))


def _upsert_one(
    *, tenant: Tenant, mapped: MappedPackage, customer: Customer,
    service_catalog: dict[str, Service], now,
) -> tuple[PurchasedPackage, bool, dict]:
    """Find-or-create the PurchasedPackage + replace its items.

    Items are REPLACED on re-import (delete + insert) so balance
    refreshes correctly when Zenoti shows new redemptions. This is
    safe because per [ADR 0030] we do NOT create PackageRedemption
    rows for imported packages — the items table IS the source of
    truth for balance. Live (non-imported) packages keep the
    standard create-only item lifecycle.

    Returns (package, created_bool, item_stats_dict).
    """
    item_stats = {
        'items_created': 0,
        'items_matched': 0,
        'items_unmatched': 0,
        'unmatched_names': set(),
    }

    with transaction.atomic():
        pkg, created = PurchasedPackage.objects.update_or_create(
            tenant=tenant,
            external_source=mapped.external_source,
            external_id=mapped.external_id,
            defaults={
                'customer': customer,
                'external_invoice_no': mapped.external_invoice_no,
                'imported_at': now,
                **mapped.to_package_kwargs(),
            },
        )

        # Wipe + re-insert items so balance refreshes idempotently.
        pkg.items.all().delete()

        for sort_idx, parsed in enumerate(mapped.items):
            service = _match_service(parsed.service_name, service_catalog)
            unit_price_cents = service.price_cents if service else 0
            PurchasedPackageItem.objects.create(
                purchased_package=pkg,
                service=service,                        # may be None
                service_name=parsed.service_name[:200], # always set the snapshot
                quantity_purchased=parsed.qty_purchased,
                quantity_remaining=parsed.qty_remaining,
                unit_value_cents=unit_price_cents,
                sort_order=sort_idx,
            )
            item_stats['items_created'] += 1
            if service is not None:
                item_stats['items_matched'] += 1
            else:
                item_stats['items_unmatched'] += 1
                item_stats['unmatched_names'].add(parsed.service_name)

    return pkg, created, item_stats
