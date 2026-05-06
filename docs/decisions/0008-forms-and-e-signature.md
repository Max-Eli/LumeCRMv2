# ADR 0008 — Forms & e-signature data model

## Status

Accepted (2026-05-02 — Session 1: template management)

## Context

Medspa workflow has two distinct form needs that operators historically
treat differently:

1. **Intake forms** — general first-visit questionnaires (medical
   history, contact preferences, photo / treatment-record consent,
   no-show policy acknowledgement). Asked **once per customer**, not
   per appointment, not per service. Operationally tied to the
   client's first visit ever.
2. **Treatment consent forms** — per-service informed consent (Botox,
   filler, laser, microneedling each have their own). Required by
   state regulation for clinical procedures; the spa cannot legally
   perform the treatment without one on file. Whether re-signing is
   needed each visit varies by jurisdiction and provider preference.

Both share the same data shape (a JSON-defined field list, a signed
PDF artifact, an audit trail), so they should share the model. But
their **assignment rules** differ enough that lumping them under one
"form" with a free-text purpose field would push policy logic into
the operator's head ("which forms apply on a new-client Botox visit?")
instead of into the system.

We also need the **fill flow to work without an account** — clients
fill forms via a tokenized link sent in email/SMS or opened in-office
on an iPad and handed across the counter. This matches what Vagaro,
Mindbody, Boulevard, and Aesthetic Record all do; a customer portal
is an option some products add but is not the default expectation.

### HIPAA + SOC 2 framing

Forms are the first feature that **collects PHI directly through the
product surface** (rather than receiving it through an appointment
booking). The model needs to be designed with these constraints from
the start, not bolted on:

- **Encryption at rest.** Submission answers contain medical history,
  consent decisions, and signatures. Postgres TDE in production
  (Phase 0c) covers this; the model design itself must not put PHI
  into URL fragments, logs, or non-encrypted side channels.
- **Audit logging.** Every read of a submission (clinical staff
  reviewing consent before treatment) and every write (signature,
  void, re-issue) needs an `AuditLog` entry naming the user, the
  resource, and the timestamp. This is SOC 2 CC 7.2 and HIPAA
  §164.312(b) "Audit controls."
- **Immutable signatures.** Once signed, the answers + signature data
  cannot be edited — only voided + re-issued. SOC 2 change-management
  control. The data model enforces this via never exposing PATCH on
  the submission's `answers` field after `signed_at` is set
  (Session 2 work).
- **Tenant isolation.** Submissions are PHI; cross-tenant leakage is
  a reportable HIPAA breach. Inherits the `TenantedModel` discipline
  from ADR 0001.
- **Minimum-necessary access.** Front-desk staff need to see a
  submission's STATUS (signed / pending / voided) to know whether to
  prompt the client; only clinical staff need to read the actual
  answers. Surface-level enforcement via permission checks on the
  submission detail endpoint (Session 2).
- **Token security.** The tokenized fill link is bearer-style — anyone
  with the URL can fill the form. Tokens must be high-entropy,
  single-use, and expire after signing. URL fragment placement is OK
  because servers don't log fragments; query string would leak into
  Nginx access logs (avoid).

## Decision

**Two-table form catalog, one-table submission storage. Form type
discriminates assignment policy at insertion time, not at read time.
Schema validated by the API serializer (not the database) because the
JSON shape is type-dependent.**

### Domain shape

| Model | Purpose |
|---|---|
| `FormTemplate` | Tenant-scoped reusable template. Discriminated by `form_type` (intake | consent) which drives auto-assignment policy. Carries `recurrence` (once | per_visit) for re-sign rules. `schema` JSON holds the field definitions. `version` auto-increments on schema change so submissions can snapshot the version they were signed against. |
| `ServiceFormAssignment` | Maps consent templates to services. Many-to-many materialized as a join table so we can add per-mapping metadata later (e.g. "skip if last signed within N days"). Intake forms aren't represented here — their auto-assignment is "first appointment ever," not service-driven. |
| `FormSubmission` *(Session 2)* | Per-customer, per-template submission record. Snapshots `template_version_at_signing` so historical signatures stay legible after the template evolves. Carries the secret token, status, answers (JSONB), signature data (base64 PNG of canvas), and the audit trail (IP, user-agent, signed_at). |

### Type / recurrence matrix

|  | `recurrence=once` | `recurrence=per_visit` |
|---|---|---|
| `form_type=intake` | **Default for intake.** Assigned on the customer's first appointment ever. Never re-asked. | Allowed but unusual — would re-prompt the intake every visit. |
| `form_type=consent` | One-time consent that survives re-treatment (rare; e.g. a permanent makeup waiver). | **Default for consent.** Re-signed every appointment that books the mapped service. CYA default for clinical work. |

### Schema validation rules (v1)

Six field types: `short_text`, `long_text`, `choice_single`,
`choice_multiple`, `date`, `signature`. Each field requires `id` (1–64
ASCII letters / digits / underscore — used as a JSON key in answers,
a DOM id in the fill page, and a stable identifier across version
bumps), `type`, and `label`. Choice fields require ≥2 distinct
options. Field ids must be unique within a template.

JSON-schema validation lives in the **serializer**, not the database,
because the shape is type-dependent and Postgres `jsonb_typeof` checks
would be cumbersome and unevolvable. Trade-off: a script bypassing
the API can write technically invalid schemas. Mitigations: the API
is the only intended write path; future polish item is a Postgres
trigger that runs the same validation.

### Why intake forms don't get service mappings

The most common mistake operators make is assigning a "general intake"
to specific services. The system rejects this explicitly with a 400
error rather than silently dropping the mapping or applying it
unexpectedly. Intake-with-service-mapping is incoherent under our
"first appointment ever" rule — the mapping wouldn't drive anything.
Better to fail early.

### Why version bumps only on schema change

Operators rename templates and tweak descriptions constantly during
the configuration phase. Bumping the version on every cosmetic edit
would balloon the version count and pollute the audit trail with
no-ops. The viewset compares the canonical normalized schema (post-
serializer) against the stored value and only bumps when they actually
differ. The audit log records the from/to versions so the change is
discoverable.

### Why no hard delete

Submissions FK into templates (Session 2). Even if a template is
"retired" by the operator, signed historical submissions point at it
for chart-review purposes. Hard delete would orphan the audit trail.
Soft-delete via `is_active=false` stops the template from
auto-assigning to new appointments while keeping historical
submissions intact.

## Consequences

### Pros

- **Assignment policy is encoded in the model**, not the operator's
  head — an intake form can't accidentally apply per-service.
- **Versioning + snapshotting** lets templates evolve without breaking
  historical chart records.
- **Tokenized fill flow** matches industry expectation; no portal to
  build, no client account management overhead.
- **HIPAA + SOC 2 considerations baked into the design** rather than
  retrofitted: tenant isolation via `TenantedModel`, audit logging
  via existing `apps.audit.services.record()`, soft-delete preserves
  trail.
- **Schema validation in the API layer** keeps the model evolvable —
  adding a new field type (image upload when S3 lands; conditional
  logic in a polish pass) is a serializer change, not a migration.

### Cons

- **JSON schema validation isn't enforced at the DB layer.** Bypassing
  the API (Django shell, scripts) can write invalid schemas. Polish:
  Postgres trigger calling the same validator. Until then, the API
  is the only write path and code review enforces this.
- **Form versioning is linear, not branched.** Operators can't have
  "Botox consent v3 — California" and "Botox consent v3 — New York"
  in parallel. v1 reflects the spa-as-single-jurisdiction reality;
  multi-state expansion would need this.
- **No exception model for the "first appointment ever" rule.** If a
  customer is migrated from another system mid-treatment-course, the
  intake won't re-prompt because their first appointment ever was
  pre-migration. Manual re-issue from the customer chart will cover
  this in Session 3.
- **Front-desk staff can READ all submissions** by default in v1
  (template-level). When Session 2 lands the submission detail
  endpoint, we'll narrow read access on `answers` to clinical roles
  + the customer's assigned provider. Acceptable today because
  templates themselves don't carry PHI.

### Production lift

- **Postgres TDE** for at-rest encryption of submission data. Phase 0c.
- **PHI field hiding** for non-clinical roles on the submission detail
  endpoint. Session 2 work.
- **Token expiry + single-use enforcement** on fill links. Session 2.
- **Audit-log immutability via DB trigger** (already in the §4.5
  polish backlog from ADR 0004 — applies here too).

## References

- [apps.forms README](../../backend/apps/forms/README.md)
- [ADR 0001 — Multi-tenancy strategy](./0001-multi-tenancy-strategy.md)
- [ADR 0004 — Audit logging](./0004-audit-logging.md)
- HIPAA Security Rule §164.312(a)(1) — Access control
- HIPAA Security Rule §164.312(b) — Audit controls
- HIPAA Security Rule §164.312(c)(1) — Integrity
- SOC 2 Trust Services Criteria CC 7.2 — System monitoring
- SOC 2 Trust Services Criteria CC 7.3 — Change management
