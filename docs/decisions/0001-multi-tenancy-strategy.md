# ADR 0001 — Multi-tenancy strategy

## Status

Accepted (2026-04-29)

## Context

Lumè serves multiple medical spas from a single deployment. Two hard constraints:

1. **HIPAA isolation.** A leak of one spa's PHI to another spa's staff is a reportable breach (HHS notification, possible press) under the HIPAA Privacy and Security Rules. Architecture must make cross-tenant access **impossible by construction**, not "we filter by `tenant_id` in queries."
2. **Operational simplicity.** Solo dev. We can't afford the operational burden of one Postgres database per tenant or a separate Kubernetes namespace per spa.

Three industry-standard approaches:

| Approach | Isolation | Operational cost |
|---|---|---|
| **Database-per-tenant** | Strongest. Physical separation. | High — N databases to back up, migrate, monitor. |
| **Schema-per-tenant** | Strong. Postgres `SET search_path` per request. | Medium — N schemas, each gets every migration. |
| **Shared schema + tenant_id column** | Weakest by default; strong with Postgres Row-Level Security. | Low — single database, single migration set. |

## Decision

**Shared schema + `tenant_id` column on every PHI table + Postgres Row-Level Security policies for defense-in-depth.**

Implementation pieces:

1. **`TenantedModel` abstract base class** (in `apps.tenants.abstract_models`). Every model holding tenant-scoped data inherits from it. The base adds the `tenant` ForeignKey automatically.
2. **`TenantedManager` with `for_current_tenant()` / `for_tenant(tenant)` methods.** App code uses these everywhere instead of `.objects.all()`. Forgetting to filter is harder by convention.
3. **Per-request tenant context via `contextvars`** (`apps.tenants.context`). `TenantMiddleware` resolves the tenant from the request subdomain and sets the context variable. `for_current_tenant()` reads from it.
4. **Subdomain-based routing.** `acmespa.lume-crm.com` → tenant `acmespa`. Reserved subdomains (`www`, `admin`, `api`) bypass tenant resolution.
5. **Postgres Row-Level Security** as the database-side enforcement. Deferred to Phase 0c (production deployment) because it requires a non-superuser application role; local dev's superuser bypasses RLS anyway.

## Consequences

### Pros

- Single database to operate, monitor, back up.
- Migrations run once, apply to all tenants.
- App-level filtering via `for_current_tenant()` is explicit and discoverable in code review.
- RLS in production catches any forgotten filter at the database level.
- The `TenantedModel` base means new PHI tables get tenant scoping with one line of inheritance.

### Cons

- **Until RLS is deployed in Phase 0c, isolation is enforced only at the app layer.** A buggy query that omits `for_current_tenant()` would return cross-tenant data. Mitigations: convention enforcement, code review, future RLS.
- **Database-level cost queries are global.** Counting "rows in `appointments`" returns a global count, not per-tenant. Reporting code must filter explicitly.
- **Backups are global.** Restoring one tenant's data without touching others requires application-level export/import — not a database restore.

### Production lift (Phase 0c)

Two Postgres roles required for RLS:

- `lume_admin` — superuser, used for migrations. Bypasses RLS.
- `lume_app` — application role, used for web requests. RLS applies.

Per-request, the app sets `app.tenant_id` via `SET LOCAL` at transaction start. RLS policies on tenanted tables filter by `tenant_id = current_setting('app.tenant_id')::bigint`.

## References

- [apps.tenants README](../../backend/apps/tenants/README.md)
- [Postgres RLS documentation](https://www.postgresql.org/docs/16/ddl-rowsecurity.html)
- HIPAA Security Rule §164.312 — Technical Safeguards
