"""Permission class for integrations endpoints.

Gated to MANAGE_INTEGRATIONS — owner + manager by default. The perm
is in `LOCKED_PERMISSIONS` so it can't be granted via per-user
override; must come from role.
"""

from rest_framework.permissions import BasePermission

from apps.tenants.permissions import P


class IntegrationPermission(BasePermission):
    """Gate every integrations endpoint to MANAGE_INTEGRATIONS."""

    message = 'Integration management requires the MANAGE_INTEGRATIONS permission.'

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        membership = getattr(request, 'tenant_membership', None)
        if not membership:
            return False
        return membership.has(P.MANAGE_INTEGRATIONS)

    def has_object_permission(self, request, view, obj):
        # Tenant isolation belt + suspenders. Queryset is already
        # for_current_tenant() filtered, but defensive check.
        if request.user.is_superuser:
            return True
        membership = getattr(request, 'tenant_membership', None)
        if not membership:
            return False
        return obj.tenant_id == membership.tenant_id
