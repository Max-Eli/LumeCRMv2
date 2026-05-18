"""Zenoti memberships import orchestration.

Per-membership workflow (mirrors the packages importer):

  1. Match Customer by Guest Name (case-insensitive); auto-create
     a placeholder when missing (same flag as appointments importer).
  2. Find-or-create MembershipPlan by name (per-tenant). Each unique
     Zenoti `Membership Name` becomes one MembershipPlan in
     /catalog/memberships so the operator can edit pricing /
     billing-interval after import.
  3. Upsert Subscription on (tenant, external_source, external_id).
  4. Wipe + re-insert SubscriptionItem rows (one per parsed benefit).
     Re-imports refresh the balance proportionally.
  5. Apply Lume status: ACTIVE / CANCELLED / EXPIRED (cancelled/
     expired memberships keep their row with quantity_remaining=0
     for historical record).

Multi-file aware (same as packages + appointments): merge by
Invoice No across N files; later wins.

Service match misses leave `service=NULL` with the snapshot name
preserved on the item (per ADR 0030).
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
from apps.memberships.models import (
    MembershipPlan, Subscription, SubscriptionItem,
)
from apps.services.models import Service
from apps.tenants.models import Tenant

from .memberships_mapper import (
    EXPECTED_HEADER,
    MappedMembership,
    MembershipMapError,
    map_row,
    merge_membership_files,
    validate_header,
)

logger = logging.getLogger(__name__)


@dataclass
class MembershipsImportReport:
    files_read: int = 0
    rows_read: int = 0
    rows_mapped: int = 0
    rows_failed_mapping: int = 0
    rows_deduped_across_files: int = 0
    rows_skipped_db_error: int = 0
    rows_created: int = 0
    rows_updated: int = 0
    items_created: int = 0
    items_matched_service: int = 0
    items_unmatched_service: int = 0
    plans_created: int = 0
    plans_reused: int = 0
    placeholder_customers_created: int = 0
    header_errors: list[str] = field(default_factory=list)
    mapping_errors: list[MembershipMapError] = field(default_factory=list)
    db_errors: list[str] = field(default_factory=list)
    unmatched_service_names: set[str] = field(default_factory=set)

    def to_summary_dict(self) -> dict:
        return {
            'files_read': self.files_read,
            'rows_read': self.rows_read,
            'rows_mapped': self.rows_mapped,
            'rows_failed_mapping': self.rows_failed_mapping,
            'rows_deduped_across_files': self.rows_deduped_across_files,
            'rows_skipped_db_error': self.rows_skipped_db_error,
            'rows_created': self.rows_created,
            'rows_updated': self.rows_updated,
            'items_created': self.items_created,
            'items_matched_service': self.items_matched_service,
            'items_unmatched_service': self.items_unmatched_service,
            'plans_created': self.plans_created,
            'plans_reused': self.plans_reused,
            'placeholder_customers_created': self.placeholder_customers_created,
            'header_error_count': len(self.header_errors),
            'mapping_error_count': len(self.mapping_errors),
            'db_error_count': len(self.db_errors),
            'unmatched_service_name_count': len(self.unmatched_service_names),
        }


def import_zenoti_memberships(
    *,
    tenant: Tenant,
    file_objs: list[IO],
    dry_run: bool = True,
    actor=None,
) -> MembershipsImportReport:
    report = MembershipsImportReport(files_read=len(file_objs))

    # ── Pass 1: parse all files ────────────────────────────────────
    per_file: list[list[MappedMembership]] = []
    for f in file_objs:
        reader = csv.DictReader(f)
        header_errs = validate_header(reader.fieldnames or [])
        if header_errs:
            report.header_errors.extend(header_errs)
            continue
        batch: list[MappedMembership] = []
        for line_number, row in enumerate(reader, start=2):
            report.rows_read += 1
            m, err = map_row(row, line_number=line_number)
            if err is not None:
                report.rows_failed_mapping += 1
                report.mapping_errors.append(err)
            if m is not None:
                batch.append(m)
        per_file.append(batch)

    if report.header_errors:
        return report

    deduped, dupes = merge_membership_files(per_file)
    report.rows_deduped_across_files = len(dupes)
    report.rows_mapped = len(deduped)

    if dry_run:
        # Pre-flight: surface unmatched services so the operator can
        # spot-check before live.
        catalog = _build_service_catalog(tenant=tenant)
        for m in deduped:
            for item in m.items:
                if _match_service(item.service_name, catalog) is None:
                    report.unmatched_service_names.add(item.service_name)
        return report

    # ── Pass 2: write ──────────────────────────────────────────────
    customer_cache: dict[tuple[str, str], Customer | None] = {}
    plan_cache: dict[str, MembershipPlan] = {}
    service_catalog = _build_service_catalog(tenant=tenant)
    now = timezone.now()
    placeholder_count = [0]

    for mapped in deduped:
        try:
            customer = _match_or_create_customer(
                tenant=tenant, mapped=mapped, cache=customer_cache,
                placeholder_count_ref=placeholder_count,
            )
            plan = _resolve_plan(
                tenant=tenant, name=mapped.plan_name,
                cache=plan_cache, report=report,
                snapshot_price_cents=mapped.price_cents,
            )
            sub, created, item_stats = _upsert_subscription(
                tenant=tenant, mapped=mapped, customer=customer,
                plan=plan, service_catalog=service_catalog, now=now,
            )
        except IntegrityError as e:
            report.rows_skipped_db_error += 1
            report.db_errors.append(f'{mapped.external_id}: {e}'[:300])
            logger.warning(
                'imports.zenoti.memberships.row_db_error',
                extra={'external_id': mapped.external_id, 'error': str(e)[:200]},
            )
            continue
        except Exception as e:  # noqa: BLE001
            report.rows_skipped_db_error += 1
            report.db_errors.append(f'{mapped.external_id}: {type(e).__name__}: {e}'[:300])
            logger.exception(
                'imports.zenoti.memberships.row_unexpected_error',
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
            resource_type='subscription',
            resource_id=sub.id,
            user=actor, tenant=tenant,
            metadata={
                'source': 'zenoti_import',
                'external_id': mapped.external_id,
                'external_invoice_no': mapped.external_invoice_no,
                'customer_id': customer.id,
                'plan_id': plan.id,
                'lume_status': mapped.lume_status,
                'upstream_status': mapped.upstream_status,
            },
        )

    audit_record(
        action=AuditLog.Action.CREATE,
        resource_type='zenoti_memberships_import_run',
        user=actor, tenant=tenant,
        metadata=report.to_summary_dict(),
    )

    report.placeholder_customers_created = placeholder_count[0]
    return report


# ── Helpers ────────────────────────────────────────────────────────


def _match_or_create_customer(
    *, tenant: Tenant, mapped: MappedMembership,
    cache: dict[tuple[str, str], Customer | None],
    placeholder_count_ref: list[int],
) -> Customer:
    """Same placeholder strategy as appointments importer."""
    key = (mapped.customer_first.lower(), mapped.customer_last.lower())
    if key in cache and cache[key] is not None:
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
    if customer is not None:
        cache[key] = customer
        return customer

    import re
    name_slug = re.sub(
        r'[^a-z0-9]+', '-',
        f'{mapped.customer_first} {mapped.customer_last}'.lower(),
    ).strip('-') or 'unknown'
    eid = f'zenoti-sub-placeholder:{name_slug}'[:100]

    existing = Customer.objects.filter(
        tenant=tenant, external_source='zenoti', external_id=eid,
    ).first()
    if existing is not None:
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
            'Auto-created by Zenoti membership import — original guest '
            'record was not present in the active-guest export. No '
            'contact info on file.'
        ),
    )
    placeholder_count_ref[0] += 1
    cache[key] = placeholder
    return placeholder


def _resolve_plan(
    *, tenant: Tenant, name: str,
    cache: dict[str, MembershipPlan], report: MembershipsImportReport,
    snapshot_price_cents: int,
) -> MembershipPlan:
    """Find-or-create a MembershipPlan per unique Zenoti name."""
    if name in cache:
        return cache[name]
    plan, created = MembershipPlan.objects.get_or_create(
        tenant=tenant,
        name=name,
        defaults={
            # Snapshot the first sale price we see as the plan's
            # default. Operator can edit via /catalog/memberships.
            'price_cents': snapshot_price_cents,
            'billing_interval': (
                MembershipPlan.BillingInterval.ANNUAL
                if 'annual' in name.lower()
                else MembershipPlan.BillingInterval.MONTHLY
            ),
        },
    )
    if created:
        report.plans_created += 1
    else:
        report.plans_reused += 1
    cache[name] = plan
    return plan


def _build_service_catalog(*, tenant: Tenant) -> dict[str, Service]:
    catalog: dict[str, Service] = {}
    for s in Service.objects.filter(tenant=tenant).only('id', 'name', 'price_cents'):
        catalog[_norm_name(s.name)] = s
    return catalog


def _norm_name(name: str) -> str:
    import re
    return re.sub(r'\s+', ' ', (name or '').lower()).strip()


def _match_service(name: str, catalog: dict[str, Service]) -> Service | None:
    return catalog.get(_norm_name(name))


def _upsert_subscription(
    *, tenant: Tenant, mapped: MappedMembership, customer: Customer,
    plan: MembershipPlan, service_catalog: dict[str, Service], now,
) -> tuple[Subscription, bool, dict]:
    """Find-or-create the Subscription + replace its items.

    Same pattern as packages: items are wiped + re-inserted on re-
    import so balance refreshes idempotently.
    """
    item_stats = {
        'items_created': 0,
        'items_matched': 0,
        'items_unmatched': 0,
        'unmatched_names': set(),
    }

    with transaction.atomic():
        sub, created = Subscription.objects.update_or_create(
            tenant=tenant,
            external_source=mapped.external_source,
            external_id=mapped.external_id,
            defaults={
                'customer': customer,
                'plan': plan,
                'external_invoice_no': mapped.external_invoice_no,
                'imported_at': now,
                'name': mapped.plan_name,
                'description': mapped.description,
                'price_cents': mapped.price_cents,
                'billing_interval': plan.billing_interval,
                'started_at': mapped.started_at,
                'current_period_starts_at': mapped.current_period_starts_at,
                'current_period_ends_at': mapped.current_period_ends_at,
                'status': mapped.lume_status,
                'cancelled_at': mapped.cancelled_at,
                'cancel_reason': mapped.cancel_reason,
            },
        )
        sub.items.all().delete()

        for sort_idx, parsed in enumerate(mapped.items):
            service = _match_service(parsed.service_name, service_catalog)
            unit_price_cents = service.price_cents if service else 0
            SubscriptionItem.objects.create(
                subscription=sub,
                service=service,
                service_name=parsed.service_name[:200],
                quantity_per_cycle=parsed.qty_per_cycle,
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

    return sub, created, item_stats
