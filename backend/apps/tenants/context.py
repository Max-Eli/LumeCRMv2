"""Per-request tenant + location context.

`TenantMiddleware` sets the current tenant at the start of each request;
`LocationMiddleware` (running after it) sets the current location within
that tenant. Anywhere in the codebase can call `get_current_tenant()` or
`get_current_location()` to read either.

Uses `contextvars` so it works in both sync and async code paths and is
properly scoped per-task in async views.

Usage:
    from apps.tenants.context import get_current_tenant, get_current_location
    tenant = get_current_tenant()
    location = get_current_location()  # always within `tenant` if non-None

    # To run a block of code with a specific tenant + location (background
    # jobs, tests, management commands):
    with tenant_context(tenant), location_context(location):
        ...
"""

from contextlib import contextmanager
from contextvars import ContextVar


_current_tenant: ContextVar = ContextVar('current_tenant', default=None)
_current_location: ContextVar = ContextVar('current_location', default=None)


def set_current_tenant(tenant):
    """Set the current tenant. Returns a token that can be passed to reset_current_tenant()."""
    return _current_tenant.set(tenant)


def reset_current_tenant(token):
    """Reset to the previous tenant value. Use the token returned by set_current_tenant()."""
    _current_tenant.reset(token)


def get_current_tenant():
    """Return the current tenant, or None if none is set."""
    return _current_tenant.get()


def set_current_location(location):
    """Set the current location. Returns a token that can be passed to reset_current_location()."""
    return _current_location.set(location)


def reset_current_location(token):
    """Reset to the previous location value. Use the token returned by set_current_location()."""
    _current_location.reset(token)


def get_current_location():
    """Return the current location, or None if none is set.

    Always within the current tenant when both are set — `LocationMiddleware`
    only resolves a location whose `tenant_id` matches `request.tenant`.
    """
    return _current_location.get()


@contextmanager
def tenant_context(tenant):
    """Context manager that sets the current tenant for the duration of the block."""
    token = _current_tenant.set(tenant)
    try:
        yield
    finally:
        _current_tenant.reset(token)


@contextmanager
def location_context(location):
    """Context manager that sets the current location for the duration of the block."""
    token = _current_location.set(location)
    try:
        yield
    finally:
        _current_location.reset(token)
