"""Pure mappers from Zenoti membership CSV rows to Lumè
Subscription + SubscriptionItem (and auto-create MembershipPlan).

Zenoti Memberships Report format (per Manhattan Laser Spa's
2022–2026 exports):

  Line 1:    header (BOM-prefixed)
  Lines 2+:  data rows

Header columns (20):

  Sale Center, Center Code, Invoice No, Membership Name,
  Membership Type, Benefit Type, Guest Name,
  Sale Date, Start Date,
  Sales, Sales(Inc. Tax),
  Benefit,
  Redeemed Value, Cancelled Value, Expired Value, Suspense,
  Balance Value, Membership Status, Recurrence Status,
  Next Recurrence Date

Shares the `Benefit` format with packages — `Service Name(Service
- N)` comma-separated — so reuses the same parser. Different from
packages in that memberships are RECURRING (Zenoti has a
"Recurrence Status" column tracking the billing-cycle health
separately from the membership-balance state).

Status mapping (Zenoti → Lumè Subscription.Status):

  | Zenoti              | Lumè      | quantity_remaining     |
  |---------------------|-----------|------------------------|
  | Active              | ACTIVE    | per balance math       |
  | Frozen              | ACTIVE    | per balance math       |
  | Suspended           | ACTIVE    | per balance math       |
  | Upgrade / Downgrade | ACTIVE    | per balance math       |
  | Cancelled           | CANCELLED | 0                      |
  | Expired             | EXPIRED   | 0                      |
  | Closed              | CANCELLED | 0 (fully consumed)     |

Frozen + Suspended both map to ACTIVE because Lumè's model
doesn't have an explicit "paused" status; the balance is what
matters operationally + the upstream status is preserved in
description for traceability.

Idempotency key: `external_id = 'zenoti-sub:<Invoice No>'`.

See [ADR 0030] for the Zenoti migration design.
"""

from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Iterable


EXPECTED_HEADER = [
    'Sale Center', 'Center Code', 'Invoice No', 'Membership Name',
    'Membership Type', 'Benefit Type', 'Guest Name',
    'Sale Date', 'Start Date',
    'Sales', 'Sales(Inc. Tax)',
    'Benefit',
    'Redeemed Value', 'Cancelled Value', 'Expired Value', 'Suspense',
    'Balance Value', 'Membership Status', 'Recurrence Status',
    'Next Recurrence Date',
]


_DEAD_STATUSES = frozenset({'cancelled', 'expired', 'closed'})

# Zenoti statuses that keep the cycle alive (balance still
# redeemable in principle, even if Frozen/Suspended pauses it).
_LIVE_STATUSES = frozenset({
    'active', 'frozen', 'suspended', 'upgrade', 'downgrade',
})


@dataclass
class ParsedBenefit:
    """One service line on the membership's benefit list."""
    service_name: str
    qty_per_cycle: int
    qty_remaining: int = 0


@dataclass
class MappedMembership:
    """One Subscription + its SubscriptionItem rows + the resolved plan name."""

    # Idempotency.
    external_id: str               # 'zenoti-sub:<Invoice No>'
    external_source: str = 'zenoti'
    external_invoice_no: str = ''

    # Customer matching.
    customer_first: str = ''
    customer_last: str = ''

    # Plan auto-create key. Importer find-or-creates a MembershipPlan
    # per unique name within the tenant.
    plan_name: str = ''

    # Subscription-level snapshots.
    description: str = ''
    price_cents: int = 0
    started_at: _dt.datetime | None = None
    current_period_starts_at: _dt.datetime | None = None
    current_period_ends_at: _dt.datetime | None = None
    lume_status: str = 'active'    # active | cancelled | expired

    # Children.
    items: list[ParsedBenefit] = field(default_factory=list)

    # Cancelled state (only when lume_status == 'cancelled').
    cancelled_at: _dt.datetime | None = None
    cancel_reason: str = ''

    # Metadata for the reconciliation report.
    sale_center: str = ''
    upstream_status: str = ''
    upstream_recurrence_status: str = ''
    balance_ratio: float = 1.0


@dataclass
class MembershipMapError:
    line_number: int
    raw_guest_name: str
    raw_invoice_no: str
    raw_plan_name: str
    reason: str


def validate_header(header_row: list[str]) -> list[str]:
    errors: list[str] = []
    for i, expected in enumerate(EXPECTED_HEADER):
        if i >= len(header_row):
            errors.append(f'Missing column at position {i}: expected {expected!r}')
            continue
        actual = (header_row[i] or '').strip()
        if actual != expected:
            errors.append(
                f'Header mismatch at column {i}: expected {expected!r}, got {actual!r}'
            )
    return errors


def map_row(row: dict, *, line_number: int) -> tuple[MappedMembership | None, MembershipMapError | None]:
    invoice_no = _clean(row.get('Invoice No', ''))
    guest_name = _clean(row.get('Guest Name', ''))
    plan_name = _clean(row.get('Membership Name', ''))

    if not invoice_no:
        return None, MembershipMapError(
            line_number=line_number,
            raw_guest_name=guest_name, raw_invoice_no=invoice_no,
            raw_plan_name=plan_name, reason='Invoice No is blank',
        )
    if not guest_name:
        return None, MembershipMapError(
            line_number=line_number,
            raw_guest_name=guest_name, raw_invoice_no=invoice_no,
            raw_plan_name=plan_name, reason='Guest Name is blank',
        )
    if not plan_name:
        return None, MembershipMapError(
            line_number=line_number,
            raw_guest_name=guest_name, raw_invoice_no=invoice_no,
            raw_plan_name=plan_name, reason='Membership Name is blank',
        )

    benefit_raw = _clean(row.get('Benefit', ''))
    parsed_items = _parse_benefit(benefit_raw)
    # Memberships may legitimately have no service-line benefit (a
    # discount-only membership). Don't reject — just create the
    # Subscription with zero items.

    first, last = _split_guest_name(guest_name)
    sale_date = _parse_date(row.get('Sale Date', ''))
    start_date = _parse_date(row.get('Start Date', ''))
    next_recurrence = _parse_date(row.get('Next Recurrence Date', ''))

    value_in_tax = _parse_amount(row.get('Sales(Inc. Tax)', '')) or _parse_amount(row.get('Sales', ''))
    price_cents = int((value_in_tax * 100).to_integral_value()) if value_in_tax else 0

    # Balance ratio: prefer the sale-price denominator (Sales(Inc. Tax)).
    balance = _parse_amount(row.get('Balance Value', ''))
    value_for_ratio = _parse_amount(row.get('Sales(Inc. Tax)', '')) or _parse_amount(row.get('Sales', ''))

    upstream_status = _clean(row.get('Membership Status', '')).lower()
    upstream_recurrence = _clean(row.get('Recurrence Status', '')).lower()
    is_live = upstream_status in _LIVE_STATUSES

    if value_for_ratio > 0 and is_live:
        ratio = float(balance) / float(value_for_ratio)
        ratio = max(0.0, min(1.0, ratio))
    else:
        ratio = 0.0

    for item in parsed_items:
        if not is_live or ratio == 0:
            item.qty_remaining = 0
        else:
            item.qty_remaining = max(
                0, min(item.qty_per_cycle, int(item.qty_per_cycle * ratio)),
            )

    # Lumè status resolution.
    if upstream_status == 'expired':
        lume_status = 'expired'
    elif upstream_status in ('cancelled', 'closed'):
        lume_status = 'cancelled'
    else:
        lume_status = 'active'

    cancelled_at: _dt.datetime | None = None
    cancel_reason = ''
    if lume_status == 'cancelled':
        cancelled_at = _to_dt(sale_date) or _to_dt(start_date)
        cancel_reason = f'Zenoti import (upstream status: {upstream_status})'

    desc_parts = [
        f'Imported from Zenoti (invoice {invoice_no}).',
        f'Upstream membership status: {upstream_status or "unknown"}.',
        f'Upstream recurrence status: {upstream_recurrence or "unknown"}.',
        f'Original sale center: {_clean(row.get("Sale Center", "")) or "unknown"}.',
    ]
    if next_recurrence:
        desc_parts.append(f'Next Zenoti recurrence date: {next_recurrence.isoformat()}.')
    if value_for_ratio > 0:
        desc_parts.append(
            f'Original value: ${value_for_ratio:.2f}; balance at import: '
            f'${balance:.2f} ({int(ratio * 100)}%).'
        )

    return (
        MappedMembership(
            external_id=f'zenoti-sub:{invoice_no}'[:100],
            external_invoice_no=invoice_no[:100],
            customer_first=first[:100],
            customer_last=last[:100],
            plan_name=plan_name[:200],
            description='\n'.join(desc_parts),
            price_cents=price_cents,
            started_at=_to_dt(start_date) or _to_dt(sale_date),
            current_period_starts_at=_to_dt(start_date) or _to_dt(sale_date),
            current_period_ends_at=_to_dt(next_recurrence),
            lume_status=lume_status,
            items=parsed_items,
            cancelled_at=cancelled_at,
            cancel_reason=cancel_reason,
            sale_center=_clean(row.get('Sale Center', '')),
            upstream_status=upstream_status,
            upstream_recurrence_status=upstream_recurrence,
            balance_ratio=ratio,
        ),
        None,
    )


def merge_membership_files(
    per_file: list[list[MappedMembership]],
) -> tuple[list[MappedMembership], list[str]]:
    """Combine files by external_id; later wins. Same pattern as
    packages_mapper.merge_files."""
    by_id: dict[str, MappedMembership] = {}
    dupes: list[str] = []
    for batch in per_file:
        for m in batch:
            if m.external_id in by_id:
                dupes.append(m.external_id)
            by_id[m.external_id] = m
    return list(by_id.values()), dupes


# ── Parsers ────────────────────────────────────────────────────────


def _clean(value: str | None) -> str:
    if not value:
        return ''
    return re.sub(r'\s+', ' ', str(value)).strip()


def _split_guest_name(full: str) -> tuple[str, str]:
    parts = full.split()
    if not parts:
        return '', ''
    if len(parts) == 1:
        return parts[0], ''
    return parts[0], ' '.join(parts[1:])


_BENEFIT_PATTERN = re.compile(
    r'(?P<name>.+?)\(\s*Service\s*-\s*(?P<qty>\d+)\s*\)',
)


def _parse_benefit(raw: str) -> list[ParsedBenefit]:
    """Same shape as packages benefits: 'Name(Service - N),Name2(Service - N)'."""
    if not raw:
        return []
    items: list[ParsedBenefit] = []
    chunks = re.split(r',(?=[A-Z0-9])', raw) if ',' in raw else [raw]
    for chunk in chunks:
        m = _BENEFIT_PATTERN.search(chunk.strip())
        if not m:
            continue
        name = m.group('name').strip().rstrip(',').strip()
        try:
            qty = int(m.group('qty'))
        except ValueError:
            continue
        if name and qty > 0:
            items.append(ParsedBenefit(
                service_name=name[:200], qty_per_cycle=qty,
            ))
    return items


def _parse_date(value: str | None) -> _dt.date | None:
    raw = _clean(value)
    if not raw:
        return None
    for fmt in ('%m/%d/%Y', '%m/%d/%y', '%Y-%m-%d'):
        try:
            return _dt.datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    try:
        return _dt.date.fromisoformat(raw)
    except (ValueError, TypeError):
        return None


def _to_dt(d: _dt.date | None) -> _dt.datetime | None:
    if d is None:
        return None
    return _dt.datetime.combine(d, _dt.time.min, tzinfo=_dt.timezone.utc)


def _parse_amount(value: str | None) -> Decimal:
    raw = _clean(value)
    if not raw:
        return Decimal('0')
    cleaned = re.sub(r'[\$,\s]', '', raw)
    try:
        return Decimal(cleaned)
    except (InvalidOperation, ValueError):
        return Decimal('0')


def map_rows(
    rows: Iterable[dict], *, line_offset: int = 2,
) -> tuple[list[MappedMembership], list[MembershipMapError]]:
    successes: list[MappedMembership] = []
    errors: list[MembershipMapError] = []
    for i, row in enumerate(rows, start=line_offset):
        m, e = map_row(row, line_number=i)
        if e is not None:
            errors.append(e)
        if m is not None:
            successes.append(m)
    return successes, errors
