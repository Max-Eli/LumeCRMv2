from django.apps import AppConfig


class PlatformConfig(AppConfig):
    """Platform admin — Lumè-the-company managing its customer tenants.

    Distinct from the tenant-scoped CRM that runs at every customer's
    subdomain. Endpoints under `/api/platform/` are gated to
    `is_superuser=True` and operate cross-tenant. Every action writes
    an audit log entry with `resource_type='platform_tenant'` so the
    platform-side audit trail can be filtered apart from per-tenant
    activity.

    No models of its own — operates against `apps.tenants.Tenant`
    and friends.
    """

    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.platform'
    label = 'platform'
