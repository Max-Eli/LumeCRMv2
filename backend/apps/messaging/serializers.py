"""Read shapes for the messaging API.

Two operator-facing shapes:

  - `MessageSerializer` — one full row, used in the conversation
    detail view. Includes the body (PHI) + Twilio status fields +
    `sent_by_email` for "who from staff sent this."
  - `ThreadSummarySerializer` — one row per customer who has any
    messages. Used in the inbox left-rail. Carries the LATEST
    message preview + an unread count so the UI can render the
    inbox without N+1.

Inbound input from Twilio uses a dedicated form-data path in the
webhook view, not a DRF serializer (Twilio POSTs application/x-
www-form-urlencoded; we extract `From`, `To`, `Body`, `MessageSid`,
`NumMedia`, `MediaUrl0..N` directly).

Operator-initiated outbound uses `SendMessageInputSerializer` for
payload validation on `POST /conversations/<customer_id>/send/`.
"""

from __future__ import annotations

from rest_framework import serializers

from .models import Message


class SendMessageInputSerializer(serializers.Serializer):
    """Payload for the operator's "send a message" action."""

    body = serializers.CharField(
        max_length=1600,  # ~10 SMS segments — Twilio splits longer; we cap to avoid surprise bills.
        allow_blank=False,
        trim_whitespace=True,
    )


class MessageSerializer(serializers.ModelSerializer):
    """Single-message read shape. Used by the conversation detail
    endpoint + by the send-message response so the caller can
    optimistically render the row it just created."""

    sent_by_email = serializers.CharField(
        source='sent_by.email', read_only=True, allow_null=True,
    )
    sent_by_name = serializers.SerializerMethodField()
    media_urls = serializers.SerializerMethodField()

    class Meta:
        model = Message
        fields = [
            'id',
            'direction',
            'body',
            'status',
            'provider_message_id',
            'from_number', 'to_number',
            'media_urls',
            'sent_by_email', 'sent_by_name',
            'read_at',
            'failure_reason',
            'sent_at', 'delivered_at', 'failed_at',
            'created_at', 'updated_at',
        ]
        read_only_fields = fields

    def get_sent_by_name(self, obj: Message) -> str | None:
        if obj.sent_by_id is None:
            return None
        u = obj.sent_by
        name = f'{u.first_name} {u.last_name}'.strip()
        return name or u.email

    def get_media_urls(self, obj: Message) -> list[str]:
        # Model stores newline-separated; serializer normalises to a
        # JSON list so the frontend can `.map(...)` over it directly.
        raw = (obj.media_urls or '').strip()
        return [line for line in raw.split('\n') if line.strip()]


class ThreadSummarySerializer(serializers.Serializer):
    """One row per customer who has any messages with this tenant.
    Built ad-hoc in the view (not a ModelSerializer) because it
    aggregates across rows — latest message body, unread count,
    customer-name preview etc."""

    customer_id = serializers.IntegerField()
    customer_first_name = serializers.CharField()
    customer_last_name = serializers.CharField()
    customer_phone = serializers.CharField()

    last_message_id = serializers.IntegerField()
    last_message_body = serializers.CharField(allow_blank=True)
    last_message_direction = serializers.CharField()
    last_message_at = serializers.DateTimeField()

    unread_inbound_count = serializers.IntegerField()
