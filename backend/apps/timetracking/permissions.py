"""DRF permission for the time tracking API.

Read access:
  - Self (own membership) — any authenticated active member.
  - Others — `MANAGE_STAFF` OR `VIEW_STAFF_REPORTS`.

Mutations:
  - clock-in / clock-out for self — any authenticated active member.
  - clock-in / clock-out for others — `MANAGE_STAFF`.
  - Edit / delete (PATCH / DELETE) — `MANAGE_STAFF` (post-hoc
    payroll corrections).

All decisions are object-level when applicable; the view also
filters the queryset to enforce "see only your own" for non-
privileged callers.
"""

from rest_framework.permissions import BasePermission

from apps.tenants.permissions import P


class TimeEntryPermission(BasePermission):
    """Self-service for own entries; manager gating for others."""

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True

        membership = getattr(request, 'tenant_membership', None)
        if not membership or not membership.is_active:
            return False

        # Edit / delete (PATCH / DELETE on detail) — manager only.
        if view.action in {'update', 'partial_update', 'destroy'}:
            return membership.has(P.MANAGE_STAFF)

        # All other actions are list-or-detail filtered by the
        # queryset in the view; permission here is "is a tenant
        # member at all."
        return True

    def has_object_permission(self, request, view, obj):
        if request.user.is_superuser:
            return True

        membership = getattr(request, 'tenant_membership', None)
        if not membership:
            return False
        if obj.tenant_id != membership.tenant_id:
            return False

        # Manager + owner can do anything within the tenant.
        if membership.has(P.MANAGE_STAFF):
            return True
        # Otherwise: own entries only.
        return obj.membership_id == membership.pk
