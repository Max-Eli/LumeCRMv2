# `apps.invoices`

Tenant-scoped billing records. Every appointment creates an invoice;
standalone invoices (POS, packages, gift cards — Phase 2A) reuse the same
model with `appointment` left null.

## Why this app exists

The user's rule, codified in [ADR 0007](../../../docs/decisions/0007-invoicing-and-completion-gate.md):

> An appointment can only be marked **completed** by **closing its invoice**
> (taking payment). Owners and managers may **reopen** a paid invoice within
> **60 days** of its first close.

The app exists to make that rule structural rather than aspirational:

- the only code path that writes `Appointment.status = COMPLETED` is
  `Invoice.close()`;
- the API rejects any direct `PATCH status=completed` on appointments with
  a clear error pointing the caller at the close action;
- reopens are permission-gated (`REOPEN_INVOICE`, owner+manager only,
  locked against per-user override) and time-gated (≤ 60 days from
  `closed_at`).

## Models

- `Invoice` (`TenantedModel`)
  - FKs: `customer` (PROTECT), `appointment` (`OneToOneField`, nullable
    PROTECT).
  - State: `OPEN | PAID | VOID`.
  - Money in cents (`subtotal_cents`, `tax_cents`, `total_cents`).
    Denormalized but recomputed from line items on save; constrained
    `total = subtotal + tax` at the DB level.
  - Audit fields: `created_by`, `closed_at`, `closed_by`, `reopened_at`,
    `reopened_by`, `reopen_count`, `voided_at`, `voided_by`, `void_reason`.
- `InvoiceLineItem`
  - FKs: `invoice` (CASCADE), `service` (PROTECT, nullable for non-service
    items in future).
  - Snapshots `description`, `unit_price_cents`, `tax_rate_percent` at
    line-creation time so future service-price changes never alter
    historical invoices.

## Lifecycle

```
appointment booked
        │  (post_save signal)
        ▼
   Invoice OPEN  ──── close() ─────► Invoice PAID
        │                                │
        │                                │ reopen()  (≤ 60d, owner/manager)
        │                                ▼
        │                          Invoice OPEN
        │
        └─── void() ─────► Invoice VOID  (terminal)
```

`Invoice.close()` and `Invoice.reopen()` both:

- run inside `transaction.atomic()`,
- acquire `select_for_update()` on the invoice row before re-checking
  invariants (so racing close requests serialize cleanly),
- write a structured `AuditLog` entry via `apps.audit.services.record(...)`,
- on close: lock the linked appointment, set
  `Appointment.status = COMPLETED`, set `completed_at`,
- on reopen: lock the linked appointment, set
  `Appointment.status = CHECKED_IN`, clear `completed_at`.

## Permissions

| Action | Permission | Default roles | Locked* |
|---|---|---|---|
| read / list | (authenticated tenant member) | all roles | n/a |
| close | `PROCESS_PAYMENT` | owner, manager, front_desk | no |
| void | `VOID_INVOICE` | owner, manager | no |
| reopen | `REOPEN_INVOICE` | owner, manager | **yes** |

*Locked = cannot be granted to a non-default role via per-user
`extra_permissions` (separation of duties; see
[ADR 0003](../../../docs/decisions/0003-permission-model.md)).

## API

```
GET    /api/invoices/                  list (filters: ?customer=, ?status=, ?appointment=)
GET    /api/invoices/{id}/             retrieve
POST   /api/invoices/{id}/close/       close (take payment) — body: {payment_method, payment_reference, notes}
POST   /api/invoices/{id}/reopen/      reopen — owner/manager only, ≤ 60 days from closed_at — body: {reason}
POST   /api/invoices/{id}/void/        void (cancel without payment) — body: {reason}
```

All mutations are audit-logged (`apps.audit.services.record`).

## Tests

`tests.py` covers:

- the post-save signal creates one invoice per appointment with the
  correct line item snapshot,
- closing transitions the appointment to `COMPLETED` atomically; both
  rows roll back if either side fails,
- direct `PATCH status=completed` on appointment is rejected with the
  guidance message,
- reopen requires `REOPEN_INVOICE` and is rejected outside the 60-day
  window (computed from `closed_at`, the first close — re-closes don't
  extend it),
- tenant isolation on list/retrieve — a user in tenant A cannot see
  invoices from tenant B,
- close is idempotent under racing requests (the second one sees status
  PAID and returns 409 with a clear error).

## Future

- Multi-line invoices with discounts, tip lines, accommodating retail
  items (Phase 2A POS).
- Per-tenant invoice numbering sequence (Phase 1E).
- PDF generation (Phase 1E).
- Real payment processor integration — `payment_method` enum gains
  `card_processed` (Phase 2A).
