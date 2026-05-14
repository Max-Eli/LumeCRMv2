# ADR 0020 — Form-submission PDF rendering (Phase 1D)

## Status

Accepted (2026-05-13).

## Context

Signed consent and intake forms are the legal record that a customer agreed to a treatment. Today the customer profile shows "Signed on May 12" and can re-open the signed view at `/sign/<token>`, plus operator-initiated email delivery is wired (ADR 0012). Two real needs remain unmet:

1. **Customer-facing PDF copy** — when a customer says "send me a copy of what I signed," the operator should be able to hand off a single self-contained file. The "view at /sign/<token>" link works for live access but doesn't help if the customer wants to file the consent into their own records, send it to a referring physician, or read it offline.
2. **HIPAA + audit defensibility** — a signed consent that exists only in a database row is harder to defend at audit than a PDF artifact bearing the signature image, customer name, timestamps, and IP. Auditors expect concrete documents.

The invoice PDF feature (ADR 0018) already solved the same problem-shape — render on demand from the source-of-truth row, no caching, no S3 — and the reportlab pattern is reusable.

### HIPAA + SOC 2 framing

- **Audit logging** — every PDF download writes an `AuditLog` entry with submission id + customer id + byte count. HIPAA §164.312(b) requires every PHI access be traceable; the existing list/retrieve audit already covers reads of the row, and the PDF endpoint extends that to the file artifact.
- **Tenant scope** — the viewset's queryset is filtered via `for_current_tenant()`. Cross-tenant requests get 404, not 403, which is the stricter pattern (doesn't leak existence).
- **Permission** — same as list + retrieve. Any authenticated tenant member can download. The signature + answers are already exposed via retrieve; gating the PDF more tightly than the row would be inconsistent. A future polish (called out in the 1D open list) is to tighten the detail endpoint behind `VIEW_CLIENT_PHI`, which would apply identically to the PDF.

## Decision

### 1. Renderer: `render_form_submission_pdf` in `apps.forms.services`

Lives next to the existing `email_signed_copy` helper. Lazy-imports reportlab to keep the dep out of normal Django request import graphs. Reuses `_format_field_value` so the PDF and email body render identical text for each answer.

Output shape:

- **Header** — tenant name, form template name, optional VOIDED banner with reason
- **Client + signed timestamp** — two-column header table
- **Field-by-field** — each non-signature field rendered as label + value. The render is driven off `schema_snapshot.fields` (frozen at submission time), so the PDF reflects exactly what was signed even if the live template has changed since.
- **Signature image** — decoded from the stored base64 PNG, embedded via reportlab `Image` flowable, sized 3"×1.2" proportionally. Corrupt or missing base64 renders a clear placeholder rather than failing the whole PDF.
- **Footer** — submission ID, template name, signed-at timestamp, signing IP (when captured). These are the audit-trail fields and they belong on the page if the spa ever needs to defend the document in a complaint.

### 2. Endpoint: `GET /api/form-submissions/<id>/pdf/`

A new `@action(detail=True, methods=['get'])` on `FormSubmissionViewSet`. Returns `application/pdf` with `Content-Disposition: attachment; filename="<template name> — <id>.pdf"`.

PENDING submissions return **400** with `{detail: "Cannot render PDF for a pending submission. Sign or void it first."}`. There's nothing meaningful to render before a signature exists; surfacing the boundary explicitly is better than emitting a half-empty PDF.

### 3. Storage: on-demand, no cache

Same trade-off as ADR 0018:

- **PHI surface minimized** — bytes live in transit + the requester's browser memory. No filesystem, no S3, no Redis.
- **Deterministic projection** — COMPLETED and VOIDED submissions have immutable `answers` + `signature_data` + `schema_snapshot`. Render is repeatable; PDFs of the same submission produced on different days are byte-equivalent except for the "generated at" implicit metadata in the PDF trailer.
- **Template-change safety** — `schema_snapshot` is frozen at submission time, so changing the live template (adding a field, renaming a label) doesn't retroactively alter past PDFs.
- **No staleness window** — there's no cache to invalidate when an operator voids a submission. The void state shows up on the next download immediately.

If a future jurisdiction demands byte-identical archival (rare in US medspa context, more common in EU GDPR), we'd add S3 caching keyed by `(submission_id, template_version)` without rewriting the renderer.

### 4. Frontend: Download button on the customer profile Forms tab

A small `DownloadFormPdfButton` sits next to the existing "Email signed copy" + "View signed" actions on each completed (or voided) submission row. Uses the established fetch+Blob+anchor download pattern (CSV exports, invoice PDF) so the X-Tenant-Slug header gets forwarded in dev. The button is intentionally compact — just "PDF" — to avoid crowding the action row.

## Consequences

### Positive

- Closes one of the open Phase 1D items. Spa owners now have a self-contained legal record per signed consent they can hand to customers, file with referring physicians, or surface in a HIPAA audit.
- Reuses the reportlab pattern from invoices end-to-end (renderer + endpoint + frontend button + tests + audit logging), so there's no new infrastructure or new pattern to learn.
- 9 tests cover both halves: renderer correctness (COMPLETED + VOIDED + PENDING-refused + corrupt-signature graceful), endpoint behavior (auth required, cross-tenant 404, audit log written, PENDING → 400).
- Unblocks future enhancements: bulk PDF download per customer (a "download all my signed forms" feature), automatic PDF attachment to the email-signed-copy flow (currently HTML-inline only).

### Negative

- `reportlab` was already in `requirements.txt` for invoices, so no new dep — but every form PDF spends 5-30ms of CPU on a Fargate task. For 2 spas at launch, irrelevant. At 1000 tenants with high signed-form volume, worth measuring; the fix would be the same cache layer we'd add for invoices.
- The signature image quality depends on what the signature canvas captures. Today the canvas is a low-DPR PNG; the PDF embeds it at 3"×1.2" which can look pixelated under inspection. A polish item is to capture at higher resolution and let the PDF embed at native dimensions.

### Risks accepted

- **No PDF/A** — the output is regular PDF, not the archival PDF/A standard some compliance regimes require. Acceptable for US medspa context; we'd add PDF/A as a separate ADR if a tenant requests it.
- **No digital signature on the PDF itself** — the PDF embeds the customer's drawn signature image but the file isn't cryptographically signed by Lumè. A determined adversary with the row data could regenerate a near-identical PDF. The audit trail (`AuditLog` entries on read + write) is the integrity backstop; if PDF-level signing becomes required, we'd add it via reportlab's PKCS7 support.
- **Permission ties to retrieve** — same access tier as reading the row. The 1D open-list "tighten detail behind `VIEW_CLIENT_PHI`" polish will apply to both endpoints simultaneously when it lands.

## Implementation references

- Renderer: [apps/forms/services.py](../../backend/apps/forms/services.py) — `render_form_submission_pdf`
- Endpoint: [apps/forms/views.py](../../backend/apps/forms/views.py) — `FormSubmissionViewSet.pdf`
- Tests: [apps/forms/tests.py](../../backend/apps/forms/tests.py) — `FormSubmissionPDFTests` (9 tests)
- Frontend button: [frontend/src/app/(app)/clients/[id]/page.tsx](../../frontend/src/app/(app)/clients/[id]/page.tsx) — `DownloadFormPdfButton`
- Pattern reused from: [ADR 0018 — Invoice PDF rendering](./0018-invoice-pdf-rendering.md)
