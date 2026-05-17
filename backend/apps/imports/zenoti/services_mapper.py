"""Pure mappers from Zenoti `serviceswithprices.csv` rows to Lumè Service dicts.

Same shape as `mappers.py` (customer importer) — kept separate
because services have their own column schema, category-creation
side-effect, and price-extraction logic that doesn't belong in the
customer module.

Zenoti `serviceswithprices.csv` format (per Manhattan Laser Spa's
May 2026 export):

  Lines 1–4: preamble (Notification, Center : Florida, Service
             Centers, blank)
  Line 5:    header (14 real columns + 1 trailing blank)
  Lines 6+:  data rows

Header columns:

  ServiceName, Category, SubCategory, Duration, RecoveryTime,
  CommissionEligible, ServiceDescription, CommissionFactor,
  ServiceInternalCost, Code, FloridaPricePrice, FloridaPriceTax,
  MidtownPricePrice, MidtownPriceTax

Per-center prices: this export carries Florida + Midtown prices.
Per the operator's instruction the Lumè tenant is single-location
(Florida only), so we use ONLY the Florida column. Services with
a blank Florida price import at $0 — operator fills later via the
UI, or removes services the Florida location doesn't actually
offer.

See ADR 0030 §"Services migration" for the rationale on per-center
collapse, Nails-category skip, and SubCategory → description capture.
"""

from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Iterable


# Preamble line count before the header. Same shape as the
# customer export — validate it on read so a format change fails
# loudly rather than mis-mapping 350 rows.
PREAMBLE_LINES = 4

# Header columns Zenoti emits. The CSV has one trailing blank
# column (Zenoti's exporter quirk) which we tolerate.
EXPECTED_HEADER = [
    'ServiceName', 'Category', 'SubCategory', 'Duration',
    'RecoveryTime', 'CommissionEligible', 'ServiceDescription',
    'CommissionFactor', 'ServiceInternalCost', 'Code',
    'FloridaPricePrice', 'FloridaPriceTax',
    'MidtownPricePrice', 'MidtownPriceTax',
]


@dataclass
class MappedService:
    """The shape `importer.py` writes for each Service row.

    Field names match the `Service` model attributes so the importer
    can call `Service.objects.update_or_create(**upsert_kwargs(),
    defaults=write_kwargs())`.
    """

    external_id: str           # e.g. 'zenoti-service:INJADDON1'
    external_source: str = 'zenoti'

    # Required.
    name: str = ''

    # Optional fields with sensible defaults that match the Service
    # model's own defaults.
    code: str = ''             # truncated Zenoti Code (<=50 chars)
    description: str = ''
    category_name: str = ''    # used to find-or-create ServiceCategory
    duration_minutes: int = 60
    price_cents: int = 0
    tax_rate_percent: Decimal = Decimal('0')

    # Provenance.
    imported_at: _dt.datetime | None = None

    # Metadata captured for the reconciliation report but not stored.
    sub_category: str = ''
    florida_price_raw: str = ''

    def upsert_kwargs(self) -> dict:
        return {
            'external_source': self.external_source,
            'external_id': self.external_id,
        }

    def write_kwargs(self) -> dict:
        """The fields written on every import run.

        Excludes `service_type` so a re-run never overwrites an
        operator's later "this is actually an add-on" classification.
        Excludes `is_bookable_online` for the same reason — operators
        opt-in per service via the UI.
        """
        return {
            'name': self.name,
            'code': self.code,
            'description': self.description,
            'duration_minutes': self.duration_minutes,
            'price_cents': self.price_cents,
            'tax_rate_percent': self.tax_rate_percent,
            'imported_at': self.imported_at,
        }


@dataclass
class ServiceMapError:
    line_number: int
    raw_name: str
    raw_code: str
    raw_category: str
    reason: str


# Categories we DO NOT import. Per operator instruction: the spa
# doesn't run nails anymore; importing them just clutters the
# catalog. Also skip the literal "category" placeholder rows
# (Zenoti exports sometimes have these as data-quality junk).
_SKIP_CATEGORIES = frozenset({'nails', 'category'})


def validate_header(header_row: list[str]) -> list[str]:
    """Return list of errors; empty list = OK. Same shape as the
    customer-mapper validator — tolerates trailing blank columns."""
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


def is_skipped_category(category: str) -> bool:
    """Centralised so the importer + tests use the same rule."""
    return (category or '').strip().lower() in _SKIP_CATEGORIES


def map_row(row: dict, *, line_number: int) -> tuple[MappedService | None, ServiceMapError | None]:
    """Map one Zenoti service row to a MappedService.

    Returns `(mapped, None)` on success, `(None, error)` on rejection
    (Nails category, junk row, missing name).
    """
    name = _clean(row.get('ServiceName', ''))
    code = _clean(row.get('Code', ''))
    category = _clean(row.get('Category', ''))

    if not name:
        return None, ServiceMapError(
            line_number=line_number,
            raw_name=name, raw_code=code, raw_category=category,
            reason='ServiceName is blank',
        )

    if is_skipped_category(category):
        return None, ServiceMapError(
            line_number=line_number,
            raw_name=name, raw_code=code, raw_category=category,
            reason=f'Skipped (category={category!r})',
        )

    # Idempotency key. Always prefer Zenoti's Code; if it's blank,
    # synthesize from the service name (services without codes are
    # rare in Zenoti so the synthetic-id collision risk is minimal).
    if code:
        external_id = f'zenoti-service:{code}'
    else:
        external_id = f'zenoti-service:syn-{_slugify(name)[:80]}'

    # Description: Zenoti's `ServiceDescription` + the SubCategory
    # nuance ("Juvederm Product", "Massage Therapy", etc.) so the
    # operator doesn't lose the finer grouping when we collapse to
    # Lumè's single-category model.
    sub_category = _clean(row.get('SubCategory', ''))
    zenoti_desc = _clean(row.get('ServiceDescription', ''))
    parts = []
    if zenoti_desc and zenoti_desc != name:
        parts.append(zenoti_desc)
    if sub_category and sub_category != category:
        parts.append(f'Subcategory: {sub_category}')
    description = '\n'.join(parts)

    # Duration. Zenoti exports 0 for add-ons and products. Lumè's
    # Service model defaults to 60 min; preserving a 0 would create
    # un-bookable rows. Use 0 → 60 fallback so the operator sees
    # reasonable defaults; they can shorten via UI.
    duration = _parse_int(row.get('Duration', '')) or 60

    # Price: Florida ONLY. Single-location tenant (Florida) per
    # operator instruction — Midtown column ignored entirely.
    # Services blank in Florida import at $0.
    fl_raw = _clean(row.get('FloridaPricePrice', ''))
    price_cents = _parse_price_to_cents(fl_raw) or 0
    fl_tax = _clean(row.get('FloridaPriceTax', ''))
    tax_rate = _parse_tax_percent(fl_tax) or Decimal('0')

    return (
        MappedService(
            external_id=external_id[:100],
            name=name[:200],
            code=(code or '')[:50],
            description=description[:5000],
            category_name=category[:100],
            duration_minutes=duration,
            price_cents=price_cents,
            tax_rate_percent=tax_rate,
            sub_category=sub_category,
            florida_price_raw=fl_raw,
        ),
        None,
    )


def map_rows(rows: Iterable[dict]) -> tuple[list[MappedService], list[ServiceMapError]]:
    successes: list[MappedService] = []
    errors: list[ServiceMapError] = []
    for i, row in enumerate(rows, start=PREAMBLE_LINES + 2):
        mapped, err = map_row(row, line_number=i)
        if err is not None:
            errors.append(err)
        if mapped is not None:
            successes.append(mapped)
    return successes, errors


def detect_duplicate_external_ids(
    mapped: list[MappedService],
) -> dict[str, list[MappedService]]:
    by_id: dict[str, list[MappedService]] = {}
    for m in mapped:
        by_id.setdefault(m.external_id, []).append(m)
    return {k: v for k, v in by_id.items() if len(v) > 1}


# ── Cleaners ───────────────────────────────────────────────────────


def _clean(value: str | None) -> str:
    if not value:
        return ''
    return re.sub(r'\s+', ' ', str(value)).strip()


def _slugify(value: str) -> str:
    return re.sub(r'[^a-z0-9]+', '-', (value or '').lower()).strip('-')


def _parse_int(value: str | None) -> int:
    raw = _clean(value)
    if not raw:
        return 0
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return 0


def _parse_price_to_cents(value: str | None) -> int:
    """Parse a dollars-and-cents string like '479.00' or '$1,299.50'
    into integer cents. Returns 0 on blank or unparseable input."""
    raw = _clean(value)
    if not raw:
        return 0
    # Strip currency symbols, commas, surrounding parens (rare).
    cleaned = re.sub(r'[\$,\s]', '', raw).replace('(', '').replace(')', '')
    try:
        amount = Decimal(cleaned)
    except (InvalidOperation, ValueError):
        return 0
    if amount < 0:
        return 0
    cents = int((amount * 100).to_integral_value())
    return cents


def _parse_tax_percent(value: str | None) -> Decimal:
    """Parse '8.88%(Tax Excluded)' → Decimal('8.88'). Returns 0 on
    blank or unparseable input."""
    raw = _clean(value)
    if not raw:
        return Decimal('0')
    # Find the first floating-point number in the string.
    m = re.search(r'(\d+(?:\.\d+)?)', raw)
    if not m:
        return Decimal('0')
    try:
        pct = Decimal(m.group(1))
    except InvalidOperation:
        return Decimal('0')
    # Cap to the model's max_digits=5, decimal_places=3 → max 99.999.
    if pct > Decimal('99.999'):
        return Decimal('99.999')
    return pct.quantize(Decimal('0.001'))
