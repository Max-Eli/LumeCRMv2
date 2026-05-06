# ADR 0015 — Clinical chart notes (Phase 4A, sessions 1–2)

## Status

Accepted (2026-05-04 — Phase 4A session 1; written at design time
per the discipline locked in for PHI-bearing surfaces).
Extended 2026-05-05 with session 2 (addenda + voiding) — see
"Session 2 — Addenda and voiding" at the bottom of this document.

## Context

Medical spas keep two kinds of records on a customer:

1. **Operational** — appointments, invoices, notes from the front
   desk ("birthday cake to the room", "VIP — extra time"). These
   are everyone's-business; front desk + provider + manager all
   read and write.
2. **Clinical** — what the provider observed during a treatment,
   what they administered, dose / lot / site, post-op care
   instructions, complications. This is the chart record. It's
   PHI in the strongest sense (treatment history tied to identity)
   and HIPAA's documentation + integrity rules apply.

We have operational notes today on `Appointment.notes`. We don't
have a clinical chart record. Without one, providers either
(a) keep paper / Word docs that defeat the "single system of
record" pitch, or (b) cram clinical detail into appointment notes
that front desk can read — neither acceptable for a med-spa CRM
that wants to compete against Boulevard, Modmed, AestheticsPro.

This ADR covers session 1 of Phase 4A: a **provider-only
timestamped notes thread** on the customer profile. Sessions 2+
add structured templates (SOAP / CC-HPI-ROS), per-appointment
treatment records, photo support, and co-signing workflows. Those
are out of scope here.

### HIPAA + SOC 2 framing

This is the first surface that:

- **Distinguishes clinical access from general-staff access.** Up
  to now, anyone authenticated in the tenant could see anything
  PHI-bearing. Chart notes need a tighter gate — front desk must
  not read clinical notes even though they're in the same tenant.
- **Treats individual records as legally significant.** A signed
  chart note is the spa's defense in a malpractice complaint.
  Edits after the fact undermine that — the integrity property is
  what makes the record valid evidence.

Specific HIPAA + SOC 2 obligations:

- **§164.502(b) Minimum-necessary**: chart notes are clinical PHI;
  the access tier here is narrower than the rest of the customer
  profile. Front desk gets `VIEW_CLIENT_LIST` but NOT `VIEW_CHART`.
- **§164.312(b) Audit controls**: every read of a chart note is
  audit-logged. Reads by clinical staff are part of treatment;
  reads by managers (oversight) need to be distinguishable in the
  trail so a compliance reviewer can answer "who looked at this
  patient's treatment record."
- **§164.312(c)(1) Integrity**: signed chart notes are immutable
  after a short typo-correction window. Amendments are addenda
  (separate rows; future session), not in-place edits. Voiding is
  a separate transition that doesn't erase.
- **§164.526 Right to amend**: HIPAA gives the patient a right to
  request amendment of their record. The amendment workflow lands
  with addenda in a future session. v1 captures the integrity
  primitive (immutability after window) so the v2 amendment work
  has a solid base.
- **SOC 2 CC 7.3 Change management**: the provider who signed the
  note is the only one who can edit it within the window. No
  proxy / delegate edits.

## Decision

**A `ChartNote` model attached per-customer, optionally per-
appointment. Notes are append-only after a 1-hour typo-correction
window. Read access requires `VIEW_CHART`; write access requires
`SIGN_CHART`; both granted to the `provider` role by default.
Owner + manager get all permissions including these. Front desk
is explicitly excluded. Every read writes an audit log entry.
Amendments and voids land in future sessions; v1 captures the
data + access primitives.**

### Domain shape

```python
class ChartNote(TenantedModel):
    customer = FK(Customer, on_delete=PROTECT)
    appointment = FK(Appointment, null=True, on_delete=SET_NULL)
    # Why SET_NULL on appointment: we don't want a deleted
    # appointment to take its chart record with it. The clinical
    # record outlives the operational reason it was written.

    body = TextField()  # PHI

    author = FK(TenantMembership, on_delete=PROTECT)
    # Author's clinical-flag at the moment of signing. We snapshot
    # because a provider may later switch job titles (move from
    # 'Aesthetician' to 'Nurse Practitioner'); the legal status of
    # the record at signing time is what matters for the audit.
    author_was_clinical = bool

    signed_at = DateTimeField(auto_now_add=True)  # immutable after creation
    edit_window_ends_at = DateTimeField()  # signed_at + 60 min
    locked = bool  # computed in serializer + UI; not stored

    is_voided = bool = False
    voided_at, voided_by, voided_reason  # populated on void path

    created_at, updated_at
```

No content versioning in v1. The body is editable until
`edit_window_ends_at`; after that, the API rejects edits. If the
provider needs to add to a locked note, they write a new note
that references the same appointment (or same customer, no
appointment). When addenda land, they'll be separate rows
linking back to the original via `parent_note` FK.

### Permission tier

| Action | Required permission | Default holders |
|---|---|---|
| List / read | `VIEW_CHART` | provider, owner, manager |
| Create | `SIGN_CHART` | provider, owner, manager |
| Edit (within window) | `SIGN_CHART` (and must be the original author) | author only |
| Void | `EDIT_SIGNED_CHART` (separate, owner/manager only) | owner, manager |

Front desk: no chart access. Marketing: no chart access.
Bookkeeper: no chart access. They can see the customer profile
but the Notes tab returns empty + a "you don't have access"
state — same posture as the financial reports card on the
calendar (lock icon, brief explainer, no error noise).

### Edit window: 60 minutes, then locked

60 minutes is enough for typo correction during a session — a
provider finishing a treatment writes the note, realizes they
mis-typed the dose, and fixes it within the visit. After that,
the legal posture is "this is what was signed at the time." 24
hours is too long; 5 minutes is too short. 60 is the established
medical-records middle ground (Epic uses ~12 hours, Athena uses
~24, smaller systems use 30-60 min).

This is intentionally NOT configurable per-tenant. If a tenant
asks for "we want to edit charts forever," we explain why we
won't: the integrity property is what makes the record useful
evidence in a complaint. SOC 2 CC 7.3 + medical-records best
practice override operator preference here.

### Eligibility: not gated to "providers who saw this customer"

ADR 0003 set up role-based permissions, not relationship-based.
A provider with `VIEW_CHART` can read any customer's notes within
their tenant. v2 may refine to "providers who have an appointment
with this customer in the last N days" — that's a real
minimum-necessary tightening — but for v1 the role gate is the
boundary.

The audit log is the compensating control: every chart read
writes an entry, so a compliance reviewer can spot patterns of
abuse (a provider browsing many unrelated customer charts).

### Audit log shape

Every read writes:

```
AuditLog(
  action=READ,
  resource_type='chart_note',     # detail
  # OR  'chart_note_list',        # list per customer
  resource_id=<note_id>,          # for detail; absent for list
  user=request.user,
  tenant=request.tenant,
  metadata={
    'customer_id': <id>,
    'appointment_id': <id or null>,
    # NO 'body' or excerpt — the body lives on the row, not the log
  },
)
```

Every create / edit writes:

```
AuditLog(
  action=CREATE | UPDATE,
  resource_type='chart_note',
  resource_id=<note_id>,
  user=request.user,
  tenant=request.tenant,
  metadata={
    'customer_id': <id>,
    'appointment_id': <id or null>,
    'body_length_chars': <int>,    # length, not content
    'editing_within_window': bool, # for UPDATE
  },
)
```

The audit log itself is queryable across roles broader than the
chart access; PHI must not leak through it. Body length captures
"non-empty / substantive" without recording the content.

### Per-appointment optional linkage

A note may attach to a specific appointment (`appointment_id`
populated) or be a standalone clinical observation (null). The
attached form is the common case: "this is the chart record for
the Botox treatment on May 11." Standalone notes are for between-
visit context: "client called about hyperpigmentation, will
discuss at next visit."

`SET_NULL` on appointment delete: clinical records outlive the
operational reason they were written. A deleted appointment (rare
— soft delete is preferred) shouldn't cascade-orphan the chart.

## Consequences

### What's covered today (Session 1)

- Append-only model with 60-min typo-correction window.
- Permission gating on read + write, separate from
  `VIEW_CLIENT_PHI` (charts are tighter than the customer
  profile).
- Author snapshot of clinical-flag at signing time so a future
  job-title change doesn't muddy the legal status of past records.
- Audit log on every read + write, body-length only (no PHI in
  metadata).
- Tenant scoping via `TenantedModel`; cross-tenant lookup
  rejected.
- Per-customer thread sorted by signed_at descending (newest
  first — provider's eye lands on the most recent treatment).
- API: list per customer, create, retrieve, amend (within window
  only). No void in v1 — that's session 2 with the addendum work.

### What's deferred to future sessions of 4A

- **Addenda** — when a locked note needs amendment, the
  addendum gets a separate row with `parent_note_id`. UI shows
  it threaded under the original.
- **Voiding** — `EDIT_SIGNED_CHART` permission unlocks a void
  transition that marks the note as invalidated (excluded from
  clinical reads) but leaves the row in the audit trail.
- **Templates** — SOAP / CC-HPI-ROS / treatment-record forms.
  Free-form text is v1; structured templates are session 3.
- **Per-appointment treatment records** — separate model with
  dose / lot / site / vendor specifics for injectables and
  laser. Session 4.
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
  product principle, not a polish item.
- **In-place version history.** No `body_v1, body_v2, body_v3`.
  The within-window edit is a single row update; once locked,
  the body is the body. Addenda capture all subsequent context.
- **Bulk-export to outside EHRs.** Lumè is not an EHR; we do not
  speak HL7 / FHIR / DICOM. If a med-spa wants to integrate with
  a real EHR, that's an integration phase (Phase 7+) not a v1
  feature.

## See also

- [ADR 0001 — Multi-tenancy strategy](0001-multi-tenancy-strategy.md)
  for `TenantedModel` + `for_current_tenant()`. Chart notes
  inherit it; cross-tenant lookup is impossible.
- [ADR 0003 — Permission model](0003-permission-model.md) for
  the role-based gate this ADR layers on. `VIEW_CHART` and
  `SIGN_CHART` already exist in the catalog from day one;
  `EDIT_SIGNED_CHART` exists for the future void/amend path.
- [ADR 0004 — Audit logging](0004-audit-logging.md) for the
  shape of `AuditLog` entries this ADR uses. Every chart read
  writes one with PHI-free metadata.
- [ADR 0011 — Form submissions and tokenized fill](0011-form-submissions-and-tokenized-fill.md)
  for the immutable-record posture this ADR mirrors. Form
  submissions and chart notes are both legally-significant;
  same reasoning applies.

---

## Session 2 — Addenda and voiding (2026-05-05)

Session 1 shipped a chart record that locks 60 minutes after
signing and never moves again. That left a real correctness gap:
**a provider who realizes 90 minutes later they wrote the wrong
dose has no recourse.** Writing a free-standing note that says
"previous note had wrong dose" is not equivalent to a properly
threaded amendment — a compliance reviewer scrolling the chart
sees the original incorrect note unchanged.

This session closes the gap with two paired primitives:

1. **Addenda** — any clinical signer can attach a follow-up note
   to a locked parent. The addendum is its own row with its own
   60-min edit window, threaded under the parent in the UI. This
   is the **ordinary corrective workflow** — "actually, the dose
   was 0.5mL not 5mL."

2. **Voiding** — owner / manager can mark a note as invalidated
   with a reason. The note remains in the database (audit trail)
   but is excluded from clinical reads by default and renders
   struck-through in the UI. This is the **escape hatch for
   serious errors** — wrong patient, malicious entry, fundamental
   mistake.

### Why addenda are SIGN_CHART, not EDIT_SIGNED_CHART

Addenda are the everyday correction path. Forcing a provider to
get a manager's blessing every time they need to clarify a chart
note would be hostile to the workflow and would push providers
back to "I'll just write a freestanding note and hope someone
notices it relates" — exactly the failure mode this is trying to
solve.

The provider's name + clinical-flag-snapshot are captured on
every addendum independently, so the audit trail still answers
"who wrote what and when" even though no manager approved the
amendment. SOC 2 CC 7.3 change-management is satisfied by the
audit trail + the immutability of each individual row, not by a
multi-actor approval workflow.

### Why voiding is EDIT_SIGNED_CHART, not SIGN_CHART

Voiding marks a record as "this should never have existed." That's
a stronger statement than "I want to add context" and warrants a
heavier gate. By default `EDIT_SIGNED_CHART` is owner+manager only
(it was already in the permission catalog from day one but
unassigned to roles).

Solo NPs running their own spas naturally hold the owner role and
can self-void; that's fine. Multi-provider clinics get the
two-actor pattern by default — the provider who made the error
flags it to the manager, who reviews and voids.

### Domain shape additions

```python
class ChartNote(TenantedModel):
    # ... existing fields ...

    # Addendum chain. Self-referential FK; null for top-level notes.
    parent_note = FK('self', null=True, on_delete=PROTECT,
                     related_name='addenda')
    # PROTECT (not CASCADE): if the parent is deleted (which can
    # only happen at the DB level — there's no DELETE endpoint),
    # the addenda must be cleaned up first. The addenda are
    # standalone signed statements; orphaning them would lose
    # authorship attribution.

    # Void state.
    is_voided = BooleanField(default=False)
    voided_at = DateTimeField(null=True, blank=True)
    voided_by = FK(TenantMembership, null=True, blank=True,
                   on_delete=SET_NULL, related_name='voided_chart_notes')
    voided_reason = CharField(max_length=500, blank=True, default='')
```

No new content versioning. The within-window edit semantics
established in session 1 still apply to addenda — each addendum
has its own 60-min window relative to its own `signed_at`.

### Threading rules

- An addendum's `parent_note` must belong to the same tenant +
  same customer. Cross-tenant references rejected explicitly in
  the create handler.
- The parent must be **locked** (i.e. past its own edit window).
  If the parent is still editable, the provider should just edit
  the parent — addenda exist for the locked case. Returns 400
  with a clear message: "Edit the original note instead — it's
  still in the typo-correction window."
- The parent must NOT be voided. A voided note is invalidated;
  attaching new context to it would muddle whether the addendum
  is also invalidated. If the parent should be amended after a
  void, that's a fresh top-level note. Returns 400.
- Addenda CANNOT have addenda (no nested chains). One level of
  depth keeps the threading legible. If a clinical thought needs
  multiple corrective passes, write multiple addenda on the same
  parent.

### Voiding rules

- A note cannot be voided within its edit window — within the
  window, the original author edits in place. After the window
  locks, voiding becomes available. Returns 400 if attempted on
  an editable note.
- A `reason` is required. Stored verbatim on `voided_reason` and
  surfaced on the voided note's UI so a clinical reviewer
  understands why it was struck.
- Voiding is one-way. There is no "un-void" — restoring a voided
  note would defeat the integrity property. If a void was a
  mistake, the operator writes a NEW note that explains and
  references the voided record.
- Voiding the parent does NOT cascade to its addenda. Each
  addendum is a separately-authored statement; voiding the
  parent doesn't retroactively invalidate them. They remain
  visible (with the parent struck-through above them) so a
  reviewer can interpret what actually happened.
- Already-voided notes return 400 on a second void attempt. The
  voider doesn't get to overwrite the original `voided_reason`.

### List-endpoint behavior

The list endpoint returns a flat array — addenda come back as
separate top-level entries with `parent_note_id` populated. The
frontend groups client-side. Reasons:

- One serializer shape, one query path. Nesting would require a
  prefetch join + a special `addenda` field on the parent
  serializer, both adding complexity for marginal benefit.
- Pagination doesn't break — with a nested-children shape,
  pagination of children gets awkward.
- The frontend's group-by-parent is a one-liner with `Map`.

By default, voided notes ARE included in list responses with
`is_voided=true` so the UI can render the strikethrough. A
`?include_voided=false` query param lets a clinical view filter
them out for the everyday treatment-history read.

### Audit log additions

Addendum CREATE writes:
```
AuditLog(
  action=CREATE,
  resource_type='chart_note',
  resource_id=<addendum_id>,
  metadata={
    'event': 'addendum_created',
    'parent_note_id': <parent_id>,
    'customer_id': <id>,
    'body_length_chars': <int>,
    'author_was_clinical': bool,
  },
)
```

Void writes:
```
AuditLog(
  action=UPDATE,
  resource_type='chart_note',
  resource_id=<note_id>,
  metadata={
    'event': 'voided',
    'reason': '<reason>',         # the reason IS recorded — it's
                                  # not PHI; it's an operator
                                  # justification for a state change.
    'parent_note_id': <id or null>,
    'customer_id': <id>,
  },
)
```

The voided reason is in metadata because it's an operator-
authored justification (think "wrong patient", "malicious entry",
"signed in error"). It's not patient-PHI in the same sense as the
note body. The body itself remains absent from audit metadata.

### Permission additions

| Action | Required permission | Default holders |
|---|---|---|
| Create addendum | `SIGN_CHART` | provider, owner, manager |
| Void note | `EDIT_SIGNED_CHART` | owner, manager (already in catalog) |

`EDIT_SIGNED_CHART` was reserved in the permission catalog from
day one but never actually used by any role's defaults — it was
only granted via the `ALL_PERMISSIONS` set that owner + manager
receive. Session 2 wires it into the void endpoint as the gate.

### What's still deferred (Session 3+)

Voiding cascade rules — should voiding a parent void its addenda?
v1 says no (each is independently authored). Larger clinics may
want the cascade as policy. Add a `void_addenda_too` flag to the
void payload in a future session if customer feedback says so.

Patient-facing amendment requests (HIPAA §164.526) — a patient
can request amendment of their record. v1 has no patient-facing
surface for this; comes with the patient portal in Phase 7+.
