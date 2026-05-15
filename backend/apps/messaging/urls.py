"""URL routing for the customer messaging surface.

Mounted at `/api/`. Routes use distinct prefixes for the inbox-list
view (`/threads/`) vs the per-customer thread view
(`/conversations/<customer_id>/`) because they're semantically
different shapes — DRF's `DefaultRouter` assumes `list` and
`retrieve` share a single resource URL, which isn't the case here.

See [ADR 0022 — Customer messaging inbox].
"""

from __future__ import annotations

from django.urls import path

from .views import MessagingViewSet, TwilioInboundView

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
]
