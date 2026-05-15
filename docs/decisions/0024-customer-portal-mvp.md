# ADR 0024 — Customer portal MVP

## Status

Accepted (2026-05-15).

## Context

Every comparable medspa CRM (Mindbody, Boulevard, Fresha, Vagaro, Booker) ships a customer-facing self-service portal as table stakes. Spa owners assume it during pre-sales — "where do my clients log in to see their appointments?" — and a "no portal" answer can mean a lost sale. We're onboarding the first real tenant imminently, and the portal needs to be live before customers start asking about it.

The full Phase 3E vision (PROJECT_PLAN.md) covers magic-link auth, appointments, profile, packages, memberships, gift cards, invoices, forms, document upload, notification preferences, branded shell, and a per-tenant feature-flag matrix for which surfaces each spa wants exposed. That's months of work. This ADR scopes the MVP that ships now.

## Decision

### 1. MVP scope — what's in v1

Five surfaces, three pages of customer-visible UI plus the auth flow:

- **Magic-link login.** Customer enters their email on the portal sign-in page → SES delivers a tenant-branded email with a one-time link → click consumes the link, sets a session cookie, lands the customer on `/portal`.
- **Dashboard (`/portal`).** Welcome, next appointment, last visit, quick action links, summary of contact details.
- **Appointments (`/portal/appointments`).** Upcoming + past, with a self-cancel button on future booked/confirmed slots.
- **Profile (`/portal/profile`).** Read-only identity (name + email), editable phone + marketing consents, sign-out.

Deferred (Phase 3E session 2 and later):
- Reschedule (needs availability surfacing + service/provider fit re-validation).
- Packages / memberships / gift cards balance.
- Invoices + payment history.
- Forms (pending + completed).
- Document upload.
- Tenant feature-flag matrix.
- Per-tenant subdomain (`portal.<tenant>.<domain>`) — v1 uses the existing per-tenant subdomain at `/portal/...`.

### 2. Identity layer — a parallel auth surface, not a `User` overload

Customers (`apps.customers.Customer`) are NOT Django `User` rows. Conflating them would:

- Force every `request.user.is_authenticated` check across the staff CRM to disambiguate "staff or customer?" — a thousand-callsite refactor for marginal benefit.
- Expose customers to features they shouldn't see (TenantMembership, role + permission gates, staff invitations).
- Confuse audit logs that assume `user_id` means a Lumè employee.

Instead, the portal runs its own session layer:

- **`CustomerPortalToken`** — one-time magic-link token. 256-bit `secrets.token_urlsafe(32)` value, 30-min expiry, single-use, atomic `used_at` flip inside a `select_for_update()` transaction. Single-use means a forwarded email loses its utility after the first click + a replay returns 410 Gone.
- **`CustomerPortalSession`** — persistent session created on token consumption. Token value sits in an `httponly` + `samesite=Lax` + `secure=true` cookie named `lume_portal_session`. Two expiry conditions: absolute (14 days) and idle (4 hours, refreshed on every request via `last_seen_at`).
- **`PortalSessionMiddleware`** — extracts `request.customer` from the cookie on every request. Anonymous on miss / stale cookie / revoked / expired. Bumps `last_seen_at` only on active sessions so a dead session can't keep refreshing itself.
- **`IsPortalCustomer`** DRF permission class — gates the authenticated portal endpoints.

### 3. Tenant scoping — the two-headed check

Portal sessions are bound to one Customer → one Tenant by foreign key. But a customer with a stale cookie could in theory hit a different spa's portal subdomain. Defense in depth:

- The request's tenant (from `TenantMiddleware`, resolved by host or `X-Tenant-Slug` header) must match `request.customer.tenant_id`. Mismatch → 403.
- The consume endpoint requires the token's tenant to match the request's tenant. A token issued for spa A cannot be redeemed on spa B's host, even if the URL is guessed.

Both checks are explicit in `views.py:_guard_tenant_consistency`.

### 4. Email-enumeration resistance

The request-magic-link endpoint returns the same 200 + body whether the email matches a customer or not. No different status code, no different message length. A probing attacker can't enumerate which addresses are clients of a given spa. This costs ~0 — the response is identical, the work the server does is slightly different (issue + email or not), but the client can't time-side-channel the call meaningfully over HTTPS.

Inactive customers are explicitly excluded from the lookup so a deleted account can't be re-animated via the portal.

### 5. Branding — three tenant fields, propagated via CSS custom properties

Tenants already had `Tenant.primary_color` + `Tenant.logo_url`; the portal piggybacks on those. The `/api/portal/me/` response includes a `tenant` slice (`name`, `slug`, `primary_color`, `logo_url`); the portal layout reads it once and sets `--portal-brand` on the root wrapper. Individual pages reference `var(--portal-brand)` for accent strokes, button surfaces, and the toggle "on" colour — so each spa's portal looks visibly theirs without us threading the colour through every component prop.

The magic-link email uses the same fields in the rendered template (button background, logo image, fallback header colour). Tenant brand consistency from inbox through web is intentional — it's the first touchpoint a customer has with the spa's "brand surface" before logging in.

### 6. HIPAA + SOC 2 posture

PHI: a customer's own appointment data is PHI in the medspa context (service performed, provider, time, location). Posture:

- **Access scope.** Customers see only their own rows — every portal endpoint filters by `customer=request.customer` and is tenant-scoped. There is no "list all customers" or "view another customer" endpoint.
- **Audit logging.** Every authenticated portal read writes an `AuditLog` entry (`portal_me`, `portal_appointments`, `appointment`) with the session's customer_id. Reads are noisier than the staff path because customers tend to refresh, but the storage cost is bounded and the trail answers "what did this customer access and when?" cleanly.
- **At-rest encryption.** Tokens + sessions live in Postgres → RDS storage-encryption KMS key, same posture as everything else.
- **In-transit.** TLS 1.2+ everywhere (ALB termination); the cookie is `secure=true` so the browser refuses to send it over plaintext.
- **Cookie hygiene.** `httponly` defeats XSS exfiltration of the session token; `samesite=Lax` defeats trivial CSRF (the only state-changing portal endpoints are POST/PATCH, all behind the cookie).
- **Token compromise.** Magic links are short-lived + single-use, so a forwarded email becomes useless after click or after 30 minutes (whichever first). Session compromise via cookie theft is bounded by the 4-hour idle window — a stolen cookie loses validity if the legitimate customer (or attacker) doesn't touch the portal for 4 hours.
- **Identity changes (name, DOB, email).** Intentionally NOT editable from the portal. Those changes go through staff, who have an authenticated audit trail + can re-verify identity. A customer can change their own phone + marketing consents only.

### 7. SOC 2 mapping

- **CC6.1 (logical access)** — magic-link consumption is the access-grant event, audit-logged. Session revocation flows through the logout endpoint.
- **CC6.7 (transmission security)** — TLS + secure cookie.
- **CC7.2 (system monitoring)** — every portal request flows through the existing CloudWatch logs; audit events are queryable.
- **CC8.1 (change management)** — captured in this ADR + the test suite covers all seven invariants below.

### 8. Test coverage

19 backend tests in `apps.portal.tests` covering:

1. Email-enumeration resistance (matched + unmatched return identical responses).
2. Magic-link single-use (second consume → 410).
3. Magic-link expiry (expired token → 410).
4. Cross-tenant token rejection.
5. Cross-tenant session rejection.
6. Idle timeout invalidates session.
7. Absolute expiry invalidates session.
8. Inactive customer not matched.
9. Case-insensitive email match.
10. `/portal/me/` returns customer + tenant.
11. `/portal/me/` PATCH updates marketing consents + stamps `*_consent_at` + `*_consent_source='portal'`.
12. Appointments list returns only the calling customer's rows.
13. Future booked/confirmed → cancellable.
14. Past appointments → not cancellable (400).
15. Cross-customer appointment → 404.
16. Logout revokes session.
17. Logout idempotent.
18. Authenticated endpoints require auth.
19. Anonymous session yields anonymous request.

## Consequences

### Good

- First real tenant has a customer-facing surface from day one — the "where do my clients log in?" question has an answer.
- Each spa looks distinctly theirs — the branding fields tenants already had now light up where it matters most.
- Magic-link flow has no password-storage risk + no "forgot my password" support load. Customers also can't reuse a leaked password across surfaces.
- The customer-identity layer is intentionally isolated from staff `User`, so adding portal-only features (saved cards, notification preferences, document upload) won't pollute the staff CRM.

### Bad / Deferred

- **No reschedule.** Cancel only. A customer who wants to move a slot has to cancel + call. Phase 3E session 2 ships reschedule with the availability picker that's already built into `apps.booking`.
- **No tenant cancellation-policy enforcement.** Customer can cancel any future booked/confirmed appointment regardless of how close it is. Late-cancel fees + cancellation-window blocks land with the broader payment-flow work.
- **No package/membership/gift-card visibility.** Customers can't see their balances yet. The data exists; the portal endpoints don't.
- **No invoices / receipts.** Customers can't pull up a past receipt — a real ask we'll hear within the first week.
- **No forms surface.** Customers can't see pending intake forms in the portal (today's flow: emailed token link). Phase 3E session 2.
- **Document upload.** Insurance card, ID, before-photo upload from the portal — needs an S3 presign + virus scan path that's beyond v1.
- **English-only.** No i18n. Acceptable for the first US-based tenants; comes back when we sell internationally.

### Acknowledged

- **One Customer per Tenant identity model.** A single human who's a customer at two different spas in our platform has two Customer rows + two portal accounts. The customer-side product UX treats this as separate spas, which is correct semantically (they have different histories, different consents, different relationships). A future "unify your portal accounts across spas" feature would require a separate Identity concept above Customer, intentionally not built yet.
- **No password fallback.** Some customers find magic-link annoying ("I have to keep checking my email"). The PROJECT_PLAN includes "optional password sign-in for clients who prefer it" as a future addition, but every reputable medspa portal I've inspected defaults magic-link-only on first sign-in and adds password as opt-in.

## Alternatives considered

### Reuse Django `User` for customers

Considered. Rejected for the reasons in §2: invasive callsite-by-callsite refactor of the staff CRM, plus blurring of identity in audit logs.

### Per-tenant subdomain at portal.<tenant>.<domain>

Considered for v1. Rejected because it requires per-tenant DNS provisioning + ACM-cert SAN management for every new tenant. Path-based (`<tenant-subdomain>/portal/...`) reuses the existing wildcard cert + the same routing pattern the booking page uses, and ships today. The future migration to a dedicated portal subdomain is straightforward (rename routes, add DNS, both work in parallel during cutover).

### Username/password instead of magic-link

Rejected. Passwords come with mandatory baggage: reset flow, rate-limiting brute-force attempts, breach-list checking, complexity rules, recovery, lockouts. Magic-link sidesteps all of that for marginally worse mid-task UX (the customer occasionally has to switch to their inbox). The medspa-CRM industry has converged on magic-link-first for exactly this reason.

### Server-rendered portal pages (no client-side React)

Considered briefly because the portal could in principle be server-rendered Django templates + HTMX. Rejected because the existing frontend has the design system, the Tailwind tokens, the React Query stack, and the build pipeline — adding a Django-template path would mean a parallel design system for a single surface. Cost outweighs benefit for v1.
