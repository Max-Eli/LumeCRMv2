"""URL routing for the AI inbox app — mounted at /api/.

Three resource groups:

  - /api/ai-inbox/conversations/<customer_id>/...
        GET                         — current AI status
        POST .../pause/             — operator pause
        POST .../resume/            — operator resume (also clears escalations)
  - /api/ai-inbox/config/
        GET / PATCH                 — tenant AIConfig CRUD
  - /api/ai-inbox/escalations/...
        GET                         — list (default: open only)
        POST .../<id>/acknowledge/
        POST .../<id>/resolve/

The conversation endpoints are routed by customer_id rather than
AIConversation.id so the inbox UI (which natively knows the
customer) doesn't have to round-trip to find the conversation row.
"""

from __future__ import annotations

from django.urls import path

from .views import AIConfigView, AIConversationViewSet, EscalationAlertViewSet

urlpatterns = [
    # Per-conversation status + controls.
    path(
        'ai-inbox/conversations/<int:pk>/',
        AIConversationViewSet.as_view({'get': 'retrieve'}),
        name='ai-inbox-conversation-status',
    ),
    path(
        'ai-inbox/conversations/<int:pk>/pause/',
        AIConversationViewSet.as_view({'post': 'pause'}),
        name='ai-inbox-conversation-pause',
    ),
    path(
        'ai-inbox/conversations/<int:pk>/resume/',
        AIConversationViewSet.as_view({'post': 'resume'}),
        name='ai-inbox-conversation-resume',
    ),
    # Tenant config (singleton; GET creates lazily).
    path(
        'ai-inbox/config/',
        AIConfigView.as_view(),
        name='ai-inbox-config',
    ),
    # Escalation alerts.
    path(
        'ai-inbox/escalations/',
        EscalationAlertViewSet.as_view({'get': 'list'}),
        name='ai-inbox-escalations',
    ),
    path(
        'ai-inbox/escalations/<int:pk>/acknowledge/',
        EscalationAlertViewSet.as_view({'post': 'acknowledge'}),
        name='ai-inbox-escalation-acknowledge',
    ),
    path(
        'ai-inbox/escalations/<int:pk>/resolve/',
        EscalationAlertViewSet.as_view({'post': 'resolve'}),
        name='ai-inbox-escalation-resolve',
    ),
]
