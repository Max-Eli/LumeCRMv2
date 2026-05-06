"""DRF permission for the gift cards API.

Read access (list / retrieve / lookup) open to any authenticated
tenant member — front-desk needs to look up balances at checkout.

Write actions (void) require `MANAGE_PACKAGES_MEMBERSHIPS` (Owner /
Manager). Voiding a gift card cuts off a customer's outstanding
balance; same gravity as cancelling a subscription.

Sale + redemption happen through invoice action endpoints, gated
by `PROCESS_PAYMENT` (front-desk allowed) — handled in the
invoice permission class, not here.
"""

from rest_framework.permissions import BasePermission

from apps.tenants.permissions import P


class GiftCardPermission(BasePermission):
    """Read open to any member; void requires MANAGE_PACKAGES_MEMBERSHIPS."""

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True

        membership = getattr(request, 'tenant_membership', None)
        if not membership:
            return False

        if view.action == 'void':
            return membership.has(P.MANAGE_PACKAGES_MEMBERSHIPS)
        return True
