"""Django auth signal handlers → AuditLog.

Wires `user_logged_in`, `user_logged_out`, and `user_login_failed` signals to
audit log entries. Hooked up in `AuditConfig.ready()`.
"""

from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.dispatch import receiver

from .models import AuditLog
from .services import record


@receiver(user_logged_in)
def on_user_logged_in(sender, request, user, **kwargs):
    record(action=AuditLog.Action.LOGIN, user=user, request=request)


@receiver(user_logged_out)
def on_user_logged_out(sender, request, user, **kwargs):
    record(action=AuditLog.Action.LOGOUT, user=user, request=request)


@receiver(user_login_failed)
def on_user_login_failed(sender, credentials, request=None, **kwargs):
    email = (credentials or {}).get('username') or (credentials or {}).get('email') or ''
    record(
        action=AuditLog.Action.LOGIN_FAILED,
        request=request,
        metadata={'attempted_email': email[:254]},
    )
