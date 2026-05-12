# ADR 0019 — Staff invitation flow (Phase 1H)

## Status

Accepted (2026-05-12).

## Context

Until now, adding an employee to a tenant generated a temp password that the owner had to copy and share manually. The temp-password ribbon was visible exactly once after creation, never recoverable, and required the owner to play telephone with the new hire's credentials — an awkward, error-prone, and unprofessional first impression for the new staff member. It also created a real security gap: temp passwords flow through whatever channel the owner picks (Slack DM, sticky note), often weak and reused.

Now that SES is verified and production-approved, the proper pattern is available: email a tokenized one-time link, let the recipient set their own password on a public accept page, and atomically create the `User` + `TenantMembership` rows. This is the convention every modern SaaS uses (Slack, Notion, Linear), and it's what spa owners will expect when they're comparing Lumè to Boulevard / Mindbody.

### HIPAA + SOC 2 framing

- **Credential rotation** — the new hire chooses their own password. The owner never knows it. SOC 2 CC6.1 implications: access provisioning is auditable (the `Invitation` row carries `invited_by` and `accepted_at`), and the credential never traverses an unmonitored channel.
- **Tokenized link, 7-day expiry** — the token is 256 bits of entropy (`secrets.token_urlsafe(32)`), single-use (atomic check + accept), and expires automatically. If the email is forwarded or leaked, the blast radius is bounded.
- **Audit trail** — `Invitation.created_at` + `invited_by` + `accepted_at` + `accepted_by_user` survive even if the user later changes their email; `AuditLog` entries capture both ends (`invitation` resource on send, `invitation_accept` on accept).

## Decision

### 1. New model: `Invitation`

Lives in `apps.tenants.models`. Tenant-scoped (`TenantedModel`). Fields:

- `email` — recipient address (case-insensitive comparison via `iexact`)
- `role` — pre-selected by the inviter; baked into the eventual membership
- `job_title` (FK, nullable) + `is_bookable` — same
- `token` — 256-bit URL-safe random string, unique
- `expires_at` — default `now() + 7 days`
- `invited_by` (FK to User) + `accepted_at` + `accepted_by_user` (FK)

Uniqueness of "outstanding pending invitations per (tenant, email)" is enforced in service-layer code rather than a partial-unique DB index — the predicate `accepted_at IS NULL AND expires_at > now()` is awkward to express as a unique constraint and the race window is tiny (operator double-clicks Send).

### 2. Two new endpoints

- **`POST /api/memberships/invite/`** — authenticated, `MANAGE_STAFF` gated. Payload mirrors the legacy create endpoint minus `first_name` / `last_name` (those come from the recipient on accept). Returns the `Invitation` row.
- **`POST /api/auth/invitation/accept/`** — public (`AllowAny`, no auth, no CSRF). Payload: token + first_name + last_name + password (≥12 chars). Atomic: `select_for_update` on the Invitation, create User + Membership + MembershipLocation (default location), mark accepted, log the user in (Django session). Returns the redirect target (`/dashboard`).
- **`GET /api/auth/invitation/<token>/`** — public lookup so the accept page can render "you've been invited to join Acme Spa" before the recipient fills the form. Returns tenant name + role + inviter name + expiry; **does not echo the recipient email** (the token is the identifier; surfacing the email would be a small information leak if a link is shared).

URL ordering matters: `accept/` must come **before** `<token>/` in the urlpatterns list because Django's `<str:>` converter happily matches the literal "accept" as a token value.

### 3. Existing-user case is explicitly rejected

If the recipient email matches a User that already exists (e.g. they work at another spa on Lumè), the accept endpoint returns 400 with a clear `detail` rather than attempting to attach the membership. Two reasons:

- The public accept flow requires the recipient to set a password. Clobbering an existing user's password from an emailed link is a credential-takeover footgun.
- Existing-user-attach was the original temp-password flow's edge case anyway. That code path (`POST /api/memberships/` with the `MembershipCreateSerializer`) **stays around** as the documented fallback when an owner needs to attach a known existing user.

The error message points the owner to the legacy direct-add flow. A future polish: detect this case at invite-time and offer "this person already has a Lumè account — attach them directly?" before sending the email.

### 4. Frontend changes

- `AddEmployeeSheet` now collects `email` + `role` + optional `job_title_id` + `is_bookable`. No more first/last name (recipient enters those). On submit → `useInviteEmployee` → toast + close. The temp-password reveal panel is gone.
- New page `frontend/src/app/(auth)/accept-invitation/[token]/page.tsx`. Uses the existing `(auth)` layout (centered card, no app shell). Looks up the invitation on mount, renders accept form (first / last / password / confirm) for pending invitations, renders explicit error states for accepted / expired / unknown / existing-account cases.

### 5. Email content

- Subject: `You're invited to join {tenant_name} on Lumè CRM`
- Branded HTML body (single-column, inline styles, max-560 width) with a prominent "Accept invitation" button and the link in plain text for copy-paste
- 7-day expiry called out explicitly
- HIPAA-aware footer ("Lumè CRM is a HIPAA-eligible practice management system…")

Templates live in `apps/tenants/templates/tenants/email/invitation.{txt,html}`.

## Consequences

### Positive

- Closes the "professional-grade onboarding" gap. New staff members get an email they can act on directly, no awkward password-sharing through Slack or text. This is the table-stakes flow every modern CRM has.
- The temp-password ribbon (and the polish-backlog item to replace it) are both retired.
- 12 tests cover the full flow including role gates, duplicate invitations, lookup privacy (no email echo), accept idempotency, expiry, and existing-account rejection.
- The Invitation row is reusable for follow-on features: "Resend invitation", "Revoke invitation", "Pending invitations" list on `/staff/employees`. None of those are built yet; the model is shaped to support them without a migration.

### Negative

- Email delivery becomes part of the onboarding path. SES outages now block staff onboarding. Mitigated by: SES has 99.9% SLA; the temp-password fallback (`POST /api/memberships/`) is still available; bounce/complaint monitoring is on the §4.55 week-1 list.
- The token lives in plaintext in the DB. Hashing would prevent legitimate token-lookup (the lookup endpoint takes a raw token in the URL, so a stored hash would force a full-table scan on every GET). Accepting plaintext storage because the token's secrecy is bounded by the 7-day expiry + single-use semantics; an attacker with read-DB access has bigger problems anyway.
- Existing-user-different-spa case requires the legacy direct-add flow. Future polish to detect this at invite time and offer a one-click attach.

### Risks accepted

- **Password complexity** is currently a single rule: ≥12 chars. No upper/lower/digit/symbol requirements. Industry guidance (NIST 800-63B) is moving toward "length-only" since composition rules don't materially improve real-world strength. We accept the simple rule; if a tenant demands stricter policy as part of their compliance posture, we'd add tenant-level password rules in a follow-up ADR.
- **No 2FA on accept** — the recipient sets a password and is in. Lumè doesn't have 2FA yet (Phase 1A.5 polish backlog). Once 2FA lands, the accept flow can be extended to enroll a TOTP device before completing.
- **Email-confirmation step is implicit** — possession of the token (delivered to the email) is treated as proof the recipient owns that email. Standard SaaS pattern; consistent with how Slack / Notion / Linear handle invitation accepts.

## Implementation references

- Model: [apps/tenants/models.py](../../backend/apps/tenants/models.py) — `Invitation`
- Services: [apps/tenants/services.py](../../backend/apps/tenants/services.py) — `invite_staff`, `accept_invitation`, `InvitationError`
- Views: [apps/tenants/views.py](../../backend/apps/tenants/views.py) — `MembershipViewSet.invite`, `InvitationLookupView`, `InvitationAcceptView`, `MembershipInviteInputSerializer`, `InvitationSerializer`
- URLs: [apps/users/urls.py](../../backend/apps/users/urls.py) — auth-side `invitation/accept/` and `invitation/<token>/`
- Email templates: [apps/tenants/templates/tenants/email/invitation.txt](../../backend/apps/tenants/templates/tenants/email/invitation.txt) + .html
- Tests: [apps/tenants/tests.py](../../backend/apps/tenants/tests.py) — `StaffInvitationTests` (12 tests)
- Frontend hook: [frontend/src/lib/tenant.ts](../../frontend/src/lib/tenant.ts) — `useInviteEmployee`, `Invitation`, `InviteEmployeeInput`
- Frontend sheet: [frontend/src/app/(app)/staff/_components/add-employee-sheet.tsx](../../frontend/src/app/(app)/staff/_components/add-employee-sheet.tsx)
- Accept page: [frontend/src/app/(auth)/accept-invitation/[token]/page.tsx](../../frontend/src/app/(auth)/accept-invitation/[token]/page.tsx)
