# apps.services

Service catalog — what each tenant offers, how long it takes, and what it costs. Foundation for the booking calendar (Phase 1D), invoices (Phase 1E), packages (Phase 2B), and the public booking page (Phase 1I).

## What's in here

- **[models.py](models.py)** — `Service` (extends `TenantedModel`), `ServiceCategory` (per-tenant grouping).
- **[permissions.py](permissions.py)** — `ServicePermission`. Read for any authenticated tenant member; write requires `MANAGE_SERVICES`.
- **[serializers.py](serializers.py)** — `ServiceSerializer` + `ServiceCategorySerializer`.
- **[views.py](views.py)** — `ServiceViewSet` + `ServiceCategoryViewSet`, both with audit logging.
- **[urls.py](urls.py)** — DRF router mounting both at `/api/services/` and `/api/service-categories/`.
- **[admin.py](admin.py)** — Grouped fieldsets for Service (Basics / Booking / Pricing) and a flat Category admin.

## API endpoints

| Method | Path | Notes |
|---|---|---|
| `GET` | `/api/services/` | List. Filters: `?q=` (name, description), `?category=<id>`, `?active=true\|false` |
| `POST` | `/api/services/` | Create. Requires `MANAGE_SERVICES`. |
| `GET` | `/api/services/{id}/` | Retrieve. |
| `PATCH` / `PUT` | `/api/services/{id}/` | Update. Requires `MANAGE_SERVICES`. |
| `DELETE` | `/api/services/{id}/` | Delete. Requires `MANAGE_SERVICES`. |
| `GET` | `/api/service-categories/` | List categories. |
| `POST` | `/api/service-categories/` | Create category. Requires `MANAGE_SERVICES`. |
| `PATCH` / `PUT` / `DELETE` | `/api/service-categories/{id}/` | Mutations. Require `MANAGE_SERVICES`. |

Audit log entries: `read service_list` (one per list call), `read service:{id}`, `create service:{id}`, `update service:{id}` (with `fields_changed` metadata), `delete service:{id}`.

## Why no PHI gating?

Services aren't PHI — they're business config (price, duration, name). Any authenticated tenant member needs to read them: front desk to book, providers to know what they're doing, owners to manage. That's why `ServicePermission` allows reads broadly and gates only writes.

## Pricing

`price_cents` is the canonical field — integer, dollars × 100, no float drift. The serializer also exposes a read-only `price_dollars` formatted string (`"$240.00"`) for display. The frontend converts user-typed dollar amounts via `centsFromDollars()` before posting.

## Categories

Categories are per-tenant. They're display-only metadata (color, sort order). They don't grant or restrict permissions. Default seeds when a new tenant is provisioned will be added to the onboarding service in a follow-up — for now categories must be created manually after a tenant exists.

## Out of scope (deferred)

- **Per-provider service eligibility** (which staff can perform which services) — Phase 1B.1, lands with the booking calendar where it has practical effect.
- **Service add-ons** (extra Botox units, upgrade tier on a facial) — Phase 2A, alongside POS work.
- **Variations** (10u vs 20u Botox as one "service" with options) — deferred. Currently each variation is its own Service row.
- **Sales tax** — Phase 2A. The `price_cents` field is treated as net for now.
- **Internationalization / multi-currency** — Phase 0c+. Currently USD-only.
