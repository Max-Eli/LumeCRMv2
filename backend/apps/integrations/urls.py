"""URL routes for integrations."""

from django.urls import path

from .views import (
    IntegrationConnectBeginView,
    IntegrationDisconnectView,
    IntegrationListView,
)

urlpatterns = [
    path('integrations/', IntegrationListView.as_view(), name='integrations-list'),
    path(
        'integrations/<str:provider>/connect/begin/',
        IntegrationConnectBeginView.as_view(),
        name='integrations-connect-begin',
    ),
    path(
        'integrations/<int:pk>/disconnect/',
        IntegrationDisconnectView.as_view(),
        name='integrations-disconnect',
    ),
]
