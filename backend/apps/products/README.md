# apps.products

Retail product catalog. What each tenant sells over the counter:
skincare, supplements, gift cards, intake fees. Distinct from
`services.Service` (bookable on the calendar) and from
`Package` / `Membership` (which bundle services).

## What's in here

- **[models.py](models.py)** — `Product` + `ProductCategory`.
  Pricing in cents (matches Service); tax rate per-product;
  inventory tracked as a single signed integer (so backorders show
  as negative rather than clamping to zero); `track_inventory=False`
  is the escape hatch for items where stock count is meaningless
  (gift cards, digital fees).
- **[serializers.py](serializers.py)** — `ProductSerializer`,
  `ProductCategorySerializer`, `StockAdjustmentInputSerializer`.
  Uniqueness pre-validated at serializer level so duplicate-name
  categories return 400 not 500.
- **[permissions.py](permissions.py)** — `ProductPermission`. Read
  open to any authenticated tenant member; write + stock-adjust
  require `MANAGE_SERVICES` (Owner / Manager).
- **[views.py](views.py)** — `ProductViewSet` (full CRUD +
  `adjust-stock` action) + `ProductCategoryViewSet`. List supports
  `?q=`, `?category=`, `?active=`, `?low_stock=`. Audit logging
  on every mutation; aggregate `product_list` audit on list calls.
- **[urls.py](urls.py)** — `/api/products/` + `/api/product-categories/`.
- **[tests.py](tests.py)** — 29 tests: model SKU auto-gen +
  collision-retry, low-stock helper edges (track-off / threshold-0 /
  at/below threshold), permission gating (anon / front-desk / owner),
  CRUD, tenant isolation, search + filter (`q` matches name+sku,
  category filter, active filter, low-stock filter), stock
  adjustment (positive / negative / zero rejected / note required /
  audit-log-shape / front-desk forbidden), CRUD audit log shape,
  category uniqueness.

## Mental model

```
ProductCategory (tenant-scoped)         e.g. Skincare, Supplements
  ├── color                             chip color on the catalog list
  └── sort_order

Product (tenant-scoped, tax-snapshotted at sale time)
  ├── identity:    name, sku (auto-gen), description, category
  ├── pricing:     price_cents, cost_cents, tax_rate_percent
  ├── inventory:   track_inventory, stock_quantity, low_stock_threshold
  ├── lifecycle:   is_active, sort_order
  └── timestamps:  created_at, updated_at
```

## Compliance posture

### HIPAA

Products are not PHI. The catalog itself is non-clinical business
config — no patient identifiers, no clinical data. The link to a
specific customer happens at invoice-line time, and that surface is
already governed by the invoice app's per-row audit logging (every
invoice action records the customer + line breakdown).

Two operational notes:

- **Sale-time audit lives on the invoice, not here.** When a
  customer buys a Product, the audit row is on the Invoice +
  InvoiceLineItem, not Product. This module's audit log is
  configuration-only: who edited the catalog, who adjusted stock.
- **Stock adjustments require an operator note.** The
  `/products/<id>/adjust-stock/` endpoint refuses requests without
  a note string, and the note is persisted to AuditLog metadata
  alongside before/after counts. So "why did this SKU drop by 12
  in October?" is always answerable from the audit trail.

### SOC 2

- **Processing integrity (PI1.1).** `price_cents`, `tax_rate_percent`,
  and the product description are snapshotted onto the invoice line
  at sale time (handled by the invoice integration, not here).
  Subsequent catalog edits cannot alter historical financial
  records — same pattern as `services.Service`.
- **Separation of duties.** Front-desk staff can read the catalog
  (needed at point-of-sale) but cannot edit it. Manager + Owner
  edit the catalog and adjust stock. This matches the existing
  `MANAGE_SERVICES` permission boundary.
- **Audit trail on stock adjustments.** Manual deltas record
  delta + before + after + operator note + actor — the exact
  inputs an auditor needs to reconstruct any single inventory
  change.

## Building on this

When wiring product line-items into invoices (next session):

1. Add `product` FK to `InvoiceLineItem` (nullable, alongside the
   existing nullable `service` FK; one of the two should be set).
2. Snapshot `description`, `unit_price_cents`, `tax_rate_percent`
   from the Product onto the line. Don't re-derive at totals time.
3. On invoice CLOSE, decrement `stock_quantity` for every line
   whose `product.track_inventory=True`. Use `select_for_update`
   on the Product row so concurrent invoices serialize.
4. On invoice REOPEN/VOID, reverse the decrement (restock).
5. New POST `/api/invoices/<id>/add-line/` endpoint — takes
   either `service_id` or `product_id` plus an optional quantity
   override; creates the line on an OPEN invoice. Audit-logged.

When tracking real inventory operations beyond a single counter:

- Lot numbers + expiration dates → out of scope for v1. Track in
  spreadsheet or use a real PMS (e.g. Boulevard, Mindbody) until
  a tenant explicitly asks for it. Adding it later is a
  ProductLot model with its own migration; the current Product
  surface stays unchanged.
- Multi-location stock split → currently the `stock_quantity`
  is per-tenant, not per-location. Multi-location spas with
  separate inventory pools should wait for Phase 4E session 5
  (location-aware models).
