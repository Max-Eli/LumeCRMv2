"""DRF permission for portal endpoints.

Gates on `request.customer` being set by `PortalSessionMiddleware`.
Returns 401 (not 403) on miss so the frontend can distinguish "log
back in" from "you don't have permission" — same convention as the
staff session expiry path.
"""

from __future__ import annotations

from rest_framework.permissions import BasePermission


class IsPortalCustomer(BasePermission):
    """Permission class for portal-facing endpoints.

    Pass when `request.customer` is a non-null Customer (set by
    `PortalSessionMiddleware` on successful cookie auth). Fail
    otherwise — DRF maps this to a 403 by default; we override
    `message` so the frontend can rely on the body. The frontend's
    API client treats portal 401/403 identically as "redirect to
    /portal/login".
    """

    message = 'Portal authentication required.'

    def has_permission(self, request, _view) -> bool:
        return getattr(request, 'customer', None) is not None
