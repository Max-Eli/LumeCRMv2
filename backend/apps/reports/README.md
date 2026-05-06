# apps.reports

Categorized aggregations over the existing OLTP tables. No models of
its own — reports are thin views that compose aggregate queries
across `apps.invoices`, `apps.appointments`, `apps.customers`, and
`apps.tenants`. Every report run writes an `AuditLog` entry per ADR
0013 (SOC 2 CC 6.1, HIPAA §164.312(b)).

The user's bar for Phase 1G shipping is "all reports on everything
possible" — this README lives in lockstep with the ADR's session
plan. Session 1 (this slice) lands the architecture + one report per
category as the proof. Sessions 2 + 3 fill out the catalog.

## What's in here

- **[base.py](base.py)** — `BaseReportView`. Subclasses set
  `report_id`, `category`, `permission`, `title`, `description`,
  `phi_tier` and implement `run(request, **params)`. Base handles
  parameter parsing (`parse_date_range` default), permission gating
  via `ReportPermission`, response envelope, and the audit-log
  write on every successful call.
- **[permissions.py](permissions.py)** — `ReportPermission` reads
  the `permission` attribute off the view class and gates against
  the membership. `ReportCatalogPermission` lets any authenticated
  member ask "what can I run?"; the response is filtered server-
  side by what the user actually has access to.
- **[catalog.py](catalog.py)** — `ReportCatalogView` and the
  `REPORT_CATALOG` data structure. Single source of truth for which
  reports exist + which category they belong to. When adding a new
  report: append to `REPORT_CATALOG`, register the URL, and the
  frontend library auto-renders the new card on next load.
- **[views/](views/)** — concrete report classes, one per file by
  category:
  - **[views/financial.py](views/financial.py)** —
    `SalesByDateRangeReport`, `DailyCloseOutReport`,
    `ARAgingReport`, `RevenueByServiceReport`,
    `RevenueByLocationReport`, `TaxCollectedReport` (6 reports).
  - **[views/staff.py](views/staff.py)** —
    `RevenueByProviderReport`, `ScheduleUtilizationReport`,
    `NoShowRateByProviderReport`, `NewClientsByProviderReport`,
    `RepeatRateByProviderReport` (5 reports).
  - **[views/guests.py](views/guests.py)** —
    `NewVsReturningReport`, `TopSpendersReport`,
    `InactiveClientsReport`, `BirthdayListReport`,
    `VisitFrequencyReport`, `FormsOutstandingReport` (6 reports).
  - **[views/operations.py](views/operations.py)** —
    `AppointmentsByStatusReport`, `NoShowRateReport`,
    `CancellationRateReport`, `BookingLeadTimeReport`,
    `ServiceMixReport`, `BusiestHoursReport` (6 reports).
- **[urls.py](urls.py)** — one path per report under
  `/api/reports/<category>/<slug>/`, plus the catalog at
  `/api/reports/`.
- **[tests.py](tests.py)** — 54 tests covering envelope shape,
  date-range parsing, aggregation correctness, payment-method
  breakdown, classification rules, catalog filtering by role,
  per-report permission gating, tenant isolation, audit-log
  shape (with the no-PHI-in-metadata regression guard), plus
  Session 2 per-endpoint smoke (200 + envelope + audit on all
  18 new reports), input validation on the non-date params
  (top-spenders limit, inactive-days threshold, birthday window),
  tenant isolation on the per-customer-PHI reports, plus Session
  3 CSV exports (per-tier downloads, PHI confirmation gate with
  `phi_confirmation_required` code, EXPORT audit entry shape, no-
  duplicate-READ guard, daily close-out custom columns, filename
  includes date range, category permission still gates).

See:

- [ADR 0013 — Reports module](../../../docs/decisions/0013-reports-module.md)
  for the architectural rationale (one APIView per report, OLTP
  not warehouse, category-level permissions, PHI tiers).
- [ADR 0003 — Permission model](../../../docs/decisions/0003-permission-model.md)
  for the permission catalog this module gates against.
- [ADR 0004 — Audit logging](../../../docs/decisions/0004-audit-logging.md)
  for the audit log shape every report runs through.

## Mental model

```
GET /api/reports/                         → ReportCatalogView
                                            (returns categories + reports
                                             the current user can run)

GET /api/reports/<category>/<slug>/       → BaseReportView subclass
   ?date_from=YYYY-MM-DD                    1. ReportPermission gates by
   ?date_to=YYYY-MM-DD                         membership.has(view.permission)
                                            2. parse_date_range (or override)
                                            3. run(...) → {summary, rows}
                                            4. Audit log: action=READ,
                                               metadata={category, params, row_count}
                                            5. Response envelope:
                                               {report_id, params, summary, rows}
```

Categories (5 total; permissions already in `apps.tenants.permissions.P`):

| Category | Permission | Default roles |
|---|---|---|
| Financial | `VIEW_FINANCIAL_REPORTS` | owner, manager, bookkeeper |
| Staff | `VIEW_STAFF_REPORTS` | owner, manager, bookkeeper |
| Guests | `VIEW_GUEST_REPORTS` | owner, manager, marketing |
| Operations | `VIEW_OPERATIONS_REPORTS` | owner, manager, front_desk |
| Marketing | `VIEW_MARKETING_REPORTS` | owner, manager, marketing |

PHI tiers (drives the Session 3 export-confirmation modal):

| Tier | Examples |
|---|---|
| `none` | Sales by day (no customer column), appointments by status |
| `aggregated` | Revenue by provider — names staff but not customers |
| `per_customer` | New vs returning, top spenders, AR aging — names individual customers |

## HIPAA + SOC 2 considerations

This module is the canonical example of **reports + PHI** thinking
on the product surface. Reports concentrate PHI in a way individual
record reads don't — anything new here goes through the same review.

### What's covered today (Session 1)

- **Tenant isolation.** Every report calls
  `Model.objects.for_current_tenant()`. No raw SQL; no manual
  tenant_id filters that could be forgotten. Three `TenantIsolationTests`
  prove tenant A's reports never include tenant B's data even when
  the same person owns both.
- **Audit logging on every read.** `BaseReportView._audit()` writes
  `AuditLog(action=READ, resource_type='report', resource_id=<id>,
  metadata={category, params, row_count})`. SOC 2 CC 6.1 + HIPAA
  §164.312(b). Failed runs (permission-denied) deliberately do
  NOT write — the test `test_failed_run_does_not_write_audit_entry`
  is the regression guard.
- **No PHI in audit metadata.** Even for the `per_customer` tier,
  the metadata records only `category`, `params`, and `row_count` —
  never customer names, emails, or IDs. `test_audit_metadata_contains_no_phi`
  pins the metadata key set so a future change that smuggles PHI
  into the audit log breaks loudly.
- **Category-level permissions.** Five gates, not 50+. Per-report
  permissions multiply role catalog complexity without buying
  isolation that matches how operators reason about access.
- **Response envelope is uniform.** `{report_id, params, summary,
  rows}` — frontend can render any report without a per-report
  schema. Easier to audit (one shape to grep for) and easier to
  add CSV export later (Session 3 — same envelope serializes).
- **PHI-tier metadata in the catalog.** Each report self-describes
  its PHI sensitivity (`phi_tier`); the frontend uses this to
  show "Contains PHI" badges and (Session 3) to gate CSV downloads
  behind a confirmation modal.
- **Date-range bounds.** `MAX_DATE_RANGE_DAYS = 366` caps how far
  back a single query can reach. Stops a runaway "give me all
  history" call from drowning Postgres.

### What's covered today (Session 3)

- **Server-rendered streaming CSV** on every endpoint via
  `?download=csv` (NOT `?format=csv` — DRF reserves `format`).
  `BaseReportView._export_csv()` uses `StreamingHttpResponse` so
  large exports don't load into memory. Override `csv_rows()` +
  `csv_columns()` to flatten nested data; daily close-out does
  this to expand `by_method` into one column per payment method.
- **PHI confirmation gate** — `per_customer` reports require
  `?phi_confirmed=true` or return 403 with
  `{code: 'phi_confirmation_required', phi_tier: 'per_customer'}`
  so the frontend can detect the specific gate. Truthy values
  accepted: `true`, `1`, `yes`, `on` (case-insensitive).
- **EXPORT audit entries** — `action=EXPORT` (vs. READ for on-
  screen views) with metadata `{category, params, row_count,
  phi_tier, phi_confirmed}`. The `phi_confirmed` flag is the SOC 2
  attestation evidence — answers "did the operator click through"
  without re-deriving from the URL.

### What's deferred (Phase 0c production lift)

- **Per-tenant timezone for date bucketing.** Today
  `closed_at__date` is interpreted in the connection's TZ (UTC).
  At our `MAX_DATE_RANGE_DAYS=366` ceiling, UTC-vs-local drift only
  touches the two boundary days. Per-tenant TZ bucketing lights up
  when the first non-US/Eastern tenant lands.
- **Materialized views** for any report that exceeds 2s at p95 in
  production. Refreshed nightly via Celery beat (Phase 1F). Add
  per-tenant views if a single tenant dominates.
- **Read replica** if report load contends with OLTP write load.
  PgBouncer routing decides per-query.
- **Saved report views** (Session 4) — a small `SavedReport` model
  per tenant + per user storing the report ID + frozen params.
- **Scheduled email delivery** — depends on Celery beat (Phase 1F)
  and email infrastructure (ADR 0012).
- **Drill-down navigation** between related reports (e.g. provider
  card → that provider's appointments).
- **Per-report PHI export gate** (`EXPORT_PHI_REPORT`) if the
  category-gate granularity proves too coarse in practice.

## Building on this

When adding a new report:

1. Write the view class in the appropriate `views/<category>.py`,
   subclassing `BaseReportView`. Set the metadata attributes,
   implement `run(request, **params)`. Return `{summary, rows}`.
2. Re-export from `views/__init__.py`.
3. Add a path to `urls.py`.
4. Add the `(view_class, url_path)` tuple to the right category in
   `catalog.REPORT_CATALOG`.
5. Add tests. The conventions in `tests.py` are: aggregation
   correctness with seed data, tenant isolation, permission gating,
   and an audit-log entry assertion. PHI reports get the
   no-PHI-in-metadata regression guard.
6. Add the matching frontend page under
   `frontend/src/app/(app)/reports/<category>/<slug>/page.tsx`,
   wire the typed hook into `frontend/src/lib/reports.ts`, and
   register the URL in `REPORT_HREF` on the library page.

The catalog endpoint will auto-include the new report for every
user with the right permission. No frontend list to update.
