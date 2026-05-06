# ADR 0009 — Multi-location architecture

## Status

Accepted (2026-05-02 — pulled forward from Phase 4E; documented retroactively after sessions 1–5 shipped)

> **Backfill note.** This ADR was written after the implementation
> shipped (sessions 1–5 across one working day). The user explicitly
> called out that ADRs should be written at decision time, not
> retroactively, and this is one of two we're filing late (the other
> is ADR 0010, scheduling). Going forward, ADRs land in the same
> session as the code that implements the decision.

## Context

The originally-scoped "tenant" in ADR 0001 was "one row per spa
business." That conflated two distinct concepts that real medspas
care about:

1. **The business** — the corporate identity. Brand, login subdomain,
   subscription, payroll-of-record. One tax ID.
2. **The location(s)** — physical site(s) where service is delivered.
   Address, business hours, timezone, calendar, staff roster.

A single business often has multiple physical locations (Manhattan +
Brooklyn, NY + LA), each with:

- Different addresses (obviously)
- **Different timezones** in some cases (NY + LA)
- Different business hours
- Different staff rosters (not every employee works at every site)
- Different calendars (an appointment at LA isn't visible from
  Manhattan's day view)

A user surfacing the per-employee profile's "Multi-center" section
made the gap concrete: showing cross-tenant memberships there was
incoherent with what spa operators actually mean by "multi-center."
They mean the SAME business with MULTIPLE LOCATIONS.

This was originally scoped as Phase 4E (Months 7+). Honest scope
discussion with the user landed on **pulling it forward to v1
launch** because:

- Both waiting medspas were going to operate at multiple sites
  eventually; making them migrate later would be painful.
- Half-doing it ("just add a location dropdown") would leave hidden
  data gaps everywhere — calendar, payroll, reporting.
- Doing it now meant every PHI table that lands going forward
  (Forms in 1D, prescriptions in Phase 4D) gets location-awareness
  as part of its design rather than retrofit.

### HIPAA + SOC 2 framing

Multi-location doesn't fundamentally change the HIPAA tenancy story
(ADR 0001) — locations live WITHIN a tenant, so the tenant boundary
is still the PHI isolation boundary. But the design needs to be
explicit that:

- **Location is a SOFT scoping concern, not a security boundary.**
  All staff in a tenant can technically be granted access to all
  locations. The location switcher UX hides data they don't need to
  see (HIPAA "minimum-necessary"), but a scoped query at the database
  layer is the SECURITY enforcement, not the UX.
- **Per-location managers need the option to scope down**
  (operationally common at chain spas) — flagged as Phase 1H polish
  ("per-location manager scope") since v1 keeps `MANAGE_STAFF` as a
  tenant-wide permission. Until then, multi-site businesses with
  different management structures per site need to use careful role
  assignment.
- **Audit trail needs location attribution.** Every appointment,
  schedule change, location-membership change records the location
  involved. SOC 2 CC 7.2 — change tracking with full context.
- **Default-location invariant must hold.** Every tenant always has
  exactly one active default location at all times — `LocationMiddleware`
  resolution depends on it. Without this, `request.location` could
  resolve to None on a perfectly legitimate request, and downstream
  scoping logic would silently widen.

## Decision

**Two-tier model: `Tenant` is the business identity (account-level —
name, slug, branding, subscription status). `Location` holds every
per-site concern (address, hours, timezone, phone). 1:N from Tenant
→ Location with a partial unique index enforcing "exactly one
default per tenant." `MembershipLocation` join table assigns staff
to one or more locations within their tenant. Active location is
resolved per-request from a `lume_active_location` cookie via
`LocationMiddleware`, parallel to the existing `lume_active_tenant`
cookie.**

### Domain shape

| Model | Purpose |
|---|---|
| `Tenant` | Account-level identity. After Phase 4E session 4 cleanup migration: `name`, `slug`, `status`, `primary_color`, `logo_url`, `created_at`, `updated_at`. Per-site fields removed. |
| `Location` | Physical site within a tenant. Tenant FK, name, slug (unique per tenant), `is_default` (partial unique index — exactly one per tenant), `is_active`, timezone, address, hours, phone, email. Soft-delete only. |
| `MembershipLocation` | Join: which staff work at which sites. Per-site `is_active` lets an operator suspend a person at one site without removing them from others. Unique together `(membership, location)`. |
| `request.location` (contextvar) | Set per-request by `LocationMiddleware` to the cookie-resolved location, falling back to the tenant's default. Mirrors the `request.tenant` pattern from ADR 0001. |

### Default-location invariant

Enforced at three levels:

1. **DB**: partial unique index on `(tenant, is_default=True)`. Only
   one row per tenant can have `is_default=True`. Postgres rejects a
   second insert with `IntegrityError`.
2. **API**: location update viewset rejects (a) un-setting
   `is_default=True` on the current default, (b) deactivating the
   default, (c) deactivating the last active location. Promoting
   another location to default atomically demotes the previous one
   in the same transaction — so the user-visible action is "set this
   as default" (single PATCH), not "demote A then promote B."
3. **Onboarding**: `create_tenant_with_defaults` creates a "Main"
   default location as part of the same transaction as tenant
   creation. Per-location fields routed from kwargs to Location, not
   Tenant.

### Location-aware data: Appointment

`Appointment.location` FK landed in three migrations (the canonical
"adding a required FK to populated tables" pattern):

1. **0002**: add nullable FK + composite index `(tenant, location, start_time)`.
2. **0003**: data migration backfilling every existing appointment
   to its tenant's default location.
3. **0004**: alter to `NOT NULL` (hand-written to skip the
   interactive `makemigrations` default-value prompt).

Validation in `AppointmentSerializer`:

- Cross-tenant guard on `location_id` (must belong to current tenant
  + be active).
- Provider-at-location guard (provider must have an active
  `MembershipLocation` row for the appointment's location).
- Day-window timezone resolved from `request.location.timezone`, not
  `tenant.timezone` (the tenant field was removed in the cleanup
  migration; the calendar reads from location).

### Location-aware data: bookable memberships

`/api/memberships/?location=current|<slug>` opt-in scoping. Used by
the calendar's bookable-providers query so the LA day view only
shows providers actually assigned to LA. Unknown slug returns empty
queryset (safer than silently widening to org-wide).

### URL scheme

- `/org/*` for org-level surfaces (business profile, locations
  management, org dashboard).
- Bare paths for active-location-scoped surfaces (`/calendar`,
  `/clients`, `/staff/*`).
- Active location is cookie-driven, not URL-driven, so URLs stay
  clean and bookmarkable without per-location prefixes. Trade-off:
  bookmarks don't capture which location was active. Acceptable for
  v1; URL-driven location is a polish concern.

### Sidebar IA

Single-location tenants (the 80% case at v1 launch) see no IA
changes — sidebar is a flat list. Multi-location tenants get:

- A `<LocationSwitcher>` in the sidebar header (popover with
  per-location options, default-star indicator, current selection
  check).
- Visual group headers in the nav: "Location · {name}" above
  day-to-day items (Dashboard / Calendar / Clients / Services /
  Staff / Forms / Reports), "Organization" above the cross-cutting
  parent (Org Dashboard / Business profile / Locations).
- An inline `LocationSwitcher` in the scheduler page header
  (operator's mental model is "schedule this person here," so the
  control belongs in context, not just the sidebar).

## Consequences

### Pros

- **Location semantics encoded in the model**, not in the operator's
  head. The calendar at LA can never accidentally show Manhattan's
  bookings. Schedules are per-location-per-provider so "Sarah works
  9-3 at Manhattan, 4-8 at Brooklyn" is expressible.
- **Per-feature retrofit cost is low.** Future PHI surfaces (forms
  submissions, prescriptions, charts) inherit `TenantedModel` and
  optionally add a `location` FK. The middleware + cookie
  infrastructure is in place.
- **Cookie-driven active location** keeps URLs clean. Switching
  sites doesn't change the route; the same `/calendar` URL means
  "current location's calendar."
- **Single-location tenants pay no IA tax.** Switcher hidden,
  sidebar group headers hidden, page-header location pills hidden.
- **HIPAA + SOC 2 trail intact**. All location operations are
  audit-logged with before/after. Default-swap recorded as a single
  audit event with `from_is_default` / `to_is_default` metadata.

### Cons

- **`MANAGE_STAFF` is tenant-wide in v1.** Multi-site businesses
  with different managers per site can't constrain a manager to one
  location. Per-location manager scope is in §4.5 polish backlog.
- **Customers + services are tenant-wide for v1.** Booking a
  customer at Brooklyn surfaces them in Manhattan's customer search.
  Most spas treat clients as tenant-wide, so this matches the
  expected mental model — but a future polish could add per-location
  primary association.
- **No per-location reporting yet.** The day-stats footer shows
  active-location stats; cross-location rollup reports are Phase 1G.
- **Cookie loses on browser-clear**, falls back to default. Loud
  enough not to be confusing; a stronger fallback (last-used
  location stored on User) is a polish item.

### Production lift

- **No additional infra needed.** Multi-location is data-model only;
  inherits the existing Postgres + Django stack.
- **Audit log retention applies to location events** like everything
  else (Phase 0c partitioning + 7-year cold-S3 archive).
- **RLS policies (Phase 0c)** filter by `tenant_id` only;
  per-location filtering stays in the application layer because
  RLS-per-location would add a 2nd `SET LOCAL` per request and
  benefit only the soft-scoping case (same staff still has access in
  principle).

## References

- [apps.tenants README](../../backend/apps/tenants/README.md)
- [ADR 0001 — Multi-tenancy strategy](./0001-multi-tenancy-strategy.md)
- [ADR 0004 — Audit logging](./0004-audit-logging.md)
- HIPAA Security Rule §164.312(a)(1) — Access control
- HIPAA Security Rule §164.312(b) — Audit controls
- SOC 2 Trust Services Criteria CC 7.2 — System monitoring
