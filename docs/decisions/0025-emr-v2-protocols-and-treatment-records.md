# ADR 0025 — EMR v2: service protocols + treatment record templates

## Status

Accepted (2026-05-15).

## Context

`apps.charts` shipped free-form `ChartNote` (Phase 4A sessions 1 + 2). It covers the legal "what was observed" requirement, but two gaps surface the moment a real medspa starts using it:

1. **No procedural reference.** Providers and onboarding staff have no system-of-record place to look up "how do we do a HydraFacial here?" Industry-standard EMRs (Aesthetic Record, Symplast, Boulevard, PatientNow) ship per-service protocols as a baseline. Without it, spas keep procedures in shared Google Docs, which drift and don't audit.
2. **No structured records.** The free-form `ChartNote` body is fine for general observations, but injectable documentation needs structured fields — units, lots, sites, expirations — for both compliance (FDA, state board) and reporting ("how many units of Botox did we dose last quarter?"). The README explicitly noted this as a future "session 4."

This ADR captures both pieces, shipped as EMR v2.

## Decision

### 1. `ServiceProtocol` — provider-facing reference per service

A new model in `apps.services` with one-to-one to `Service`:

- **`pre_treatment`** — intake checks, contraindications, consent confirmation, photos.
- **`intra_treatment`** — the procedure itself (numbered steps, equipment settings, technique).
- **`post_treatment`** — immediate post-care + take-home guidance.
- **`notes`** — free-form (lot tracking conventions, vendor preferences).

Why a separate model (not JSON fields on Service):
- Audit log treats protocol edits as distinct events (`service_protocol` resource type) — answers "who changed the laser-eye-shield safety step?"
- Future versioning (regulatory: which protocol was in effect when this treatment was performed) plugs in cleanly as a separate history table.
- Permission gating is independent of Service catalog edits — a clinical lead can own protocols even if they don't manage pricing.

PHI posture: protocols are **not** PHI. They're the spa's procedural reference.

API: singleton-per-service at `GET/PUT /api/services/<id>/protocol/`. First PUT upserts; GET returns an empty-shape payload when none exists yet so the UI doesn't juggle 404-vs-empty.

UI: a "Protocol" tab on `/catalog/services/<id>` with four section editors + a sticky save bar.

### 2. `TreatmentRecordTemplate` — schema-driven form spec

A new model in `apps.charts`. Schema shape mirrors `apps.forms.FormTemplate.schema` deliberately so the field-type vocabulary stays consistent:

- `short_text`, `long_text`, `choice_single`, `choice_multiple`, `date`, `signature` — same as customer-facing forms.
- **`number`** — added for medical fields (units used, dosages, side counts).

Distinct from `FormTemplate` because the surfaces differ:
- `FormTemplate` = customer-completed (intake + consent), triggered before/at the visit.
- `TreatmentRecordTemplate` = provider-completed (chart-grade record of what happened), triggered at or after the visit.

Per-service assignment via `ServiceTreatmentTemplateAssignment` (parallel to `ServiceFormAssignment`). A template can be assigned to many services; a service can have many templates.

Versioning: `version` auto-increments on every save where `schema` changed. Submitted records (`TreatmentRecord`) snapshot the version they were signed against, so editing the template doesn't retroactively change historical records — the same "frozen at signing time" guarantee `FormTemplate` gives.

CRUD: `/api/treatment-record-templates/` ViewSet, gated by `MANAGE_SERVICES` for writes (catalog-config tier), reads open to any tenant member.

### 3. `TreatmentRecord` — signed instance per appointment

A new model in `apps.charts` mirroring `ChartNote`'s lifecycle but holding structured `answers` (keyed by field id) + a frozen `schema_snapshot`:

```
pending edit  ─►  locked  ─►  optional addendum chain
(≤60 min)         (forever)   (each addendum is a separate row, also
                    │          with its own 60-min window)
                    ▼
                 voided
                 (owner/manager only, requires reason; excluded
                  from clinical reads but row survives in audit)
```

Why a separate model (not unified with `ChartNote`):
- Free-form text vs. structured `answers` keyed by field id is a different data shape; cramming both into one model means awkward nullability + serializer branching.
- Compliance reporting wants to query JUST the structured records ("show me every Botox unit dosed last quarter") without scanning free-form text.
- Permission gates and lifecycle are identical; the existing `ChartNoteWritePermission` is reused for `TreatmentRecord` to keep the access-control surface uniform.

PHI posture: `TreatmentRecord.answers` IS PHI — provider-authored treatment data tied to a specific patient. Same audit logging on every read + write as `ChartNote`. Tenant-scoped + customer-scoped. Append-only after the edit window; the `destroy` action returns 405 explicitly so a misplaced DELETE can't bypass the lock.

Endpoints: `/api/treatment-records/` ViewSet with `addendum` and `void` action endpoints — exactly the same shape as `ChartNote`.

### 4. UI surfaces

**Catalog → EMR templates** (`/catalog/treatment-record-templates/`):
- List view grouping active vs. inactive templates with version + service-assignment counts.
- Editor with three sections: basics (name, description, active toggle), service assignments (multi-select grid), and a tactical schema builder (rows of `{type dropdown, label input, required checkbox, options for choice fields}`). Field IDs auto-generate from labels via slugify; existing IDs are preserved so submitted records that snapshot the schema stay legible.

**Service detail → Protocol tab** (`/catalog/services/<id>?tab=protocol`):
- Four section editors with filled/empty indicators per section, sticky save bar, last-edited attribution.

**Customer profile → Treatment records tab** (`/clients/<id>?tab=treatment-records`):
- Read-only history of records signed against this customer, grouped with addenda nested under their parent.
- Renders the `schema_snapshot` + `answers` exactly as they were at signing time.
- "+ Sign new record" CTA opens an inline dialog: pick template → renders the schema as a form → submit creates the record. Required-field check on the client; the backend re-enforces.

The appointment-detail integration (signing a record from the appointment popover with the appointment_id pre-filled) is a follow-up — the customer-profile path covers the workflow today.

### 5. HIPAA + SOC 2 posture

- **PHI scope.** `TreatmentRecord.answers` and `schema_snapshot` are PHI. `ServiceProtocol` and `TreatmentRecordTemplate` are NOT PHI (procedural reference + schema spec).
- **Access control.** `VIEW_CHART` for record reads (provider, owner, manager — front-desk + bookkeeper + marketing roles get 403). `SIGN_CHART` for create + within-window edit. `EDIT_SIGNED_CHART` for void. Same gates as `ChartNote`.
- **Audit log.** Every record read writes `treatment_record` (or `treatment_record_list`) entries; every mutation writes `treatment_record` with the event (`within_window_edit`, `addendum`, `voided`). Body content is NEVER in audit metadata — only event + customer_id + parent_record_id. Same hygiene as `ChartNote`.
- **Edit posture.** Author-only within 60-minute typo-correction window; locked forever after, additions only via addenda. Voiding is one-way + requires a reason and a stronger permission. ADR 0015's posture rationale carries forward.
- **Snapshot guarantee.** `schema_snapshot` + `template_version_at_signing` mean future template edits never alter historical records — the legal record stays exactly as it was signed.

### 6. Test coverage

48 backend tests in `apps.charts.tests` (35 ChartNote + 13 new) + 8 in `apps.services.tests` for the protocol singleton:
- Template CRUD: create / version-bump on schema change / version-no-bump on metadata-only change / service-filter / front-desk read-vs-write split.
- Schema validation: missing fields / non-array fields / invalid id pattern / choice fields requiring 2+ options / unknown field type.
- Record submission: clinical author flag snapshot / template-version snapshot / schema_snapshot frozen.
- Within-window edit / locked record rejects edit / addendum lifecycle / owner-can-void / destroy-returns-405.

## Consequences

### Good

- Spas have a real EMR template authoring surface that competes with industry baselines.
- Structured records unlock compliance reporting + cleaner provider workflows ("Botox visit" template auto-rendered with the right field set every time).
- The sandwich of ChartNote (free-form) + TreatmentRecord (structured) covers both unstructured observations + chart-grade documentation without forcing one into the other's shape.

### Bad / Deferred

- **Body diagrams + injection-site mapping.** No visual injection map yet; sites are captured as text in a long_text field. Real EMRs render a face/body diagram with click-to-mark. Future polish: needs a canvas component + a structured site-coordinate field type.
- **Before/after photo capture.** Out of scope for v2; needs S3 + KMS infra + EXIF stripping + consent-gate enforcement (Phase 4B).
- **Co-signing.** RN-signed records requiring NP/MD review + counter-sign in some states. The `cosigned_by` field shape is documented in the model docstring as a future addition; not built.
- **Patient-export PDF.** HIPAA §164.524 right-of-access export of all chart records for a customer. Future polish; needs a PDF renderer.
- **Appointment popover integration.** Today the operator signs records from the customer profile (Treatment records tab → "+ Sign new record"). Surfacing the same flow on the appointment detail page is a small follow-up that auto-fills the `appointment_id`.
- **Tactical schema builder.** The catalog-side template builder uses comma-separated options + dropdown type pickers, not the polished drag-handle UI of the existing customer FormTemplate builder. Acceptable trade-off for shipping v2 in this session; a future polish can either share the builder or upgrade the EMR one in place.
- **Signature field type.** Schema accepts `signature` but the client-side input renders a placeholder ("(Signature capture coming with the iPad Pencil flow)"). Real signature capture needs the existing `<SignatureCanvas>` component to be wired; this is a small fast-follow.

### Acknowledged

- Field IDs are derived from labels via slugify on first save. Renaming a field after submitted records exist keeps the original ID, preserving record legibility — this is intentional and matches `FormTemplate`'s posture.
- The schema-builder JSON shape mirrors `FormTemplate.schema` plus `number`. We deliberately did NOT factor a shared "schema engine" between the two modules. They overlap today but have different evolution paths (the EMR side will grow body-diagram fields, dose-with-units composite fields; the customer side will grow file-upload, conditional logic). YAGNI on the shared layer until we know they want the same things.

## Alternatives considered

### One unified `Note` model with optional structured fields

Considered: a single `Note` model with `body` (text) + optional `schema_snapshot` + `answers`. Rejected because nullability everywhere makes the API surface awkward (`body` required only when `template` is null, etc.) and reporting queries get more complex (filter `WHERE schema_snapshot IS NOT NULL` on a heterogeneous table). Two clean models > one branchy one.

### Repurpose `apps.forms.FormTemplate` for both customer + provider forms

Considered. Rejected for reasons in §3: PHI tier differs (provider-completed = stricter access), permission gates differ, lifecycle differs (FormSubmission has no addendum chain), UI surfaces differ. Sharing the schema-vocabulary is enough; sharing the model would force compromises on both surfaces.

### Schema-as-Pydantic-model per template (typed answers)

Considered. Rejected: requires runtime-generating Pydantic classes from operator-edited schemas, which is fragile. The current "validate answers against schema_snapshot in the serializer" approach is simpler and still gives us the safety guarantees we need (required-field check, type coercion, choice-value validation).
