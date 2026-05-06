"""Permission classes for the chart-notes surface.

Two distinct gates:

  - `ChartNoteReadPermission` — gates list + retrieve. Requires
    `VIEW_CHART` (provider role + owner/manager). Front desk +
    bookkeeper + marketing roles see "no access" UI.
  - `ChartNoteWritePermission` — gates create + edit. Requires
    `SIGN_CHART` (same default holders as VIEW_CHART today, but
    keeping them separate so a future "read-only clinical
    reviewer" role can hold VIEW without SIGN).

Edit-within-window + author-ownership checks are NOT in the
permission class — they live on the model
(`ChartNote.can_be_edited_by`) and the view, because they depend on
the specific record being mutated. The permission class is the
"can the caller hit this endpoint at all" gate.
"""

from rest_framework.permissions import BasePermission

from apps.tenants.permissions import P


class ChartNoteReadPermission(BasePermission):
    """Gate read access (list / retrieve) on `VIEW_CHART`."""

    message = 'Chart access requires the VIEW_CHART permission.'

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        membership = getattr(request, 'tenant_membership', None)
        if not membership:
            return False
        return membership.has(P.VIEW_CHART)

    def has_object_permission(self, request, view, obj):
        # Tenant isolation belt + suspenders. The queryset is already
        # for_current_tenant() filtered, but the defensive check
        # catches cross-tenant retrieval if the queryset shape ever
        # changes.
        if request.user.is_superuser:
            return True
        membership = getattr(request, 'tenant_membership', None)
        if not membership:
            return False
        if obj.tenant_id != membership.tenant_id:
            return False
        return membership.has(P.VIEW_CHART)


class ChartNoteWritePermission(BasePermission):
    """Gate write access (create / edit) on `SIGN_CHART`.

    Edit-within-window + author-ownership are enforced separately
    by the view (see `ChartNote.can_be_edited_by`) — those depend
    on the specific record, not the caller's role.
    """

    message = 'Signing chart notes requires the SIGN_CHART permission.'

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.method in ('GET', 'HEAD', 'OPTIONS'):
            # Read methods fall back to ChartNoteReadPermission's
            # check; this class only adds the SIGN_CHART gate on
            # writes.
            return _has_read_perm(request)
        if request.user.is_superuser:
            return True
        membership = getattr(request, 'tenant_membership', None)
        if not membership:
            return False
        return membership.has(P.SIGN_CHART)

    def has_object_permission(self, request, view, obj):
        if request.user.is_superuser:
            return True
        membership = getattr(request, 'tenant_membership', None)
        if not membership:
            return False
        if obj.tenant_id != membership.tenant_id:
            return False
        if request.method in ('GET', 'HEAD', 'OPTIONS'):
            return membership.has(P.VIEW_CHART)
        return membership.has(P.SIGN_CHART)


def _has_read_perm(request) -> bool:
    if request.user.is_superuser:
        return True
    membership = getattr(request, 'tenant_membership', None)
    if not membership:
        return False
    return membership.has(P.VIEW_CHART)
