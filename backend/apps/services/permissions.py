"""DRF permission class for the services API.

Services aren't PHI — they're business config. Anyone authenticated within a
tenant can read them (needed for booking, calendar display, public-facing
booking page, etc.). Mutating actions require `MANAGE_SERVICES`, which by
default is granted to Owner and Manager roles.
"""

from rest_framework.permissions import BasePermission

from apps.tenants.permissions import P


MUTATING_ACTIONS = frozenset({'create', 'update', 'partial_update', 'destroy'})

# HTTP methods that mutate state. Used as the fallback gate for
# APIView-based endpoints (e.g. ServiceProtocolView) where DRF
# doesn't populate `view.action`.
MUTATING_METHODS = frozenset({'POST', 'PUT', 'PATCH', 'DELETE'})


class ServicePermission(BasePermission):
    """Read for any authenticated tenant member; write requires MANAGE_SERVICES.

    Recognises both ViewSet `action` semantics AND raw HTTP methods so
    APIView-based singletons (like `ServiceProtocolView`) get the same
    gate without each one re-implementing the role check.
    """

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True

        membership = getattr(request, 'tenant_membership', None)
        if not membership:
            return False

        action = getattr(view, 'action', None)
        is_mutation = (
            action in MUTATING_ACTIONS
            or (action is None and request.method in MUTATING_METHODS)
        )
        if is_mutation:
            return membership.has(P.MANAGE_SERVICES)
        return True
