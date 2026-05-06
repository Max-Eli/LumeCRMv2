"""Permission classes for the marketing surface.

Two tiers:

  - `MarketingReadPermission` — list / retrieve audiences,
    templates, campaigns. Uses `VIEW_AUDIENCE_SEGMENTS`. Marketing,
    owner, manager, front-desk roles all have it by default.
  - `MarketingWritePermission` — create / update / delete + send.
    Uses `SEND_MARKETING_CAMPAIGN`. Marketing role + owner have it
    by default; manager has it via the all-permissions grant.
"""

from rest_framework.permissions import BasePermission

from apps.tenants.permissions import P


class MarketingReadPermission(BasePermission):
    """Gate read access on `VIEW_AUDIENCE_SEGMENTS`."""

    message = 'Marketing access requires the VIEW_AUDIENCE_SEGMENTS permission.'

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        membership = getattr(request, 'tenant_membership', None)
        if not membership:
            return False
        return membership.has(P.VIEW_AUDIENCE_SEGMENTS)

    def has_object_permission(self, request, view, obj):
        # Tenant-isolation belt + suspenders. The queryset is
        # already for_current_tenant() filtered.
        if request.user.is_superuser:
            return True
        membership = getattr(request, 'tenant_membership', None)
        if not membership:
            return False
        return obj.tenant_id == membership.tenant_id


class MarketingWritePermission(BasePermission):
    """Gate write access on `SEND_MARKETING_CAMPAIGN`. Reads still
    allowed via the Read perm; writes need the heavier gate."""

    message = 'Creating + sending marketing requires the SEND_MARKETING_CAMPAIGN permission.'

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        membership = getattr(request, 'tenant_membership', None)
        if not membership:
            return False
        if request.method in ('GET', 'HEAD', 'OPTIONS'):
            return membership.has(P.VIEW_AUDIENCE_SEGMENTS)
        return membership.has(P.SEND_MARKETING_CAMPAIGN)

    def has_object_permission(self, request, view, obj):
        if request.user.is_superuser:
            return True
        membership = getattr(request, 'tenant_membership', None)
        if not membership:
            return False
        if obj.tenant_id != membership.tenant_id:
            return False
        if request.method in ('GET', 'HEAD', 'OPTIONS'):
            return membership.has(P.VIEW_AUDIENCE_SEGMENTS)
        return membership.has(P.SEND_MARKETING_CAMPAIGN)
