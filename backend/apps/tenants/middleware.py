"""Subdomain-based tenant resolution + cookie-based location resolution.

Two middlewares live here. Both must be installed (in this order) in
`MIDDLEWARE`:

  1. `TenantMiddleware` — resolves `request.tenant` from the subdomain
     (or `X-Tenant-Slug` header in dev), plus `request.tenant_membership`
     when the user is authenticated.
  2. `LocationMiddleware` — resolves `request.location` from the
     `lume_active_location` cookie, scoped to `request.tenant`. Falls back
     to the tenant's default location when the cookie is missing,
     malformed, or points at a location that no longer exists / belongs
     to a different tenant. The middleware never raises — a missing
     active location just means downstream code uses the default site.

Subdomains "www", "admin", "api", and "localhost" are reserved and never
treated as tenant slugs.
"""

from .context import (
    reset_current_location,
    reset_current_tenant,
    set_current_location,
    set_current_tenant,
)
from .models import Location, Tenant, TenantMembership


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

        token = set_current_tenant(request.tenant)
        try:
            return self.get_response(request)
        finally:
            reset_current_tenant(token)

    def _resolve_tenant(self, request):
        # 1. Try the request subdomain (production canonical path).
        host = request.get_host().split(':', 1)[0]
        parts = host.split('.')

        if len(parts) >= 2:
            subdomain = parts[0].lower()
            if subdomain not in RESERVED_SUBDOMAINS:
                try:
                    return Tenant.objects.get(slug=subdomain, status=Tenant.Status.ACTIVE)
                except Tenant.DoesNotExist:
                    pass

        # 2. Fallback: X-Tenant-Slug header. Used in dev where the frontend at
        #    localhost:3000 calls the backend at localhost:8000 and there's no
        #    real tenant subdomain in play. Production typically uses subdomains.
        header_slug = request.META.get('HTTP_X_TENANT_SLUG', '').strip().lower()
        if header_slug:
            try:
                return Tenant.objects.get(slug=header_slug, status=Tenant.Status.ACTIVE)
            except Tenant.DoesNotExist:
                return None

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
