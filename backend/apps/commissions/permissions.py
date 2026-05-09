"""DRF permissions for the commissions API.

Two surfaces:

1. **Rules** (`CommissionRule` + `CommissionRuleOverride` CRUD).
   Owner / Manager only. Rate changes affect everyone's pay; not
   a place for distributed authority.

2. **Entries** (`CommissionEntry` ledger reads + per-staff totals).
   - Own entries / own totals: any active member with
     `VIEW_STAFF_PAYROLL_OWN`.
   - Others' entries: `VIEW_STAFF_REPORTS` (manager / bookkeeper /
     owner / marketing). Reads only — entries are never edited
     directly; reversal happens via the service layer.

The ledger is **append-only**. There's no DELETE on entries
exposed here.
"""

from rest_framework.permissions import BasePermission

from apps.tenants.permissions import P


class CommissionRulePermission(BasePermission):
    """Read open to any tenant member; write requires MANAGE_STAFF."""

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True

        membership = getattr(request, 'tenant_membership', None)
        if not membership or not membership.is_active:
            return False

        if view.action in {
            'create', 'update', 'partial_update', 'destroy',
        }:
            return membership.has(P.MANAGE_STAFF)
        return True


class CommissionEntryPermission(BasePermission):
    """Reads only. Own entries vs. tenant-wide split by perm."""

    def has_permission(self, request, view):
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            return False
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        membership = getattr(request, 'tenant_membership', None)
        if not membership or not membership.is_active:
            return False
        return True
