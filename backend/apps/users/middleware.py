"""
Auth-side middleware — HIPAA technical safeguards.

`IdleSessionTimeoutMiddleware` enforces an automatic logoff after a
configurable idle window (default 30 minutes). HIPAA §164.312(a)(2)(iii)
requires "procedures that terminate an electronic session after a
predetermined time of inactivity" — this is that procedure.

How it works: every authenticated request stamps `request.session` with
the current epoch second. On the next request we compare; if the gap
exceeds `IDLE_SESSION_TIMEOUT_SECONDS`, we call `logout(request)` and
let the response flow through normally. The view sees an anonymous
user and renders a 401 (the frontend's auth gate redirects to
`/login`).

Public endpoints (login, logout, csrf, healthz, the public booking
surface) are exempt — they're either anonymous-only or LB-driven.

Configuration:

    IDLE_SESSION_TIMEOUT_SECONDS    int, default 1800 (30 min)

We don't make this user-configurable. HIPAA's "reasonable" framing
puts the burden on us as the system designer; per-tenant overrides
would invite "we set it to 8 hours" defenses we don't want to argue.
"""

from __future__ import annotations

import time
from typing import Callable

from django.conf import settings
from django.contrib.auth import logout
from django.http import HttpRequest, HttpResponse


_LAST_ACTIVITY_KEY = '_lume_last_activity_at'

# Paths that bypass the idle check. Match by prefix (startswith).
# Anonymous endpoints + LB endpoints never need a stamp because there's
# no session to expire.
_EXEMPT_PREFIXES = (
    '/healthz',
    '/api/auth/login/',
    '/api/auth/logout/',
    '/api/auth/csrf/',
    '/api/auth/platform/login/',
    '/api/booking/',                # public client booking surface
    '/static/',
    '/admin/login/',                # let the admin handle its own redirect
)


class IdleSessionTimeoutMiddleware:
    """Log the user out when their session has been idle too long."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response
        self.timeout_seconds = getattr(
            settings,
            'IDLE_SESSION_TIMEOUT_SECONDS',
            30 * 60,
        )

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if self._should_skip(request):
            return self.get_response(request)

        if request.user.is_authenticated:
            now = int(time.time())
            last = request.session.get(_LAST_ACTIVITY_KEY)
            if isinstance(last, int) and (now - last) > self.timeout_seconds:
                # Drop the session before passing the request along —
                # the view sees an anonymous user and DRF returns 401.
                logout(request)
            else:
                # Fresh activity stamp. Writing every request keeps the
                # idle clock honest at the cost of one session-table
                # write per call. We accept the cost; the alternative
                # (only stamp every N seconds) opens a "near-the-edge"
                # race we don't want to argue about in audit.
                request.session[_LAST_ACTIVITY_KEY] = now

        return self.get_response(request)

    def _should_skip(self, request: HttpRequest) -> bool:
        path = request.path or ''
        return any(path.startswith(prefix) for prefix in _EXEMPT_PREFIXES)
