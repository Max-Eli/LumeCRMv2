"""DRF permission class for the services API.

Services aren't PHI — they're business config. Anyone authenticated within a
tenant can read them (needed for booking, calendar display, public-facing
booking page, etc.). Mutating actions require `MANAGE_SERVICES`, which by
default is granted to Owner and Manager roles.
"""

from rest_framework.permissions import BasePermission

from apps.tenants.permissions import P


MUTATING_ACTIONS = frozenset({'create', 'update', 'partial_update', 'destroy'})


class ServicePermission(BasePermission):
    """Read for any authenticated tenant member; write requires MANAGE_SERVICES."""

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
