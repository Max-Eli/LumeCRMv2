"""DRF permission for the packages API.

Read access open to any authenticated tenant member (front-desk
needs the catalog at point-of-sale to add a package to an invoice).
Write access (catalog edits + manual void on a PurchasedPackage)
gated to `MANAGE_PACKAGES_MEMBERSHIPS`, granted to Owner + Manager
by default.

Sale + redemption are NOT here — they happen via invoice action
endpoints, gated by `PROCESS_PAYMENT` (front-desk allowed). That
keeps the catalog config layer separate from the day-to-day POS
surface, matching how Service / Product are gated.
"""

from rest_framework.permissions import BasePermission

from apps.tenants.permissions import P


MUTATING_ACTIONS = frozenset({
    'create',
    'update',
    'partial_update',
    'destroy',
})


class PackagePermission(BasePermission):
    """Read for any member; write requires MANAGE_PACKAGES_MEMBERSHIPS."""

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True

        membership = getattr(request, 'tenant_membership', None)
        if not membership:
            return False

        if view.action in MUTATING_ACTIONS:
            return membership.has(P.MANAGE_PACKAGES_MEMBERSHIPS)
        return True
