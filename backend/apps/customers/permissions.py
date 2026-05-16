"""DRF permission class for the customers API.

Maps ViewSet actions (list, retrieve, create, etc.) to the Lumè permission
identifiers defined in `apps.tenants.permissions.P` and resolved via the
request's `TenantMembership`.
"""

from rest_framework.permissions import BasePermission

from apps.tenants.permissions import P


class CustomerPermission(BasePermission):
    """Action-to-permission mapping for `CustomerViewSet`.

    Platform superusers bypass these checks. Everyone else must:
      1. Be authenticated.
      2. Have a `TenantMembership` resolved by `TenantMiddleware`.
      3. Hold the permission listed in `ACTION_PERMS` for the action.
    """

    ACTION_PERMS = {
        'list': P.VIEW_CLIENT_LIST,
        'retrieve': P.VIEW_CLIENT_LIST,
        'create': P.EDIT_CLIENT_RECORD,
        'update': P.EDIT_CLIENT_RECORD,
        'partial_update': P.EDIT_CLIENT_RECORD,
        'destroy': P.DELETE_CLIENT_RECORD,
        # Social-guest → real-customer merge (ADR 0027 §8b).
        'merge_into': P.EDIT_CLIENT_RECORD,
    }

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True

        membership = getattr(request, 'tenant_membership', None)
        if not membership:
            return False

        required = self.ACTION_PERMS.get(view.action)
        if not required:
            return False
        return membership.has(required)
