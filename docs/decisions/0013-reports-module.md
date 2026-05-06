# ADR 0013 — Reports module: categories, architecture, and PHI handling

## Status

Accepted (2026-05-03 — Phase 1G design; written at design time per the discipline)

## Context

The two waiting spas need operational visibility from day one: "did
I make money this week," "which provider is busiest," "who hasn't
booked in 90 days." This is the Phase 1G slot in PROJECT_PLAN.md
and the bar set by the user is explicit:

> we are not shipping until we can have all reports on everything
> possible

Industry baseline (Zenoti, Mindbody, Boulevard, Vagaro, Aesthetic
Record): 30–80 reports across 4–6 categories. The full catalog won't
land in one session — Session 1 establishes the architecture and
ships one proof report per category so the categorization pattern
is real, not theoretical. Sessions 2+ fill out the catalog.

Three architectural questions that need a defensible answer before
the first line of code:

1. **Where do report queries run?** Same OLTP Postgres? A read
   replica? A warehouse?
2. **One viewset for all reports, or one endpoint per report?**
3. **PHI in reports** — guest lists, top-spender lists, inactive-
   client lists all include name + contact + treatment context.
   How does the audit + permission story handle that?

### HIPAA + SOC 2 framing

Reports concentrate PHI in a way individual record reads don't:

- A "top spenders" report names 50 customers with their lifetime
  treatment value. That's a population-level view of PHI that
  HIPAA's minimum-necessary rule (§164.502(b)) cares about more
  than a single chart read.
- A "new vs returning by month" report names individual customers
  by ID + name. Same PHI exposure.
- An "AR aging" report names customers with unpaid balances.
  Combined with treatment context (the line items), it's PHI.
- CSV export amplifies this — a downloaded file leaves the
  application's audit boundary.

The baseline rule: **every report run is audit-logged**. SOC 2 CC
6.1 (logical access controls) wants "who pulled what when." HIPAA
§164.312(b) wants the same trail for PHI access. We log the report
ID, the user, the parameters, and the row count — enough to answer
"was this access authorized" without storing the actual rows in
the audit table.

Permissions split the catalog by category, not by report. Five
gates (one per category) is a tractable surface; per-report
permissions would multiply our role catalog by 50× and add no real
isolation since within a category the reports share a sensitivity
tier.

## Decision

**Build `apps.reports` as a thin aggregation layer over the
existing OLTP tables. Group reports into 5 categories — Financial,
Staff, Guests, Operations, Marketing — with one permission per
category. One DRF `APIView` per report (not a generic ViewSet),
mounted under `/api/reports/<category>/<report-id>/`. A catalog
endpoint at `/api/reports/` returns the list of reports the
current user can access, driving the frontend library page. Every
report run writes an `AuditLog` entry. CSV export ships in Session
3 with explicit PHI confirmation.**

### Categories + permissions

| Category | Permission | Default roles | Examples |
|---|---|---|---|
| Financial | `VIEW_FINANCIAL_REPORTS` (existing) | owner, manager, bookkeeper | Sales by date / service / payment method / location, AR aging, daily close-out, tax collected |
| Staff | `VIEW_STAFF_REPORTS` (new) | owner, manager | Revenue by provider, appointments per provider, utilization %, new clients per provider, no-show rate per provider |
| Guests | `VIEW_GUEST_REPORTS` (new) | owner, manager, marketing | New vs returning, top spenders (LTV), inactive clients, birthday list, visit frequency, forms outstanding |
| Operations | `VIEW_OPERATIONS_REPORTS` (new) | owner, manager, front_desk | Appointments by status, no-show rate, cancellation rate, busiest hours/days, service mix |
| Marketing | `VIEW_MARKETING_REPORTS` (existing) | owner, manager, marketing | Referral source performance, campaign ROI (Phase 3) |

Three new permissions: `VIEW_STAFF_REPORTS`, `VIEW_GUEST_REPORTS`,
`VIEW_OPERATIONS_REPORTS`. Two existing ones reused without
renaming: `VIEW_FINANCIAL_REPORTS` (already on bookkeeper) and
`VIEW_MARKETING_REPORTS` (already on marketing).

Why category-level not per-report: per-report would be 50+
permission strings the operator can't reason about; category-level
matches how operators actually think about who-sees-what ("front
desk should see operations, not financials").

### Query architecture: OLTP, no warehouse yet

All reports query the live Postgres tables via the ORM with
aggregate functions (`Sum`, `Count`, `Avg`) + `select_related`.

- **Scale today**: single-digit spas, low-thousands of appointments
  per spa per year. A "sales by date for the last 30 days" query
  hits at most a few hundred invoice rows. Postgres laughs.
- **When this stops working**: single tenant with >100k
  appointments AND a report that aggregates over the whole history
  (e.g. lifetime revenue per customer with 5 years of data).
  Materialized views land then, refreshed nightly.
- **Read replica**: deferred. With PgBouncer + connection pooling
  in Phase 0c, even a single RDS Postgres handles report load
  alongside OLTP at our scale. Read replica adds ops cost without
  buying anything until we're CPU-bound on the primary.
- **No warehouse (Snowflake / BigQuery / Redshift) ever for v1**.
  Adding a warehouse means a CDC pipeline, schema duplication, and
  a second compliance posture (BAA on the warehouse provider). Not
  worth it until we're selling to enterprise spas with a BI team.

This is the correct shape for the next 12–18 months. Re-evaluate
when a single tenant crosses 100k appointments OR a report
regularly exceeds 2 seconds.

### One APIView per report (not a generic ViewSet)

Each report is its own `APIView` subclass:

```python
class SalesByDateRangeReport(BaseReportView):
    report_id = 'financial.sales_by_date_range'
    category = 'financial'
    permission = P.VIEW_FINANCIAL_REPORTS
    title = 'Sales by date range'
    description = 'Daily gross / tax / net, with payment-method breakdown.'

    def run(self, *, date_from, date_to):
        # ORM aggregates → dict matching the response schema
        ...
```

Why not a generic `ReportViewSet` that dispatches on `report_id`:

- Each report has its own param shape, response shape, and
  permission. A dispatcher would re-implement DRF routing badly.
- drf-spectacular generates clean per-endpoint OpenAPI docs when
  each report is its own view.
- Per-report tests are clearer when each report has its own URL.

`BaseReportView` handles the shared concerns: parameter parsing
(`date_from`, `date_to` with sane defaults), permission gating
against `self.permission`, audit-log write on every successful run,
and the catalog metadata that the catalog endpoint uses. Each
concrete report just implements `run(...)`.

### Catalog endpoint

`GET /api/reports/` returns:

```json
{
  "categories": [
    {
      "id": "financial",
      "label": "Financial",
      "reports": [
        {"id": "financial.sales_by_date_range", "title": "Sales by date range", "description": "...", "url": "/api/reports/financial/sales-by-date-range/"}
      ]
    }
  ]
}
```

Frontend renders the library page from this — no hardcoded list.
When a new report ships, it auto-appears (gated by the user's
permissions; a category with zero accessible reports is omitted).
This is the same pattern Stripe Reports + Mindbody Reporting use.

### Audit logging shape

Every successful report run writes:

```python
record(
    action=AuditLog.Action.READ,
    resource_type='report',
    resource_id='financial.sales_by_date_range',  # the report_id
    request=request,
    metadata={
        'category': 'financial',
        'params': {'date_from': '2026-04-01', 'date_to': '2026-05-01'},
        'row_count': 30,
    },
)
```

CSV exports (Session 3) write `action=AuditLog.Action.EXPORT`
instead of `READ`, and include `'phi_confirmed': True` in
metadata when the report includes PHI columns and the user clicked
through the confirmation modal.

No PHI in audit metadata — same rule as form submissions. Customer
names, emails, treatment lists never appear in `AuditLog.metadata`,
even though the report response itself contains them. The trail
answers "was this report run" without itself becoming a PHI store.

### PHI handling in report responses

Reports fall into three PHI tiers:

| Tier | Examples | Treatment |
|---|---|---|
| **No PHI** | Sales by day (no customer column), appointments by status (counts only), service mix (counts) | Standard role gate, audit log on run |
| **Aggregated PHI** | Revenue by provider (employee names, not customer names), no-show rate per provider | Same as no PHI — staff identifiers aren't PHI in this context |
| **Per-customer PHI** | Top spenders, inactive clients, new vs returning (when expanded to customer-level), AR aging | Role gate + audit log + **CSV export requires confirmation modal + EXPORT audit entry** |

The per-customer-PHI tier is where the population-level concern
lives. v1 displays these reports in the UI without a barrier (the
operator is already inside the authenticated app, looking at one
spa's data); CSV export is what triggers the modal because the
download leaves the application's reach.

Refinement (Phase 0c-ish): per-customer PHI tier could require a
second permission gate (`EXPORT_PHI_REPORT` or similar) on top of
the category gate. Today the category gate is sufficient because
all roles with the category gate are already trusted with PHI in
that category.

### CSV export (Session 3)

Server-rendered, streamed. Single source of truth — never re-built
in the browser, otherwise rounding / formatting / column-order
drift between UI and export.

```python
# Common pattern Session 3 will land
class CSVReportMixin:
    def export_csv(self, request):
        rows = self.run(**self.parse_params(request))
        response = StreamingHttpResponse(
            self._stream_csv(rows),
            content_type='text/csv',
        )
        response['Content-Disposition'] = f'attachment; filename="{self.report_id}_{date.today()}.csv"'
        # Audit log: action=EXPORT, metadata includes row_count + phi_confirmed
        return response
```

Confirmation modal (frontend, Session 3): for per-customer-PHI
reports, "This export contains client names, contact info, and
treatment data. By downloading you confirm this access is
necessary for spa operations [Cancel] [Download]." The click is
the human attestation; the audit log records `phi_confirmed: True`.

### Session sequencing

- **Session 1 (this ADR + the first slice)**: architecture, 3
  reports (Sales by date range, Revenue by provider, New vs
  returning), catalog endpoint, frontend library + 3 detail pages.
- **Session 2**: fill out the rest of Financial + Staff + Guests +
  Operations to the catalog table above.
- **Session 3**: CSV export across all reports, PHI confirmation
  modal, EXPORT audit trail.
- **Session 4 (post-launch polish)**: saved report views (date-
  range presets the operator named); scheduled email delivery
  (lights up after Phase 1F SMS/email plumbing matures).

The user's bar — "all reports on everything possible" — is met at
the end of Session 2 + 3, not Session 1. The Phase 1G ✅ entry in
PROJECT_PLAN.md only flips when Sessions 1–3 are all shipped.

## Consequences

### Pros

- **Vertical slice from day one.** Session 1 ships a working
  end-to-end report (data → API → audit → UI → permission gate)
  before scaling out. Bugs in the architecture surface immediately.
- **Catalog endpoint = no hardcoded frontend lists.** New reports
  auto-appear in the library; permission-filtering is server-side.
- **Category-level permissions** match how operators reason about
  access. Bookkeeper sees Financial; front desk sees Operations.
- **OLTP query path** keeps ops surface small. No second database,
  no CDC pipeline, no replica until measured pain.
- **HIPAA framing baked in from the first report.** Audit log,
  PHI tiers, CSV-export gating all defined before code lands.
- **OpenAPI docs per report** — drf-spectacular renders each
  report's params + response cleanly because each is its own view.

### Cons

- **One APIView per report** = 50+ files when the catalog is full.
  Mitigated by keeping each view ~30 lines (param parsing + ORM
  aggregate + serialization); the `BaseReportView` carries the
  shared logic.
- **No saved views in v1.** Operator picks date range each time
  they open a report. Saved views land Session 4.
- **No scheduled email delivery in v1.** Operator pulls reports
  ad-hoc; nothing fires automatically. Lights up post-Phase 1F.
- **No cross-report drill-down.** Clicking a provider in "Revenue
  by provider" doesn't open a filtered "Appointments by provider"
  view yet. Each report is standalone in v1; drill-downs are a
  Session 4 polish item.
- **Postgres aggregates won't scale forever.** When a tenant
  crosses ~100k appointments AND queries lifetime data, materialized
  views become necessary. Documented; not blocking.

### Production lift (Phase 0c+)

- **Materialized views** for any report that exceeds 2s at p95 in
  production. Refreshed nightly via Celery beat (Phase 1F). Add
  per-tenant if a single tenant dominates.
- **Read replica** if report load contends with OLTP write load.
  PgBouncer routing decides per-query. Deferred.
- **PHI export confirmation gate** (Session 3) — required before
  any CSV export feature ships.
- **Saved report views** (Session 4) — a small `SavedReport` model
  per tenant + per user storing the report ID + frozen params.
- **Scheduled email delivery** — depends on Celery beat (Phase 1F)
  + email infrastructure (ADR 0012).
- **Drill-down navigation** between related reports (e.g. provider
  card → that provider's appointments).
- **Per-report PHI export gate** (`EXPORT_PHI_REPORT`) if the
  category-gate granularity proves too coarse in practice.

## References

- [PROJECT_PLAN.md §1G](../../PROJECT_PLAN.md) — Phase 1G basic reporting
- [ADR 0003 — Permission model](./0003-permission-model.md)
- [ADR 0004 — Audit logging](./0004-audit-logging.md)
- [ADR 0007 — Invoicing + completion gate](./0007-invoicing-and-completion-gate.md) — source-of-truth for financial reports
- [ADR 0001 — Multi-tenancy strategy](./0001-multi-tenancy-strategy.md)
- HIPAA Security Rule §164.312(b) — Audit controls
- HIPAA Privacy Rule §164.502(b) — Minimum necessary
- SOC 2 Trust Services Criteria CC 6.1 — Logical access controls
- SOC 2 Trust Services Criteria CC 7.2 — System monitoring
