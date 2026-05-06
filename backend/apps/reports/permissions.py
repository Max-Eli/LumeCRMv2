"""Permission class for the reports API.

Each report view sets a `permission` class attribute (one of the
`P.VIEW_*_REPORTS` constants); this class reads that attribute at
request time and gates against the current membership. Centralizing
the gate here keeps every report view consistent with the audit-
logging expectation set in ADR 0013 — if you can call the view, the
audit log will record it.

The catalog endpoint (`GET /api/reports/`) uses
`ReportCatalogPermission`: any authenticated tenant member can ask
"which reports am I allowed to run?" — the response is
permission-filtered server-side, so listing the catalog never leaks
a report the user can't actually call.
"""

from rest_framework.permissions import BasePermission


class ReportPermission(BasePermission):
    """Gate a report view by the permission constant on the view class.

    Subclassed by every concrete report view via
    `permission_classes = [ReportPermission]`. The view's `permission`
    attribute (e.g. `P.VIEW_FINANCIAL_REPORTS`) determines what role
    the membership needs.

    Read-only — every report endpoint is GET-only by design.
    """

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True

        membership = getattr(request, 'tenant_membership', None)
        if not membership:
            return False

        required = getattr(view, 'permission', None)
        if not required:
            return False

        return membership.has(required)


class ReportCatalogPermission(BasePermission):
    """Gate the catalog list endpoint to any authenticated tenant member.

    The response is filtered server-side by what the membership can
    actually run — a report the user lacks permission for is omitted
    from the catalog entirely, so this gate just enforces "you must be
    in a tenant."
    """

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        return getattr(request, 'tenant_membership', None) is not None
