"""URL routing for the customer messaging surface.

Mounted at `/api/`. Routes use distinct prefixes for the inbox-list
view (`/threads/`) vs the per-customer thread view
(`/conversations/<customer_id>/`) because they're semantically
different shapes — DRF's `DefaultRouter` assumes `list` and
`retrieve` share a single resource URL, which isn't the case here.

See [ADR 0022 — Customer messaging inbox].
"""

from __future__ import annotations

from rest_framework.routers import DefaultRouter

from django.urls import path

from .views import (
    AutomatedTemplatesView,
    MessagingViewSet,
    SavedReplyViewSet,
    TwilioInboundView,
)

# Saved replies use the standard CRUD verb mapping, so DRF's
# DefaultRouter is the right fit — keeps the URL surface in sync with
# the serializer's read-only fields automatically.
_router = DefaultRouter()
_router.register(
    r'messaging/saved-replies', SavedReplyViewSet, basename='messaging-saved-reply',
)

urlpatterns = [
    # Inbox — one row per customer with whom we've messaged.
    path(
        'messaging/threads/',
        MessagingViewSet.as_view({'get': 'list'}),
        name='messaging-threads',
    ),
    # Full conversation history for one customer.
    path(
        'messaging/conversations/<int:pk>/',
        MessagingViewSet.as_view({'get': 'retrieve'}),
        name='messaging-conversation-detail',
    ),
    # Operator-initiated send.
    path(
        'messaging/conversations/<int:pk>/send/',
        MessagingViewSet.as_view({'post': 'send'}),
        name='messaging-conversation-send',
    ),
    # Clear unread state on a thread.
    path(
        'messaging/conversations/<int:pk>/mark-read/',
        MessagingViewSet.as_view({'post': 'mark_read'}),
        name='messaging-conversation-mark-read',
    ),
    # Twilio inbound webhook — X-Twilio-Signature verified.
    path(
        'messaging/twilio/incoming/',
        TwilioInboundView.as_view(),
        name='messaging-twilio-incoming',
    ),
    # Tenant-singleton automated-SMS templates (confirmation + 24h
    # reminder + review-request) — GET + PATCH only.
    path(
        'messaging/automated-templates/',
        AutomatedTemplatesView.as_view(),
        name='messaging-automated-templates',
    ),
    *_router.urls,
]
