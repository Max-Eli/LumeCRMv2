"""Pure mappers from Zenoti CSV rows to Lumè model dicts.

Kept separate from the importer so the orchestration (file I/O,
validation pipeline, DB writes, audit logging) doesn't drag mapping
logic into a hard-to-test ball. Every function here is a pure
function — same input always produces the same output, no side
effects, no DB access. Tests exercise them directly with literal
dicts.

Zenoti customer export format (per Manhattan Laser Spa's
`ZenotiActiveGuest.csv`, May 2026):

  Lines 1–5: metadata preamble (Table name, Center, "UserExport", blank)
  Line 6:    header row (26 columns)
  Lines 7+:  data rows

Header columns:

  FirstName, LastName, Code, BaseCenter, Gender, Type, Email,
  Mobile, HomePhone, Address1, Address2, City, Zip Code, State,
  Country, Nationality, DOB, Anniversary Date, ReferralSource,
  ReceiveMarketingEmail, ReceiveMarketingSMS, Primary Employee,
  Target Segment Center, CreationDate, (blank), (blank)

See ADR 0030 (filed with this code) for the rationale on
idempotency strategy, blank-Code synthetic keys, and the deliberate
NON-mapping of BaseCenter to a hard FK.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import re
from dataclasses import dataclass
from typing import Iterable


# Number of preamble lines before the header. Stable in Zenoti's
# UserExport format; we re-validate it on read so a format change
# fails loudly rather than silently importing garbage.
PREAMBLE_LINES = 5

# The header row Zenoti emits. Used to assert the file is the export
# we expect — if Zenoti adds/removes columns, this fence fires.
EXPECTED_HEADER = [
    'FirstName', 'LastName', 'Code', 'BaseCenter', 'Gender', 'Type',
    'Email', 'Mobile', 'HomePhone', 'Address1', 'Address2', 'City',
    'Zip Code', 'State', 'Country', 'Nationality', 'DOB',
    'Anniversary Date', 'ReferralSource', 'ReceiveMarketingEmail',
    'ReceiveMarketingSMS', 'Primary Employee', 'Target Segment Center',
    'CreationDate',
]


@dataclass
class MappedCustomer:
    """The shape `importer.py` writes to the DB.

    Fields match `Customer` model attributes 1:1 so the importer can
    call `Customer.objects.update_or_create(**mapped.upsert_kwargs(),
    defaults=mapped.write_kwargs())`. `external_id` is the idempotency
    key; the importer uses it (plus `tenant`) to upsert.
    """

    # Idempotency key components.
    external_id: str           # Zenoti Code, or synthetic when Code is blank
    external_source: str = 'zenoti'

    # Required fields.
    first_name: str = ''
    last_name: str = ''

    # Optional contact fields — all blank-friendly on the model.
    email: str = ''
    phone: str = ''
    home_phone_note: str = ''  # captured in notes; no second-phone field on Customer

    # Optional address fields.
    address_line1: str = ''
    address_line2: str = ''
    city: str = ''
    state: str = ''
    zip_code: str = ''

    # Demographics + marketing.
    date_of_birth: _dt.date | None = None
    email_marketing_opt_in: bool = False
    sms_marketing_opt_in: bool = False

    # Provenance.
    imported_at: _dt.datetime | None = None
    notes: str = ''

    # Non-persistent metadata for the audit log / reconciliation.
    base_center: str = ''   # "Brooklyn" / "Midtown" / "Florida"
    creation_date: _dt.date | None = None  # original Zenoti CreationDate

    def upsert_kwargs(self) -> dict:
        """The fields used to FIND the existing row (or create if missing).

        Tenant is added by the importer. `external_source` + `external_id`
        together form the idempotency key.
        """
        return {
            'external_source': self.external_source,
            'external_id': self.external_id,
        }

    def write_kwargs(self) -> dict:
        """The fields written on every import run.

        On re-run, these OVERWRITE the existing row. We intentionally
        do NOT include `acquisition_source` here — it's set on first
        create only (immutable post-create, per the AcquisitionSource
        docstring on the model).
        """
        out: dict = {
            'first_name': self.first_name,
            'last_name': self.last_name,
            'email': self.email,
            'phone': self.phone,
            'address_line1': self.address_line1,
            'address_line2': self.address_line2,
            'city': self.city,
            'state': self.state,
            'zip_code': self.zip_code,
            'date_of_birth': self.date_of_birth,
            'email_marketing_opt_in': self.email_marketing_opt_in,
            'sms_marketing_opt_in': self.sms_marketing_opt_in,
            'imported_at': self.imported_at,
            'notes': self.notes,
        }
        return out


@dataclass
class MapError:
    """One row that failed mapping. Surfaced in the per-row error log."""
    line_number: int           # 1-indexed line in the source CSV
    raw_first_name: str
    raw_last_name: str
    raw_code: str
    reason: str


# ── Header validation ──────────────────────────────────────────────


def validate_header(header_row: list[str]) -> list[str]:
    """Return a list of human-readable errors; empty list = OK.

    Zenoti pads with trailing empty columns; we ignore those after
    the expected 24 columns. If a NEW expected column is missing or
    a known column is renamed, this surfaces it before the importer
    blindly processes 7k rows with wrong field mapping.
    """
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


# ── Per-row mapping ────────────────────────────────────────────────


def map_row(row: dict, *, line_number: int) -> tuple[MappedCustomer | None, MapError | None]:
    """Convert one CSV row dict to a MappedCustomer.

    Returns `(mapped, None)` on success or `(None, error)` on failure.
    Failures: missing first+last name (we can't auto-generate either).
    Everything else is best-effort — blank email, blank phone, blank
    DOB are fine.
    """
    first = _clean(row.get('FirstName', ''))
    last = _clean(row.get('LastName', ''))
    code = _clean(row.get('Code', ''))

    if not (first or last):
        return None, MapError(
            line_number=line_number,
            raw_first_name=first, raw_last_name=last, raw_code=code,
            reason='Both FirstName and LastName are blank — cannot identify the guest',
        )

    # Idempotency key: Zenoti Code when present, otherwise a synthetic
    # hash of (name + normalized phone + normalized email). Blank Codes
    # are common in the export (~30% in the Manhattan sample) so a
    # synthetic key keeps re-runs safe AND lets us catch true duplicates
    # within a single export (same person, same phone, no code).
    email = _clean_email(row.get('Email', ''))
    phone = _clean_phone(row.get('Mobile', ''))

    if code:
        external_id = f'zenoti-code:{code}'
    else:
        external_id = _synthetic_id(first=first, last=last, phone=phone, email=email)

    # Address pieces — Zenoti exports them blank often, but when
    # populated we keep them as-is.
    address_line1 = _clean(row.get('Address1', ''))[:200]
    address_line2 = _clean(row.get('Address2', ''))[:200]
    city = _clean(row.get('City', ''))[:100]
    state = _normalise_state(row.get('State', ''))
    zip_code = _clean(row.get('Zip Code', ''))[:20]

    dob = _parse_date(row.get('DOB', ''))
    creation_date = _parse_date(row.get('CreationDate', ''))

    home_phone = _clean_phone(row.get('HomePhone', ''))
    base_center = _clean(row.get('BaseCenter', ''))

    # Notes: capture data we can't model as first-class fields so the
    # operator can see them on the customer profile but they don't
    # silently disappear. Compact, one line per piece of info.
    notes_pieces: list[str] = []
    if base_center:
        notes_pieces.append(f'Zenoti home center: {base_center}')
    if home_phone and home_phone != phone:
        notes_pieces.append(f'Home phone: {home_phone}')
    nationality = _clean(row.get('Nationality', ''))
    if nationality:
        notes_pieces.append(f'Nationality: {nationality}')
    referral_src = _clean(row.get('ReferralSource', ''))
    if referral_src:
        notes_pieces.append(f'Original referral source: {referral_src}')
    if creation_date:
        notes_pieces.append(f'Original Zenoti record created: {creation_date.isoformat()}')
    notes = '\n'.join(notes_pieces)

    return (
        MappedCustomer(
            external_id=external_id[:100],
            first_name=first[:100],
            last_name=last[:100],
            email=email,
            phone=phone,
            home_phone_note=home_phone,
            address_line1=address_line1,
            address_line2=address_line2,
            city=city,
            state=state,
            zip_code=zip_code,
            date_of_birth=dob,
            email_marketing_opt_in=_parse_yes_no(row.get('ReceiveMarketingEmail', '')),
            sms_marketing_opt_in=_parse_yes_no(row.get('ReceiveMarketingSMS', '')),
            notes=notes,
            base_center=base_center,
            creation_date=creation_date,
        ),
        None,
    )


# ── Field cleaners ─────────────────────────────────────────────────


def _clean(value: str | None) -> str:
    """Strip + collapse internal whitespace. Empty string for falsy input."""
    if not value:
        return ''
    return re.sub(r'\s+', ' ', str(value)).strip()


def _clean_email(value: str | None) -> str:
    """Lowercase + strip. Empty when the input doesn't look like an email."""
    addr = _clean(value).lower()
    if '@' not in addr or addr.count('@') != 1:
        return ''
    local, _, domain = addr.partition('@')
    if not (local and '.' in domain):
        return ''
    return addr[:254]


def _clean_phone(value: str | None) -> str:
    """Preserve the human-readable Zenoti format `(NNN) NNN-NNNN` when
    we recognise it; otherwise return digits-only (still legible).

    Customer.phone is CharField(max_length=20) — both forms fit.
    """
    raw = _clean(value)
    if not raw:
        return ''
    digits = re.sub(r'\D', '', raw)
    if len(digits) == 10:
        return f'({digits[0:3]}) {digits[3:6]}-{digits[6:]}'
    if len(digits) == 11 and digits[0] == '1':
        return f'({digits[1:4]}) {digits[4:7]}-{digits[7:]}'
    # Unrecognised format — keep digits only so it's at least usable.
    return digits[:20]


_STATE_ABBREV = {
    'alabama': 'AL', 'alaska': 'AK', 'arizona': 'AZ', 'arkansas': 'AR',
    'california': 'CA', 'colorado': 'CO', 'connecticut': 'CT',
    'delaware': 'DE', 'florida': 'FL', 'georgia': 'GA', 'hawaii': 'HI',
    'idaho': 'ID', 'illinois': 'IL', 'indiana': 'IN', 'iowa': 'IA',
    'kansas': 'KS', 'kentucky': 'KY', 'louisiana': 'LA', 'maine': 'ME',
    'maryland': 'MD', 'massachusetts': 'MA', 'michigan': 'MI',
    'minnesota': 'MN', 'mississippi': 'MS', 'missouri': 'MO',
    'montana': 'MT', 'nebraska': 'NE', 'nevada': 'NV',
    'new hampshire': 'NH', 'new jersey': 'NJ', 'new mexico': 'NM',
    'new york': 'NY', 'north carolina': 'NC', 'north dakota': 'ND',
    'ohio': 'OH', 'oklahoma': 'OK', 'oregon': 'OR', 'pennsylvania': 'PA',
    'rhode island': 'RI', 'south carolina': 'SC', 'south dakota': 'SD',
    'tennessee': 'TN', 'texas': 'TX', 'utah': 'UT', 'vermont': 'VT',
    'virginia': 'VA', 'washington': 'WA', 'west virginia': 'WV',
    'wisconsin': 'WI', 'wyoming': 'WY',
}


def _normalise_state(value: str | None) -> str:
    """Zenoti exports state as a full name ("New York"). Lumè stores
    a short code where possible to match the address-form UX
    elsewhere. Pass through unrecognised values; keeps non-US OK."""
    raw = _clean(value)
    abbrev = _STATE_ABBREV.get(raw.lower())
    return abbrev or raw[:50]


def _parse_date(value: str | None) -> _dt.date | None:
    """Parse Zenoti's M/D/YYYY or MM/DD/YYYY format. Return None on
    blank / unparseable so the caller can leave the DB field null."""
    raw = _clean(value)
    if not raw:
        return None
    for fmt in ('%m/%d/%Y', '%-m/%-d/%Y', '%m/%d/%y'):
        try:
            return _dt.datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    # Last attempt: ISO-style 2024-12-15 (some Zenoti exports use this).
    try:
        return _dt.date.fromisoformat(raw)
    except (ValueError, TypeError):
        return None


def _parse_yes_no(value: str | None) -> bool:
    """Zenoti emits the string 'Yes' / 'No'. Anything else → False."""
    return _clean(value).lower() == 'yes'


def _synthetic_id(*, first: str, last: str, phone: str, email: str) -> str:
    """Stable per-(person, contact) ID for rows with no Zenoti Code.

    Same person on a re-run produces the same ID, so the importer's
    upsert is idempotent. Different people with the same name but
    different phone/email get different IDs (avoids accidental merge).
    Two with NO phone AND NO email AND identical names will collide —
    rare enough that we accept it; the operator can manually split
    later if needed.
    """
    seed = '|'.join([
        first.lower(),
        last.lower(),
        re.sub(r'\D', '', phone or ''),
        (email or '').lower(),
    ])
    digest = hashlib.sha256(seed.encode('utf-8')).hexdigest()[:16]
    return f'zenoti-syn:{digest}'


# ── Bulk helpers ───────────────────────────────────────────────────


def map_rows(rows: Iterable[dict]) -> tuple[list[MappedCustomer], list[MapError]]:
    """Map a stream of CSV row dicts. Returns (successes, errors).

    Line numbers in errors are 1-indexed and ASSUME the data rows
    start at line `PREAMBLE_LINES + 2` (data line index + the 5
    preamble lines + 1 header line). Callers that read directly from
    the CSV iterator should pass `enumerate(rows, start=PREAMBLE_LINES+2)`
    or compute line numbers themselves.
    """
    successes: list[MappedCustomer] = []
    errors: list[MapError] = []
    for i, row in enumerate(rows, start=PREAMBLE_LINES + 2):
        mapped, err = map_row(row, line_number=i)
        if err is not None:
            errors.append(err)
        if mapped is not None:
            successes.append(mapped)
    return successes, errors


def detect_internal_duplicates(
    mapped: list[MappedCustomer],
) -> dict[str, list[MappedCustomer]]:
    """Group mapped rows by external_id; return groups of size > 1.

    Catches:
      - Same Zenoti Code appearing twice in the export (data error).
      - Two synthetic-ID rows for the same person (same name +
        same phone or email).

    Operator reviews the report before live import — duplicates aren't
    auto-resolved; the importer skips them on the second occurrence
    and logs which row in the export caused the skip.
    """
    by_id: dict[str, list[MappedCustomer]] = {}
    for m in mapped:
        by_id.setdefault(m.external_id, []).append(m)
    return {k: v for k, v in by_id.items() if len(v) > 1}
