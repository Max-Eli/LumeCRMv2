# ADR 0002 — Authentication strategy

## Status

Accepted (2026-04-30) — interim. Will be revisited in Phase 0c when AWS Cognito comes online.

## Context

Lumè staff (Owners, Managers, Front Desk, Providers, Bookkeepers, Marketing) and platform admins (us) need to authenticate. Customers booking online via the public booking page do NOT log in — that flow is anonymous with tokenized confirmation links.

Three credential strategies considered:

| Approach | Pros | Cons |
|---|---|---|
| **Django session cookies** | Built into Django. CSRF protection mature. Works out-of-box with DRF SessionAuthentication. | Cookies need cross-port handling in dev (CORS + SameSite). Not stateless. Requires sticky sessions or shared session store at scale. |
| **JWT tokens** | Stateless. Easier mobile / multi-origin. | Logout is hard (have to maintain a denylist). Token storage in browser (cookie vs localStorage) is its own decision. CSRF still applies for cookie storage. |
| **Auth0 / Cognito hosted login** | Outsource auth complexity. MFA + social login built in. | Adds a paid dependency early. Cognito has free tier up to 50k MAU; Auth0 HIPAA tier is $240+/mo. |

For Phase 0b–0d (local dev, no production yet), we want **the simplest thing that gets us to a working login flow** without adding paid services.

## Decision

**Use Django sessions + DRF `SessionAuthentication` for v1. Migrate to AWS Cognito in Phase 0c when production deploys.**

Implementation:

- DRF default `DEFAULT_AUTHENTICATION_CLASSES = [SessionAuthentication]` and `DEFAULT_PERMISSION_CLASSES = [IsAuthenticated]`.
- Endpoints that should be public (login, csrf endpoint) opt into `permission_classes = [AllowAny]`.
- CSRF protection enforced on POST/PUT/PATCH/DELETE via DRF's session auth.
- Frontend (Next.js, separate origin) calls `GET /api/auth/csrf/` on mount/login to ensure the `csrftoken` cookie is set, then reads the cookie and sends it as `X-CSRFToken` header on mutating requests.
- `credentials: 'include'` on every `fetch` so the session cookie is sent cross-origin.
- `django-cors-headers` configured with `CORS_ALLOWED_ORIGINS` and `CORS_ALLOW_CREDENTIALS = True`.
- `CSRF_TRUSTED_ORIGINS` includes the frontend origin so DRF accepts CSRF tokens from it.

API surface:

| Method | Path | Returns |
|---|---|---|
| `GET` | `/api/auth/csrf/` | Sets `csrftoken` cookie. 200. |
| `POST` | `/api/auth/login/` | `{ user }` on 200, 401 on bad creds. Sets `sessionid` cookie. |
| `POST` | `/api/auth/logout/` | 204. Clears `sessionid`. |
| `GET` | `/api/auth/me/` | `{ user }` with memberships, or 403 if not logged in. |

## Consequences

### Pros

- Zero external dependencies. No Auth0 bill, no Cognito setup yet.
- Django's password storage (PBKDF2-SHA256 by default), session expiry, and CSRF are battle-tested.
- DRF integration is one line of `permission_classes`.
- Login / logout / failed login already audit-logged via Django auth signals (see [ADR 0004](0004-audit-logging.md)).

### Cons

- **Cross-origin cookies in dev are fiddly.** Browser SameSite policies, especially under stricter Chrome settings, can drop cookies. Mitigated by both servers running on `localhost` (same site, different ports — SameSite=Lax allows it).
- **Not stateless.** Sessions live in Postgres (`django_session` table). Fine for a single backend; needs sticky load balancer or shared session backend (Redis) at scale.
- **No native MFA.** Adding `django-otp` is on the Phase 0b checklist. For production, MFA will be Cognito's responsibility.
- **No social login.** Not needed for v1 (spa staff have to be invited).

### Production migration (Phase 0c)

Move auth to **AWS Cognito**:

- Cognito User Pool with email-as-username.
- MFA enforced for all roles.
- Lumè backend trusts Cognito-issued JWTs via DRF custom `Authentication` class.
- Frontend uses Cognito's hosted UI or AWS Amplify Auth UI library for login.
- The `apps.users.User` model stays — Cognito sub becomes a unique field on it. We sync user creation between Cognito and our DB via post-signup Lambda.
- Endpoints `/api/auth/login/` and `/api/auth/logout/` get retired in favor of Cognito's flows. `/api/auth/me/` stays — it returns our internal user record, which is what the app cares about.

This lets us defer the Cognito wiring (and the BAA setup it requires) until production deployment, when we have a paying spa whose data needs the protection.

## References

- [apps.users README](../../backend/apps/users/README.md)
- [DRF SessionAuthentication docs](https://www.django-rest-framework.org/api-guide/authentication/#sessionauthentication)
- [Django session security notes](https://docs.djangoproject.com/en/5.1/topics/security/#cross-site-request-forgery-csrf-protection)
