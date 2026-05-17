"""URL routes for integrations.

The webhook, OAuth callback, and data-deletion endpoints sit
alongside the regular list/connect/disconnect routes. They're
CSRF-exempt and AllowAny because Meta is the caller (signature +
state token are the security boundaries — ADR 0027).

Social inbox routes (under `/api/social/`) are tenant-scoped
authenticated endpoints serving the `/social` UI.
"""

from django.urls import path

from .views import (
    DataDeletionStatusView,
    IntegrationConnectBeginView,
    IntegrationDiagnosticsView,
    IntegrationDisconnectView,
    IntegrationListView,
    MetaDataDeletionView,
    MetaOAuthCallbackView,
    MetaWebhookView,
    SocialThreadDetailView,
    SocialThreadListView,
    SocialThreadMarkReadView,
    SocialThreadReplyView,
)

urlpatterns = [
    path('integrations/', IntegrationListView.as_view(), name='integrations-list'),
    path(
        'integrations/diagnostics/',
        IntegrationDiagnosticsView.as_view(),
        name='integrations-diagnostics',
    ),
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

    # Meta OAuth callback — browser redirect target after consent
    path(
        'integrations/meta/oauth/callback/',
        MetaOAuthCallbackView.as_view(),
        name='integrations-meta-oauth-callback',
    ),

    # Meta webhook receiver — GET subscription handshake + POST events
    path(
        'integrations/webhooks/meta/',
        MetaWebhookView.as_view(),
        name='integrations-webhook-meta',
    ),

    # Meta data-deletion callback — POST signed_request when a user
    # removes the app from their Facebook settings (ADR 0027 §9)
    path(
        'integrations/meta/data-deletion/',
        MetaDataDeletionView.as_view(),
        name='integrations-meta-data-deletion',
    ),
    # Public confirmation lookup so the user can verify their
    # deletion request was processed
    path(
        'integrations/meta/data-deletion-status/<str:code>/',
        DataDeletionStatusView.as_view(),
        name='integrations-meta-data-deletion-status',
    ),

    # Social inbox API — backs the /social frontend page
    path(
        'social/threads/',
        SocialThreadListView.as_view(),
        name='social-thread-list',
    ),
    path(
        'social/threads/<int:pk>/',
        SocialThreadDetailView.as_view(),
        name='social-thread-detail',
    ),
    path(
        'social/threads/<int:pk>/mark-read/',
        SocialThreadMarkReadView.as_view(),
        name='social-thread-mark-read',
    ),
    path(
        'social/threads/<int:pk>/reply/',
        SocialThreadReplyView.as_view(),
        name='social-thread-reply',
    ),
]
