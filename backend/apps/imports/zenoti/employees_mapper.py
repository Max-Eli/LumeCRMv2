"""Pure mappers from Zenoti `Employees.csv` rows to Lumè
User + TenantMembership + MembershipLocation dicts.

Zenoti Employees export format (per Manhattan Laser Spa's May 2026
export):

  Line 1:    header (BOM-prefixed, fully-quoted)
  Lines 2+:  data rows

Header columns (27):

  CODE, FIRST NAME, LAST NAME, UserName, PHONE NO, StartDate,
  Enddate, NickName, HourlyRate, Salary, EmployeeDisplayName,
  OverTimeAboveHours, OverTimeMultiplier, OverTimeType, JobCode,
  JOB, Effective Date, ACTIVE, CenterCode, CenterName,
  IsConsultant, Additional Field1, Additional Field2,
  Additional Date 1, Additional Date 2, ShowInCatalog,
  MobileCountryFK

Mapping decisions (per operator approval):

  - ACTIVE=Yes only. Inactive staff aren't imported (they clutter
    the calendar's bookable list and have no operational value).
  - JOB IN {MANAGER, OWNER} → SKIP. Operator explicitly excluded
    these roles ("we only need bookable employees like technicians,
    nurses, etc.").
  - JOB → Lumè role:
      TECHNICIAN, NURSE, MASSAGE THERAPIST, NAILTECH/NAIL TECH
          → role=PROVIDER, is_bookable=True
      RECEPTIONIST → role=FRONT_DESK, is_bookable=False
      (Any unrecognised JOB → role=PROVIDER, is_bookable=False;
       operator promotes via UI when ready)
  - JobTitle: find-or-create per-tenant by title-cased Zenoti JOB.
  - UserName → User.email when it parses as an email; otherwise
    a placeholder `firstname.lastname@imported.lume-crm.local`.
    Operator can edit later via /staff/employees/<id>.
  - StartDate → hire_date.
  - HourlyRate → pay_rate_cents + pay_type=HOURLY when > 0.

Idempotency key: User.email is unique. The importer upserts the
User by email, then finds-or-creates the TenantMembership by
(tenant, user). Re-running is a no-op write-wise.

Email collisions across imports: when two employees share the
same name (e.g. two "Julia Smith"s) AND both fall back to
placeholder emails, we suffix the placeholder with the Zenoti
CODE to keep them distinct: `julia.smith.SMITH02@imported.lume
-crm.local`.
"""

from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass
from typing import Iterable


EXPECTED_HEADER = [
    'CODE', 'FIRST NAME', 'LAST NAME', 'UserName', 'PHONE NO',
    'StartDate', 'Enddate', 'NickName', 'HourlyRate', 'Salary',
    'EmployeeDisplayName', 'OverTimeAboveHours', 'OverTimeMultiplier',
    'OverTimeType', 'JobCode', 'JOB', 'Effective Date', 'ACTIVE',
    'CenterCode', 'CenterName', 'IsConsultant', 'Additional Field1',
    'Additional Field2', 'Additional Date 1', 'Additional Date 2',
    'ShowInCatalog', 'MobileCountryFK',
]


# Roles the operator explicitly excluded. Case-insensitive compare
# against Zenoti JOB column.
SKIPPED_JOBS = frozenset({'manager', 'owner'})


# Mapping from Zenoti JOB → (Lume role, is_bookable).
# Unknown JOBs default to (PROVIDER, False) — operator can flip
# bookable on via the staff page when ready.
JOB_TO_ROLE: dict[str, tuple[str, bool]] = {
    'technician':       ('provider', True),
    'nurse':            ('provider', True),
    'massage therapist': ('provider', True),
    'nailtech':         ('provider', True),
    'nail tech':        ('provider', True),
    'receptionist':     ('front_desk', False),
}


PLACEHOLDER_EMAIL_DOMAIN = 'imported.lume-crm.local'


@dataclass
class MappedEmployee:
    """One employee → User + TenantMembership + (optional) MembershipLocation.

    The importer creates the User row first (find-or-create by
    email), then the TenantMembership (find-or-create by tenant+user),
    then auto-assigns to the tenant's default Location.
    """

    # Idempotency key for User.
    email: str

    # User fields.
    first_name: str = ''
    last_name: str = ''
    phone: str = ''

    # TenantMembership fields.
    role: str = 'provider'           # default safe role
    is_bookable: bool = False
    is_active: bool = True
    job_title_name: str = ''         # find-or-create JobTitle by this
    hire_date: _dt.date | None = None
    pay_rate_cents: int = 0
    pay_type: str = ''               # '' / 'hourly' / 'salary' / 'commission_only'

    # Metadata for the reconciliation report (not persisted directly;
    # but the audit log entries capture the Zenoti CODE).
    zenoti_code: str = ''
    upstream_job: str = ''
    upstream_center: str = ''        # Florida / Midtown / etc.


@dataclass
class EmployeeMapError:
    line_number: int
    raw_code: str
    raw_first_name: str
    raw_last_name: str
    raw_job: str
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


# ── Row mapper ─────────────────────────────────────────────────────


def map_row(row: dict, *, line_number: int) -> tuple[MappedEmployee | None, EmployeeMapError | None]:
    """Map one row.

    Returns `(mapped, None)` on success or `(None, error)` if the
    row is intentionally skipped (inactive, MANAGER/OWNER, or
    missing name). The importer treats "Skipped" errors as
    `rows_skipped_filtered` (distinct from `rows_failed_mapping`).
    """
    code = _clean(row.get('CODE', ''))
    first = _clean(row.get('FIRST NAME', ''))
    last = _clean(row.get('LAST NAME', ''))
    job = _clean(row.get('JOB', ''))
    active = _clean(row.get('ACTIVE', '')).lower()

    if active != 'yes':
        return None, EmployeeMapError(
            line_number=line_number,
            raw_code=code, raw_first_name=first, raw_last_name=last, raw_job=job,
            reason=f'Skipped (ACTIVE={active!r})',
        )

    if job.lower() in SKIPPED_JOBS:
        return None, EmployeeMapError(
            line_number=line_number,
            raw_code=code, raw_first_name=first, raw_last_name=last, raw_job=job,
            reason=f'Skipped (JOB={job!r} excluded per operator instruction)',
        )

    if not (first or last):
        return None, EmployeeMapError(
            line_number=line_number,
            raw_code=code, raw_first_name=first, raw_last_name=last, raw_job=job,
            reason='Both FIRST NAME and LAST NAME are blank',
        )

    # Resolve role + bookable from the JOB column.
    role, is_bookable = JOB_TO_ROLE.get(job.lower(), ('provider', False))

    # Email: real if it looks like one, else stable placeholder.
    raw_username = _clean(row.get('UserName', ''))
    if _looks_like_email(raw_username):
        email = raw_username.lower()
    else:
        # Suffix with the Zenoti CODE so duplicate names (two "Julia
        # Smith"s) get distinct placeholders.
        slug_first = _slugify(first) or 'employee'
        slug_last = _slugify(last) or 'unknown'
        slug_code = _slugify(code) or 'noc'
        email = f'{slug_first}.{slug_last}.{slug_code}@{PLACEHOLDER_EMAIL_DOMAIN}'.lower()

    hire = _parse_date(row.get('StartDate', '')) or _parse_date(row.get('Effective Date', ''))

    hourly = _parse_amount(row.get('HourlyRate', ''))
    salary = _parse_amount(row.get('Salary', ''))
    if hourly > 0:
        pay_type = 'hourly'
        pay_rate_cents = int(hourly * 100)
    elif salary > 0:
        pay_type = 'salary'
        pay_rate_cents = int(salary * 100)
    else:
        pay_type = ''
        pay_rate_cents = 0

    return (
        MappedEmployee(
            email=email[:254],
            first_name=first[:60],
            last_name=last[:60],
            phone=_clean(row.get('PHONE NO', ''))[:20],
            role=role,
            is_bookable=is_bookable,
            is_active=True,
            job_title_name=_title_case_job(job),
            hire_date=hire,
            pay_rate_cents=pay_rate_cents,
            pay_type=pay_type,
            zenoti_code=code,
            upstream_job=job,
            upstream_center=_clean(row.get('CenterName', '')),
        ),
        None,
    )


def map_rows(rows: Iterable[dict]) -> tuple[list[MappedEmployee], list[EmployeeMapError]]:
    successes: list[MappedEmployee] = []
    errors: list[EmployeeMapError] = []
    for i, row in enumerate(rows, start=2):
        mapped, err = map_row(row, line_number=i)
        if err is not None:
            errors.append(err)
        if mapped is not None:
            successes.append(mapped)
    return successes, errors


def detect_email_duplicates(
    mapped: list[MappedEmployee],
) -> dict[str, list[MappedEmployee]]:
    by_email: dict[str, list[MappedEmployee]] = {}
    for m in mapped:
        by_email.setdefault(m.email, []).append(m)
    return {k: v for k, v in by_email.items() if len(v) > 1}


# ── Cleaners ───────────────────────────────────────────────────────


def _clean(value: str | None) -> str:
    if not value:
        return ''
    return re.sub(r'\s+', ' ', str(value)).strip()


def _looks_like_email(value: str) -> bool:
    if '@' not in value or value.count('@') != 1:
        return False
    local, _, domain = value.partition('@')
    if not local or '.' not in domain:
        return False
    # Reject obvious non-email handles like 'julia' or 'ad'.
    return True


def _slugify(value: str) -> str:
    return re.sub(r'[^a-z0-9]+', '-', (value or '').lower()).strip('-')


def _title_case_job(job: str) -> str:
    """'TECHNICIAN' → 'Technician', 'NAIL TECH' → 'Nail Tech'."""
    if not job:
        return ''
    return ' '.join(w.capitalize() for w in job.split())


def _parse_date(value: str | None) -> _dt.date | None:
    raw = _clean(value)
    if not raw:
        return None
    # Zenoti's StartDate is 'YYYY-MM-DD HH:MM:SS', Effective Date is 'M/D/YYYY'.
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d', '%m/%d/%Y', '%m/%d/%y'):
        try:
            return _dt.datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    try:
        return _dt.date.fromisoformat(raw)
    except (ValueError, TypeError):
        return None


def _parse_amount(value: str | None) -> float:
    raw = _clean(value)
    if not raw:
        return 0.0
    cleaned = re.sub(r'[\$,\s]', '', raw)
    try:
        return float(cleaned)
    except (TypeError, ValueError):
        return 0.0
