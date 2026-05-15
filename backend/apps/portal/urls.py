"""Customer-portal URL routes. Mounted at `/api/portal/`.

Public auth (no session required):
    POST /api/portal/auth/request-magic-link/
    POST /api/portal/auth/consume/
    POST /api/portal/auth/logout/

Authenticated portal data:
    GET    /api/portal/me/
    PATCH  /api/portal/me/
    GET    /api/portal/appointments/
    POST   /api/portal/appointments/<id>/cancel/

See [ADR 0024 — Customer portal].
"""

from __future__ import annotations

from django.urls import path

from .views import (
    AppointmentsView,
    CancelAppointmentView,
    ConsumeMagicLinkView,
    LogoutView,
    MeView,
    RequestMagicLinkView,
)

urlpatterns = [
    path('portal/auth/request-magic-link/', RequestMagicLinkView.as_view(), name='portal-auth-request-magic-link'),
    path('portal/auth/consume/', ConsumeMagicLinkView.as_view(), name='portal-auth-consume'),
    path('portal/auth/logout/', LogoutView.as_view(), name='portal-auth-logout'),
    path('portal/me/', MeView.as_view(), name='portal-me'),
    path('portal/appointments/', AppointmentsView.as_view(), name='portal-appointments'),
    path('portal/appointments/<int:pk>/cancel/', CancelAppointmentView.as_view(), name='portal-appointment-cancel'),
]
