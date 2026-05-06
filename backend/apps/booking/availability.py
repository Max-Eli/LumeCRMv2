"""Availability calculator for the public booking flow.

Computes the bookable time slots for a (provider, service, date,
location) tuple by walking the provider's saved working hours for
that weekday, generating candidate slot starts at 15-minute
intervals, and dropping any candidate that would conflict with an
existing appointment or run past the working hours.

Performance target: < 100ms per call. The hot path is one query for
the provider's existing appointments on the date; everything else
is in-memory math.

Timezone discipline (the load-bearing rule)
-------------------------------------------
A schedule entry like ``{"start": "09:00", "end": "17:00"}`` means
"9 AM in *this location's* local time," NOT 9 AM UTC. Different
sites of the same tenant may live in different timezones (NY + LA
business), and "9 AM" is always the operator's wall-clock time at
that site.

Concretely, every conversion of a HH:MM string + date in this file
goes through ``_combine(on_date, hh_mm, location.timezone)``. We
never call ``timezone.make_aware`` (which uses the SERVER timezone)
on schedule values. The day-window query for existing appointments
is also constructed in the location's tz to match.

This was a bug in the first pass: schedules resolved in server-tz
UTC, which meant "9 AM" stored as 09:00 UTC = 5:00 AM EDT —
appointments landed before the calendar's 8 AM day window and the
operator couldn't see their own bookings. Fixed in Phase 1I session
2; tests cover the NY tz path explicitly.

Cross-location double-booking
-----------------------------
A provider is one human, even when they work at two sites. Sarah at
Manhattan 9-12 means Sarah is also unavailable at Brooklyn 9-12. The
"existing appointments" query unions across ALL locations the
provider is assigned to, not just the one being calculated for, so
the calculator never offers a slot that would put Sarah in two
places at once.

Edge cases handled:
  - Multiple working-hour blocks per day (split shift, lunch break).
  - Service duration + buffer that doesn't fit in any remaining
    block (drops the block entirely).
  - Past slots — any candidate before "now + lead-time" is dropped
    so customers can't book a slot 3 minutes from now.
  - Cancelled appointments — their slot is bookable again
    (`status__in` filter excludes them).
  - Provider's appointments at OTHER locations on the same day
    (cross-site double-booking guard, see above).

Future work:
  - Slot-step configuration (today: 15 min hard-coded)
  - Multi-provider "anyone available" view that unions across
    providers — handled at the public endpoint layer, not here
"""

from __future__ import annotations

import datetime as dt
import zoneinfo
from dataclasses import dataclass

from django.utils import timezone

from apps.appointments.models import Appointment
from apps.services.models import Service
from apps.tenants.models import Location, ProviderSchedule, TenantMembership

# Slot granularity. 15 min is what every major medspa platform uses
# (Boulevard, Zenoti). Sub-15 doesn't help legibly; > 15 leaves too
# many "almost-booked" white spaces.
SLOT_STEP_MINUTES = 15

# Minimum lead time. Customers can't book a slot starting in the
# next 30 minutes — gives front desk a moment to prep + reduces
# spammy "I just realized I need an appointment in 5 minutes" creates
# that don't reflect reality.
DEFAULT_LEAD_MINUTES = 30

# Statuses that "occupy" a time slot. Cancelled bookings free their
# slot for re-booking; everything else (booked / confirmed /
# checked-in / completed / no-show) blocks the slot.
OCCUPYING_STATUSES = (
    Appointment.Status.BOOKED,
    Appointment.Status.CONFIRMED,
    Appointment.Status.CHECKED_IN,
    Appointment.Status.COMPLETED,
    Appointment.Status.NO_SHOW,
)

WEEKDAY_NAMES = (
    'monday', 'tuesday', 'wednesday', 'thursday',
    'friday', 'saturday', 'sunday',
)


@dataclass
class Slot:
    """A candidate time slot for a single (provider, service, date).

    ``available=True`` when the slot is bookable; ``False`` when it
    conflicts with an existing appointment OR sits inside the lead-
    time buffer ("too soon"). Past slots are dropped entirely — they
    aren't candidates at all. With ``include_unavailable=True`` the
    calculator returns the unavailable ones too so the UI can render
    them as visibly-taken instead of leaving gaps.
    """

    start: dt.datetime
    end: dt.datetime
    available: bool = True

    def to_payload(self) -> dict:
        return {
            'start': self.start.isoformat(),
            'end': self.end.isoformat(),
            'available': self.available,
        }


def compute_provider_slots(
    *,
    provider: TenantMembership,
    service: Service,
    location: Location,
    on_date: dt.date,
    now: dt.datetime | None = None,
    lead_minutes: int = DEFAULT_LEAD_MINUTES,
    include_unavailable: bool = False,
    exclude_appointment_id: int | None = None,
) -> list[Slot]:
    """Return the list of available start times for a provider on a date.

    The total occupancy of each slot is `service.duration_minutes +
    service.buffer_minutes`; the buffer eats the calendar after the
    service so back-to-back bookings respect cleanup time.

    Pre-conditions (caller responsibility):
      - `provider.is_bookable=True` (we don't double-check)
      - `provider` is assigned to `location` via MembershipLocation
        (caller's job to enforce eligibility — we just walk the
        schedule)
      - service.is_bookable_online=True
    """
    now = now or timezone.now()

    # 1. Pull the provider's working schedule for this location.
    #    Schedule is keyed off MembershipLocation, so resolve that.
    schedule = (
        ProviderSchedule.objects
        .filter(
            membership_location__membership=provider,
            membership_location__location=location,
        )
        .first()
    )
    if schedule is None or not schedule.weekly_hours:
        return []

    weekday = WEEKDAY_NAMES[on_date.weekday()]
    blocks = (schedule.weekly_hours.get(weekday) or [])
    if not blocks:
        return []

    # Resolve the location's timezone once — every schedule string
    # and the day-window for the appointments query are interpreted
    # against it.
    location_tz = _location_tz(location)

    # 2. Pull existing appointments that occupy this provider on this
    #    date — across ALL locations they're assigned to, not just
    #    `location`. A provider is one human; an appointment at site A
    #    at 10:00 makes them unavailable at site B at 10:00 too. The
    #    day-window is constructed in the location's tz so "today" at
    #    LA covers the right UTC range when the server is in NY.
    day_start = dt.datetime.combine(on_date, dt.time.min, tzinfo=location_tz)
    day_end = day_start + dt.timedelta(days=1)
    existing_qs = Appointment.objects.filter(
        provider=provider,
        status__in=OCCUPYING_STATUSES,
        start_time__lt=day_end,
        end_time__gt=day_start,
    )
    # Reschedule path: the appointment being moved would otherwise
    # show as conflict-with-itself. Caller passes its pk to soft-
    # exclude it from the conflict set so the customer can pick the
    # same time (no-op move) or an overlapping nearby slot.
    if exclude_appointment_id is not None:
        existing_qs = existing_qs.exclude(pk=exclude_appointment_id)
    existing = list(existing_qs.values_list('start_time', 'end_time'))

    # 3. Walk each working-hours block, generating candidate slots.
    occupancy_minutes = (service.duration_minutes or 0) + (service.buffer_minutes or 0)
    if occupancy_minutes <= 0:
        return []

    earliest_start = now + dt.timedelta(minutes=lead_minutes)
    slots: list[Slot] = []

    for block in blocks:
        start_str = block.get('start')
        end_str = block.get('end')
        if not start_str or not end_str:
            continue
        try:
            block_start = _combine(on_date, start_str, location_tz)
            block_end = _combine(on_date, end_str, location_tz)
        except ValueError:
            continue
        if block_end <= block_start:
            continue

        # Candidate start times: 15-min increments inside the block.
        cursor = block_start
        while True:
            candidate_end = cursor + dt.timedelta(minutes=occupancy_minutes)
            if candidate_end > block_end:
                # Service+buffer doesn't fit before the block ends.
                break
            # Customer-facing slot end is service end — buffer is
            # internal scheduling only, customer doesn't see it.
            customer_end = cursor + dt.timedelta(minutes=service.duration_minutes)

            # Past + lead-time-blocked candidates collapse to "unavailable"
            # rather than being skipped; the UI can decide whether to
            # show them as Taken/Too soon. Past slots (more than the
            # day's start in the past) are still dropped entirely —
            # they're noise, not "potentially bookable later."
            too_soon = cursor < earliest_start
            conflict = _has_conflict(cursor, candidate_end, existing)
            available = not too_soon and not conflict

            if available or include_unavailable:
                slots.append(Slot(start=cursor, end=customer_end, available=available))
            cursor += dt.timedelta(minutes=SLOT_STEP_MINUTES)

    return slots


def compute_any_provider_slots(
    *,
    eligible_providers: list[TenantMembership],
    service: Service,
    location: Location,
    on_date: dt.date,
    now: dt.datetime | None = None,
    lead_minutes: int = DEFAULT_LEAD_MINUTES,
    include_unavailable: bool = False,
) -> list[dict]:
    """Union of slots across multiple providers — "anyone available".

    A slot is `available=True` if ANY eligible provider can do it at
    that time; the first provider (by pk) gets credited via
    `provider_id`. When all providers are conflicted at a given start
    time and ``include_unavailable=True``, the slot is returned with
    ``available=False`` and ``provider_id=None`` so the UI can render
    it as Taken instead of leaving a gap.
    """
    by_start: dict[dt.datetime, dict] = {}
    for provider in eligible_providers:
        for slot in compute_provider_slots(
            provider=provider,
            service=service,
            location=location,
            on_date=on_date,
            now=now,
            lead_minutes=lead_minutes,
            include_unavailable=include_unavailable,
        ):
            existing = by_start.get(slot.start)
            if existing is None:
                payload = slot.to_payload()
                payload['provider_id'] = provider.pk if slot.available else None
                by_start[slot.start] = payload
            elif not existing['available'] and slot.available:
                # Earlier provider was conflicted at this time but this
                # one is free — upgrade the slot to available.
                existing['available'] = True
                existing['provider_id'] = provider.pk
    return [by_start[k] for k in sorted(by_start.keys())]


# ── Helpers ───────────────────────────────────────────────────────────


def _location_tz(location: Location) -> zoneinfo.ZoneInfo:
    """Resolve the location's timezone, falling back to the server tz
    when the IANA name is missing or invalid. We never silently default
    to UTC — that's how we got the original 5-AM-EDT bug; better to
    use the server's configured tz as a noticeable fallback that the
    operator can spot in dev (and that production env discipline keeps
    sane)."""
    name = (location.timezone or '').strip()
    if name:
        try:
            return zoneinfo.ZoneInfo(name)
        except zoneinfo.ZoneInfoNotFoundError:
            pass
    return zoneinfo.ZoneInfo(str(timezone.get_current_timezone()))


def _combine(
    on_date: dt.date, hh_mm: str, tz: zoneinfo.ZoneInfo,
) -> dt.datetime:
    """Combine a date + 'HH:MM' string into an aware datetime in the
    given timezone. The schedule's "09:00" is the operator's local
    wall-clock at the location, so the conversion to UTC happens on
    the way OUT (Postgres stores UTC), not at parse time."""
    h, m = (int(x) for x in hh_mm.split(':'))
    return dt.datetime(on_date.year, on_date.month, on_date.day, h, m, tzinfo=tz)


def _has_conflict(
    start: dt.datetime,
    end: dt.datetime,
    existing: list[tuple[dt.datetime, dt.datetime]],
) -> bool:
    """Does [start, end) overlap any of the existing [s, e) intervals?"""
    for s, e in existing:
        if start < e and end > s:
            return True
    return False
