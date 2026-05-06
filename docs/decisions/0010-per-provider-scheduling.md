# ADR 0010 — Per-provider scheduling (per-location)

## Status

Accepted (2026-05-02 — Phase 1C session 4; documented retroactively after the implementation shipped)

> **Backfill note.** Like ADR 0009, this was written after the
> implementation shipped. Both backfills filed in the same session
> the user called out the discipline gap. Going forward, ADRs land
> with the code that implements them.

## Context

Before this work, the calendar's day window came from each
location's `business_open_time` / `business_close_time` (8 AM – 8
PM by default). Every provider was bookable across that whole
window — no per-provider hours. Real medspa workflow doesn't work
that way:

- "Sarah does injectables Mon/Wed 9-3, Tue/Thu 4-8."
- "Bob is part-time at Brooklyn — Tue/Sat only, 10-4."
- "Carla works at both sites: 9-5 Mon-Fri at Manhattan, 10-3 Sat at
  Brooklyn."

Without per-provider hours encoded in the system:

- Front desk has to remember everyone's hours by hand → mistakes.
- Online booking (Phase 1I) can't compute available slots → can't
  ship.
- Calendar shows "available everywhere" tinting that's misleading.
- Drag-drop reschedule lets you put a 2 PM appointment on Sarah's
  Wednesday morning window even though she's gone home.

The user explicitly asked for "a professional scheduling system,
not just location assignment" with a visual editor and calendar
consumption. They confirmed the schedule must reflect on the
calendar — meaning we needed both the editor AND the consumption
in this session.

### HIPAA + SOC 2 framing

Schedules are operational data, not PHI. But several considerations
still apply:

- **Tenant + location isolation.** Schedule changes must be scoped:
  a manager at Manhattan can't accidentally edit a Brooklyn-only
  provider's hours. Inherited from `MembershipLocation`'s tenant
  scoping — no separate enforcement needed.
- **Audit trail on every change.** Schedule edits are operational
  decisions with downstream payroll implications (Phase 1G reports
  will compute scheduled vs worked hours). SOC 2 CC 7.2 — every PUT
  is `AuditLog`-ed with day-level diff metadata.
- **Indirect PHI exposure.** A schedule reveals when a specific
  named provider is at a specific location. This is operational, not
  patient-identifying. The schedule API is gated by `MANAGE_STAFF`
  (owner + manager) for writes; reads are open to anyone in the
  tenant (front desk needs the calendar to render properly).
- **Defense in depth on bookings.** The schedule check on appointment
  create/update prevents a buggy or scripted client from booking
  outside hours. The calendar UX shows the visual overlay as a hint;
  the API enforces the rule.

## Decision

**`ProviderSchedule` model 1:1 with `MembershipLocation` (not with
`TenantMembership`) so the same person can have different hours at
different sites. `weekly_hours` is JSONB keyed by lowercase weekday
with arrays of `{start, end}` HH:MM blocks. Empty array = explicitly
off; missing schedule entirely = unconstrained (treated as
"available all day," matching pre-feature behavior). Schedule fit
is enforced server-side in `AppointmentSerializer.validate`; the
calendar's day view dims non-working hours as a translucent overlay
above the time grid but below appointment blocks.**

### Domain shape

| Decision | Rationale |
|---|---|
| 1:1 with `MembershipLocation`, not `TenantMembership` | Same person legitimately has different hours per site. Couples schedule to location assignment so removing a person from a site removes their schedule there too. |
| `weekly_hours` as JSONB rather than separate per-block rows | Atomic edits (PUT replaces the whole week in one transaction). Cross-block validation (no overlap within a day) is application-layer; storing as one document keeps it together. Trade-off: can't query "find all providers working Tuesday at 2 PM" via SQL — requires Python loop. Acceptable for v1; if cross-provider time-of-day queries become a hot path, we can extract to a normalized table. |
| `null` schedule = unconstrained vs `[]` per day = explicitly off | Operators distinguish "I haven't set up Sarah's schedule yet, she's fine to book any time" from "Sarah is off Mondays." Conflating these would force every operator to fully fill out every employee's week before the calendar works. |
| Weekday keys are full lowercase names (`monday`...) | Self-documenting in the JSON payload — no integer-day-of-week confusion (Sunday=0 vs Monday=0 ambiguity). DRF serializers pick this up cleanly. |
| `version` field NOT included | Schedule changes don't snapshot historical bookings. The booking already happened; if Sarah's schedule changes after, that's just operations. (Forms snapshot version because the SIGNED CONSENT must reflect what the client saw — different concern.) |

### API shape

`GET / PUT /api/schedules/{membership_location_id}/`. Singleton-per-
membership-location surface. GET returns the canonical 7-weekday shape
even when no row exists yet (lazy materialization on first PUT) so
the editor can render a consistent grid regardless of whether the
person has been scheduled before. PUT is full-replace with strict
validation:

- Each `weekly_hours[day]` is an array; values are `{start, end}`
  HH:MM strings.
- `end > start` per block.
- No overlapping blocks within a day (split shifts allowed; lunch
  breaks allowed; "9-12 + 11-14" rejected).
- Exactly the 7 weekday keys (typos like `tueday` rejected with the
  bad key named in the error).
- HH:MM regex enforced; `9am` rejected.

Owner + manager write via `MANAGE_STAFF`. Read open to anyone in the
tenant.

### Calendar consumption

Two ends:

1. **Backend** — bookable memberships endpoint embeds
   `schedule_for_location` per provider when called with
   `?location=current|<slug>`. Calendar gets schedule data in one
   round-trip; no per-provider fetch storm.
2. **Frontend** — `<WorkingHoursOverlay>` in `day-view.tsx` derives
   the current weekday from the visible date, reads each provider's
   `schedule_for_location[weekday]`, and renders translucent
   muted-foreground overlays for the non-working segments. Sits
   above the time grid lines but BELOW appointment blocks (booked
   appointments stay readable even outside working hours so the
   operator can see exceptions). `pointer-events-none` so the
   column's right-click context menu still fires on overlay
   regions.

### Schedule-fit validation on appointments

`AppointmentSerializer.validate` rejects a booking that doesn't fit
within the provider's working blocks for the day. Resolution:

1. Look up the provider's `MembershipLocation` for the appointment's
   location. If no schedule row, skip the check (unconstrained).
2. Convert the appointment's UTC start/end to the location's
   timezone to derive the local weekday + HH:MM window.
3. If the day's blocks are empty (`[]` = off), reject with
   `"{name} is not scheduled to work on {day} at {location}…"`.
4. If the day has blocks, reject if the appointment's `[start, end]`
   isn't fully contained in at least one block. Error names the
   blocks: `"Time falls outside Sarah's working hours (09:00–12:00,
   13:00–17:00) at Manhattan…"`.

Cross-midnight bookings rejected with a friendly message
(out-of-scope for v1; spa workflow rarely needs them, and weekday
straddle would require dual-day validation).

Cancellation + no-show transitions skip the check. Closing out an
existing booking shouldn't fight a later schedule change ("we'd
have rejected this if you booked it now, but you booked it three
weeks ago when Sarah was scheduled — let her cancel it without
fighting").

## Consequences

### Pros

- **Calendar is honest.** The dimmed overlay shows operators where
  providers aren't working at a glance. Front desk decisions get
  better info.
- **Booking constraints encoded once, enforced everywhere.** The
  validator in `AppointmentSerializer` catches the new-appointment
  sheet, the drag-drop reschedule path, and (when it lands) the
  online booking POST.
- **Per-location scheduling is a real product feature**, not an
  afterthought. "Sarah works 9-3 here Tue, 4-8 there Wed" is a
  one-form expression in the editor.
- **JSONB schema scales** — adding new fields per block (e.g.
  `notes` on a shift, `is_overtime` flag) is zero migration.
- **Audit trail captures intent.** PUT writes record `from_version`
  / `to_version` and `days_with_hours` diff so a SOC 2 reviewer
  answers "who changed Sarah's Tuesday hours and when."

### Cons

- **No `ScheduleException` model in v1.** "Sarah off Christmas Eve"
  requires editing the weekly template, which then over-writes
  back to normal (or stays off forever, which is wrong). Polish
  item — needs a date-keyed override table.
- **Drag-drop visual feedback during drag is overlay-only.** When
  the operator drags into off-hours the overlay shows it, but the
  drop target itself doesn't tint until the API rejects. Tightening
  to mid-drag rejection is a polish item.
- **No per-provider per-day schedule history.** Changing Sarah's
  Tuesday hours doesn't snapshot the prior version — just bumps the
  rows and audit-logs the change. If we ever need "what was Sarah's
  schedule on 2026-01-15?" we'd need event-sourcing or a separate
  history table. Not a current need.
- **JSONB structure can't be queried cross-provider in SQL.** "All
  providers working at 2 PM Tuesday" requires Python iteration. If
  this becomes a hot path (e.g. online booking slot computation has
  to scan every provider), we'd extract to a normalized
  `ProviderShift` table.
- **Online booking (Phase 1I) will need slot computation** that
  intersects schedules with existing appointments + service buffer.
  Not built yet; the schedule data shape is ready for it.

### Production lift

- **No additional infra needed.** JSONB is built into Postgres.
- **Audit-log retention** applies to schedule events like everything
  else.
- **Polish items** flagged in PROJECT_PLAN.md §4.5: `ScheduleException`,
  drag-drop hard rejection, online-booking slot computation, mobile
  scheduler.

## References

- [apps.tenants README](../../backend/apps/tenants/README.md)
- [apps.appointments README](../../backend/apps/appointments/README.md)
- [ADR 0009 — Multi-location architecture](./0009-multi-location-architecture.md)
- [ADR 0004 — Audit logging](./0004-audit-logging.md)
- HIPAA Security Rule §164.312(b) — Audit controls
- SOC 2 Trust Services Criteria CC 7.2 — System monitoring
