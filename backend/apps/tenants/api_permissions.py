"""Shared DRF permission classes for staff-side tenant endpoints.

Separate file from `permissions.py` (which is the *catalog* of role
permission identifiers like `P.VIEW_CLIENT_LIST`) so the DRF
boundary doesn't pollute the role-permission module + so other
apps can import this without dragging the catalog along.

`IsTenantStaff` is the load-bearing gate every staff-facing
endpoint that doesn't have a more specific permission class should
use. It replaces bare `IsAuthenticated` — staff endpoints must
require a current-tenant membership, not just *any* authenticated
session, otherwise a user signed into tenant A could read tenant
B's data simply by changing the URL.

`TenantMiddleware` also enforces this at the request-routing level
(kills the session when a user lands on a tenant they have no
membership for), so this permission class is defense in depth —
even if the middleware fix is bypassed somehow, every endpoint
still re-checks.

Platform admins (`is_superuser` or `is_platform_admin`) bypass the
membership check — support engineers and the platform console need
cross-tenant reach.
"""

from rest_framework.permissions import BasePermission


class IsTenantStaff(BasePermission):
    """Authenticated user + active membership on the request's
    tenant. The middleware-level enforcement should make this a
    no-op in practice; the class exists so the security boundary is
    visible at every endpoint signature."""

    message = 'You must be a member of this spa to access this resource.'

    def has_permission(self, request, _view):
        user = getattr(request, 'user', None)
        if user is None or not user.is_authenticated:
            return False
        if getattr(user, 'is_superuser', False) or getattr(user, 'is_platform_admin', False):
            return True
        # `request.tenant_membership` is populated by `TenantMiddleware`
        # only when the user has an active membership on the request's
        # resolved tenant. Anything else (no membership, no tenant
        # resolved, wrong-tenant cookie) is rejected.
        return getattr(request, 'tenant_membership', None) is not None
