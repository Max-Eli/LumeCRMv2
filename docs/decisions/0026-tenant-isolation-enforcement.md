# ADR 0026 — Tenant isolation: enforce membership at the middleware layer

## Status

Accepted (2026-05-16). Shipped as a security fix in response to a
live vulnerability report.

## Context

Multi-tenant CRMs that serve the same staff users across multiple
spas need the session cookie to be readable on every tenant
subdomain (`acme.<domain>`, `gloss.<domain>`, etc.) so a logged-in
user can navigate between spas they're a member of. The cookie's
`Domain` attribute is `.<domain>` for that reason — the browser
sends it along with every subdomain request.

That has a sharp edge: if a staff user is signed into tenant A and
navigates to tenant B's URL, the browser sends the same session
cookie. The Django session validates as authenticated. The previous
behaviour:

- `TenantMiddleware` resolved `request.tenant` = tenant B from the
  subdomain.
- `_resolve_membership` returned None because the user has no
  active membership on tenant B — set `request.tenant_membership`
  to None but did NOT terminate the session.
- App-specific permission classes (`CustomerPermission`,
  `ChartNoteWritePermission`, etc.) check
  `request.tenant_membership`, so most mutating endpoints would 403.
- **But several read endpoints + the `/api/auth/me/` endpoint
  used bare `IsAuthenticated`**, which passes whenever a Django
  session exists. Those endpoints then ran their tenant-scoped
  querysets against `request.tenant` (= tenant B) and returned
  tenant B's data to a user with no membership.
- The frontend, holding a valid `/api/auth/me/` response, rendered
  the dashboard chrome as if the user belonged here.

A live report (2026-05-16) demonstrated this end-to-end: a demo
tenant owner browsing to a sibling tenant's URL landed on that
spa's dashboard and could read + mutate certain surfaces.

This is a HIPAA boundary failure. Patient data lives behind
tenant scoping; a cross-tenant data read on one of the
`IsAuthenticated`-only endpoints is a PHI disclosure event.

## Decision

### 1. Middleware-level enforcement (primary)

`TenantMiddleware` now kills any Django session whose authenticated
user has no active membership on the resolved tenant:

```
if authenticated user is on tenant subdomain AND
   user is NOT a platform admin/superuser AND
   request.tenant_membership is None:
       logout(request)
       request.user = AnonymousUser()
```

Why middleware rather than per-endpoint:

- It's the single chokepoint every request flows through.
- It works even for endpoints that were missed in audit.
- It works even for future endpoints added without the right
  permission class — the request reaches the view as anonymous, so
  even a bare `AllowAny` view sees no user.
- It deliberately mirrors what should happen at the cookie layer
  — "your session is not valid for this tenant" — without needing
  the browser to know.

Platform admins (`is_superuser` or `is_platform_admin`) are
intentionally exempt. They need cross-tenant reach to support
spas. Their session survives the navigation.

When a session is terminated, the middleware logs a
`tenants.security.cross_tenant_session_terminated` event (no PII —
just user_id, tenant_slug, path) so the trail is auditable.

### 2. `IsTenantStaff` permission class (defense-in-depth)

New `apps.tenants.api_permissions.IsTenantStaff`. Same boolean as
the middleware kill condition. Every staff endpoint that
previously used bare `IsAuthenticated` now uses `IsTenantStaff`
instead:

| File                              | Endpoints              |
| --------------------------------- | ---------------------- |
| `apps.tenants.views`              | 5 (settings, JobTitles, memberships, locations, MembershipLocation) |
| `apps.waitlist.views`             | 1 (WaitlistEntry CRUD) |
| `apps.forms.views`                | 2 (FormTemplate, FormSubmission) |
| `apps.messaging.views`            | 3 (MessagingViewSet, SavedReplyViewSet, AutomatedTemplatesView) |

`LogoutView` + `MeView` in `apps.users.views` keep
`IsAuthenticated` — they must work for any authenticated session,
including one being terminated by the cross-tenant middleware kill
(the kill happens first; `MeView` then sees an anonymous user and
returns 401, which the frontend handles).

Login / CSRF / portal-magic-link / Twilio webhooks remain
`AllowAny`. They're either anonymous flows or have their own
HMAC-signature-based auth.

### 3. Frontend defense (visible)

The `(app)/layout.tsx` now parses `window.location.hostname` and
checks that the current user has an active membership for the
first-label subdomain. If not, it fires `logout` + redirects to
`/login`. This catches the case where the React Query cache for
`/api/auth/me/` is still warm from the previous tenant — the
user briefly arrives with a valid `user` object, but the
membership check prevents them seeing the chrome.

Platform admins skip this check on the frontend too (mirrors the
backend rule).

### 4. Tests

`CrossTenantSessionTerminationTests` in
`apps.tenants.tests` covers six scenarios:

1. Staff on their own tenant → session preserved + membership
   populated.
2. Staff on a foreign tenant → session force-terminated +
   downstream user is anonymous.
3. Platform admin on a foreign tenant → session preserved.
4. Superuser on a foreign tenant → session preserved.
5. Anonymous request on a foreign tenant → unaffected (no session
   to revoke).
6. Bare/unknown hostname (no resolved tenant) → unaffected.

Full suite: 931 backend tests passing after the change. No
existing assertions had to be adjusted — the permission swap from
`IsAuthenticated` to `IsTenantStaff` is a strict tightening, not
a behaviour change for legitimate users (anyone hitting an
endpoint already had a valid membership in their session).

## Consequences

### Good

- The original bug class — cross-tenant session ride-through — is
  closed at the routing layer, not patched per-endpoint.
- Defense in depth: even if a future endpoint forgets the
  `IsTenantStaff` permission, the middleware would have already
  anonymized the request.
- Multi-tenant staff workflows still work: a user who's a member
  of both tenants can navigate freely (their session has memberships
  on both, so the middleware check passes either way).
- Platform admins can still hop tenants for support.

### Bad / Deferred

- A staff user who's a member of two tenants and signs OUT of
  tenant A must explicitly sign in again at tenant B (the logout
  flushes the session entirely). This is the standard multi-
  tenant SaaS UX (Slack, Linear, Notion all behave this way) but
  worth flagging if the assumption was "one session, all tenants."
- Platform admin "view-as-tenant" mode (where an admin walks into
  a tenant's UI without becoming a member) is intentionally
  permissive here. A future polish could add an explicit
  `?as_tenant=<slug>` audit flag so the trail distinguishes
  admin-impersonation from regular-user activity.
- The security event log is in CloudWatch only — there's no
  alert pipeline yet. Phase 0c production-hardening item:
  surface the `cross_tenant_session_terminated` events on a
  Grafana panel so a sudden spike (= a credential-stuffing attempt
  walking subdomains) is visible.

### Acknowledged

- The cookie scope itself (`.<domain>`) is what makes cross-tenant
  navigation possible at all. We don't change that — narrowing
  the cookie to per-subdomain would break the legitimate
  multi-tenant-staff UX. The middleware-kill approach is the
  correct lever.
- Users with the staff session cookie can still HIT a wrong-
  tenant URL. They just get logged out + redirected. The visible
  side effect is one round-trip of "Signing you out…" before the
  login page; acceptable for a defensive layer that almost never
  fires for legitimate users.

## Alternatives considered

### Narrow the session cookie to per-subdomain

Considered briefly. Rejected: would force a re-login every time a
multi-tenant staff user clicked between spas. Standard SaaS
pattern is the domain-wide cookie + membership check.

### Per-endpoint `request.tenant_membership` check (no middleware kill)

This is what the codebase mostly already had, plus the `IsTenantStaff`
swap that's now done. We layered the middleware kill on top because:
- The vulnerability proved that "everyone remembers to use the right
  permission class" is not an enforceable rule under feature pressure.
- The middleware kill is one ~30-line block to audit; the per-
  endpoint approach is N classes that have to stay in lockstep.

### Server-rendered tenant check (in the frontend)

Considered. Rejected — Next.js `'use client'` layouts don't have a
clean way to do this server-side. Adding a server component shim
for a single check isn't worth the architectural cost. The backend
middleware + client-side defense in (app)/layout.tsx covers it.

## Audit checklist for future endpoints

Adding a new staff-facing API endpoint? It must use
`IsTenantStaff` OR an app-specific permission class that itself
checks `request.tenant_membership`. Things that may NOT be
`IsAuthenticated`-only:

- Anything that reads a tenant-scoped queryset.
- Anything that writes a tenant-scoped row.
- Anything that returns tenant-identifying data (the spa name,
  config flags, branding fields).

Things that legitimately use `IsAuthenticated` only:

- LogoutView — must work for any session being terminated.
- MeView — exists specifically to tell the client who they are,
  before tenant routing is meaningful. The middleware kill ensures
  this returns 401 for cross-tenant attempts anyway.

Anything `AllowAny` must justify why no auth is needed (public
booking endpoints, Twilio webhooks with HMAC verification, etc.).
