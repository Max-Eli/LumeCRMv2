from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    JobTitleViewSet,
    LocationViewSet,
    MembershipViewSet,
    ScheduleView,
    TenantSettingsView,
)

router = DefaultRouter()
router.register('job-titles', JobTitleViewSet, basename='job-title')
router.register('locations', LocationViewSet, basename='location')
router.register('memberships', MembershipViewSet, basename='membership')

urlpatterns = [
    # Singleton — current tenant settings (resolved by subdomain).
    # Belongs outside the router because there's no list/detail-by-pk
    # surface; the caller is always operating on "their" tenant.
    path('tenant/', TenantSettingsView.as_view(), name='tenant-settings'),
    # Provider schedule per MembershipLocation. Surface is GET / PUT
    # against the membership-location id, with a canonical empty shape
    # returned when no schedule row exists yet.
    path(
        'schedules/<int:pk>/',
        ScheduleView.as_view(),
        name='provider-schedule',
    ),
    *router.urls,
]
