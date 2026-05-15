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

from .models import Message, SavedReply


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
            'kind',
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


class SavedReplySerializer(serializers.ModelSerializer):
    """Read/write shape for canned inbox replies.

    `tenant` is set by the view from request context; `created_by` is
    set to `request.user` on create. Neither is writable from the
    client — both would let a caller forge cross-tenant or
    cross-user rows.
    """

    created_by_email = serializers.CharField(
        source='created_by.email', read_only=True, allow_null=True,
    )

    class Meta:
        model = SavedReply
        fields = [
            'id', 'name', 'body',
            'created_by_email',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_by_email', 'created_at', 'updated_at']

    def validate_name(self, value: str) -> str:
        v = (value or '').strip()
        if not v:
            raise serializers.ValidationError('Name is required.')
        return v

    def validate_body(self, value: str) -> str:
        v = (value or '').strip()
        if not v:
            raise serializers.ValidationError('Body is required.')
        return v

    def validate(self, attrs):
        # Surface tenant-scoped name uniqueness as a 400 with a clean
        # error rather than letting the DB unique constraint raise an
        # IntegrityError (which DRF turns into a 500). We can't use
        # `UniqueTogetherValidator` here because `tenant` is set by the
        # view, not the serializer, so DRF doesn't see it.
        from apps.tenants.context import get_current_tenant

        tenant = get_current_tenant()
        name = attrs.get('name')
        if tenant is not None and name is not None:
            qs = SavedReply.objects.filter(tenant=tenant, name=name)
            if self.instance is not None:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError({
                    'name': f'A saved reply named "{name}" already exists.',
                })
        return attrs


class AutomatedTemplatesSerializer(serializers.Serializer):
    """Read/write shape for the tenant's three automated SMS templates
    + the review-request automation settings.

    Reads + writes the live `Tenant` row directly — there's no
    intermediate model because these are tenant-singleton settings
    (one of each per tenant). The view loads/saves the Tenant.

    Default bodies are surfaced read-only on GET so the operator can
    see what the platform would send if they leave the template
    blank, and copy-paste-edit if they want to customise.
    """

    confirmation_sms_template = serializers.CharField(
        max_length=1600, allow_blank=True, required=False,
        help_text='Custom confirmation SMS body. Blank = use default.',
    )
    reminder_sms_template = serializers.CharField(
        max_length=1600, allow_blank=True, required=False,
    )
    review_request_sms_template = serializers.CharField(
        max_length=1600, allow_blank=True, required=False,
    )
    review_request_enabled = serializers.BooleanField(required=False)
    review_request_hours_after = serializers.IntegerField(
        min_value=1, max_value=168, required=False,  # cap at one week
    )
    google_review_url = serializers.URLField(
        max_length=500, allow_blank=True, required=False,
    )

    # Read-only mirrors of the platform defaults so the UI can show
    # "what will be sent if I leave this blank" + provide a "reset to
    # default" affordance.
    default_confirmation_body = serializers.SerializerMethodField()
    default_reminder_body = serializers.SerializerMethodField()
    default_review_request_body = serializers.SerializerMethodField()

    def get_default_confirmation_body(self, _obj) -> str:
        from apps.appointments.sms import DEFAULT_CONFIRMATION_BODY
        return DEFAULT_CONFIRMATION_BODY

    def get_default_reminder_body(self, _obj) -> str:
        from apps.appointments.sms import DEFAULT_REMINDER_BODY
        return DEFAULT_REMINDER_BODY

    def get_default_review_request_body(self, _obj) -> str:
        from apps.appointments.sms import DEFAULT_REVIEW_REQUEST_BODY
        return DEFAULT_REVIEW_REQUEST_BODY

    def validate(self, attrs):
        # If the review request is enabled, require a Google review URL.
        # We check both the incoming attrs and the instance to handle
        # PATCH semantics (you can enable it in a separate request from
        # setting the URL).
        enabled = attrs.get('review_request_enabled')
        if enabled is None and self.instance is not None:
            enabled = getattr(self.instance, 'review_request_enabled', False)

        url = attrs.get('google_review_url')
        if url is None and self.instance is not None:
            url = getattr(self.instance, 'google_review_url', '')

        if enabled and not (url or '').strip():
            raise serializers.ValidationError({
                'google_review_url': (
                    'A Google Review URL is required when review-request '
                    'SMS is enabled.'
                ),
            })
        return attrs
