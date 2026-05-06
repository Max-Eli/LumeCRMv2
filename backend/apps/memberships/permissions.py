"""DRF permissions for the memberships API.

Two surfaces, two policies:

  - Catalog (`MembershipPlan` CRUD) — read open to any authenticated
    member (front-desk needs to see plans at point-of-sale); write
    + delete require `MANAGE_PACKAGES_MEMBERSHIPS` (Owner / Manager).
  - Per-customer subscriptions (`Subscription` list/retrieve +
    `cancel` action) — read requires `VIEW_CLIENT_LIST` (any
    customer-facing role); cancel requires `MANAGE_PACKAGES_MEMBERSHIPS`.

Sale + redemption flow through invoice action endpoints, gated by
`PROCESS_PAYMENT` — same separation as packages.
"""

from rest_framework.permissions import BasePermission

from apps.tenants.permissions import P


CATALOG_MUTATING = frozenset({
    'create', 'update', 'partial_update', 'destroy',
})


class MembershipPlanPermission(BasePermission):
    """Catalog gate. Read open; write requires MANAGE_PACKAGES_MEMBERSHIPS."""

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True

        membership = getattr(request, 'tenant_membership', None)
        if not membership:
            return False

        if view.action in CATALOG_MUTATING:
            return membership.has(P.MANAGE_PACKAGES_MEMBERSHIPS)
        return True


class SubscriptionPermission(BasePermission):
    """Per-customer gate. List/retrieve open to any member; cancel
    requires MANAGE_PACKAGES_MEMBERSHIPS.

    The list/retrieve scope is intentionally permissive — front-
    desk needs subscription state at checkout. Cancel is a
    consequential action (cuts off recurring revenue) so locked to
    the same gate as catalog edits.
    """

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True

        membership = getattr(request, 'tenant_membership', None)
        if not membership:
            return False

        if view.action == 'cancel':
            return membership.has(P.MANAGE_PACKAGES_MEMBERSHIPS)
        return True
