# ADR 0003 — Permission model

## Status

Accepted (2026-04-30)

## Context

Lumè needs role-based access control across six different staff types (Owner, Manager, Front Desk, Provider, Bookkeeper, Marketing) with HIPAA-aware constraints (Bookkeeper sees money but not charts; Marketing sees contact info but not medical history). Plus, Owners must be able to **customize** permissions per individual staff member — the spa down the street wants Front Desk to issue refunds; the spa across town doesn't.

Three approaches considered:

| Approach | Flexibility | Complexity |
|---|---|---|
| **Django Groups + Permissions** | Low. Django's per-model permission system is granular but tedious for cross-cutting actions like "void invoice." | Low for built-in, high once you add custom permissions. |
| **Pure role enum (fixed mapping)** | Low. Six roles → six permission sets. No per-user override possible. | Very low. Just a dict in code. |
| **Role + per-user override JSON** | High. Default behavior from role, escape hatches per user. | Medium. Two JSON columns + a resolver function. |
| **Custom roles per tenant** | Maximum. Each tenant defines its own roles + permissions. | High. Full role-management UI required. Overkill for v1. |

The competing requirements: simple defaults for the 95% case, and flexibility for the 5% case.

## Decision

**Six fixed roles defined in code, with per-user `extra_permissions` and `revoked_permissions` JSON arrays on `TenantMembership`. A small `LOCKED_PERMISSIONS` set of permissions cannot be granted via override.**

The math:

```
effective_permissions = (ROLE_DEFAULTS[role] ∪ extra_permissions) − revoked_permissions
```

Implementation in [`apps.tenants.permissions`](../../backend/apps/tenants/permissions.py):

- **`P` namespace** — flat string identifiers for every permission (`MANAGE_BILLING`, `VIEW_CLIENT_PHI`, `VOID_INVOICE`, etc.). Adding a new permission means adding one line.
- **`ROLE_DEFAULTS`** — `dict[str, frozenset[str]]` mapping role to its default permission set.
- **`LOCKED_PERMISSIONS`** — `frozenset[str]`. Permissions an Owner cannot grant via override (currently `DELETE_TENANT`, `MANAGE_BILLING`). They must come from role.
- **`has_permission(membership, permission)`** — the resolver. Also exposed as `membership.has(permission)` on the model.

### The six roles

| Role | High-level scope |
|---|---|
| Owner | Everything. Account-level controls. |
| Manager | Most of Owner except billing settings and tenant deletion. |
| Front Desk | Front-of-house operations: clients, calendar, payments. No clinical chart access. |
| Provider | Clinical work: their own schedule, their own clients, sign chart notes. |
| Bookkeeper | Financial reports + accounting export. **No PHI** (charts, medical history). |
| Marketing | Send campaigns + view audience segments. **No clinical data**, but contact info is allowed (still PHI but minimum-necessary for the role). |

### Job titles vs roles

Roles drive **permissions** (what you can DO). Job titles describe **identity** (what you ARE). They're orthogonal:

- A Nurse Practitioner is `role=Provider, job_title=Nurse Practitioner`.
- An Owner who also injects Botox is `role=Owner, job_title=Nurse Practitioner, is_bookable=True`.
- A receptionist is `role=Front Desk, job_title=Receptionist`.

Job titles are tenant-customizable (each spa edits the list). Roles are fixed in code.

## Consequences

### Pros

- **Simple defaults.** New tenants get sensible permissions from the moment they're created.
- **Escape hatch for unusual setups.** "Sarah at our front desk handles our refunds" — Owner grants `VOID_INVOICE` via override; she keeps Front Desk role.
- **Auditable.** Per-user overrides are visible in the `TenantMembership` row and in audit log events when granted/revoked.
- **Locked permissions prevent footguns.** No matter how many overrides you stack, a Front Desk user can never delete the tenant.
- **HIPAA "minimum necessary" alignment.** Each role's defaults are scoped to what that role actually needs.
- **Non-clinical staff can't sign chart notes** even if granted `SIGN_CHART` — the model has an additional check via `job_title.is_clinical`.

### Cons

- **Permission catalog grows.** As features land we'll add new strings to `P`. Need to keep the role-to-permissions mapping in sync. Mitigation: every PR adding a permission updates `ROLE_DEFAULTS`.
- **Per-user override UI is its own work.** Building the UI for Owners to manage overrides is in Phase 1H.
- **No "custom roles" yet.** A spa that wants a "Senior Provider" role with extra permissions has to use overrides on individual users, not define a new role. This is a deliberate v1 limit; we can add custom-roles-per-tenant if real demand surfaces.

### Owner protection (deferred)

Owners shouldn't be able to revoke permissions from other Owners (prevents lockout / coup). Currently enforced at the API layer (Phase 1H). The model itself accepts whatever is set; the surrounding code rejects invalid changes.

## References

- [apps.tenants README](../../backend/apps/tenants/README.md#permissions)
- HIPAA Privacy Rule §164.502(b) — "minimum necessary" standard
