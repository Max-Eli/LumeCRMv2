"""Abstract model + manager for tenant-scoped tables.

Every PHI table (customers, appointments, invoices, forms, charts, etc.) should
inherit from `TenantedModel`. This:
  - forces a `tenant` foreign key on every row
  - exposes `Model.objects.for_current_tenant()` which auto-filters by the
    request-scoped current tenant
  - makes cross-tenant data leaks an explicit code smell (you'd have to bypass
    the helper) rather than something that happens by forgetting a `.filter()` call

Production deployment will additionally apply Postgres Row-Level Security policies
to these tables for defense-in-depth (set up in Phase 0c when the lume_app /
lume_admin role split lands).
"""

from django.db import models

from .context import get_current_tenant


class TenantedQuerySet(models.QuerySet):
    def for_current_tenant(self):
        """Filter to rows belonging to the current request-scoped tenant.

        Returns an empty queryset if no tenant is set (rather than raising) so
        callers in unscoped contexts (admin, shell, system jobs) get safe defaults
        and bugs surface as "no data" rather than "all tenants' data".
        """
        tenant = get_current_tenant()
        if tenant is None:
            return self.none()
        return self.filter(tenant=tenant)

    def for_tenant(self, tenant):
        """Filter to rows belonging to the given tenant. Use when not in a request context."""
        if tenant is None:
            return self.none()
        return self.filter(tenant=tenant)


class TenantedManager(models.Manager.from_queryset(TenantedQuerySet)):
    pass


class TenantedModel(models.Model):
    """Abstract base for any model that holds tenant-scoped data."""

    tenant = models.ForeignKey(
        'tenants.Tenant',
        on_delete=models.CASCADE,
        related_name='+',
    )

    objects = TenantedManager()

    class Meta:
        abstract = True
