"""Pure mappers from Zenoti package-status CSV rows to Lumè
PurchasedPackage + PurchasedPackageItem dicts.

Zenoti Package Status report format (per Manhattan Laser Spa's
2024–2026 exports):

  Line 1:    header (BOM-prefixed)
  Lines 2+:  data rows

Header columns (18):

  Sale Center, Invoice No, Package Name, Guest Name,
  Sale Date, Start Date, Expiry Date,
  Sales, Sales(Inc. Tax),
  Benefit Name,
  Value, Redeemed Value, Refunded Value, Balance Value,
  Expired Value, Suspense, Package Status, Schedule Packages Info

The interesting field is `Benefit Name`, which encodes the bundled
services + per-service session counts:

  "Brazilian Bikini(Service - 6),Full Arms(Service - 6),..."

For each service in the bundle, we compute remaining sessions
proportionally:

  remaining_sessions = qty_purchased × (balance_value / value)

with `floor` rounding and a ceiling of `qty_purchased`. Expired /
Closed / Refunded packages always have 0 remaining sessions
regardless of the balance math (Zenoti sometimes leaves a non-zero
balance on expired packages — it's still un-redeemable post-expiry).

Customer matching: `Guest Name` is parsed into first + last name
and matched case-insensitively against the tenant's customers.
Service matching: each parsed service name from Benefit is matched
case-insensitively against `Service.name`; misses leave
`service=NULL` with the snapshot name kept on the item row (per
operator instruction).

Idempotency key: `external_id = 'zenoti-package:<Invoice No>'`.

See [ADR 0030] for the broader Zenoti migration design rationale;
this mapper shares the same shape + safety posture.
"""

from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Iterable


# Expected header columns Zenoti emits. Trailing blank columns
# tolerated as elsewhere.
EXPECTED_HEADER = [
    'Sale Center', 'Invoice No', 'Package Name', 'Guest Name',
    'Sale Date', 'Start Date', 'Expiry Date',
    'Sales', 'Sales(Inc. Tax)',
    'Benefit Name',
    'Value', 'Redeemed Value', 'Refunded Value', 'Balance Value',
    'Expired Value', 'Suspense', 'Package Status',
    'Schedule Packages Info',
]


# Status values that mean "no sessions can be redeemed anymore."
# We still import these (operator wanted full history) but the
# per-item quantity_remaining is forced to 0.
_DEAD_STATUSES = frozenset({'expired', 'closed', 'refunded'})

# Status values that count as live (still redeemable balance).
_LIVE_STATUSES = frozenset({'active', 'active (refunded)'})


@dataclass
class ParsedBenefit:
    """One service line item parsed from the Benefit Name column."""
    service_name: str          # raw Zenoti name, e.g. 'Brazilian Bikini'
    qty_purchased: int         # total sessions originally bundled
    qty_remaining: int = 0     # computed by the mapper using balance ratio


@dataclass
class MappedPackage:
    """One PurchasedPackage + its PurchasedPackageItem rows.

    The importer turns this into a parent + N children in one
    atomic transaction.
    """

    # Idempotency.
    external_id: str           # e.g. 'zenoti-package:M-MT-19488'
    external_source: str = 'zenoti'
    external_invoice_no: str = ''

    # Customer matching key (case-insensitive lookup).
    customer_first: str = ''
    customer_last: str = ''

    # Package-level snapshots.
    name: str = ''
    description: str = ''
    price_cents: int = 0
    purchased_at: _dt.datetime | None = None
    expires_at: _dt.datetime | None = None
    status: str = 'active'     # Lumè status: active | voided

    # Children.
    items: list[ParsedBenefit] = field(default_factory=list)

    # Metadata for the reconciliation report (not written to DB).
    sale_center: str = ''
    upstream_status: str = ''      # original Zenoti status verbatim
    balance_ratio: float = 1.0     # 1.0 = full balance, 0.0 = none

    def to_package_kwargs(self) -> dict:
        """Fields used on PurchasedPackage create/update (excludes
        items which are handled separately, and excludes the FK +
        provenance fields which the importer sets explicitly)."""
        return {
            'name': self.name,
            'description': self.description,
            'price_cents': self.price_cents,
            'purchased_at': self.purchased_at,
            'expires_at': self.expires_at,
            'status': self.status,
        }


@dataclass
class PackageMapError:
    line_number: int
    raw_guest_name: str
    raw_invoice_no: str
    raw_package_name: str
    reason: str


# ── Header validation ──────────────────────────────────────────────


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


# ── Per-row mapper ─────────────────────────────────────────────────


def map_row(row: dict, *, line_number: int) -> tuple[MappedPackage | None, PackageMapError | None]:
    """Convert one Zenoti package row to a MappedPackage.

    Returns `(mapped, None)` on success or `(None, error)` if the
    row can't be processed. Failure modes:

      - blank Invoice No (we can't dedupe / idempotency-key it)
      - blank Guest Name (can't match a customer)
      - Benefit Name doesn't parse into any service line items
    """
    invoice_no = _clean(row.get('Invoice No', ''))
    guest_name = _clean(row.get('Guest Name', ''))
    package_name = _clean(row.get('Package Name', ''))

    if not invoice_no:
        return None, PackageMapError(
            line_number=line_number,
            raw_guest_name=guest_name, raw_invoice_no=invoice_no,
            raw_package_name=package_name,
            reason='Invoice No is blank (cannot dedupe)',
        )
    if not guest_name:
        return None, PackageMapError(
            line_number=line_number,
            raw_guest_name=guest_name, raw_invoice_no=invoice_no,
            raw_package_name=package_name,
            reason='Guest Name is blank',
        )

    benefit_raw = _clean(row.get('Benefit Name', ''))
    parsed_items = _parse_benefit_name(benefit_raw)
    if not parsed_items:
        return None, PackageMapError(
            line_number=line_number,
            raw_guest_name=guest_name, raw_invoice_no=invoice_no,
            raw_package_name=package_name,
            reason=f'Could not parse any service items from Benefit Name: {benefit_raw!r}',
        )

    first, last = _split_guest_name(guest_name)

    sale_date = _parse_date(row.get('Sale Date', ''))
    expiry_date = _parse_date(row.get('Expiry Date', ''))

    value = _parse_amount(row.get('Value', ''))
    balance = _parse_amount(row.get('Balance Value', ''))
    sales_inc_tax = _parse_amount(row.get('Sales(Inc. Tax)', '')) or _parse_amount(row.get('Sales', ''))
    price_cents = int((sales_inc_tax * 100).to_integral_value()) if sales_inc_tax else 0

    upstream_status = _clean(row.get('Package Status', '')).lower()
    is_live = upstream_status in _LIVE_STATUSES

    # Balance ratio drives the per-service remaining-session math.
    if value > 0 and is_live:
        ratio = float(balance) / float(value)
        if ratio < 0:
            ratio = 0.0
        if ratio > 1:
            ratio = 1.0
    else:
        ratio = 0.0  # dead status → 0 sessions remaining everywhere

    # Compute remaining per service. Floor (operator's loss when
    # the math doesn't divide cleanly — never grant unearned sessions).
    for item in parsed_items:
        if not is_live or ratio == 0:
            item.qty_remaining = 0
        else:
            item.qty_remaining = max(0, min(item.qty_purchased, int(item.qty_purchased * ratio)))

    # Map Zenoti status → Lumè PurchasedPackage.Status enum:
    #   Active / Active (Refunded) → 'active'
    #   Expired / Closed / Refunded → 'active' too, BUT with
    #     all items at quantity_remaining=0. We do NOT void them
    #     because the operator might want to see the history with
    #     "0 of 6 remaining" rather than "package was voided" —
    #     they're closer in meaning to "fully consumed" than to
    #     "deliberately cancelled."
    lume_status = 'active'

    # Description: capture upstream metadata so the operator can
    # trace the row back to Zenoti if questions arise.
    desc_parts = [
        f'Imported from Zenoti (invoice {invoice_no}).',
        f'Original status: {upstream_status or "unknown"}.',
        f'Original sale center: {_clean(row.get("Sale Center", "")) or "unknown"}.',
    ]
    if value > 0:
        desc_parts.append(
            f'Original value: ${value:.2f}; balance remaining at import: '
            f'${balance:.2f} ({int(ratio * 100)}%).'
        )

    return (
        MappedPackage(
            external_id=f'zenoti-package:{invoice_no}'[:100],
            external_invoice_no=invoice_no[:100],
            customer_first=first[:100],
            customer_last=last[:100],
            name=(package_name or f'Zenoti Package {invoice_no}')[:200],
            description='\n'.join(desc_parts),
            price_cents=price_cents,
            purchased_at=_to_dt(sale_date),
            expires_at=_to_dt(expiry_date),
            status=lume_status,
            items=parsed_items,
            sale_center=_clean(row.get('Sale Center', '')),
            upstream_status=upstream_status,
            balance_ratio=ratio,
        ),
        None,
    )


def map_rows(rows: Iterable[dict], *, line_offset: int = 2) -> tuple[list[MappedPackage], list[PackageMapError]]:
    """Map a stream of rows. `line_offset` is the 1-indexed source
    line of the first data row (header is at line 1)."""
    successes: list[MappedPackage] = []
    errors: list[PackageMapError] = []
    for i, row in enumerate(rows, start=line_offset):
        mapped, err = map_row(row, line_number=i)
        if err is not None:
            errors.append(err)
        if mapped is not None:
            successes.append(mapped)
    return successes, errors


def merge_files(per_file_results: list[list[MappedPackage]]) -> tuple[list[MappedPackage], list[str]]:
    """Combine per-file mapper outputs into one deduped list.

    Zenoti exports cap at ~11 months per report, so we accept N
    files and merge them. If the SAME invoice appears in two files
    (boundary overlap), the later occurrence wins (most-recent
    balance is the authoritative one).

    Returns (deduped_list, list_of_duplicate_invoice_nos_for_audit).
    """
    by_id: dict[str, MappedPackage] = {}
    dupes: list[str] = []
    for batch in per_file_results:
        for m in batch:
            if m.external_id in by_id:
                dupes.append(m.external_id)
            by_id[m.external_id] = m  # later wins
    return list(by_id.values()), dupes


# ── Cleaners + parsers ─────────────────────────────────────────────


def _clean(value: str | None) -> str:
    if not value:
        return ''
    # Zenoti emits HTML entities in service names (`&amp;` for `&`,
    # `&#39;` for `'`, etc.) — decode them so service-catalog matching
    # works. `html.unescape` is a no-op on plain text.
    import html
    return html.unescape(re.sub(r'\s+', ' ', str(value)).strip())


def _split_guest_name(full: str) -> tuple[str, str]:
    """Parse "Wendy Penn" → ("Wendy", "Penn"). Handles middle initials,
    hyphenated last names, and stray whitespace."""
    parts = full.split()
    if not parts:
        return '', ''
    if len(parts) == 1:
        return parts[0], ''
    return parts[0], ' '.join(parts[1:])


# Match `Service Name(Service - 6)` — captures name + count.
# Zenoti sometimes uses `(Service-6)` without the space, so the
# regex is permissive on whitespace.
_BENEFIT_PATTERN = re.compile(
    r'(?P<name>.+?)\(\s*Service\s*-\s*(?P<qty>\d+)\s*\)',
)


def _parse_benefit_name(raw: str) -> list[ParsedBenefit]:
    """Parse the comma-separated `Benefit Name` column into items.

    Format: `"Brazilian Bikini(Service - 6),Full Arms(Service - 6)"`.
    Returns a list of `ParsedBenefit(name, qty)` ordered as written.

    Robustness:
      - Trailing whitespace inside each chunk is stripped.
      - Empty input returns an empty list.
      - Items without a `(Service - N)` suffix are skipped (Zenoti
        sometimes embeds product names that don't fit the pattern).
    """
    if not raw:
        return []
    items: list[ParsedBenefit] = []
    # Splitting on commas naively is unsafe — service names CAN
    # contain commas in rare cases (e.g. "Treatment, Premium"). But
    # the (Service - N) suffix is uniquely-shaped, so split on
    # `,(?=[A-Z])` (comma followed by capital letter starting the
    # next item) is a workable heuristic. Fall back to plain `,`
    # split when no capital follows (most rows).
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
            items.append(ParsedBenefit(service_name=name[:200], qty_purchased=qty))
    return items


def _parse_date(value: str | None) -> _dt.date | None:
    raw = _clean(value)
    if not raw:
        return None
    for fmt in ('%m/%d/%Y', '%-m/%-d/%Y', '%m/%d/%y'):
        try:
            return _dt.datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    try:
        return _dt.date.fromisoformat(raw)
    except (ValueError, TypeError):
        return None


def _to_dt(d: _dt.date | None) -> _dt.datetime | None:
    """Convert a date to a timezone-aware datetime at midnight UTC
    (the DB stores datetime; Zenoti gives us dates only)."""
    if d is None:
        return None
    return _dt.datetime.combine(d, _dt.time.min, tzinfo=_dt.timezone.utc)


def _parse_amount(value: str | None) -> Decimal:
    raw = _clean(value)
    if not raw:
        return Decimal('0')
    cleaned = re.sub(r'[\$,\s]', '', raw)
    try:
        amount = Decimal(cleaned)
    except (InvalidOperation, ValueError):
        return Decimal('0')
    return amount
