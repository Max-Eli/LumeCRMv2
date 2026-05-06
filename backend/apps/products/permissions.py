"""DRF permission for the products API.

Read for any authenticated tenant member (front-desk needs the
catalog at point-of-sale; providers may glance to recommend a
product to a client). Mutating actions plus the stock-adjustment
action require `MANAGE_SERVICES`, which Owner + Manager have by
default. Front-desk sells products via the invoice flow (which
auto-decrements stock) but cannot edit the catalog itself.

Products are not PHI. The catalog itself is non-clinical business
config; the per-customer link happens at invoice-line time and is
governed by invoice-level audit logging.
"""

from rest_framework.permissions import BasePermission

from apps.tenants.permissions import P


MUTATING_ACTIONS = frozenset({
    'create',
    'update',
    'partial_update',
    'destroy',
    'adjust_stock',
})


class ProductPermission(BasePermission):
    """Read for any authenticated member; write requires MANAGE_SERVICES."""

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True

        membership = getattr(request, 'tenant_membership', None)
        if not membership:
            return False

        if view.action in MUTATING_ACTIONS:
            return membership.has(P.MANAGE_SERVICES)
        return True
