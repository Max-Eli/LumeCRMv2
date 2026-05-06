# ADR 0007 — Invoicing model and the appointment-completion gate

## Status

Accepted (2026-05-02)

## Context

A booking appointment can be marked `completed` today by anyone with
`RESCHEDULE_ANY_APPOINTMENT` simply by `PATCH`ing the status field. There is
no requirement that money has been collected, no invoice record, no audit of
the financial side at all.

That's wrong on three fronts:

1. **Business correctness.** A spa visit isn't "complete" until the customer
   has paid (or been explicitly comp'd). If staff can mark visits complete
   without taking payment, revenue silently leaks: the daily reports say
   the day's services were performed, but no money was collected.
2. **SOC 2.** A financial event (revenue recognized for a service rendered)
   with no immutable record, no separation of duties, and no traceable
   approver is exactly the kind of control gap that fails an SOC 2
   Type II audit on Common Criteria 7.2 (audit log) and 7.3 (change
   management). Re-opening a closed invoice in particular needs to be
   logged with who, when, and why, and bounded in time.
3. **HIPAA defense in depth.** PHI is implicated whenever a service is
   recorded against a patient. Tying completion to invoice closure means
   we get audit-log coverage on revenue events for free, alongside the
   PHI access trail we already capture.

The user also clarified the invoicing domain: **"all appointments are an
invoice but not all invoices are appointments."** Standalone invoices —
retail walk-in, package purchase, gift cards (Phase 2A POS) — exist
independently of any booking.

## Decision

**Introduce an `Invoice` first-class model. Auto-create one OPEN invoice
per appointment at booking time. The only path to `Appointment.status =
COMPLETED` is `Invoice.close()`. Owners and managers may reopen a paid
invoice within 60 days of its first closure; the appointment reverts to
`CHECKED_IN` so it can be re-closed via the same path.**

### Domain shape

| Model | Purpose |
|---|---|
| `Invoice` | Tenant-scoped, customer-scoped, optionally appointment-scoped (`OneToOneField`, nullable to allow standalone invoices). Holds totals, status, and audit timestamps. |
| `InvoiceLineItem` | Many-per-invoice. Snapshots the service's name, unit price, and tax rate at line-creation time so future service-price changes never retroactively alter a billed line. |

### Status state machine

```
              ┌────────────── reopen* ───────────────┐
              ▼                                      │
    create  OPEN  ──── close ─────► PAID  ───────────┘
              │
              └─── void ─────► VOID  (terminal)
```

`*reopen` is permission-gated (`REOPEN_INVOICE` — owner + manager) and
time-gated (≤ 60 days from `closed_at`, the first close).

### Money handling

- All monetary values stored in cents as `PositiveIntegerField`. No floats
  in the money path.
- Tax computed at line level: `line_tax_cents = round_half_up(qty *
  unit_price_cents * tax_rate_percent / 100)`. Decimal arithmetic; ROUND_HALF_UP
  for predictability (banker's rounding is mathematically nicer but creates
  surprising 1¢ deltas vs. what a customer expects from invoice math).
- Invoice totals are denormalized (`subtotal_cents`, `tax_cents`,
  `total_cents`) but always recomputed from the line items inside `save()`.
  A `CheckConstraint` enforces `total_cents = subtotal_cents + tax_cents`.

### The completion gate

The `Appointment` serializer's status state machine drops the
`CHECKED_IN → COMPLETED` transition. A `PATCH` that sets
`status: 'completed'` returns 400 with the message "Completion happens
when the appointment's invoice is closed. POST `/api/invoices/<id>/close/`."

`Invoice.close()` is the only code path that writes
`Appointment.status = COMPLETED`. It does so inside the same transaction
as the invoice update — they succeed together or fail together.

### Reopen window

- 60 calendar days from `closed_at`. `closed_at` is set on the *first*
  close and never updated; re-closes after a reopen don't extend the
  window. This is the user's explicit requirement.
- On reopen, the linked appointment is transitioned back to `CHECKED_IN`.
  We don't try to restore the appointment's pre-close status (it was
  always going through `CHECKED_IN → COMPLETED` to get here, so reverting
  to `CHECKED_IN` is the natural state for "service delivered, payment
  pending again").
- `reopen_count` increments on each reopen for SOC 2 traceability.

### Concurrency

- `close()` and `reopen()` both wrap their work in `transaction.atomic()`
  and acquire `SELECT FOR UPDATE` on the invoice row before re-checking
  invariants. Two parallel close requests serialize cleanly: one wins, the
  other sees status=PAID and raises a 409 Conflict.
- The linked appointment is also locked (`select_for_update` on the
  appointment row) so its status update is serialized against any
  concurrent appointment-side mutation.

### Audit trail (SOC 2 mapping)

Every state-changing operation writes an `AuditLog` entry via
`apps.audit.services.record(...)`:

| Operation | Action | resource_type | metadata |
|---|---|---|---|
| Auto-create on appointment booking | `create` | `invoice` | `{appointment_id, total_cents, source: 'appointment_signal'}` |
| Close (take payment) | `update` | `invoice` | `{transition: 'open→paid', total_cents, payment_method, payment_reference}` |
| Reopen | `update` | `invoice` | `{transition: 'paid→open', reopen_count, days_since_closed_at}` |
| Void | `update` | `invoice` | `{transition: 'open→void', reason}` |
| Read invoice or list | `read` | `invoice` / `invoice_list` | `{invoice_id, count}` |

Combined with `AuditLog`'s append-only enforcement (ADR 0004), this gives
us tamper-evident financial event history.

### Permissions

| Action | Permission | Default roles |
|---|---|---|
| List/read invoices | none beyond authenticated tenant member | all roles |
| Close invoice (take payment) | `PROCESS_PAYMENT` | owner, manager, front_desk |
| Void invoice | `VOID_INVOICE` | owner, manager (manager via role default — already in catalog) |
| Reopen invoice | `REOPEN_INVOICE` (NEW) | owner, manager |

`REOPEN_INVOICE` is added to `LOCKED_PERMISSIONS` so it cannot be granted
to a non-manager via per-user `extra_permissions`. This enforces
separation-of-duties at the permission layer (front-desk staff can take
payment but cannot reopen a closed sale to refund or re-bill).

### Backfill

Existing appointments in dev/seed databases need invoices to exist for the
gate to be coherent. A data migration creates one invoice per appointment:

- For appointments in `completed` status: invoice is `PAID` with
  `closed_at = appointment.completed_at` and `closed_by = NULL` (the
  pre-existing data has no actor; we intentionally leave it null with a
  metadata note rather than backfill a fake user).
- For all others: invoice is `OPEN`.
- The migration writes a single `AuditLog` entry per invoice with
  `metadata = {source: 'backfill_migration_0001'}` for traceability.

## Alternatives considered

### A. Just block `status=completed` at the API; defer all invoicing to Phase 1E.

Rejected. The gate without the gated thing means nobody can complete any
appointment until Phase 1E lands. It also doesn't give us the audit
coverage SOC 2 needs.

### B. Make the invoice a leaf attribute on Appointment (`paid_at`, `total_cents`).

Rejected. The user's "not all invoices are appointments" clarification
rules this out — invoices need to outlive a single appointment for
standalone POS, packages, gift cards. Doing it as a flat field now would
require an expensive refactor when those features land.

### C. Build the full Phase 1E (multi-line invoices with discounts, tip,
   per-tenant numbering, PDF, real payment processor) right now.

Rejected for scope. We get the gate and the audit trail with the minimum
shape; the richer features land incrementally on the same model.

### D. Allow reopen with no time limit, just permission-gated.

Rejected. SOC 2 wants "change management" controls — reopening a paid
invoice 18 months later is materially different from fixing a same-week
mistake. The 60-day window is the user's call and is enforceable in code,
auditable in the metadata, and adjustable in one constant.

## Consequences

### Pros

- Single auditable source of truth for "service was paid for".
- The gate is structural (DB + API) not a UI-layer reminder, so no
  back-channel can quietly skip it.
- Standalone invoices land naturally when Phase 2A POS arrives — same
  model, same `close()` flow, just no `appointment` FK.
- Reopen window is one constant; tightening to 30 days is a one-line PR.
- SOC 2: full who-when-what-why trail on every financial state change,
  separation of duties via locked permissions, time-bounded reopens.

### Cons

- Adds an app, a couple of models, and a backfill migration. Real cost.
- The auto-creation signal couples appointment creation to invoice
  creation. If invoice creation fails (e.g., schema bug), the appointment
  fails too. Mitigation: the signal is wrapped in `transaction.atomic()`
  and unit-tested explicitly.
- "Take payment" UI in the calendar popover now does real work and needs
  proper error handling (permission, 60-day, idempotency under double-tap).

## References

- [apps.invoices README](../../backend/apps/invoices/README.md) — module overview
- [ADR 0003 — Permission model](./0003-permission-model.md) — how
  `REOPEN_INVOICE` slots into the role catalog
- [ADR 0004 — Audit logging](./0004-audit-logging.md) — `AuditLog` shape
  used by every invoice mutation
- SOC 2 Trust Services Criteria — CC6.1 (logical access), CC7.2 (system
  monitoring), CC7.3 (change management), PI1.1 (data integrity)
