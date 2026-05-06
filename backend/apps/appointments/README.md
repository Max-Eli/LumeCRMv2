# apps.appointments

Booking appointments — the core scheduling unit. An `Appointment` ties a customer to a provider (a `TenantMembership`), a service, and a time block.

## What's in here

- **[models.py](models.py)** — `Appointment` (extends `TenantedModel`). Status enum, time fields, snapshot price, status-transition timestamps, `created_by` provenance. Database-level check constraint enforces `end_time > start_time`.
- **[permissions.py](permissions.py)** — `AppointmentPermission`. Reads open to any tenant member; writes gated by `BOOK_APPOINTMENT` / `RESCHEDULE_*` / `CANCEL_APPOINTMENT`. Object-level check enforces "providers can only reschedule their own" when they have `RESCHEDULE_OWN_APPOINTMENT` but not the broader perm.
- **[serializers.py](serializers.py)** — `AppointmentSerializer` with nested `_CustomerSummary`, `_ServiceSummary`, `_ProviderSummary` so calendar payloads render without N+1 round-trips. Mutations accept `customer_id`, `service_id`, `provider_id`. End-after-start validated in `validate()`.
- **[views.py](views.py)** — `AppointmentViewSet`. Supports `?date=YYYY-MM-DD` (interpreted in tenant timezone), `?start=…&end=…`, `?provider=…`, `?customer=…`, `?status=…`. Audit logs every action.
- **[admin.py](admin.py)** — Django admin with grouped fieldsets (Identity / Time / Workflow / Notes / Provenance), date hierarchy on `start_time`.

## Status lifecycle

```
booked  ─►  confirmed  ─►  checked_in  ─►  completed
    │           │             │
    ▼           ▼             ▼
cancelled   cancelled    no_show
```

Status transitions populate the timestamp fields (`checked_in_at`, `completed_at`, `cancelled_at`). For now those fields are written manually; transition helpers and audit-logged transition events ship with Phase 1C session 2.

## Time and timezones

`USE_TZ=True`, so all DateTime fields are stored in UTC. The day view filter (`?date=YYYY-MM-DD`) interprets the date in **the active location's** `Location.timezone` (NOT a tenant-wide timezone — multi-site businesses can span timezones; ADR 0009 made `Tenant.timezone` go away in favor of per-location). The frontend converts back to the same timezone for display.

## Snapshot pricing

`quoted_price_cents` is set at create time from the service's current `price_cents`. This is so retroactive price changes don't alter quoted appointments — important for honoring the price the customer was told. Phase 2A invoicing reads this field, not the live service price.

## Location + schedule scoping

Every `Appointment` carries a `location` FK (NOT NULL after the three-phase migration in Phase 4E session 4). The list endpoint filters by `request.location` so the LA day view never shows Manhattan's bookings. Create defaults `location` from the active location when omitted. The serializer's `validate()` enforces:

- **Cross-tenant guard** on `location_id` — must belong to current tenant + be active.
- **Provider-at-location guard** — provider must have an active `MembershipLocation` row at the appointment's location.
- **Schedule-fit guard** — if the provider has a `ProviderSchedule` at that location, the appointment must fit within one of the day's working blocks (skipped on cancel/no-show transitions; skipped when no schedule exists, treated as "unconstrained").

See:

- [ADR 0009 — Multi-location architecture](../../../docs/decisions/0009-multi-location-architecture.md) for `Appointment.location` rollout (3-phase migration), bookable-membership filtering, and URL scheme.
- [ADR 0010 — Per-provider scheduling](../../../docs/decisions/0010-per-provider-scheduling.md) for the schedule-fit validation logic + calendar overlay.

## What's coming

- **Hard conflict prevention** — preventing double-booking the same provider in overlapping time windows. Today we softly warn; tighten to enforce + respect `Service.buffer_minutes`.
- **Drag-drop schedule rejection during drag** — today the working-hours overlay shows visually that the drop is invalid, and the API rejects on drop attempt; tightening to a mid-drag tint is in §4.5 polish.
- **`ScheduleException`** for one-off schedule overrides ("Sarah off Christmas Eve") — Phase 1D's polish list.
- **Recurring appointments** — Phase 2 territory.
