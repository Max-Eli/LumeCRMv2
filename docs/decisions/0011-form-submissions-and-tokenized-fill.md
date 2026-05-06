# ADR 0011 — Form submissions, auto-assignment, and tokenized fill flow

## Status

Accepted (2026-05-03 — Phase 1D session 2/3 combined; written at design time per the discipline locked in after ADR 0008)

## Context

ADR 0008 established the form-template data model. This ADR covers
the per-customer materialization (`FormSubmission`), the
auto-assignment rules that create them from appointment bookings,
and the public tokenized fill flow that lets a client sign without
an account.

Three concrete questions to resolve:

1. **Snapshot the schema, or look it up live?** Form templates can be
   edited after submissions are issued. If a pending submission is
   filled tomorrow but the template was edited today, what does the
   client see?
2. **How does auto-assignment fire?** A signal on `Appointment`
   `post_save` is convenient but has nasty edge cases (fires from
   data migrations, hard to test, racy if used naively). Explicit
   service-function call from the appointment view is more code but
   cleaner semantics.
3. **What does the public fill URL look like?** Path token,
   query-string token, fragment token. Each has different audit /
   leakage / CSRF properties.

### HIPAA + SOC 2 framing

This is the first product surface that:

- **Collects PHI directly from the client** without the operator
  acting as an intermediary (medical history, treatment consent,
  signature-as-legal-attestation).
- **Exposes a public, unauthenticated endpoint** (the tokenized fill
  page). Tokens become the security boundary; the design must make
  them effectively unguessable.
- **Generates immutable signed records** that have legal weight (the
  client's signed consent IS the spa's evidence of informed consent
  if there's a complaint or lawsuit).

Specific HIPAA + SOC 2 obligations the design must address:

- **Audit log on every read of a signed submission**
  (HIPAA §164.312(b) "Audit controls" — every access to a patient's
  consent record needs to be traceable to a user + timestamp).
- **Audit log on every void / re-issue** (SOC 2 CC 7.2 "System
  monitoring" + HIPAA §164.312(c)(1) "Integrity").
- **Minimum-necessary access** (HIPAA §164.502(b)) — front desk
  needs to see a submission's STATUS to prompt the client; only
  clinical staff need to read the actual answers. Different scope
  per role on the detail endpoint vs the list.
- **Immutable signed records** (SOC 2 CC 7.3 "Change management") —
  once `signed_at` is populated, `answers` and `signature_data`
  cannot be edited. Only the void path can invalidate a record;
  voiding doesn't erase it.
- **Tenant isolation** (HIPAA §164.312(a)(1)) — submissions inherit
  `TenantedModel`. Cross-tenant leak via mis-typed token would be
  a reportable breach; the API filters tokens by tenant.

## Decision

**Submissions snapshot the schema at assignment time. Auto-assignment
runs as an explicit service-function call from the appointments
view (not a signal). Tokens go in the URL path of the public fill
endpoint — not query string, not fragment — for both audit-log
discoverability and operational simplicity. Signing transitions
status from `pending` to `completed` exactly once; subsequent POSTs
are rejected. Voiding is a separate transition that doesn't allow
re-signing the voided row.**

### Domain shape

| Field | Purpose |
|---|---|
| `form_template` | FK with `PROTECT` on delete. Submissions outlive template retirement; soft-delete via `is_active=False` on the template stops new auto-assignments without orphaning history. |
| `template_version_at_assignment` | Snapshot of `FormTemplate.version` at the time this submission was created. Audit + display ("signed against v3"). |
| `schema_snapshot` | Full snapshot of `FormTemplate.schema` at assignment. The fill page renders from this, never the live template. See the snapshot decision below. |
| `customer` | FK with `PROTECT`. PHI; tenant-scoped. |
| `appointment` | FK with `PROTECT`, nullable. Intake forms aren't tied to a specific appointment — the customer's first appointment ever triggers them, but the submission lives at the customer level (so renaming the appointment or rescheduling doesn't unmoor the consent). Consent submissions ARE tied to an appointment for chart-review traceability. |
| `token` | Default-generated via `secrets.token_urlsafe(32)` (~256 bits). Unique + indexed. Bearer credential for the public fill page. |
| `status` | `pending` → `completed` OR `pending` → `voided`. No other transitions. |
| `answers` (PHI) | JSONB keyed by field id from the schema snapshot. Empty `{}` until completed. Detail endpoint gates this read behind clinical role. |
| `signature_data` (PHI) | Base64-encoded PNG of the canvas signature. Empty until completed. Same gating as `answers`. |
| `signed_at`, `ip_address`, `user_agent` | Audit trail of the signing event. Captured server-side from the request, never trusted from the payload. |
| `voided_at`, `voided_by`, `voided_reason` | Void audit. `voided_reason` required at the API layer. |

### Schema snapshot vs live lookup

Snapshot wins decisively. Reasons:

- **Pending submission predictability.** Client fills out a form on
  Tuesday. Operator edits the template on Wednesday. Client signs on
  Thursday. The client signs what they were promised — not what the
  operator changed mid-flight.
- **Signed submission integrity.** A signed consent's evidentiary
  value depends on showing exactly what the client agreed to.
  Re-rendering a signed submission against a newer template version
  could change field labels, add fields, remove fields — destroying
  the chain of evidence.
- **No version-history table needed.** We could rebuild "what was
  the schema at version N" by keeping a separate `FormTemplateVersion`
  table, but that's two tables of state to keep in sync with one
  table that just snapshots inline.

Trade-off: storage cost. A 10-field form schema is ~2 KB per
submission. 1000 customers × 5 forms each = ~10 MB. Acceptable.

### Auto-assignment via explicit service call

**`forms.services.assign_forms_for_appointment(appointment)`** is
called from `AppointmentViewSet.perform_create` AFTER the appointment
is saved + the audit log entry is written. Logic:

1. **Intake forms.** Check whether this is the customer's first
   appointment ever in this tenant (`Appointment.objects.filter(
   tenant=tenant, customer=customer).exclude(pk=appointment.pk).exists()`).
   If first ever, for each active intake template:
   - Skip if a `completed` submission of this template already exists
     for this customer (recurrence='once' fence — handles the case
     where the customer is being re-onboarded after a Zenoti import).
   - Otherwise create a new pending submission, snapshot the schema.
2. **Consent forms.** For the appointment's service, look up
   `ServiceFormAssignment` rows pointing at active consent templates.
   For each:
   - If recurrence='once' AND a completed submission of this template
     exists for this customer, skip.
   - If recurrence='per_visit', always create a new pending submission.

**Why explicit, not signal:**

- Tested in isolation with a unit test.
- Tests that create appointments via fixtures don't accidentally
  create submission rows.
- Easy to call from elsewhere (e.g. operator manually re-issues a
  voided form via the customer chart in Session 3).
- No surprise behavior in data migrations or shell sessions.

**Race conditions:** the "first appointment ever" check is racy if
two appointments are booked concurrently. Both could trigger intake
assignment. Mitigation: defensive uniqueness check at creation —
"don't create another pending intake submission if one already
exists for this customer." The rule isn't "exactly one" but
"at most one pending and not already signed once."

### Public fill flow

Public route: `/api/forms/sign/<token>/` with two methods:

- **GET** — load the schema snapshot + status (and answers if
  completed, since the operator viewing-the-signed-form flow goes
  through the same URL). Skips the customer's PHI in the payload
  for unauthenticated callers; the public client only needs the
  schema + their answers (which they're about to fill).
- **POST** — submit answers + signature data. Captures IP from
  `X-Forwarded-For` (or `REMOTE_ADDR` fallback) and user-agent.
  Validates answers against the schema snapshot's required fields.
  Atomic transition `pending` → `completed`; subsequent POSTs to
  the same token reject with 409.

**No auth required, CSRF-exempt.** The token IS the security
boundary. Adding CSRF on top would require either a session (which
defeats "no account") or a separate fetch-then-submit dance that
doesn't add real protection — an attacker who knows the token can
already submit. CSRF protects against cross-origin attacks where
the attacker DOESN'T know the secret; here the secret is the URL.

**URL path placement, not query string.** Query strings appear in
nginx access logs by default; path segments don't appear by name in
log lines. Fragments don't get sent to the server at all (so the
server can't validate). Path is the right home.

**Token expiry: deferred.** v1 tokens live forever (until status
flips). Polish item: invalidate when the related appointment is
cancelled or > 30 days past. Not blocking launch — a stale link to a
voided form just shows the void status.

### Detail-endpoint access tiers (Session 3)

Read scope on `/api/form-submissions/{id}/`:

- **Status, template name, customer name, signed_at, voided_at** —
  open to anyone in the tenant (front desk needs the prompt-the-
  client signal).
- **`answers`, `signature_data`** — gated behind `VIEW_CLIENT_PHI`
  (clinical roles + the customer's assigned provider on the
  appointment). HIPAA §164.502(b) minimum-necessary.

For v1 (Session 3), the simpler split: owner+manager+provider can
read everything; front-desk gets status only. Refine when the
permission catalog needs more granularity.

### Audit log shape

| Event | `action` | Metadata |
|---|---|---|
| Submission created (auto-assigned) | `CREATE` | `{template_id, template_version, customer_id, appointment_id, trigger: 'intake_first_appt' | 'consent_per_service'}` |
| Submission read (operator viewing details) | `READ` | `{customer_id}` |
| Submission signed (public fill page) | `UPDATE` | `{from_status: 'pending', to_status: 'completed', ip_recorded: True, signature_bytes: <length>}` — no PHI in metadata. |
| Submission voided | `UPDATE` | `{from_status: 'pending' | 'completed', to_status: 'voided', reason}` |

The signing event's audit-log entry has NO authenticated user (the
client isn't logged in). `apps.audit.services.record` accepts
`user=None`; the IP + user-agent in the metadata are the audit trail
the SOC 2 reviewer relies on.

## Consequences

### Pros

- **Schema snapshot decouples templates from in-flight submissions.**
  Operators can edit freely without breaking pending forms or
  invalidating signed history.
- **Token-only public flow** lets the front-desk iPad workflow work
  identically to the email-link workflow — same URL, no special
  "in-office" code path. (The "Open for signing" button is just a
  fancy way to load the same URL on a local browser.)
- **Auto-assignment is testable in isolation** — the service
  function takes an appointment, returns the created submissions.
  No `post_save` voodoo.
- **Audit trail captures the unauthenticated signing event**
  meaningfully (IP + user-agent + timestamp) so SOC 2 + HIPAA
  reviewers can answer "this signature exists; who signed it from
  where" even though no user account was involved.
- **PHI access tiers are explicit** in the design, not retrofitted.

### Cons

- **Tokens never expire in v1.** A bookmarked old fill link points
  at a voided submission and shows the void state — informational
  but a polish item.
- **Schema snapshot duplicates storage.** ~2 KB per submission
  acceptable at v1 scale.
- **Cross-origin embed risk on the public fill page is unmitigated.**
  An attacker could embed `/forms/sign/<token>` in an iframe on
  another site to capture clicks. Polish: `X-Frame-Options: DENY`
  + `Content-Security-Policy: frame-ancestors 'none'` on the public
  route. Tracked.
- **No re-issue UX in Session 2** — operator has to void + manually
  trigger a new submission. Session 3 polish item.

### Production lift

- **Postgres TDE** for at-rest encryption of `answers` +
  `signature_data` (Phase 0c).
- **Token expiry policy** + cleanup job (when reasonable to
  invalidate "old" pending submissions — e.g. > 90 days past the
  related appointment).
- **Frame-options + CSP headers** on the public route (Phase 0c
  middleware).
- **Audit log retention + immutability** applies same as elsewhere.
- **PDF generation** for signed submissions (Session 3 follow-up;
  needs a server-side renderer like WeasyPrint).

## References

- [ADR 0008 — Forms data model](./0008-forms-and-e-signature.md)
- [ADR 0001 — Multi-tenancy strategy](./0001-multi-tenancy-strategy.md)
- [ADR 0004 — Audit logging](./0004-audit-logging.md)
- [apps.forms README](../../backend/apps/forms/README.md)
- HIPAA Security Rule §164.312(a)(1) — Access control
- HIPAA Security Rule §164.312(b) — Audit controls
- HIPAA Security Rule §164.312(c)(1) — Integrity
- HIPAA Privacy Rule §164.502(b) — Minimum-necessary access
- SOC 2 Trust Services Criteria CC 7.2 — System monitoring
- SOC 2 Trust Services Criteria CC 7.3 — Change management
