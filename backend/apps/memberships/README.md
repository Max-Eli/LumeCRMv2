# apps.memberships

Recurring-membership catalog + per-customer subscriptions + the
ledger of redemptions.

A `MembershipPlan` is a tenant-wide catalog template ("Glow Club:
$99/month, 1 facial included"). A `Subscription` is the
customer-facing instance — created when Jane buys the plan on an
invoice, drawn down per visit, renewed by selling a fresh
subscription each cycle.

This app ships in three sessions:

  - **Step 1 (current)** — catalog CRUD: `MembershipPlan`,
    `MembershipPlanItem`, the read-only Subscription endpoints, and
    the cancel action.
  - **Step 2** — sale + redemption: hook `add-line` on the invoice
    surface to accept `membership_plan_id`; new
    `redeem-from-membership` action; PENDING→ACTIVE flip on
    invoice close; cascade-cancel on void.
  - **Step 3** — frontend: catalog list/edit, customer profile
    Memberships tab with current-period balance, redemption UI on
    the invoice page.

## What's in here

- **[models.py](models.py)** — five models. Catalog: `MembershipPlan`
  + `MembershipPlanItem`. Customer-facing: `Subscription` +
  `SubscriptionItem` (per-period balance) + `SubscriptionRedemption`
  (append-only ledger).
- **[serializers.py](serializers.py)** — `MembershipPlanSerializer`
  reads + writes the catalog including nested `items_input` (with
  wholesale-replace on update). `SubscriptionSerializer` is read-
  only; `CancelSubscriptionInputSerializer` for the cancel action.
- **[permissions.py](permissions.py)** — split into
  `MembershipPlanPermission` (catalog: read open / write requires
  `MANAGE_PACKAGES_MEMBERSHIPS`) and `SubscriptionPermission`
  (per-customer: read open / cancel requires
  `MANAGE_PACKAGES_MEMBERSHIPS`).
- **[views.py](views.py)** — `MembershipPlanViewSet` (full CRUD,
  delete-with-subs blocked) + `SubscriptionViewSet` (read-only +
  cancel action).
- **[urls.py](urls.py)** — `/api/membership-plans/` +
  `/api/subscriptions/`.
- **[tests.py](tests.py)** — 30 tests. Model SKU auto-gen +
  collision retry, billing-interval defaults, item quantity-
  positive constraint, item per-service uniqueness, permission
  gating (anon / front-desk / owner), CRUD with nested items
  (duplicate-service rejection, cross-tenant rejection, items-
  wholesale-replace on update), filter (active, q), audit log
  shape, Subscription read endpoints (filter by customer + status),
  cancel action (reason required, already-cancelled 409,
  front-desk forbidden, audit log shape).

## Mental model

```
MembershipPlan (catalog template, tenant-scoped)
  ├── identity:    name, sku, description
  ├── pricing:     price_cents (per cycle), tax_rate_percent
  ├── billing:     billing_interval (monthly | annual)
  ├── discounting: member_discount_percent (NOT auto-applied in v1)
  ├── lifecycle:   is_active, sort_order
  └── items: 1:N → MembershipPlanItem
       └── (service, quantity_per_cycle)

──────────── sale happens ────────────

Subscription (per-customer, ONE billing cycle)
  ├── customer (FK), plan (FK)
  ├── source_invoice_line (1:1 to InvoiceLineItem)
  ├── snapshots:   name, description, price_cents,
  │                billing_interval, member_discount_percent
  ├── timestamps:  started_at, current_period_starts_at,
  │                current_period_ends_at
  ├── status:      pending → active → expired | cancelled
  ├── auto_renew:  forward-compat for Phase 2A processor
  └── items: 1:N → SubscriptionItem
       └── (service snapshot, quantity_per_cycle, quantity_remaining,
            unit_value_cents)

SubscriptionRedemption (append-only ledger)
  ├── subscription, item, quantity (signed)
  ├── invoice_line (the $0 line on the redemption invoice)
  └── appointment, by_user, redeemed_at, note
```

## Why no auto-recurring billing in v1

Auto-charge requires a payment processor + cron. The processor
selection is Phase 2A territory. v1 ships "manual billing":

1. Operator generates next month's invoice when the customer
   shows up (or proactively, before the period ends).
2. Customer pays externally (cash / check / external card).
3. Closing that invoice creates a NEW Subscription for the next
   cycle. The expiring subscription transitions to EXPIRED via
   a future cron (out of scope for step 1; can be a manual
   marker until the cron lands).

The `auto_renew` flag exists on the model so the Phase 2A cron
has a target — when a processor is wired, set it to True on
existing subscriptions and the renewal cron will pick them up.
No data migration needed.

## Why each cycle is a separate Subscription

Two design options were considered:

  (a) One Subscription that gets reset each cycle (mutating).
  (b) New Subscription per cycle (history preserved).

(b) is what we shipped. The `SubscriptionRedemption` ledger plus a
chronological sweep of `Subscription.objects.filter(customer=jane)`
gives operations a clean audit story: every cycle's credits and
redemptions are addressable. (a) would have to introduce a
`SubscriptionCycle` parent table to preserve cycle-level history,
adding another model for marginal benefit.

The downside is "membership age" (how long has Jane been a member?)
isn't a single column. Solve via aggregation when we need it; if
tenants ask for "5-year member" perks, add a parent `Membership`
table grouping subscriptions later.

## Compliance posture

### HIPAA

Membership rows are private but financial, not clinical. Tenant
scoping via `TenantedModel.for_current_tenant()`. Audit logging on
every state change.

### SOC 2

- **Sale-time snapshot (PI1.1).** Every Subscription carries its
  own copy of `name`, `description`, `price_cents`,
  `billing_interval`, `member_discount_percent` plus per-item
  `service_name`, `quantity_per_cycle`, `unit_value_cents`.
  Subsequent edits to the catalog plan do NOT alter Jane's
  record.
- **Append-only ledger (CC7.2).** `SubscriptionRedemption` is
  never edited. Reversing a redemption creates a new row with
  negative quantity.
- **Separation of duties.** Catalog edits and cancel both require
  `MANAGE_PACKAGES_MEMBERSHIPS` (Owner / Manager). Sale +
  redemption flow through invoice action endpoints gated by
  `PROCESS_PAYMENT` (front-desk allowed). A front-desk operator
  can sell + redeem memberships, but not reshape the catalog or
  cancel mid-flight.

## Building on this

Step 2 (sale + redemption) wiring:

1. Add `membership_plan` FK to `InvoiceLineItem` and extend the
   "at most one source" mutual-exclusion constraint.
2. Extend `AddLineInputSerializer` to accept `membership_plan_id`.
3. In the `add-line` view, branch on `membership_plan_id`:
   snapshot the plan into a `Subscription` + per-service
   `SubscriptionItem` rows; status starts PENDING.
4. In `Invoice.close()`, find every line whose linked
   Subscription is PENDING; flip to ACTIVE, set `started_at`,
   `current_period_starts_at = now`, `current_period_ends_at =
   now + cycle_days`.
5. New action `POST /api/invoices/<id>/redeem-from-membership/`
   — same shape as `redeem-from-package`. Validates ACTIVE +
   in-period + service-in-plan + balance-remaining. Atomic
   decrement + $0 line + ledger row.
6. On `Invoice.reopen()`: refuse if any Subscription on the
   invoice has been redeemed against (same rule as packages).
7. On `Invoice.void()`: cascade-cancel any PENDING Subscriptions
   on the invoice (`status=CANCELLED`, `cancel_reason='invoice_voided'`).
