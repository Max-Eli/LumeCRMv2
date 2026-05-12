# ADR 0018 — Invoice PDF rendering (Phase 1E)

## Status

Accepted (2026-05-12).

## Context

Phase 1E (invoicing) shipped most of its scope in May 2026: per-tenant invoice numbering, state machine (OPEN/PAID/VOID), line-item snapshotting, permissions, audit-logged actions. Three items remained open: PDF generation, calendar status badge, and emailing invoices to clients. The PDF is the keystone — it is both the customer-facing artifact spas hand over at the end of a visit ("can I get a receipt?") and the prerequisite for the email flow (the PDF is the email's attachment).

The motivating questions for this ADR are:

1. **What renders the PDF?** Pick a library that runs in the Alpine Fargate container, doesn't require system packages, and produces consistently formatted output.
2. **Where do the rendered bytes live?** On disk, in S3, or generated on demand per request?
3. **What permission gates it?** Same as reading the invoice, or stricter?

### HIPAA + SOC 2 framing

An invoice combines the customer's name, contact, services rendered, dates, and prices. That is **identifiable financial data** tied to a treatment relationship — covered as PHI under HIPAA (45 CFR 164.501's "treatment, payment, and health care operations"). Implications:

- The PDF endpoint must require authentication + tenant membership and audit-log every fetch.
- Stored PDFs (if we cached them) would expand the PHI footprint: an additional surface that needs encryption at rest, IAM controls, retention policy, and a backup story. On-demand rendering keeps the PHI surface area minimal — bytes live only in transit and in the requester's browser memory.
- SOC 2 CC6.1 (Logical Access) maps to the same audit-log + tenant-scope requirements we already enforce on the read endpoint.

## Decision

### 1. Renderer: `reportlab` (pure Python)

We use `reportlab==4.5.1`, pinned in `requirements.txt`. Selected over `weasyprint`, `xhtml2pdf`, and `borb` for these reasons:

- **Pure Python, no system packages.** `weasyprint` needs Cairo + Pango + GObject; our Alpine-based Fargate image would balloon by ~50MB and add a class of native-lib bugs. `reportlab` is wheelable on `linux/arm64` with no system deps.
- **Mature platypus API.** We use the higher-level `Paragraph`/`Table`/`SimpleDocTemplate` flow — declarative, table-aware, deterministic across versions. Lower-level `canvas` primitives are also available if a future invoice variant needs absolute positioning (e.g., a logo at exact coords).
- **License: BSD-style** (`reportlab` is dual-licensed under their own BSD-like terms; commercial use of this version is unrestricted).
- **Output size + speed.** Empty-line invoice → ~2.3KB PDF, ~10ms render. Even a 50-line invoice stays under 30KB and renders in well under 100ms. No reason to cache.

Renderer lives in `apps/invoices/services.py` as `render_invoice_pdf(invoice: Invoice) -> bytes` — a pure function. Lazy `import reportlab` inside the function body so the dependency stays out of Django's startup graph (every other PDF-free request pays nothing).

### 2. Storage: on-demand, no cache

**The PDF is a deterministic projection of the invoice row.** PAID and VOID invoices have immutable totals (state machine + CheckConstraints enforce this); OPEN invoices reflect the current line-item state at the moment of render. Every fetch re-renders from the row. We do not write PDFs to S3, disk, or memory cache.

Why this is the right call for v1:

- **Smaller PHI surface.** Every PDF stored is another place we have to encrypt, scope, replicate, and eventually delete on customer request. On-demand keeps PHI in transit, where the existing HTTPS + IAM controls already cover it.
- **No staleness window.** If we cached and the invoice mutated (a line edit on an OPEN invoice), we'd need a cache-invalidation hook. Trivial to write, easy to forget; bugs in this class are silent leaks of "the customer got an outdated receipt."
- **Render is fast.** Sub-100ms on the typical invoice. The latency budget on a download endpoint is forgiving — humans expect a download to take a moment.
- **Template changes regenerate.** When we polish the invoice layout (e.g., add a tenant logo in 1H polish), every PDF immediately reflects the change without a migration. The downside — historical PDFs might look different from when they were originally downloaded — is acceptable because the legal record is the database row, not the PDF.

If we later need stable-bytes archival (e.g., a tax-audit requirement that wants byte-identical PDFs over years), we'll add S3 storage as a separate concern — keyed by `(invoice_id, template_version)` — without rewriting the renderer.

### 3. Permission: same as `retrieve` (added to `READ_ACTIONS`)

The PDF is a presentational projection of the invoice row. Anyone who can `GET /api/invoices/{id}/` can `GET /api/invoices/{id}/pdf/`. We added `'pdf'` to `InvoicePermission.READ_ACTIONS`. That matches the existing pattern: read access is open to any authenticated tenant member; mutating actions are individually gated.

Audit-log: every PDF download writes an `AuditLog` entry with `resource_type='invoice_pdf'`, `resource_id=invoice.pk`, and `metadata.bytes=len(pdf)`. The byte count is a cheap integrity signal — if PDFs suddenly drop to ~500 bytes, something broke in rendering and we'll see it in the audit query.

### 4. Frontend: `<button>` fetch → Blob → anchor click

The CSV-export pattern is already established in `frontend/src/app/(app)/reports/_components/export-csv-button.tsx`. A plain `<a href="https://api.../pdf/" download>` skips the `X-Tenant-Slug` header that the dev backend needs to resolve the tenant. We use `fetch` with `credentials: 'include'` + the tenant slug header, turn the response into a Blob, generate an object URL, and click a temporary anchor element. This is the standard download-via-blob idiom across the codebase now (CSV + PDF).

The button lives in the PageHeader actions slot on `/appointments/[id]/invoice` — visible regardless of invoice status (OPEN, PAID, VOID). Spas need receipts for all three.

## Consequences

### Positive

- Closes one of the three remaining 1E items; unblocks the email-invoice flow that depends on a `bytes` source.
- No new infrastructure: no S3 bucket, no cache layer, no background job. The endpoint is a stateless GET that does math.
- ~8KB of new Python in `services.py`, ~80 lines of TypeScript in the page component, 8 new tests. Small footprint, easy to grok.
- Renderer pattern is reusable: future statement PDFs, receipt PDFs, chart-note exports (Phase 4) can copy the platypus + flow pattern.

### Negative

- Each PDF download is 5-10ms of CPU on a Fargate task. For 2 spas at our launch scale, irrelevant. At 1000 tenants with high download volume (~10/sec), this becomes ~100ms of aggregate CPU per second — still well within a single task's capacity, but worth knowing. If it ever matters, the fix is `cache.set(f'invoice_pdf:{id}:{updated_at}', bytes)` in front of the renderer.
- `reportlab` is a moderate dep — ~3MB wheel, ~12MB installed. Acceptable but not free.
- The PDF layout is hand-coded as Python flowables, not a designer-friendly template. Iterating on visual design requires Python changes. We accept this for v1; if the design churn becomes painful, swap in a Jinja-driven HTML→reportlab flow later.

### Risks accepted

- **No template versioning.** If we change the invoice layout in v2, downloads of v1 invoices will use the v2 layout. Acceptable: the row data hasn't changed, only the presentation. If a customer disputes a v1 invoice years later, the database row and the audit log are the authoritative record.
- **No byte-identical archival.** Same reasoning as above. For tax-audit jurisdictions that require byte-stable copies (rare in US medspa context; common in EU), we'd add S3 caching as a separate ADR.

## Implementation references

- Renderer + helpers: [apps/invoices/services.py](../../backend/apps/invoices/services.py) — `render_invoice_pdf`, `_format_money`
- Endpoint: [apps/invoices/views.py](../../backend/apps/invoices/views.py) — `InvoiceViewSet.pdf` action
- Permission addition: [apps/invoices/permissions.py](../../backend/apps/invoices/permissions.py) — `READ_ACTIONS` includes `'pdf'`
- Tests: [apps/invoices/tests.py](../../backend/apps/invoices/tests.py) — `InvoicePDFTests` (8 tests)
- Frontend button: [frontend/src/app/(app)/appointments/[id]/invoice/page.tsx](../../frontend/src/app/(app)/appointments/[id]/invoice/page.tsx) — `DownloadPdfButton`
- CSV pattern reused: [frontend/src/app/(app)/reports/_components/export-csv-button.tsx](../../frontend/src/app/(app)/reports/_components/export-csv-button.tsx)
