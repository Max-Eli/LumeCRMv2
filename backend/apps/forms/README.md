# apps.forms

Per-tenant form templates + (Session 2) tokenized fill flow + (Session 3)
submission storage. The first feature where the product surface
**collects PHI directly** (medical history, treatment consent), so the
HIPAA + SOC 2 framing is explicit throughout.

## What's in here

- **[models.py](models.py)** — `FormTemplate` (intake / consent
  discriminator, JSON schema, version, recurrence),
  `ServiceFormAssignment` (consent ↔ service mapping),
  `FormSubmission` (per-customer materialization, schema snapshot,
  status, signed answers + signature data, audit trail).
- **[serializers.py](serializers.py)** — `FormTemplateSerializer`
  (hard JSON-schema validation), `FormSubmissionListSerializer`
  (no PHI), `FormSubmissionDetailSerializer` (PHI; gated),
  `PublicFormSubmissionSerializer` + `PublicFormSignSerializer`
  (unauthenticated fill flow).
- **[services.py](services.py)** — `assign_forms_for_appointment()`
  called from `AppointmentViewSet.perform_create` per the rules in
  ADR 0011 (intake on first appointment ever; consent per service
  mapping; recurrence rule fences re-issue). Plus
  `email_signed_copy()` for operator-initiated PHI delivery via
  email — see ADR 0012.
- **[templates/forms/email/](templates/forms/email/)** — HTML +
  plain-text email templates for the signed-form-copy delivery.
  Plain-text fallback is required (accessibility + non-HTML
  clients); keep in sync with the HTML version.
- **[views.py](views.py)** — `FormTemplateViewSet` (CRUD; owner-only
  writes; version-bump on schema change; service-mapping replace),
  `FormSubmissionViewSet` (list / retrieve / void / email),
  `PublicFormSignView` (unauthenticated GET schema + POST sign with
  IP/UA capture).
- **[urls.py](urls.py)** — `/api/form-templates/`,
  `/api/form-submissions/`, `/api/forms/sign/<token>/`.
- **[admin.py](admin.py)** — Django admin for FormTemplate (with
  inline ServiceFormAssignment).
- **[tests.py](tests.py)** — 53 tests covering CRUD, JSON-schema
  validation, cross-tenant isolation, permission gating, version-
  bump semantics, audit log shape, auto-assignment rules, tenant-
  scoped list/detail/void, public token GET/POST/double-sign-409/
  voided-410, AND email send (HTML + text parts, audit-domain-only,
  rejects pending/voided/no-email, owner-only, cross-tenant 404,
  double-send creates two audit entries).

See:

- [ADR 0008 — Forms & e-signature data model](../../../docs/decisions/0008-forms-and-e-signature.md)
  for the template design (intake vs consent split, recurrence
  semantics, why schema validation lives in the serializer not the DB).
- [ADR 0011 — Form submissions, auto-assignment, and tokenized fill](../../../docs/decisions/0011-form-submissions-and-tokenized-fill.md)
  for the submission design (schema snapshot, auto-assignment rules,
  tokenized fill flow, public endpoint security).
- [ADR 0012 — Email infrastructure + signed-form copy](../../../docs/decisions/0012-email-infrastructure-and-signed-form-copy.md)
  for the email send design (BAA path via SES, dev console backend,
  why operator-initiated not auto-on-sign, audit-domain-only).

## Mental model

```
FormTemplate (tenant-scoped)
  ├── form_type: intake | consent     # discriminates assignment policy
  ├── recurrence: once | per_visit    # re-sign rule
  ├── schema: JSON                    # field definitions
  │   └── fields: [{id, type, label, required, ...}]
  ├── version: int                    # auto-bumps on schema change
  ├── is_active: bool                 # soft-delete
  └── service_assignments[]           # consent forms only
       └── ServiceFormAssignment      # (form, service) pairs

FormSubmission (Session 2)
  ├── form_template: FK
  ├── template_version_at_signing: int  # snapshot for historical legibility
  ├── customer: FK
  ├── appointment: FK (nullable — intake is per-customer, not per-appointment)
  ├── token: secret                   # tokenized fill URL
  ├── status: pending | completed | voided
  ├── answers: JSONB                  # PHI
  ├── signature_data: text            # base64 PNG of canvas signature
  ├── signed_at: datetime
  ├── ip_address, user_agent          # audit trail
  └── created_at, updated_at
```

## HIPAA + SOC 2 considerations

This app is the canonical example of HIPAA + SOC 2 thinking on the
product surface. Anything new here goes through the same review.

### What's covered today (Session 1)

- **Tenant isolation.** `FormTemplate` and `ServiceFormAssignment`
  inherit `TenantedModel` (ADR 0001). The viewset uses
  `for_current_tenant()` exclusively. Cross-tenant lookup via service
  mapping rejected explicitly with a 400 (see
  `validate_set_service_ids` in serializers.py).
- **Audit logging.** Every CREATE / READ / UPDATE on a template writes
  to `AuditLog` (`apps.audit.services.record`). Metadata captures
  `from_version` / `to_version` on schema changes so a SOC 2
  reviewer can answer "when did the consent text change and who
  approved it." See HIPAA §164.312(b), SOC 2 CC 7.2.
- **Soft-delete only.** No hard-delete API exposed —
  `http_method_names = ['get', 'post', 'patch', 'head', 'options']`.
  Submissions (Session 2) FK into templates and the audit trail must
  survive even after retirement. Operators set `is_active=false` to
  retire a template.
- **Permission gating.** Read open to anyone in the tenant (front
  desk needs to see what forms are configured); writes gated by
  `MANAGE_TENANT_SETTINGS` (owner-only by default). Mirrors the
  locations + business-profile API gating.
- **Schema integrity.** All field types validated; unknown types
  rejected; duplicate field-ids rejected; choice fields require
  ≥2 distinct options. Bad templates can't be saved → bad
  submissions can't be collected → no garbage in the chart record.
- **Version snapshotting** (Session 2 will use this). Submissions
  capture the template version at signing so historical signatures
  remain legible after the template evolves. SOC 2 CC 7.3 change-
  management coverage on PHI-collection forms.

### What's covered today (Sessions 2 + 3)

- **Token security.** `secrets.token_urlsafe(32)` (~256 bits).
  Single-use for SUBMISSION (status flips `pending` → `completed`
  exactly once; subsequent POSTs return 409). URL **path** placement
  (not query string, not fragment) per ADR 0011 — Django doesn't log
  path segments by name in standard access logs.
- **Immutable signatures.** Once `signed_at` is populated, `answers`
  and `signature_data` cannot be edited through the API. The void
  path is a separate transition that records `voided_at`,
  `voided_by`, `voided_reason` — voiding doesn't erase. SOC 2 CC 7.3
  change-management coverage.
- **Audit log on submission read.** Every detail read writes an
  `AuditLog` entry naming the user + customer. HIPAA §164.312(b)
  audit controls. Signing event (unauthenticated) writes an entry
  with `user=None` and IP + user-agent in metadata so the trail
  remains complete.
- **No PHI in audit metadata.** The signing event records
  `signature_bytes: <length>` and `ip_recorded: True` instead of the
  actual answers + signature. Audit log is itself queryable widely;
  PHI must not leak through it.
- **Schema snapshot on the submission.** Submissions don't query the
  live template at fill time — they render from the
  `schema_snapshot` captured at assignment. Pending submissions are
  protected from template edits; signed submissions stay legible
  even after the template evolves.

### What's still coming

- **Encryption at rest.** Submission `answers` + `signature_data`
  rely on Postgres TDE in production (Phase 0c). The application
  layer keeps PHI off URLs, query strings, and audit metadata.
- **Minimum-necessary access tier.** v1 detail endpoint is open to
  anyone authenticated in the tenant; refines to clinical-only
  (`VIEW_CLIENT_PHI` permission) when the permission catalog grows
  more granular. HIPAA §164.502(b).
- **Token expiry.** v1 tokens live forever (until status flips).
  Polish item: invalidate when the related appointment is cancelled
  or > N days past.
- **Frame-options + CSP** on the public route to block embedding
  attacks. Phase 0c middleware.
- **PDF generation** for signed submissions (server-side render,
  WeasyPrint or similar). Customer profile shows "Signed" today;
  downloadable PDF is a follow-up.

### What's deferred (Phase 0c production lift)

- **Postgres TDE** for at-rest encryption.
- **PHI field-hiding** for non-clinical roles on submission detail.
- **Audit-log immutability** via DB triggers (already in §4.5
  polish backlog from ADR 0004).
- **Per-tenant signed-PDF storage** in S3 with KMS encryption + BAA.

## Building on this

When adding new field types (image upload when S3 lands;
conditional logic in a polish pass), update both:

1. `serializers.ALLOWED_FIELD_TYPES` and `_validate_field`.
2. Frontend `lib/form-templates.ts:FIELD_TYPES`, `FormField`
   discriminated union, `defaultField()`, and the builder's
   per-field config UI.

The field type's render is the public fill page's concern (Session 2).
Keep validation in lockstep: every type the schema accepts must have
a fill renderer, otherwise customers will get blank forms.

## Starter template library

`/forms/new` shows a starter picker (cards for "Blank form" plus
intake + consent starters). Picking a starter routes to the same
builder pre-filled with the starter's schema. **Operator can edit any
field before saving** — starters aren't read-only, just defaults.

Starter content lives in `frontend/src/lib/form-template-starters.ts`
as TypeScript data. **No DB seeding** — adding / editing / removing a
starter is a content change, not a migration. Each tenant only ends up
with the templates they actually picked + customized + saved.

Current starters (v1):

| ID | Type | Recurrence | Notes |
|---|---|---|---|
| `general-intake` | intake | once | DOB, emergency contact, medical history checkboxes, allergies, medications, photo + cancellation acks. |
| `botox-consent` | consent | per_visit | Pregnancy / nursing screen, recent neurotoxin / blood thinners, risks checklist, aftercare ack. |
| `filler-consent` | consent | per_visit | HA filler-specific; covers vascular occlusion, reversal with hyaluronidase, cold-sore history. |
| `laser-consent` | consent | per_visit | Sun-exposure / Accutane / photosensitizing meds; eye-protection + post-treatment SPF acks. |
| `photo-release` | consent | once | Standalone marketing photo release; granular use-scope + face-visibility choices. |

**Legal framing.** Starters are STRUCTURAL templates with
common-knowledge medspa content. They're not legal documents. The
builder shows a yellow disclaimer banner whenever a starter is
loaded reminding the operator that the spa's medical director +
attorney must review the language before activating — informed-
consent requirements vary by state (CA, NY, FL all add disclosures
beyond the federal floor). This is intentional product positioning,
not a hedge: a one-size-fits-all consent form built into the
software would be malpractice-adjacent for the spa using it.

When adding a new starter:

1. Append to `STARTERS` in `form-template-starters.ts` with a stable
   `id` (no spaces; lowercase + hyphens — used in URL `?starter=`).
2. Use only field types the backend validator accepts.
3. End with a `signature` field (the actual signing block).
4. Match `recurrence` to the form's purpose (intake → `'once'`;
   clinical consent → `'per_visit'`).
5. Don't claim legal authority in field labels — keep it neutral
   ("I understand the risks…" not "I waive all rights…").
