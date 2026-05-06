# apps.tenants

Multi-tenancy primitives. The most important app in the backend — every PHI table will inherit from primitives defined here.

## What's in here

- **[models.py](models.py)** — `Tenant`, `JobTitle`, `TenantMembership`.
- **[abstract_models.py](abstract_models.py)** — `TenantedModel` abstract base + `TenantedManager` with `for_current_tenant()` / `for_tenant(tenant)`.
- **[context.py](context.py)** — Per-request tenant `ContextVar` (`get_current_tenant`, `set_current_tenant`, `tenant_context`).
- **[middleware.py](middleware.py)** — `TenantMiddleware` resolves the tenant from the request subdomain and populates request context.
- **[permissions.py](permissions.py)** — Permission catalog (`P` namespace), `ROLE_DEFAULTS`, `LOCKED_PERMISSIONS`, `has_permission` resolver.
- **[services.py](services.py)** — `create_tenant_with_defaults` — atomic tenant onboarding (tenant + seeded job titles + Owner membership).
- **[admin.py](admin.py)** — Django admin for Tenant (with inline JobTitles + Memberships), JobTitle, TenantMembership.

## Mental model

```
Tenant (one row per spa)
  ├── JobTitles[]                  # tenant-customizable list
  ├── TenantMemberships[]          # one per user-in-this-tenant
  │     ├── role: Owner|Manager|Front Desk|Provider|Bookkeeper|Marketing
  │     ├── job_title: FK to JobTitle (clinical job titles can sign chart notes)
  │     ├── is_bookable: appears in calendar as a resource
  │     ├── extra_permissions: granted on top of role defaults
  │     └── revoked_permissions: stripped from role defaults
  └── (everything else — Customers, Appointments, Invoices, Forms — FKs back here via TenantedModel)
```

## Building a new PHI model

Inherit from `TenantedModel`:

```python
from apps.tenants.abstract_models import TenantedModel
from django.db import models

class Customer(TenantedModel):
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    email = models.EmailField(blank=True)
    # ...
```

Then in views:

```python
customers = Customer.objects.for_current_tenant()      # in a request scope
customers = Customer.objects.for_tenant(tenant)        # explicit tenant (background jobs)
```

`for_current_tenant()` reads from the request-scoped `ContextVar` set by `TenantMiddleware`. If no tenant is set (e.g. in a non-request context that forgot to use `tenant_context()`), it returns an empty queryset — fail-safe by default.

## Permissions

Two layers:

1. **Role-based defaults** — six fixed roles in `permissions.ROLE_DEFAULTS`. Each role maps to a `frozenset` of permission strings.
2. **Per-user overrides** — `TenantMembership.extra_permissions` and `revoked_permissions` (JSON arrays of permission strings).

Effective set = `(ROLE_DEFAULTS[role] ∪ extra_permissions) − revoked_permissions`.

Permissions in `permissions.LOCKED_PERMISSIONS` (currently `DELETE_TENANT`, `MANAGE_BILLING`) cannot be granted via override — they MUST come from role.

In code:

```python
from apps.tenants.permissions import P

if request.tenant_membership and request.tenant_membership.has(P.VOID_INVOICE):
    ...
```

See [ADR 0003 — Permission model](../../../docs/decisions/0003-permission-model.md) for the rationale.

## Tenant resolution

`TenantMiddleware` runs after `AuthenticationMiddleware` (so `request.user` is populated) and:

1. Reads `request.get_host()`, splits off the subdomain.
2. Skips reserved subdomains: `www`, `admin`, `api`, `localhost`, plus bare hostnames.
3. Looks up `Tenant.objects.get(slug=subdomain, status=ACTIVE)` — returns the model or `None`.
4. Sets `request.tenant`, `request.tenant_membership`, and the tenant `ContextVar` for the duration of the request.

For local dev, `acmespa.localhost:3000` resolves to `localhost` per browser default — no `/etc/hosts` needed.

## Why no Postgres RLS yet

RLS policies require a non-superuser app-role separation (see [ADR 0001 — Multi-tenancy strategy](../../../docs/decisions/0001-multi-tenancy-strategy.md)). For local dev where every connection is the superuser, RLS is bypassed anyway. We'll wire it up in Phase 0c when production roles exist on RDS. App-level filtering via `for_current_tenant()` is the v1 isolation layer.

## Multi-location

Tenants own one or more `Location`s — physical sites with their own address, business hours, timezone, and staff roster. `MembershipLocation` is the join table assigning staff to one or more locations within their tenant. `LocationMiddleware` (runs after `TenantMiddleware`) sets `request.location` from the `lume_active_location` cookie, falling back to the tenant's default location.

`ProviderSchedule` is 1:1 with `MembershipLocation` so the same person can have different working hours at different sites — `weekly_hours` JSONB keyed by lowercase weekday with `{start, end}` HH:MM blocks, empty array = explicitly off.

See:

- [ADR 0009 — Multi-location architecture](../../../docs/decisions/0009-multi-location-architecture.md) for the data model + default-location invariant + URL scheme.
- [ADR 0010 — Per-provider scheduling (per-location)](../../../docs/decisions/0010-per-provider-scheduling.md) for the JSONB shape, validation rules, and calendar consumption.
