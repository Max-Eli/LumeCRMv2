# ADR 0031 — Staff mobile app: architecture + JWT authentication

## Status

Accepted (2026-05-20). Phase 2 of the staff mobile app build. The
Expo project scaffold (Phase 1) and this backend auth surface
(Phase 2) are the foundation; feature screens follow in later phases.

Revised (2026-05-20, pre-deploy): tenant resolution changed from
email-first to slug-first (§3) at the product owner's direction. No
backend change was needed — the slug is validated against the existing
public branding endpoint.

## Context

Both launch spas have staff who expect to run day-to-day operations
from a phone — not every operator sits at a front desk. The web CRM is
responsive, but a native app gives push notifications, a home-screen
presence, biometric lock, and a smoother touch experience.

Constraints that shaped the decision:

- **One app for every tenant.** A single binary ships to the App Store
  and Play Store. Staff from any spa download the same "Lumè CRM" app;
  the app must work out which tenant a person belongs to at sign-in.
- **The web app must not regress.** The two spas go live on the web
  CRM. Anything built for the mobile app has to be strictly additive to
  the backend — a mobile change that breaks a web endpoint is
  unacceptable.
- **Native auth ≠ web auth.** The web CRM authenticates with Django
  session cookies + CSRF tokens. A native app cannot cleanly carry a
  session cookie + CSRF token across a long-lived app lifecycle; the
  platform-standard for native clients is bearer tokens.
- **No subdomain to resolve.** The web resolves the tenant from the
  request subdomain (`acme.<domain>`). A native app talks to one fixed
  API host (`api.<domain>`) — there is no subdomain to read.
- **HIPAA.** PHI is now reachable from a personal device. Auth
  credentials sit at rest on the device; the threat model gains
  lost/stolen devices and idle unlocked phones.

## Decision

### 1. Expo-managed React Native app at `mobile/`

A new `mobile/` package at the repo root, sibling to `frontend/`,
`backend/`, and `marketing/`. Expo (managed workflow) — chosen for a
solo developer: one codebase to iOS + Android, EAS cloud builds,
over-the-air updates, and first-party secure-storage / biometric
modules. Bare React Native was rejected as unjustified maintenance
overhead.

The app is locked to **light mode** — the web CRM ships no dark mode,
so a dark variant would only create brand drift. The design tokens in
`mobile/src/constants/theme.ts` mirror the web palette
(`frontend/src/app/globals.css`).

### 2. JWT auth as a separate, additive backend surface

Three new endpoints under `apps/users/mobile.py`, wired at
`/api/auth/mobile/`:

```
POST /api/auth/mobile/login/    email+password → { access, refresh, user }
POST /api/auth/mobile/refresh/  refresh        → { access, refresh }
POST /api/auth/mobile/logout/   refresh        → 204 (blacklisted)
```

`refresh/` is SimpleJWT's stock `TokenRefreshView`. Built on
`djangorestframework-simplejwt`. The existing session-cookie surface in
`apps/users/views.py` is **untouched** — `mobile.py` is a parallel file,
the web `LoginView` / `MeView` / `LogoutView` keep their exact
behaviour.

`MobileLoginView` mirrors the web `LoginView` security posture:
platform admins are rejected with the structured
`platform_admin_account` code (they use the web console); bad
credentials get a generic 401 with no account-enumeration leak; an
account with zero active memberships is rejected (`no_membership`).

### 3. Tenant resolution: slug-first

Sign-in is two steps:

1. **Workspace.** The operator enters their workspace slug. The app
   validates it against `GET /api/public/branding/` — public,
   unauthenticated, resolves the tenant from the `X-Tenant-Slug`
   header — and shows the spa's name. An unknown slug is caught here,
   before any password attempt.
2. **Credentials.** Email + password, scoped to that workspace.

The chosen slug is persisted to the Keychain and rides on every
authenticated request as the `X-Tenant-Slug` header — the same header
`TenantMiddleware` honours as its non-subdomain fallback. After login
the app verifies the account holds an active membership in the chosen
workspace; a valid account with no membership there is refused
client-side, and the server's `MobileJWTAuthentication` (§4) enforces
the same boundary on every subsequent request.

Tokens stay **tenant-agnostic** — they identify the person, not a
workspace. "Change workspace" re-enters the slug flow; no token
re-issue. This matches the web's domain-wide-cookie + per-request
membership model.

Slug-first was chosen over deriving the tenant from the (globally
unique) email because it makes the workspace explicit and visible
before the password step, supports a per-spa branded login, and matches
how operators think ("I'm signing into <spa>"). The slug is entered
once per install and then persisted, so the friction is one-time.

### 4. `MobileJWTAuthentication` — membership binding + fail-closed

`apps/users/authentication.py` subclasses SimpleJWT's `JWTAuthentication`
with one critical addition.

`TenantMiddleware` runs *before* DRF authentication. For a JWT request
the user is still anonymous at middleware time, so the middleware
leaves `request.tenant_membership` as `None` — but the app's permission
classes (`IsTenantStaff` and the per-app classes, see ADR 0026) all key
off `request.tenant_membership`. `MobileJWTAuthentication` re-resolves
it once the token has identified the user.

It also **fails closed**: if the request carries an `X-Tenant-Slug` for
a tenant the token holder has no active membership in, authentication is
rejected outright. This is the mobile analogue of ADR 0026's
middleware session-kill — a token can only ever act inside a tenant its
owner actually belongs to. The web enforces this by terminating the
session; the mobile surface enforces it by refusing the request.

### 5. `SessionAuthentication` stays first in the auth-class list

`DEFAULT_AUTHENTICATION_CLASSES` becomes
`[SessionAuthentication, MobileJWTAuthentication]` — **session first,
deliberately.**

DRF derives the 401-vs-403 status of an unauthenticated request from
`authenticators[0].authenticate_header()`. `SessionAuthentication`
returns nothing there (→ 403); `JWTAuthentication` advertises a
`Bearer` challenge (→ 401). Putting the JWT class first would flip
**every** unauthenticated web response from 403 to 401 — a
platform-wide behaviour change. Session-first keeps web responses
byte-identical. The JWT class runs second and returns `None` when there
is no `Bearer` header, so browser requests never touch it.

Trade-off: mobile auth failures (expired token, cross-tenant rejection)
also surface as 403 rather than 401. The mobile API client therefore
does not branch on 401-vs-403 — it checks the access token's `exp`
claim locally and refreshes proactively, with a refresh-and-retry-once
fallback on any auth failure. Decided in Phase 3.

### 6. Token lifetimes

```python
ACCESS_TOKEN_LIFETIME  = 60 minutes
REFRESH_TOKEN_LIFETIME = 7 days
ROTATE_REFRESH_TOKENS  = True
BLACKLIST_AFTER_ROTATION = True
UPDATE_LAST_LOGIN      = True
```

Every refresh rotates the refresh token and blacklists the spent one
(`token_blacklist` app), so a captured refresh token is single-use. The
7-day refresh window means a lost device's session lapses within a week
even with no explicit remote logout.

### 7. Tests

`MobileAuthTests` in `apps/users/tests.py` — 9 cases: token issuance,
the platform-admin / bad-password / no-membership gates, bearer-token
request auth, the cross-tenant fail-closed guarantee, the
no-`X-Tenant-Slug` path, refresh, and logout-blacklisting. Full backend
suite re-run to confirm the auth-class change is non-breaking.

## HIPAA / SOC 2 framing

- **Credentials at rest (Phase 3).** Tokens are stored with
  `expo-secure-store`, backed by the iOS Keychain / Android Keystore
  (hardware-backed where the device supports it) — never in plain
  `AsyncStorage`.
- **Idle / lost-device control.** The on-device biometric/PIN app-lock
  (Phase 4) is the primary control for an unlocked, unattended phone.
  The short access-token lifetime + 7-day refresh ceiling +
  rotate/blacklist are defence in depth — a lost device cannot mint
  fresh access indefinitely.
- **Tenant boundary.** §4's fail-closed check preserves the same PHI
  tenant-isolation guarantee ADR 0026 established for the web. A
  mis-addressed or malicious `X-Tenant-Slug` cannot read another spa's
  data.
- **Surface separation.** Platform admins are refused at
  `mobile/login/` — the staff app is tenant-staff only.
- **Transport.** All API traffic is HTTPS (the `api.<domain>` ALB
  listener); no cleartext fallback. Unchanged by this ADR.
- **Audit (deferred).** Login events are not yet written to `AuditLog`
  — this matches the existing web `LoginView`, which also does not
  audit logins. Login-event auditing is a cross-cutting gap tracked
  separately, not introduced asymmetrically here.

## Consequences

### Good

- The web app cannot regress: the backend change is additive
  (new endpoints, a second auth class that no-ops for browser requests)
  and the full backend suite passes unchanged.
- One app serves every tenant; the workspace slug is entered once at
  first launch and then persisted.
- Multi-spa staff switch workspace without re-authenticating.
- Cross-tenant access fails closed, consistent with ADR 0026.

### Bad / Deferred

- A second auth model now exists in the codebase (session for web, JWT
  for mobile). Two surfaces to reason about — accepted as the cost of a
  native client.
- Refresh-token blacklist rows accumulate in Postgres. SimpleJWT ships
  a `flushexpiredtokens` management command; wiring it to a periodic
  job is a Phase 9 / production-hardening item.
- No remote "log out all my devices" control yet. The 7-day refresh
  ceiling bounds exposure; an explicit per-user token-revocation
  surface is deferred.

### Acknowledged

- Tenant-agnostic tokens mean a token is valid for *any* workspace its
  holder belongs to — scoping is per-request via `X-Tenant-Slug` +
  the §4 membership check, not baked into the token. This is
  deliberate (it enables in-app workspace switching) and is the same
  model the web's domain-wide session cookie uses.
- The drf-spectacular `SPECTACULAR_SETTINGS` description still says
  "session-cookie auth". Cosmetic; the schema is an internal dev aid.

## Alternatives considered

### DRF `TokenAuthentication` (permanent opaque tokens)

Simpler — one non-expiring token per user. Rejected: no expiry, no
rotation, no blacklist-on-rotation. A captured token would be valid
forever. Not defensible for a PHI app.

### Email-first login (derive the tenant from the account)

Email is globally unique, so the app *could* skip the slug entirely and
resolve the workspace from the account's memberships (with a picker for
multi-spa staff). Initially chosen, then revised to slug-first (§3): an
explicit, visible workspace step is the clearer operator experience and
the product owner's call. Slug validation reuses a public endpoint and
the slug is entered once, so the added friction is minimal.

### JWT class first in `DEFAULT_AUTHENTICATION_CLASSES`

Rejected — flips every unauthenticated web response from 403 to 401
(see §5). Session-first preserves web behaviour exactly.

### Embedding the tenant in the JWT

Rejected: a tenant-scoped token would force a re-login to switch
workspace, and would need re-issuing if a membership changed.
Per-request `X-Tenant-Slug` scoping mirrors the web model and keeps
workspace-switching free.
