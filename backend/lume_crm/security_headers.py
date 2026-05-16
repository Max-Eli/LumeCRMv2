"""
Browser-side security headers — defense layer between Django and the
public internet, on top of what Django's `SecurityMiddleware` already
sets (HSTS, content-type nosniff, referrer policy, X-Frame-Options).

Headers added here:

  Content-Security-Policy
    Restrict what the browser will execute / load on the API origin.
    The API never serves HTML to end users — admin + DRF browsable
    are the only HTML surfaces and CSP needs to allow their inline
    scripts. Default-src 'none' makes "what's allowed" explicit;
    every directive is a deliberate carve-out.

  Cross-Origin-Opener-Policy: same-origin
    Prevents a window opened from a phishing site from cross-origin
    interactions with our API responses.

  Cross-Origin-Resource-Policy: same-origin
    Prevents other origins from embedding our API responses (e.g. via
    `<img src="https://api.xn--lumcrm-5ua.com/api/customers/1.json">` to leak
    response sizes through cross-origin timing).

  Permissions-Policy
    Disable browser features the API has no business invoking
    (camera, microphone, geolocation, etc.) so a compromised admin
    page can't be coerced into using them.

Why this isn't `django-csp`: that library has a configuration model
that fights us when the policy needs different directives per route
(admin needs unsafe-inline; API doesn't need any HTML at all). One
hand-rolled middleware reads more honestly than a config DSL.
"""

from __future__ import annotations

from typing import Callable

from django.http import HttpRequest, HttpResponse


# CSP for HTML responses. Admin + DRF browsable get a slightly looser
# policy than the JSON API needs because Django's admin ships inline
# scripts. We detect HTML responses by Content-Type to apply each.

_CSP_HTML = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "font-src 'self' data:; "
    "connect-src 'self'; "
    # Block any frame embedding regardless of X-Frame-Options support.
    "frame-ancestors 'none'; "
    # Don't allow forms to post anywhere except this origin.
    "form-action 'self'; "
    # Force any subresource to use HTTPS even if a request escapes
    # with http://.
    "upgrade-insecure-requests"
)

# JSON / API responses don't render anything in a browser. Hard-default
# to 'none' across the board; if a non-HTML response is somehow opened
# in a browser tab, the browser refuses to execute anything.
_CSP_API = (
    "default-src 'none'; "
    "frame-ancestors 'none'; "
    "form-action 'none'"
)

_PERMISSIONS_POLICY = (
    'accelerometer=(), '
    'ambient-light-sensor=(), '
    'autoplay=(), '
    'battery=(), '
    'camera=(), '
    'display-capture=(), '
    'document-domain=(), '
    'encrypted-media=(), '
    'fullscreen=(self), '
    'geolocation=(), '
    'gyroscope=(), '
    'magnetometer=(), '
    'microphone=(), '
    'midi=(), '
    'payment=(), '
    'picture-in-picture=(), '
    'publickey-credentials-get=(self), '
    'screen-wake-lock=(), '
    'sync-xhr=(self), '
    'usb=(), '
    'xr-spatial-tracking=()'
)


class SecurityHeadersMiddleware:
    """Apply browser-defense headers to every response."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        response = self.get_response(request)

        is_html = response.get('Content-Type', '').lower().startswith('text/html')
        response.setdefault(
            'Content-Security-Policy',
            _CSP_HTML if is_html else _CSP_API,
        )
        response.setdefault('Cross-Origin-Opener-Policy', 'same-origin')
        response.setdefault('Cross-Origin-Resource-Policy', 'same-origin')
        response.setdefault('Permissions-Policy', _PERMISSIONS_POLICY)

        return response
