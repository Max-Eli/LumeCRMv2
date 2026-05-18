"""Pure mappers from Zenoti appointments CSV rows to Lumè Appointment dicts.

Zenoti Appointments export format (per Manhattan Laser Spa's May
2026 export — `appointments2026.csv` and successors):

  Line 1:    header (BOM-prefixed, fully-quoted)
  Lines 2+:  data rows

Header columns (14):

  Appointment Date, Booked Date, Invoice No, Guest Name,
  Service Name, Center Name, Start Time, End Time,
  Scheduled Service Duration, Scheduled Service and Recovery Duration,
  Recovery Time, Provider, Room, Status

Status mapping (Zenoti → Lumè):

  | Zenoti                | Lumè status                    | Invoice action  |
  |-----------------------|--------------------------------|-----------------|
  | Closed                | completed / booked (by time)   | close OTHER     |
  | Closed (Cancelled)    | cancelled                      | void            |
  | Closed (No Show)      | no_show                        | void            |
  | Open + past           | completed                      | close OTHER     |
  | Open + future         | booked                         | (leave open)    |
  | Confirmed + past      | completed                      | close OTHER     |
  | Confirmed + future    | confirmed                      | (leave open)    |
  | Checkin               | checked_in                     | (leave open)    |
  | Cancelled             | cancelled                      | void            |
  | No Show               | no_show                        | void            |
  | Deleted               | (skipped — no row created)     | n/a             |

The "past = completed" rule (per operator request) ensures imported
historical appointments show as paid + done so reports + provider
revenue look right. Payment method `OTHER` is used as a deliberate
placeholder — operator can re-categorise via Reports later.

Idempotency key: `external_id = 'zenoti-appt:<Invoice No>'`.

Customer / Service / Provider matching all happen in the importer,
not the mapper. The mapper only parses + classifies the row.

See [ADR 0030] for the broader Zenoti migration design.
"""

from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass
from typing import Iterable


EXPECTED_HEADER = [
    'Appointment Date', 'Booked Date', 'Invoice No', 'Guest Name',
    'Service Name', 'Center Name', 'Start Time', 'End Time',
    'Scheduled Service Duration', 'Scheduled Service and Recovery Duration',
    'Recovery Time', 'Provider', 'Room', 'Status',
]


# Zenoti statuses we DROP entirely (don't import). "Deleted" rows
# are user-removed records the spa explicitly doesn't want in their
# audit trail.
_SKIPPED_STATUSES = frozenset({'deleted'})

# Zenoti statuses that mean "customer cancelled — invoice should
# be void, not paid."
_CANCELLED_STATUSES = frozenset({'cancelled', 'closed (cancelled)'})

# Zenoti statuses that mean "customer was a no-show — invoice void."
_NO_SHOW_STATUSES = frozenset({'no show', 'closed (no show)'})

# Zenoti statuses that mean "service was performed + invoice closed."
_CLOSED_STATUSES = frozenset({'closed'})

# Live/intent-to-attend statuses. Temporality (past vs future)
# decides the final Lumè status.
_LIVE_STATUSES = frozenset({'open', 'confirmed', 'checkin'})

# Zenoti default tenant timezone for parsing. Manhattan tenant is
# Florida-only single-location per operator decision; America/New_York
# matches the only location the data uses.
DEFAULT_TZ_NAME = 'America/New_York'


@dataclass
class MappedAppointment:
    """One Zenoti appointment ready for upsert.

    The importer combines this with matched Customer + Service +
    Provider rows to create the Appointment + (conditionally) close
    or void the auto-generated Invoice.
    """

    # Idempotency.
    external_id: str           # e.g. 'zenoti-appt:21730'
    external_source: str = 'zenoti'
    external_invoice_no: str = ''

    # Customer matching key (case-insensitive lookup).
    customer_first: str = ''
    customer_last: str = ''

    # Service matching key.
    service_name: str = ''

    # Provider matching key (full name; matched against User.first +
    # User.last on a TenantMembership in the same tenant).
    provider_name: str = ''

    # Start/end times, ALREADY tz-aware (UTC).
    start_time: _dt.datetime | None = None
    end_time: _dt.datetime | None = None

    # Resolved Lumè status — derived from Zenoti status + temporality.
    lume_status: str = 'booked'

    # Whether we should close the auto-created invoice (PAID/OTHER)
    # after creating the Appointment.
    close_invoice: bool = False

    # Whether we should void the auto-created invoice.
    void_invoice: bool = False

    # Metadata for the reconciliation report.
    upstream_status: str = ''
    upstream_center: str = ''
    room: str = ''


@dataclass
class AppointmentMapError:
    line_number: int
    raw_invoice_no: str
    raw_guest_name: str
    raw_service_name: str
    raw_status: str
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


def map_row(
    row: dict, *, line_number: int, now: _dt.datetime,
) -> tuple[MappedAppointment | None, AppointmentMapError | None]:
    """Map one Zenoti appointment row to a MappedAppointment.

    `now` is passed in so the past-vs-future decision is deterministic
    + testable. Pass `timezone.now()` from the importer.
    """
    invoice_no = _clean(row.get('Invoice No', ''))
    guest_name = _clean(row.get('Guest Name', ''))
    service_name = _clean(row.get('Service Name', ''))
    provider_name = _clean(row.get('Provider', ''))
    upstream_status = _clean(row.get('Status', '')).lower()

    if not invoice_no:
        return None, AppointmentMapError(
            line_number=line_number,
            raw_invoice_no=invoice_no, raw_guest_name=guest_name,
            raw_service_name=service_name, raw_status=upstream_status,
            reason='Invoice No is blank (cannot dedupe)',
        )

    if upstream_status in _SKIPPED_STATUSES:
        return None, AppointmentMapError(
            line_number=line_number,
            raw_invoice_no=invoice_no, raw_guest_name=guest_name,
            raw_service_name=service_name, raw_status=upstream_status,
            reason=f'Skipped (Status={upstream_status!r})',
        )

    if not guest_name:
        return None, AppointmentMapError(
            line_number=line_number,
            raw_invoice_no=invoice_no, raw_guest_name=guest_name,
            raw_service_name=service_name, raw_status=upstream_status,
            reason='Guest Name is blank',
        )
    if not service_name:
        return None, AppointmentMapError(
            line_number=line_number,
            raw_invoice_no=invoice_no, raw_guest_name=guest_name,
            raw_service_name=service_name, raw_status=upstream_status,
            reason='Service Name is blank',
        )
    if not provider_name:
        return None, AppointmentMapError(
            line_number=line_number,
            raw_invoice_no=invoice_no, raw_guest_name=guest_name,
            raw_service_name=service_name, raw_status=upstream_status,
            reason='Provider is blank',
        )

    start = _parse_datetime(row.get('Start Time', ''))
    end = _parse_datetime(row.get('End Time', ''))
    if start is None or end is None:
        return None, AppointmentMapError(
            line_number=line_number,
            raw_invoice_no=invoice_no, raw_guest_name=guest_name,
            raw_service_name=service_name, raw_status=upstream_status,
            reason=f'Cannot parse Start Time / End Time '
                   f'({row.get("Start Time", "")!r} / {row.get("End Time", "")!r})',
        )
    if end <= start:
        # Some Zenoti rows have end==start (zero-duration). Bump
        # end by the scheduled duration; if that's also missing,
        # default to +30 minutes so the appointment is at least
        # visible on the calendar.
        dur_min = _parse_duration_to_minutes(row.get('Scheduled Service Duration', ''))
        end = start + _dt.timedelta(minutes=max(dur_min, 30))

    first, last = _split_guest_name(guest_name)
    lume_status, close_inv, void_inv = _resolve_status(
        upstream_status=upstream_status, start=start, now=now,
    )

    return (
        MappedAppointment(
            external_id=f'zenoti-appt:{invoice_no}'[:100],
            external_invoice_no=invoice_no[:100],
            customer_first=first[:100],
            customer_last=last[:100],
            service_name=service_name[:200],
            provider_name=provider_name[:120],
            start_time=start,
            end_time=end,
            lume_status=lume_status,
            close_invoice=close_inv,
            void_invoice=void_inv,
            upstream_status=upstream_status,
            upstream_center=_clean(row.get('Center Name', ''))[:100],
            room=_clean(row.get('Room', ''))[:100],
        ),
        None,
    )


def map_rows(
    rows: Iterable[dict], *, now: _dt.datetime, line_offset: int = 2,
) -> tuple[list[MappedAppointment], list[AppointmentMapError]]:
    successes: list[MappedAppointment] = []
    errors: list[AppointmentMapError] = []
    for i, row in enumerate(rows, start=line_offset):
        mapped, err = map_row(row, line_number=i, now=now)
        if err is not None:
            errors.append(err)
        if mapped is not None:
            successes.append(mapped)
    return successes, errors


# ── Provider weekly-schedule inference ─────────────────────────────


_WEEKDAY_NAMES = ('monday', 'tuesday', 'wednesday', 'thursday',
                  'friday', 'saturday', 'sunday')


def infer_provider_weekly_hours(
    mapped: list[MappedAppointment],
    *, start_hhmm: str = '08:00', end_hhmm: str = '20:00',
) -> dict[str, dict]:
    """Walk every mapped appointment; for each (provider_name,
    weekday_of_start_time_in_tenant_tz) pair, mark that weekday as
    worked. Returns a dict keyed by provider_name → weekly_hours
    JSON in the shape ProviderSchedule expects.

    Per operator request: all worked days get a uniform block
    `start_hhmm`-`end_hhmm` (8am-8pm by default). Days WITHOUT any
    appointments in the dataset get an empty list (off that day).

    Note: weekday is derived from the appointment's localtime in
    America/New_York (the tenant's single location). UTC weekday
    would shift Saturday-evening appointments to Sunday for some
    eastern US sites — using the tenant tz keeps the schedule
    intuitive.
    """
    import zoneinfo
    try:
        tenant_tz = zoneinfo.ZoneInfo(DEFAULT_TZ_NAME)
    except zoneinfo.ZoneInfoNotFoundError:
        tenant_tz = _dt.timezone.utc

    per_provider_worked_days: dict[str, set[str]] = {}
    for m in mapped:
        if not m.provider_name or m.start_time is None:
            continue
        local = m.start_time.astimezone(tenant_tz)
        weekday = _WEEKDAY_NAMES[local.weekday()]
        per_provider_worked_days.setdefault(m.provider_name, set()).add(weekday)

    block = {'start': start_hhmm, 'end': end_hhmm}
    out: dict[str, dict] = {}
    for provider_name, worked in per_provider_worked_days.items():
        schedule = {day: [] for day in _WEEKDAY_NAMES}
        for day in worked:
            schedule[day] = [dict(block)]
        out[provider_name] = schedule
    return out


# ── Status resolution ─────────────────────────────────────────────


def _resolve_status(
    *, upstream_status: str, start: _dt.datetime, now: _dt.datetime,
) -> tuple[str, bool, bool]:
    """Return (lume_status, close_invoice, void_invoice)."""
    if upstream_status in _CANCELLED_STATUSES:
        return ('cancelled', False, True)
    if upstream_status in _NO_SHOW_STATUSES:
        return ('no_show', False, True)
    if upstream_status in _CLOSED_STATUSES:
        # Closed always means service was performed + paid in Zenoti,
        # regardless of date.
        return ('completed', True, False)
    if upstream_status == 'checkin':
        return ('checked_in', False, False)
    # 'open' or 'confirmed' — decide by temporality.
    is_past = start < now
    if is_past:
        # Operator's stated rule: past appointments become COMPLETED
        # with an OTHER-method payment so reports + provider revenue
        # are intact post-migration.
        return ('completed', True, False)
    if upstream_status == 'confirmed':
        return ('confirmed', False, False)
    return ('booked', False, False)


# ── Cleaners ───────────────────────────────────────────────────────


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


def _parse_datetime(value: str | None) -> _dt.datetime | None:
    """Parse Zenoti's `M/D/YYYY HH:MM AM/PM` format → tz-aware UTC datetime.

    The tenant is single-location (Florida → America/New_York).
    Naive parsed datetimes are localized to that zone, then converted
    to UTC so the DB column stores a consistent absolute moment.
    """
    raw = _clean(value)
    if not raw:
        return None
    import zoneinfo
    try:
        tenant_tz = zoneinfo.ZoneInfo(DEFAULT_TZ_NAME)
    except zoneinfo.ZoneInfoNotFoundError:
        tenant_tz = _dt.timezone.utc
    for fmt in (
        '%m/%d/%Y %I:%M %p',     # '11/13/2026 11:00 AM'
        '%m/%d/%Y %H:%M',         # '11/13/2026 13:00'
        '%Y-%m-%d %H:%M:%S',
        '%Y-%m-%d %H:%M',
    ):
        try:
            naive = _dt.datetime.strptime(raw, fmt)
            local = naive.replace(tzinfo=tenant_tz)
            return local.astimezone(_dt.timezone.utc)
        except ValueError:
            continue
    return None


def _parse_duration_to_minutes(value: str | None) -> int:
    """Parse '1:30' → 90, '0:45' → 45. Returns 0 on blank / unparseable."""
    raw = _clean(value)
    if not raw or ':' not in raw:
        try:
            return max(0, int(raw or 0))
        except (ValueError, TypeError):
            return 0
    try:
        h, m = raw.split(':', 1)
        return max(0, int(h) * 60 + int(m))
    except ValueError:
        return 0


# ── Cross-file dedup (multi-CSV imports) ───────────────────────────


def merge_appointment_files(
    per_file_results: list[list[MappedAppointment]],
) -> tuple[list[MappedAppointment], list[str]]:
    """Combine multi-file results by external_id; later file wins.

    Returns (deduped_list, duplicate_external_ids).
    Same pattern as packages_mapper.merge_files.
    """
    by_id: dict[str, MappedAppointment] = {}
    dupes: list[str] = []
    for batch in per_file_results:
        for m in batch:
            if m.external_id in by_id:
                dupes.append(m.external_id)
            by_id[m.external_id] = m
    return list(by_id.values()), dupes
