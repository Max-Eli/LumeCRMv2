"""Permission class for platform admin endpoints.

Single rule: `request.user.is_platform_admin` must be True. The
platform admin surface is Lumè-the-company; only accounts created
via `createplatformadmin` (or with the flag flipped explicitly via
Django shell / admin) can access it.

`is_superuser` does NOT grant platform admin access — those are two
distinct concepts:
  - `is_superuser` = Django admin (`/admin/`) access. Stock Django.
  - `is_platform_admin` = our cross-tenant management surface.

A user can be either, both, or neither. Platform admins are required
to have ZERO TenantMembership rows (enforced by the platform login
view) so they can't accidentally drift into tenant-side data.

The middleware-set `request.tenant_membership` is irrelevant here —
platform endpoints are NOT scoped to a single tenant.
"""

from rest_framework.permissions import BasePermission


class PlatformPermission(BasePermission):
    """Gate every platform endpoint to authenticated platform admins."""

    message = 'Platform admin access required.'

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        return bool(getattr(request.user, 'is_platform_admin', False))
