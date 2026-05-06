# apps.charts

Clinical chart notes — provider-only treatment records. The first
product surface that distinguishes **clinical** access from
general-staff access. Front desk, bookkeeper, and marketing roles
do NOT read or write chart notes even though they're authenticated
in the same tenant.

**Sessions shipped:**
- **Session 1** — append-only notes thread with 60-min typo-correction window.
- **Session 2** — addenda (clinical-signer correction workflow) + voiding (owner/manager invalidation with reason).

Still to come in later sessions of Phase 4A: structured templates
(SOAP / CC-HPI-ROS), per-appointment treatment records (dose / lot
/ site), photos, and co-signing.

## What's in here

- **[models.py](models.py)** — `ChartNote`. Append-only after a
  60-min typo-correction window. Carries an
  `author_was_clinical` snapshot so a later job-title change
  doesn't muddy the legal status of past records. `appointment`
  FK is optional (`SET_NULL` on delete) — clinical records
  outlive the operational reason they were written.
- **[serializers.py](serializers.py)** — `ChartNoteSerializer`
  (read shape; denormalized author identity), plus
  `ChartNoteCreateSerializer` (initial signing) and
  `ChartNoteUpdateSerializer` (within-window edit; rejects any
  field that isn't `body`).
- **[permissions.py](permissions.py)** — `ChartNoteReadPermission`
  gates list / retrieve on `VIEW_CHART`;
  `ChartNoteWritePermission` adds `SIGN_CHART` for create / edit.
  Edit-window + author-ownership are not in the permission class —
  they're per-record, enforced by the view + the model
  (`ChartNote.can_be_edited_by`).
- **[views.py](views.py)** — `ChartNoteViewSet` exposing list /
  create / retrieve / patch. Plus session 2 actions:
  - `POST /api/chart-notes/<id>/addendum/` (`SIGN_CHART`) — sign
    an addendum on a locked, non-voided parent. Inherits
    customer + appointment from the parent.
  - `POST /api/chart-notes/<id>/void/` (`EDIT_SIGNED_CHART`) —
    invalidate a locked note with a reason. One-way; the row
    survives.

  DELETE intentionally not exposed; the void path is the
  invalidation primitive.
- **[urls.py](urls.py)** — `/api/chart-notes/`.
- **[tests.py](tests.py)** — 35 tests across both sessions:
  - **Session 1 (17 tests):** permission gating (anonymous /
    front-desk / provider / owner), tenant scoping, clinical-flag
    snapshot semantics, edit-window enforcement (within window,
    after window, non-author), audit-log shape (PHI-free
    metadata), patch-rejects-non-body-fields.
  - **Session 2 (18 tests):** addendum threading rules (locked
    parent only, not-voided parent only, no nested addenda,
    cross-author allowed), addendum permission gating (front-desk
    blocked), void rules (owner/manager only, locked notes only,
    reason required, double-void rejected, voided-cannot-be-
    edited), `?include_voided=false` filter, audit-log carries
    parent_note_id + reason but never the body content.

See:

- [ADR 0015 — Clinical chart notes](../../../docs/decisions/0015-clinical-chart-notes.md)
  for the full design rationale, HIPAA + SOC 2 framing, and
  intentionally-deferred items.
- [ADR 0003 — Permission model](../../../docs/decisions/0003-permission-model.md)
  for the role-based gate this module layers on.
- [ADR 0004 — Audit logging](../../../docs/decisions/0004-audit-logging.md)
  for the shape of `AuditLog` entries this module writes.

## Mental model

```
ChartNote (per-tenant)
  ├── customer: FK PROTECT          # the patient
  ├── appointment: FK SET_NULL?     # optional treatment-of-record
  ├── body: text                    # PHI; free-form (templates land later)
  ├── author: FK TenantMembership PROTECT   # who signed
  ├── author_was_clinical: bool     # snapshot at signing time
  ├── signed_at: datetime           # auto_now_add; never updated
  ├── (computed) edit_window_ends_at = signed_at + 60min
  ├── (computed) is_locked = now >= edit_window_ends_at
  ├── parent_note: FK self?         # set on addenda; null on top-level
  ├── is_voided: bool               # invalidated by owner/manager
  ├── voided_at, voided_by, voided_reason   # populated on void
  └── created_at, updated_at
```

Lifecycle:

```
                                ┌──► Locked (forever)
                                │       │
Sign  ──►  Editable (≤60 min,  ─┤       ├──► Addendum chain
            author only)        │       │     (each is its own note,
                                │       │      with its own 60-min window)
                                │       │
                                │       └──► Voided (one-way; row survives)
                                │
                                └──► Edit in place (author only)
```

Threading: addenda are flat in the API (each carries
`parent_note_id`); the UI groups them under the parent client-side
in chronological order. Voiding the parent does NOT cascade — each
addendum is an independently-authored statement.

## HIPAA + SOC 2 considerations

This is the first product surface that **distinguishes clinical
access from general-staff access**. Up to now, anyone authenticated
in the tenant could see anything PHI-bearing. Chart notes need a
tighter gate.

### What's covered today (Sessions 1 + 2)

- **Two-tier permission gate.** `VIEW_CHART` for read (provider,
  owner, manager). `SIGN_CHART` for write (same default holders,
  kept separate so a future "read-only clinical reviewer" role can
  hold VIEW without SIGN). Front desk + bookkeeper + marketing get
  403 from the API and a "no access" UI on the Notes tab — by
  design (HIPAA §164.502(b) minimum-necessary).
- **Append-only after 60 min.** Provider can edit their own note
  for typo correction during the visit; after 60 min, the API
  rejects edits. Other providers (even clinical ones) cannot edit
  someone else's note — only the original author can. This is
  HIPAA §164.312(c)(1) integrity + SOC 2 CC 7.3 change-management
  posture on PHI records.
- **Author clinical-flag snapshot.** `author_was_clinical` stores
  whether the author held a clinical job title at signing time.
  A provider may switch job titles later (RN promoted to NP, or
  moved out of clinical roles). The legal status of the record
  is what was true when it was signed; the snapshot anchors that.
- **Audit log on every read.** Detail reads write
  `resource_type='chart_note'`, list reads write
  `resource_type='chart_note_list'`. User + tenant + IP + UA
  captured. HIPAA §164.312(b) audit controls. No PHI in metadata
  — the body lives on the row, not the log.
- **Audit log on every write.** Create + edit write entries with
  `body_length_chars` instead of the body itself. Editing-within-
  window writes `editing_within_window: true`. Tests pin this:
  the actual body content does not appear in any audit metadata.
- **Tenant isolation belt + suspenders.** `TenantedModel` +
  `for_current_tenant()` on the queryset; cross-tenant FKs in
  POST payloads return 400 with a generic "not found" message
  (no leak). Object-level permission re-checks tenant on
  retrieve.
- **No DELETE endpoint.** Soft-state via the void path; v1 has no
  way to hard-delete a chart note, preserving the audit trail.
- **Addenda** for locked notes (Session 2). Any clinical signer
  can add. Parent must be locked + not voided + not itself an
  addendum. One level of nesting only.
- **Voiding** (Session 2) — owner / manager via
  `EDIT_SIGNED_CHART`. Locked-only, reason required, one-way.
  Voiding the parent does NOT cascade to addenda (each is
  independently authored). Voided notes excluded from
  `?include_voided=false` reads but rendered struck-through by
  default.

### What's deferred to future sessions of 4A

- **Templates** — SOAP / CC-HPI-ROS / treatment-record forms.
  Free-form text is v1; structured templates are session 3.
- **Per-appointment treatment records** — separate model with
  dose / lot / site / vendor specifics. Required for compliant
  injectables documentation. Session 4.
- **Photo support** — before/after photos linked to chart notes.
  Big infrastructure lift (S3 + KMS + thumbnail generation).
  Session 5+ with `apps.gallery`.
- **Co-signing** — supervising NP / MD review + sign-off on RN
  charts. Phase 4 polish.
- **Patient export** — HIPAA gives the patient right of access
  (§164.524). PDF export of all chart records for a customer.
  Polish; needs WeasyPrint / similar.

### What's deferred to Phase 0c (production lift)

- **Encryption at rest.** Chart bodies rely on Postgres TDE.
  Application layer keeps PHI off URLs, query strings, audit
  metadata. Already in §4.5 backlog.
- **Audit-log immutability** via DB triggers (already in §4.5
  per ADR 0004).

### What's permanently out of scope for v1

- **Editing locked notes.** A locked note is locked. Provider
  needs to add an addendum, not retroactively rewrite. This is a
  product principle, not a polish item — it's what makes the
  record useful evidence.
- **In-place version history.** No `body_v1, body_v2, body_v3`.
  The within-window edit is a single row update; once locked,
  the body is the body. Addenda capture all subsequent context.
- **Bulk-export to outside EHRs.** Lumè is not an EHR; we don't
  speak HL7 / FHIR / DICOM. EHR integrations are Phase 7+.

## Building on this

When adding structured templates (Session 3):

1. Add a `template` FK on `ChartNote` pointing to a new
   `ChartNoteTemplate` model with a JSON schema (mirror the form-
   templates pattern in `apps.forms`).
2. The body becomes structured `answers` JSON when a template is
   set, free-form `body` when null.
3. Validation in the create serializer rejects answers that don't
   match the template schema.
4. Frontend renders the template as a structured form rather than
   a plain textarea.

When adding per-appointment treatment records (Session 4):

1. New `TreatmentRecord` model — separate from `ChartNote`. Tied
   to a specific appointment with structured fields for dose,
   lot, site, vendor, expiration, photo refs.
2. Appointment popover gets a "Treatment record" action that
   opens a sheet for the provider to fill out at-or-after the
   visit.
3. Treatment records are PHI-tier `per_customer` and follow the
   same lock-after-window + addendum + void semantics as
   `ChartNote`.

When adding co-signing (Phase 4 polish):

1. Add `cosigned_by`, `cosigned_at` to `ChartNote`.
2. Add `requires_cosign` flag based on the author's job title
   (e.g. RN-signed notes require an NP/MD co-sign in some states).
3. Manager approval queue surfaces uncosigned notes ranked by
   age.
