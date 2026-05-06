from django.apps import AppConfig


class AuditConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.audit'
    label = 'audit'

    def ready(self):
        # Wire up auth signal handlers (login/logout/login_failed → AuditLog)
        from . import signals  # noqa: F401
