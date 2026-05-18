"""URL routes for platform admin endpoints.

Mounted under `/api/platform/`. All endpoints gated to
`is_superuser=True` via `PlatformPermission`.
"""

from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    PlatformAuditLogView,
    PlatformSummaryView,
    PlatformTenantViewSet,
)

router = DefaultRouter()
router.register(
    'platform/tenants',
    PlatformTenantViewSet,
    basename='platform-tenant',
)

urlpatterns = [
    path('platform/summary/', PlatformSummaryView.as_view(), name='platform-summary'),
    path('platform/audit-log/', PlatformAuditLogView.as_view(), name='platform-audit-log'),
] + router.urls
