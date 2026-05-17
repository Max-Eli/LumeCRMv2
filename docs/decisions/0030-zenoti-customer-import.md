# ADR 0030 — Zenoti customer import

## Status

Accepted (2026-05-17).

## Context

Manhattan Laser Spa is migrating from Zenoti with 7,160 active
guests (per their May 2026 `ZenotiActiveGuest.csv` export). They
also intend to migrate service catalog, memberships, and service
history in follow-up passes; this ADR covers customers only.

Migration must be precise. Lost customer records or wrong-attribution
audit trails are real spa-business liability — a returning client
expects the front desk to know who they are on day one. A
half-imported list that re-creates the same person twice is worse
than not importing at all.

Two prior incidents informed the design discipline:

1. **Auto-created social-guest pollution** (ADR 0026 era +
   commit 0a98c06) — IG-DM webhooks auto-created Customer rows
   with placeholder names. They polluted the client list until
   we added a filter. Lesson: be very explicit about which
   surfaces real-customer-quality data lands on.

2. **Backfill rewinds** (commit f3fffee) — the IG message
   backfill blindly overwrote fresher webhook state. Lesson:
   any re-runnable bulk operation must never rewind state.

This ADR captures the design that holds both lessons:

- Customers from Zenoti are NOT social-guest-style placeholders;
  they're real client records, visible in /clients from import
  forward.
- The import is idempotent + safe to re-run; the second run never
  duplicates a row.
- Every row write is audit-logged with `source='zenoti_import'`
  + an aggregate per-run audit entry for SOC 2 traceability.

## Decision

### 1. Three-module split: `mappers.py` / `importer.py` / management command

```
backend/apps/imports/zenoti/
├── client.py         # already exists — thin Zenoti HTTP client (unused in CSV path)
├── mappers.py        # pure functions: CSV row dict → MappedCustomer dataclass
└── importer.py       # orchestration: read, validate, dry-run / write, audit

backend/apps/imports/management/commands/
└── import_zenoti_guests.py    # CLI entry; --tenant + --file + --dry-run
```

`mappers.py` is pure (no DB, no I/O) so the field-mapping logic is
unit-tested directly against literal dicts. Header validation +
synthetic-ID generation + duplicate detection live there.
`importer.py` does file I/O, the two-pass dance, and the DB writes.
The CLI command is thin glue + a reconciliation report printer.

### 2. Idempotency: `external_id` is the upsert key

Every imported Customer carries:

  - `external_source = 'zenoti'`
  - `external_id = 'zenoti-code:<CODE>'` when Zenoti's `Code` is
    present in the export, OR
  - `external_id = 'zenoti-syn:<16-char-sha256>'` when `Code` is
    blank (~52% of the Manhattan export — Zenoti often leaves it
    blank for guests added pre-Zenoti's code-required era).

The synthetic ID is a hash of `(first_name, last_name,
digits-only phone, lowercased email)`. Stable on re-runs of the
same row; different from another person with the same name as
long as their phone OR email differs. Two people with the same
name AND no phone AND no email AND no Zenoti Code will collide —
rare enough that the operator can manually split later if it
matters.

Upsert: `Customer.objects.filter(tenant=t, external_source='zenoti',
external_id=eid).first()` then update non-external fields or create.
Re-running on the same export is a no-op write-wise (everything
shows `rows_updated`, not `rows_created`).

### 3. Two-pass: validate → write

Pass 1 (always runs, dry-run or not):

  - Skip the 5-line Zenoti metadata preamble.
  - Validate the header against `EXPECTED_HEADER`. A mismatch
    aborts immediately — we don't blind-map into wrong columns.
  - Map every row. Per-row errors go to a list; successes go to
    another. No DB access.
  - Detect duplicate `external_id`s within the export itself.

Pass 2 (only when `dry_run=False`):

  - Iterate validated mapped rows.
  - Per-row atomic upsert wrapped in `transaction.atomic()`.
  - On `IntegrityError` or any unexpected exception: log + count
    + continue. One bad row never aborts the whole 7k-row import.
  - Audit-log each write: per-row CREATE/UPDATE on `resource_type=
    'customer'` with `metadata.source='zenoti_import'`, plus one
    aggregate CREATE on `resource_type='zenoti_import_run'` with
    the full reconciliation summary.

The CLI always runs Pass 1 and prints the reconciliation report;
`--dry-run` is the gate for Pass 2. Operator MUST review the
dry-run output (especially error counts + duplicate count) before
running live.

### 4. Field mapping

| Zenoti CSV column         | Lumè Customer field                                     |
|---------------------------|---------------------------------------------------------|
| `FirstName`               | `first_name`                                            |
| `LastName`                | `last_name`                                             |
| `Code`                    | `external_id` (prefixed `zenoti-code:`)                 |
| `Email`                   | `email` (lowercased; blank if malformed)                |
| `Mobile`                  | `phone` (normalised to `(NNN) NNN-NNNN` for 10-digit US)|
| `Address1` / `Address2`   | `address_line1` / `address_line2`                       |
| `City`                    | `city`                                                  |
| `State`                   | `state` (full name → 2-letter abbrev when recognised)   |
| `Zip Code`                | `zip_code`                                              |
| `DOB`                     | `date_of_birth` (parses `M/D/YYYY`)                     |
| `ReceiveMarketingEmail`   | `email_marketing_opt_in` (Yes/No → bool)                |
| `ReceiveMarketingSMS`     | `sms_marketing_opt_in` (Yes/No → bool)                  |
| `BaseCenter`              | `notes` (`"Zenoti home center: Brooklyn"`)              |
| `HomePhone`               | `notes` (when different from `Mobile`)                  |
| `Nationality`             | `notes`                                                 |
| `ReferralSource`          | `notes` (`"Original referral source: ..."`)             |
| `CreationDate`            | `notes` (`"Original Zenoti record created: 2023-11-05"`)|
| `Gender`                  | (not modeled — captured in notes if non-blank later)    |
| `Anniversary Date`        | (not modeled)                                           |
| `Primary Employee`        | (not modeled — needs staff-mapping pass)                |
| `Target Segment Center`   | (not modeled)                                           |
| `Country`                 | (not modeled — US assumed)                              |
| `Type`                    | (always `'Guest'` — filtered out implicitly)            |

`acquisition_source` is set to `AcquisitionSource.ZENOTI_IMPORT` on
**create only**. Per the model's docstring, `acquisition_source` is
immutable post-create; the importer's `write_kwargs()` deliberately
excludes it so a re-run never overwrites an operator's later
manual change.

### 5. NO hard FK to Location

The Customer model is tenant-wide, not location-wide (per multi-
location architecture in ADR 0009). `BaseCenter` (one of Brooklyn,
Florida, Midtown, Upper East Side for Manhattan) is captured as
notes metadata, not as a `MembershipLocation`-style FK.

Operator can still filter manually by searching notes ("Brooklyn"
returns every Brooklyn home-center guest). A future per-tenant
Customer tag for home-center could land if the operator asks for
it, but it's not blocking.

### 6. Customers NOT marked `is_social_guest=True`

Unlike the IG-DM auto-created rows, Zenoti-imported customers are
real client records (operator-verified data, name + email + phone).
They appear in the standard /clients list, customer search, and
appointment-booking surfaces from import forward.

The social-guest hide-filter (commit 0a98c06, `is_social_guest=
False` on the list endpoint) does NOT affect Zenoti imports —
that filter only excludes rows where `is_social_guest=True`.

## HIPAA + SOC 2 posture

- **Audit log per row**: every Customer create/update from this
  importer writes an `AuditLog` entry with `metadata.source=
  'zenoti_import'`. SOC 2 §CC7.2 system monitoring question
  "show me every PHI row that landed here and where it came from"
  is answered by a one-line query.

- **Aggregate run audit**: one `AuditLog` entry per import run
  on `resource_type='zenoti_import_run'` with the full
  reconciliation summary (counts only — no PHI). HIPAA §164.312(b)
  audit-control answer for the BULK-action vector.

- **No PHI in error messages**: the per-row error log captures
  raw FirstName/LastName/Code (operator needs them to triage)
  but never address / DOB / medical fields. Compliance balances
  diagnostic utility against minimum-necessary.

- **No PHI in operator-facing error message bodies**: the CLI
  prints first 5 errors with redacted-style identifiers. The
  full per-row log goes to a separate file the operator opens
  on a workstation, not into terminal scrollback that might
  end up in a screenshot.

## Out of scope

- **Service history / appointments**: separate importer when the
  spa exports their appointment history. Will need to map Zenoti
  staff IDs to Lumè User+Membership rows first.

- **Package + membership balances**: same — separate importer.
  Critical for the migration because losing a package balance
  is real client-trust damage; needs its own ADR.

- **Forms / consent PDFs**: needs S3 ingestion + the PDF-
  attachment field on FormSubmission (which doesn't exist
  yet — current submissions are tokenized-fill flow only).

- **Before/after photos**: needs the photo-capture feature
  (Phase 4B) shipped first.

- **Live Zenoti API ingestion**: `apps/imports/zenoti/client.py`
  already has the HTTP scaffolding for this. Deferred until/
  unless the spa's Zenoti support ticket comes through with
  ongoing API access — for now, CSV is the input.

## References

- [ADR 0009 — Multi-location architecture](0009-multi-location-architecture.md) — explains why Customer is tenant-wide, not location-FK'd.
- [ADR 0017 — PHI redaction](0017-phi-redaction.md) — the redaction patterns this importer respects in its error log.
- [ADR 0026 — Tenant isolation enforcement](0026-tenant-isolation-enforcement.md) — every Customer write here goes through the standard tenant-scope guard.
- `PROJECT_PLAN.md` §1J — Zenoti migration tooling.
- `apps/customers/models.py` — Customer field definitions; `acquisition_source` immutability rule.
