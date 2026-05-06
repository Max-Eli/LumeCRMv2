"""Waitlist API serializers — public submit + internal CRUD."""

from __future__ import annotations

from rest_framework import serializers

from .models import WaitlistEntry


class PublicWaitlistJoinSerializer(serializers.Serializer):
    """Body validation for `POST /api/booking/<slug>/waitlist/`.

    Cross-field validation (service belongs to tenant, provider
    eligible at location) lives in the view, where the URL slug
    resolves the tenant. Same posture as `SubmitBookingInputSerializer`
    in apps.booking — keep the serializer side-effect-free.

    `provider_id` is optional: null/missing means "anyone available."
    """

    service_id = serializers.IntegerField()
    location_id = serializers.IntegerField()
    provider_id = serializers.IntegerField(required=False, allow_null=True)
    preferred_date = serializers.DateField()

    customer_first_name = serializers.CharField(max_length=100)
    customer_last_name = serializers.CharField(max_length=100)
    customer_email = serializers.EmailField(max_length=254)
    customer_phone = serializers.CharField(max_length=20)

    notes = serializers.CharField(
        required=False, allow_blank=True, max_length=500,
        help_text='Optional message to the spa (e.g. "mornings preferred").',
    )


class PublicWaitlistConfirmationSerializer(serializers.ModelSerializer):
    """Response to a successful public submit. Minimum-necessary —
    we don't echo back tenant or staff details, just enough to
    reassure the customer ("you're on the list for X on Y")."""

    service_name = serializers.CharField(source='service.name', read_only=True)
    location_name = serializers.CharField(source='location.name', read_only=True)

    class Meta:
        model = WaitlistEntry
        fields = [
            'id',
            'service_name',
            'location_name',
            'preferred_date',
            'status',
            'created_at',
        ]


class WaitlistEntryCreateSerializer(serializers.Serializer):
    """Body validation for `POST /api/waitlist/` — staff-side add.

    Two customer paths:

      - **Existing customer**: pass `customer_id`. Operator picked
        them from the customer search dropdown. Most common path
        (returning client calling in).
      - **New customer**: pass `customer_first_name`, `customer_last_name`,
        `customer_email`, `customer_phone`. The view runs the same
        `find_or_create_customer` the public booking flow uses, so a
        returning client whose email or phone is on file gets
        re-attached to their existing record without the operator
        having to search.

    Exactly one path; if `customer_id` is present we ignore the new-
    customer fields entirely. If `customer_id` is absent, all four
    new-customer fields are required.
    """

    customer_id = serializers.IntegerField(required=False, allow_null=True)
    customer_first_name = serializers.CharField(
        required=False, allow_blank=True, max_length=100,
    )
    customer_last_name = serializers.CharField(
        required=False, allow_blank=True, max_length=100,
    )
    customer_email = serializers.EmailField(required=False, allow_blank=True, max_length=254)
    customer_phone = serializers.CharField(
        required=False, allow_blank=True, max_length=20,
    )

    service_id = serializers.IntegerField()
    location_id = serializers.IntegerField()
    provider_id = serializers.IntegerField(required=False, allow_null=True)
    preferred_date = serializers.DateField()
    notes = serializers.CharField(
        required=False, allow_blank=True, max_length=500,
    )

    def validate(self, attrs):
        if attrs.get('customer_id'):
            return attrs
        # No customer_id → require the new-customer fields.
        missing = [
            field
            for field in ('customer_first_name', 'customer_last_name',
                          'customer_email', 'customer_phone')
            if not (attrs.get(field) or '').strip()
        ]
        if missing:
            raise serializers.ValidationError({
                f: 'Required when no customer_id is provided.' for f in missing
            })
        return attrs


class WaitlistEntrySerializer(serializers.ModelSerializer):
    """Internal (operator-side) representation of a waitlist entry.

    Includes nested customer + service summaries so the calendar
    panel can render names + contact info without a second query.
    Status is editable (operator transitions); customer/service/
    location/provider/preferred_date/source are read-only — those
    define WHAT the entry is about. Editing them would muddle
    audit (you'd lose track of what the customer actually asked for).
    """

    customer_id = serializers.IntegerField(source='customer.id', read_only=True)
    customer_first_name = serializers.CharField(source='customer.first_name', read_only=True)
    customer_last_name = serializers.CharField(source='customer.last_name', read_only=True)
    customer_phone = serializers.CharField(source='customer.phone', read_only=True)
    customer_email = serializers.EmailField(source='customer.email', read_only=True)

    service_id = serializers.IntegerField(source='service.id', read_only=True)
    service_name = serializers.CharField(source='service.name', read_only=True)
    service_duration_minutes = serializers.IntegerField(
        source='service.duration_minutes', read_only=True,
    )

    location_id = serializers.IntegerField(source='location.id', read_only=True)
    location_name = serializers.CharField(source='location.name', read_only=True)

    provider_id = serializers.IntegerField(source='provider.id', read_only=True, allow_null=True)
    provider_display_name = serializers.SerializerMethodField()

    class Meta:
        model = WaitlistEntry
        fields = [
            'id',
            'customer_id', 'customer_first_name', 'customer_last_name',
            'customer_phone', 'customer_email',
            'service_id', 'service_name', 'service_duration_minutes',
            'location_id', 'location_name',
            'provider_id', 'provider_display_name',
            'preferred_date',
            'notes',
            'status',
            'source',
            'contacted_at', 'declined_at', 'booked_at',
            'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id',
            'customer_id', 'customer_first_name', 'customer_last_name',
            'customer_phone', 'customer_email',
            'service_id', 'service_name', 'service_duration_minutes',
            'location_id', 'location_name',
            'provider_id', 'provider_display_name',
            'preferred_date',
            'source',
            'contacted_at', 'declined_at', 'booked_at',
            'created_at', 'updated_at',
        ]

    def get_provider_display_name(self, entry: WaitlistEntry) -> str:
        if entry.provider_id is None:
            return ''
        user = entry.provider.user
        first = (user.first_name or '').strip() or user.email.split('@')[0]
        last = (user.last_name or '').strip()
        return f'{first} {last[0]}.' if last else first
