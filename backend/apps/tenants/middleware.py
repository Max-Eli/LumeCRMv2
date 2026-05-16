"""Subdomain-based tenant resolution + cookie-based location resolution.

Two middlewares live here. Both must be installed (in this order) in
`MIDDLEWARE`:

  1. `TenantMiddleware` — resolves `request.tenant` from the subdomain
     (or `X-Tenant-Slug` header in dev), plus `request.tenant_membership`
     when the user is authenticated. **Critical:** when an authenticated
     staff user lands on a tenant subdomain they have NO active
     membership for, the session is force-logged-out and the request
     continues as anonymous. Subdomain-as-tenant-boundary is the load-
     bearing isolation guarantee — without this kill-the-session step,
     a staff user on `acme.lumecrm.com` could navigate to
     `evil.lumecrm.com` and have their session silently carry over
     because the cookie is scoped to `.lumecrm.com` (necessary for the
     subdomain-routing UX to work at all). Platform admins
     (`is_superuser` or `is_platform_admin`) are intentionally exempt —
     they can hop tenants for support reasons.
  2. `LocationMiddleware` — resolves `request.location` from the
     `lume_active_location` cookie, scoped to `request.tenant`. Falls back
     to the tenant's default location when the cookie is missing,
     malformed, or points at a location that no longer exists / belongs
     to a different tenant. The middleware never raises — a missing
     active location just means downstream code uses the default site.

Subdomains "www", "admin", "api", and "localhost" are reserved and never
treated as tenant slugs.
"""

import logging

from django.contrib.auth import logout as django_logout

from .context import (
    reset_current_location,
    reset_current_tenant,
    set_current_location,
    set_current_tenant,
)
from .models import Location, Tenant, TenantMembership

logger = logging.getLogger(__name__)


RESERVED_SUBDOMAINS = {'www', 'admin', 'api', 'localhost', ''}

# Cookie used to remember which Location the operator picked from the
# location switcher (Phase 1H multi-location session 3). Same name across
# tenants — the value is a per-tenant location slug, validated against
# `request.tenant` in `LocationMiddleware`.
ACTIVE_LOCATION_COOKIE = 'lume_active_location'


class TenantMiddleware:
    """Resolve the request's tenant from its subdomain and populate request context.

    Sets three things per request:
      - `request.tenant` — the resolved Tenant model instance, or None
      - `request.tenant_membership` — current user's membership in that tenant (if authenticated), or None
      - the request-scoped tenant `ContextVar` (so non-request code can call `get_current_tenant()`)

    Reserved subdomains (`www`, `admin`, `api`, `localhost`) and bare hostnames
    are never treated as tenant slugs. Inactive tenants resolve to None.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.tenant = self._resolve_tenant(request)
        request.tenant_membership = self._resolve_membership(request)

        # Tenant-isolation enforcement. See the module docstring —
        # this is the kill-the-session step that prevents the
        # subdomain session-cookie from leaking access across tenants.
        self._enforce_tenant_isolation(request)

        token = set_current_tenant(request.tenant)
        try:
            return self.get_response(request)
        finally:
            reset_current_tenant(token)

    def _enforce_tenant_isolation(self, request):
        """If a Django-authenticated user is on a tenant subdomain
        they have no active membership for, log them out fully so the
        request continues as anonymous + the next request lands them
        on the login page.

        No-ops in three cases:
          - Tenant didn't resolve (bare host, marketing pages, etc.) —
            there's no tenant boundary to enforce.
          - User isn't authenticated — nothing to revoke.
          - User is a platform admin (`is_superuser` or
            `is_platform_admin`). Support engineers + the platform
            console need cross-tenant reach.

        We logout via Django's helper rather than just clearing
        `request.user` because the session cookie needs to be
        invalidated server-side too — otherwise the next request
        would re-attach the same session and re-trigger this code
        in a loop.
        """
        user = getattr(request, 'user', None)
        tenant = getattr(request, 'tenant', None)
        if user is None or not user.is_authenticated or tenant is None:
            return
        if getattr(user, 'is_superuser', False) or getattr(user, 'is_platform_admin', False):
            return
        if request.tenant_membership is not None:
            return

        # Mismatch. Log a security event (not the user's email) and
        # flush the session.
        logger.warning(
            'tenants.security.cross_tenant_session_terminated',
            extra={
                'tenant_slug': tenant.slug,
                'user_id': user.id,
                'path': request.path,
            },
        )
        django_logout(request)
        # Re-anonymise the current request so the rest of the stack
        # sees an unauthenticated user immediately, not just on the
        # next request.
        from django.contrib.auth.models import AnonymousUser
        request.user = AnonymousUser()
        # Membership obviously stays None — already is.

    def _resolve_tenant(self, request):
        # 1. Try the request subdomain (production canonical path).
        host = request.get_host().split(':', 1)[0]
        tenant = self._tenant_from_subdomain(host)
        if tenant is not None:
            return tenant

        # 2. Fallback: X-Tenant-Slug header. Used in dev where the frontend at
        #    localhost:3000 calls the backend at localhost:8000 and there's no
        #    real tenant subdomain in play. Also set by the staff app cookie
        #    forwarding when the user has logged in.
        header_slug = request.META.get('HTTP_X_TENANT_SLUG', '').strip().lower()
        if header_slug:
            try:
                return Tenant.objects.get(slug=header_slug, status=Tenant.Status.ACTIVE)
            except Tenant.DoesNotExist:
                return None

        # 3. Fallback: parse the originating page's host from `Origin` (or
        #    `Referer`) and look the subdomain up against the tenants table.
        #    Why: the customer portal frontend lives at `<tenant>.<domain>`
        #    but its API calls hit `api.<domain>`, where neither
        #    `request.get_host()` (the API subdomain) nor `X-Tenant-Slug`
        #    (no staff cookie for anonymous portal users) resolves a tenant.
        #    The browser sets `Origin` automatically on `fetch`; using it here
        #    is routing only — actual authorization for the portal session
        #    still requires a valid magic-link token / session cookie that's
        #    bound to a specific tenant in the database.
        origin = request.META.get('HTTP_ORIGIN', '').strip()
        if origin:
            tenant = self._tenant_from_url(origin)
            if tenant is not None:
                return tenant
        referer = request.META.get('HTTP_REFERER', '').strip()
        if referer:
            tenant = self._tenant_from_url(referer)
            if tenant is not None:
                return tenant

        return None

    def _tenant_from_subdomain(self, host: str):
        """Look up a tenant by the first label of `host`. Returns None
        when the label is reserved, when there are fewer than two labels
        (bare hostname), or when no active tenant matches."""
        parts = host.split('.')
        if len(parts) < 2:
            return None
        subdomain = parts[0].lower()
        if subdomain in RESERVED_SUBDOMAINS:
            return None
        try:
            return Tenant.objects.get(slug=subdomain, status=Tenant.Status.ACTIVE)
        except Tenant.DoesNotExist:
            return None

    def _tenant_from_url(self, url: str):
        """Parse a full URL and return the tenant matching its subdomain."""
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            host = (parsed.hostname or '').strip()
            if not host:
                return None
            return self._tenant_from_subdomain(host)
        except Exception:  # pragma: no cover - defensive
            return None

    def _resolve_membership(self, request):
        if not request.tenant:
            return None
        if not getattr(request, 'user', None) or not request.user.is_authenticated:
            return None

        return (
            TenantMembership.objects
            .filter(tenant=request.tenant, user=request.user, is_active=True)
            .select_related('job_title')
            .first()
        )


class LocationMiddleware:
    """Resolve the request's active Location and populate request context.

    Sets per request:
      - `request.location` — the active Location instance, or None when
        there's no tenant on the request (e.g. login page on a bare
        hostname).
      - the request-scoped location `ContextVar` so non-request code can
        call `get_current_location()`.

    Resolution order:
      1. `lume_active_location` cookie value, if present and the slug
         belongs to an active Location of `request.tenant`.
      2. The tenant's default Location (`is_default=True, is_active=True`).
      3. None.

    Must run AFTER `TenantMiddleware` — depends on `request.tenant` being
    populated. Falls through silently when `request.tenant is None` so
    public/unauthenticated routes don't error.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.location = self._resolve_location(request)

        token = set_current_location(request.location)
        try:
            return self.get_response(request)
        finally:
            reset_current_location(token)

    def _resolve_location(self, request):
        tenant = getattr(request, 'tenant', None)
        if tenant is None:
            return None

        # 1. Cookie-driven choice (must belong to this tenant + be active).
        cookie_slug = (request.COOKIES.get(ACTIVE_LOCATION_COOKIE) or '').strip().lower()
        if cookie_slug:
            location = (
                Location.objects
                .filter(tenant=tenant, slug=cookie_slug, is_active=True)
                .first()
            )
            if location is not None:
                return location

        # 2. Fallback to the tenant's default location.
        return (
            Location.objects
            .filter(tenant=tenant, is_default=True, is_active=True)
            .first()
        )
