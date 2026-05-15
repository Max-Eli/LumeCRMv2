"""Portal session middleware — extracts `request.customer` from the
portal session cookie on every request.

Mounted alongside but separate from Django's session/auth middleware
because the customer-identity surface is structurally different from
the staff `User` identity. A request can have a staff `User` (via
the standard `AuthenticationMiddleware`) OR a portal `Customer` (via
this middleware), but not both — they're parallel identity systems.

We DO NOT collapse the two via the `User` model because:

  - Customers don't have most User fields (no role, no
    `is_staff`, no permissions).
  - Putting them in `User` would force every existing
    `request.user.is_authenticated` check to also disambiguate
    "is this a staff user or a customer?" — a thousand-callsite
    refactor for marginal benefit.
  - Sessions for the two are isolated by cookie name, so a
    customer can never accidentally inherit staff permissions
    even if both cookies were present.

The middleware sets `request.customer` to the active Customer
instance or None. Portal endpoints depend on this attribute via
the `IsPortalCustomer` DRF permission class in `permissions.py`.
"""

from __future__ import annotations

import logging

from django.utils.deprecation import MiddlewareMixin

from .models import CustomerPortalSession

# Cookie name for the customer-portal session token. Distinct from
# Django's `sessionid` so the two identity systems are isolated even
# on the same domain.
PORTAL_SESSION_COOKIE = 'lume_portal_session'

logger = logging.getLogger(__name__)


class PortalSessionMiddleware(MiddlewareMixin):
    """Resolves `request.customer` from the portal session cookie."""

    def process_request(self, request):
        # Default the attribute so endpoints can safely read it
        # without an AttributeError when no portal session exists.
        request.customer = None
        request.portal_session = None

        token = request.COOKIES.get(PORTAL_SESSION_COOKIE)
        if not token:
            return None

        # Pull the session + the linked customer in one query. The
        # `last_seen_at` bump happens after the active-check so an
        # expired session doesn't keep refreshing itself indefinitely.
        try:
            session = (
                CustomerPortalSession.objects
                .select_related('customer', 'tenant')
                .get(token=token)
            )
        except CustomerPortalSession.DoesNotExist:
            # Stale/forged cookie — silently ignore. The portal-cookie
            # set call from the consume endpoint is the only legitimate
            # source; anything that doesn't match is treated as anonymous.
            return None

        if not session.is_active:
            # Lazy-clean expired sessions on read. Don't surface anything
            # to the request — the endpoint will treat them as anonymous
            # and the frontend will redirect to /portal/login on 401.
            return None

        session.touch()
        request.customer = session.customer
        request.portal_session = session
        return None
