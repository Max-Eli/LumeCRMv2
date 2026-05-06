# ADR 0004 — Audit logging

## Status

Accepted (2026-04-30)

## Context

HIPAA Security Rule §164.312(b) "Audit controls" requires:

> Implement hardware, software, and/or procedural mechanisms that record and examine activity in information systems that contain or use electronic protected health information.

Concretely, when a HIPAA audit happens (whether a compliance review or a breach investigation), we need to answer:

- Who accessed patient X's chart in the last 90 days?
- Did anyone export bulk customer data?
- What logins failed, from which IPs, attempting which accounts?

Two architectural questions:

1. **What gets logged?** Every read of every PHI table is the safe answer; every write only is the cheap answer.
2. **How is the log made tamper-resistant?** Logs that can be silently edited or deleted are useless in a breach investigation.

## Decision

**Append-only `AuditLog` model in `apps.audit`. Application-level immutability via overridden `save()` and `delete()`. Production will add a Postgres trigger for database-level immutability. Auth events auto-recorded via signal handlers; PHI reads/writes recorded explicitly per-feature as we build them.**

### What gets logged

| Source | Mechanism |
|---|---|
| `login`, `logout`, `login_failed` | Auto, via Django auth signal handlers in `apps.audit.signals` |
| `read`, `update`, `create`, `delete` of PHI | Explicit `audit.services.record(...)` calls in views and services |
| `export` actions (bulk data download, accounting export) | Explicit `record(...)` calls |
| Permission grants/revokes via Owner UI | Explicit `record(...)` calls (Phase 1H) |

We do **not** auto-instrument every `Model.save()`. Reasons:

1. Saves include routine internal state changes (status updates, derived field recomputes) that aren't audit-worthy and would drown the signal.
2. The view/service knows the *intent* (a viewer read the chart vs. a billing job updated the invoice status), which the model doesn't.
3. Per-view instrumentation produces a clearer audit trail aligned with user actions.

### Schema

Single `AuditLog` table:

| Field | Type | Notes |
|---|---|---|
| `timestamp` | DateTime, auto-now-add, indexed | UTC |
| `tenant` | FK Tenant, nullable | Login attempts and platform-admin actions are tenantless |
| `user` | FK User, nullable | `login_failed` events have no user |
| `action` | enum | `create`, `read`, `update`, `delete`, `login`, `logout`, `login_failed`, `export`, `permission_granted`, `permission_revoked` |
| `resource_type` | string | `customer`, `invoice`, `appointment`, etc. |
| `resource_id` | string | PK of the resource — string so different PK types coexist |
| `ip_address` | inet | from `X-Forwarded-For` or `REMOTE_ADDR` |
| `user_agent` | varchar(500) | truncated; full UA can be MB-sized in pathological cases |
| `metadata` | JSONB | free-form structured context (`fields_changed`, `old_value`, `new_value`, `attempted_email`, etc.) |

### Indexes

Tuned for the most common audit queries:

- `(tenant, -timestamp)` — "what did this tenant do in the last 30 days"
- `(user, -timestamp)` — "what did this user touch"
- `(resource_type, resource_id)` — "who touched this customer's record"
- `(action, -timestamp)` — "show all login_failed events" / "show all exports"

### Immutability

**Application layer:**

```python
def save(self, *args, **kwargs):
    if self.pk is not None:
        raise ValidationError('AuditLog entries are immutable.')
    super().save(*args, **kwargs)

def delete(self, *args, **kwargs):
    raise ValidationError('AuditLog entries cannot be deleted.')
```

Admin is registered with `has_change_permission = False` and `has_delete_permission = False`.

**Database layer (Phase 0c):**

```sql
CREATE OR REPLACE FUNCTION reject_audit_modification() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'AuditLog entries are immutable';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER no_update ON audit_auditlog BEFORE UPDATE EXECUTE FUNCTION reject_audit_modification();
CREATE TRIGGER no_delete ON audit_auditlog BEFORE DELETE EXECUTE FUNCTION reject_audit_modification();
```

This blocks even an attacker with database credentials from rewriting history (short of dropping/recreating the table, which would itself be visible in CloudTrail).

## Consequences

### Pros

- HIPAA-aligned out of the gate.
- Auth events covered automatically — login attempts on day one are auditable.
- Schema is generic enough to accommodate any future PHI access pattern without migration.
- Indexes match the queries an investigator actually runs.
- Append-only enforcement is layered (app + DB) so neither alone is the single point of trust.

### Cons

- **Per-feature instrumentation.** Every Phase 1 feature must remember to add `record(...)` calls. Mitigation: code review checklist + ADR reference + per-feature checklist in PROJECT_PLAN.md.
- **Unbounded growth.** `AuditLog` will become the largest table in the database. Mitigation: in Phase 0c, set up a partitioning + archival strategy (rolling monthly partitions, archive partitions older than 7 years to cold S3).
- **JSONB `metadata` is unindexed.** Queries filtering on metadata fields are slow. Mitigation: if a particular metadata field becomes a common filter, promote it to a dedicated column.
- **Tenant context might be wrong** for actions that happen before tenant resolution (e.g., login failures hit the audit log without a tenant). This is correct behavior — they're tenant-agnostic events — but reports that group by tenant must handle null.

## References

- [apps.audit README](../../backend/apps/audit/README.md)
- HIPAA Security Rule §164.312(b) — Audit controls
- HIPAA Security Rule §164.312(c)(1) — Integrity controls
