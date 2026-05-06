"""URL routing for the public booking surface.

Mounted under `/api/booking/`. Two URL families:

  - `<tenant_slug>/...` — tenant-scoped endpoints (info, services,
    providers, slots, book). Slug is the tenant identifier; it lives
    in the path so cross-origin marketing pages can build links
    without depending on subdomain resolution.

  - `manage/<token>/...` — token-scoped endpoints. Tenant resolves
    via the token's `Appointment.tenant` FK; no slug in the path
    because the token alone is the security boundary.
"""

from django.urls import path

from .views import (
    BookingManageCancelView,
    BookingManageRescheduleView,
    BookingManageView,
    BookingProviderListView,
    BookingServiceListView,
    BookingSlotListView,
    BookingSubmitView,
    BookingTenantInfoView,
)

urlpatterns = [
    path(
        'booking/<slug:tenant_slug>/info/',
        BookingTenantInfoView.as_view(),
        name='booking-tenant-info',
    ),
    path(
        'booking/<slug:tenant_slug>/services/',
        BookingServiceListView.as_view(),
        name='booking-service-list',
    ),
    path(
        'booking/<slug:tenant_slug>/providers/',
        BookingProviderListView.as_view(),
        name='booking-provider-list',
    ),
    path(
        'booking/<slug:tenant_slug>/slots/',
        BookingSlotListView.as_view(),
        name='booking-slot-list',
    ),
    path(
        'booking/<slug:tenant_slug>/book/',
        BookingSubmitView.as_view(),
        name='booking-submit',
    ),
    path(
        'booking/manage/<str:token>/',
        BookingManageView.as_view(),
        name='booking-manage',
    ),
    path(
        'booking/manage/<str:token>/cancel/',
        BookingManageCancelView.as_view(),
        name='booking-manage-cancel',
    ),
    path(
        'booking/manage/<str:token>/reschedule/',
        BookingManageRescheduleView.as_view(),
        name='booking-manage-reschedule',
    ),
]
