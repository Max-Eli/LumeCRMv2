"""URL routing for the waitlist surface.

Two URL families, mounted under `/api/`:

  - `/api/booking/<slug>/waitlist/` — public submit (no auth).
    Lives under the booking prefix because it's part of the public
    booking flow conceptually, even though the view itself lives in
    `apps.waitlist`.
  - `/api/waitlist/` — operator-side CRUD (auth required).
"""

from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import PublicWaitlistJoinView, WaitlistEntryViewSet

router = DefaultRouter()
router.register(r'waitlist', WaitlistEntryViewSet, basename='waitlist-entry')

urlpatterns = [
    path(
        'booking/<slug:tenant_slug>/waitlist/',
        PublicWaitlistJoinView.as_view(),
        name='public-waitlist-join',
    ),
    *router.urls,
]
