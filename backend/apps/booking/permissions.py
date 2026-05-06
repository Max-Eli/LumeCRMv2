"""Permission + throttle classes for the public booking surface.

Booking endpoints have no auth — anyone on the internet can read a
spa's services + slot calendar and submit a booking. Two enforcement
primitives:

  1. **CSRF** — disabled (no session to ride). The booking_token is
     the security boundary on manage-flow endpoints.
  2. **Rate limiting** — DRF throttle classes scoped per-IP. Read
     endpoints (info, services, slots) get a generous rate; write
     endpoints (submit, reschedule, cancel) get a tighter one to
     curb abuse without breaking legitimate iteration.

Everything else (tenant scoping, service-belongs-to-tenant,
slot-still-free) is enforced in the view because it requires DB
context the permission/throttle layer doesn't have.
"""

from rest_framework.permissions import BasePermission
from rest_framework.throttling import AnonRateThrottle


class PublicBookingPermission(BasePermission):
    """Allow any client to hit booking endpoints. The actual abuse
    gate is the throttle classes below."""

    def has_permission(self, request, view):
        return True


class BookingSubmitThrottle(AnonRateThrottle):
    """Per-IP throttle for the booking-submit endpoint.

    Rate is configured in `REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']`
    under the scope name. 10/hour is enough for a real customer who
    needs to retry a few times after a slot conflict but blocks the
    naive scraper / spam-poster. Counting is per-IP via DRF's
    AnonRateThrottle which keys on `REMOTE_ADDR` (or the first IP
    in `X-Forwarded-For` when the proxy header is trusted).

    Cache backend: Django's default `local-memory` for v1. When we
    move to multi-instance hosting (Phase 0c production lift), we
    swap to Redis so the count is shared across processes — until
    then a single-instance deploy gives us accurate counts.
    """

    scope = 'booking_submit'


class BookingRescheduleThrottle(AnonRateThrottle):
    """Per-IP throttle for the manage-token reschedule endpoint.

    Slightly higher rate than submit (20/hour) because a customer
    iterating through the slot picker may PATCH multiple times
    before settling on a final choice. Same per-IP scoping; same
    cache backend caveat as `BookingSubmitThrottle`.
    """

    scope = 'booking_reschedule'
