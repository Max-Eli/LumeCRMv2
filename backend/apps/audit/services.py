"""Audit logging helper.

Use `record(...)` from anywhere in the app to write an audit log entry. Pulls
context (user, tenant, IP, user agent) automatically from the request when
provided, or accepts explicit overrides for use in background jobs.
"""

from .models import AuditLog


def record(
    *,
    action: str,
    resource_type: str = '',
    resource_id=None,
    user=None,
    tenant=None,
    request=None,
    metadata: dict | None = None,
) -> AuditLog:
    """Record an audit log entry.

    Args:
        action: one of AuditLog.Action values (e.g. 'login', 'read', 'update')
        resource_type: e.g. 'customer', 'invoice'
        resource_id: PK of the resource being acted on (any type — coerced to str)
        user: User who performed the action; pulled from request.user if request is given
        tenant: Tenant the action belongs to; pulled from request.tenant if request is given
        request: Django HttpRequest; if provided, pulls user/tenant/IP/user-agent from it
        metadata: extra structured context (e.g. {'fields_changed': [...]})

    Returns:
        The created AuditLog row.
    """
    ip = None
    user_agent = ''

    if request is not None:
        ip = _client_ip(request)
        user_agent = (request.META.get('HTTP_USER_AGENT') or '')[:500]
        if user is None and getattr(request, 'user', None) and request.user.is_authenticated:
            user = request.user
        if tenant is None:
            tenant = getattr(request, 'tenant', None)

    return AuditLog.objects.create(
        action=action,
        resource_type=resource_type or '',
        resource_id=str(resource_id) if resource_id is not None else '',
        user=user,
        tenant=tenant,
        ip_address=ip,
        user_agent=user_agent,
        metadata=metadata or {},
    )


def _client_ip(request) -> str | None:
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')
