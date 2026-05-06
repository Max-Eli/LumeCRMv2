# apps.packages

Service-bundle catalog + per-customer purchased instances + the
ledger of redemptions.

A `Package` is what the catalog describes ("5 facials for $300").
A `PurchasedPackage` is what Jane bought (created when she paid the
invoice that contained the package line). A `PackageRedemption` is
the ledger row written each time a credit is drawn down — append-
only, signed quantity for reversals.

This app ships in three sessions:

  - **Step 1 (current)** — catalog CRUD: `Package`, `PackageItem`,
    permission-gated viewset, nested-items input, audit log.
  - **Step 2** — sale + redemption: hook `add-line` on the invoice
    surface to accept `package_id`; new `redeem-from-package`
    action; PENDING→ACTIVE flip on invoice close; restock-on-reopen.
  - **Step 3** — frontend: catalog list/edit, customer profile
    "Packages" tab with balance display, redemption UI on the
    invoice page.

## What's in here

- **[models.py](models.py)** — five models. The catalog side is
  `Package` + `PackageItem`. The customer side is `PurchasedPackage`
  + `PurchasedPackageItem` (the per-instance balance) +
  `PackageRedemption` (append-only ledger).
- **[serializers.py](serializers.py)** — `PackageSerializer` reads
  + writes the catalog including nested `items_input`. Computes
  `a_la_carte_total_cents` and `implicit_discount_cents` for the
  display layer.
- **[permissions.py](permissions.py)** — read open to any member;
  write requires `MANAGE_PACKAGES_MEMBERSHIPS` (Owner / Manager).
- **[views.py](views.py)** — `PackageViewSet`. Refuses to delete
  a package that has any `PurchasedPackage` referencing it.
- **[urls.py](urls.py)** — `/api/packages/`.
- **[tests.py](tests.py)** — 22 tests. Model SKU auto-gen +
  collision retry, item quantity-positive constraint, item
  uniqueness, permission gating (anon / front-desk / owner),
  CRUD with nested items (including duplicate-service rejection
  and cross-tenant-service rejection), update-replaces-items-
  wholesale, update-without-items-keeps-existing, search +
  active filter, audit log shape.

## Mental model

```
Package (catalog template, tenant-scoped)
  ├── identity:    name, sku, description
  ├── pricing:     price_cents (all-in), tax_rate_percent
  ├── validity:    validity_days (null = no expiration)
  ├── lifecycle:   is_active, sort_order
  └── items: M2M → Service via PackageItem
       └── PackageItem (service, quantity)

──────────── purchase happens ────────────

PurchasedPackage (per-customer instance, tenant-scoped)
  ├── customer (FK), source_template (FK Package, NULL for custom)
  ├── source_invoice_line (1:1 to InvoiceLineItem)
  ├── snapshots:   name, description, price_cents, validity_days
  ├── timestamps:  purchased_at (set when invoice closes), expires_at
  ├── status:      pending → active → voided
  └── items: 1:N → PurchasedPackageItem
       └── PurchasedPackageItem (service snapshot,
                                  quantity_purchased, quantity_remaining,
                                  unit_value_cents)

PackageRedemption (append-only ledger)
  ├── purchased_package, item, quantity (signed)
  ├── invoice_line (the $0 line on the appointment's invoice)
  └── appointment, by_user, redeemed_at, note
```

## Compliance posture

### HIPAA

Packages are not PHI — purchase records are private but financial,
not clinical. The link to a customer goes through
`PurchasedPackage.customer`, which is tenant-scoped via
`TenantedModel`. Audit logging on every state-changing endpoint;
`PackageRedemption` is append-only so the ledger is immutable.

### SOC 2 (PI1.1)

- **Snapshot at sale time.** When Jane buys "5 facials," the
  PurchasedPackage carries its own copy of `name`, `description`,
  `price_cents`, `validity_days` plus per-item
  `quantity_purchased` and `unit_value_cents`. Subsequent edits
  to the catalog Package do NOT alter Jane's record.
- **Append-only ledger.** `PackageRedemption` is never edited.
  Reversing a redemption creates a new row with negative
  quantity. Net of all rows for an item must equal
  `(quantity_purchased − quantity_remaining)`.
- **Separation of duties.** Catalog edits require
  `MANAGE_PACKAGES_MEMBERSHIPS` (Owner / Manager). Sale +
  redemption (the day-to-day POS surface) flow through invoice
  endpoints gated by `PROCESS_PAYMENT` (front-desk allowed). A
  front-desk operator can sell and redeem packages, but not
  reshape the catalog.

## Building on this

Step 2 (sale + redemption) wiring:

1. Extend `AddLineInputSerializer` to accept `package_id`.
2. In the `add-line` view, branch on package_id: snapshot the
   package's items into a `PurchasedPackage` + per-service
   `PurchasedPackageItem` rows (`quantity_remaining =
   quantity_purchased`); status starts PENDING.
3. In `Invoice.close()`, walk every InvoiceLineItem with a
   `purchased_package` reverse-FK and flip its status PENDING→
   ACTIVE, set `purchased_at = now`, compute `expires_at` from
   `validity_days`.
4. New action `POST /api/invoices/<id>/redeem-from-package/` —
   takes `package_id` (PurchasedPackage id) + `service_id`. Locks
   the row, decrements `quantity_remaining`, creates a
   PackageRedemption row + a $0 InvoiceLineItem on the invoice.
   Same patterns as the existing add-line action.
5. On `Invoice.reopen()` of an invoice that contained a package
   sale: refuse if any redemptions have happened against the
   PurchasedPackage (would orphan the redemption ledger). Allow
   reopen if no redemptions yet — flip status ACTIVE→PENDING.
6. On `Invoice.void()` of a PENDING package sale: flip the
   PurchasedPackage to VOIDED.
