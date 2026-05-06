# apps.audit

HIPAA-aligned append-only audit log. Required by HIPAA Security Rule §164.312(b) "Audit controls."

## What's in here

- **[models.py](models.py)** — `AuditLog` model. Append-only at the application layer (`save()` raises on update; `delete()` raises always).
- **[services.py](services.py)** — `record(...)` helper. Auto-pulls user/tenant/IP/User-Agent from the request when given one.
- **[signals.py](signals.py)** — Django auth signal handlers wiring `user_logged_in`, `user_logged_out`, `user_login_failed` → `AuditLog`.
- **[admin.py](admin.py)** — Read-only Django admin (no add/change/delete via the admin UI).

## Recording a log entry

```python
from apps.audit.services import record
from apps.audit.models import AuditLog

# In a DRF view:
record(
    action=AuditLog.Action.READ,
    resource_type='customer',
    resource_id=customer.id,
    request=request,                # → user, tenant, IP, UA pulled automatically
    metadata={'fields_viewed': ['medical_history']},
)

# In a background job (no request):
record(
    action=AuditLog.Action.EXPORT,
    resource_type='zenoti_import',
    user=batch_job.initiator,
    tenant=batch_job.tenant,
    metadata={'rows': 7000},
)
```

## What gets logged automatically

- `login` — successful login (via `user_logged_in` signal)
- `logout` — successful logout
- `login_failed` — failed login attempt; attempted email is recorded in `metadata`

## What DOESN'T get logged automatically

Reads, writes, and exports of PHI must be logged explicitly by the view or service that performs them. We don't auto-instrument every model save because (a) it would generate noise on routine internal state changes and (b) the calling code knows the *intent* (export vs. routine view), which the model doesn't.

The convention: when you build a Phase 1 feature, audit-log every PHI-bearing endpoint.

## Schema highlights

| Column | Notes |
|---|---|
| `timestamp` | `auto_now_add`, indexed |
| `tenant` | nullable — login/logout entries before tenant resolution have `tenant=None` |
| `user` | nullable — `login_failed` and anonymous events have `user=None` |
| `action` | one of `AuditLog.Action` values |
| `resource_type` / `resource_id` | strings — keeps the table polymorphic |
| `ip_address` | derived from `X-Forwarded-For` or `REMOTE_ADDR` |
| `user_agent` | truncated to 500 chars |
| `metadata` | JSONB for free-form structured context |

Indexes are tuned for the access patterns most likely to appear in audit reports — see the model docstring.

## Production immutability

The application-level `save()` / `delete()` overrides prevent accidental writes from app code, but a determined attacker with database access could still tamper with rows. In production we'll add a Postgres trigger that rejects UPDATE/DELETE at the database level — tracked in Phase 0c.

## Querying

```python
from apps.audit.models import AuditLog

# Everything user X did in the last 30 days, newest first
AuditLog.objects.filter(user=user, timestamp__gte=cutoff)

# All accesses to a specific customer
AuditLog.objects.filter(resource_type='customer', resource_id=str(customer.id))

# All login_failed events for a tenant
AuditLog.objects.filter(action='login_failed', tenant=tenant)
```

See [ADR 0004 — Audit logging](../../../docs/decisions/0004-audit-logging.md) for the design rationale.
