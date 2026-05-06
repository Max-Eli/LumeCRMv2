"""DRF serializers for the customers API.

Two serializers:

  - `CustomerListSerializer` — minimal record for the list view (id, name,
    contact, status, tags). Excludes medical PHI to keep list payloads small
    and to align with HIPAA "minimum necessary" for routine browsing.
  - `CustomerDetailSerializer` — full record including PHI. Used for the
    create/retrieve/update/delete actions where the user has been gated
    through `CustomerPermission`.

Tag association uses `tag_ids` (write-only) for input and `tags` (nested
read-only) for output, so consumers only have to send a list of integers.
"""

from django.utils import timezone as djtz
from rest_framework import serializers

from .models import Customer, CustomerTag


class CustomerTagSerializer(serializers.ModelSerializer):
    """Read/write serializer for `CustomerTag`."""

    class Meta:
        model = CustomerTag
        fields = ['id', 'name', 'color', 'sort_order']


class CustomerListSerializer(serializers.ModelSerializer):
    """Minimal customer record for the list endpoint — no medical PHI."""

    full_name = serializers.CharField(read_only=True)
    tags = CustomerTagSerializer(many=True, read_only=True)

    class Meta:
        model = Customer
        fields = [
            'id',
            'first_name',
            'last_name',
            'preferred_name',
            'full_name',
            'email',
            'phone',
            'status',
            'tags',
            'created_at',
        ]
        read_only_fields = fields


class CustomerDetailSerializer(serializers.ModelSerializer):
    """Full customer record for create / retrieve / update."""

    full_name = serializers.CharField(read_only=True)
    tags = CustomerTagSerializer(many=True, read_only=True)
    tag_ids = serializers.PrimaryKeyRelatedField(
        queryset=CustomerTag.objects.all(),
        many=True,
        write_only=True,
        required=False,
        source='tags',
    )

    class Meta:
        model = Customer
        fields = [
            'id',
            # Identity
            'first_name', 'last_name', 'preferred_name', 'full_name',
            'email', 'phone',
            # Demographics
            'date_of_birth', 'sex',
            # Address
            'address_line1', 'address_line2', 'city', 'state', 'zip_code',
            # Emergency contact
            'emergency_name', 'emergency_phone', 'emergency_relationship',
            # Medical
            'medical_history', 'allergies', 'medications', 'skin_type_fitzpatrick',
            # CRM
            'notes', 'referral_source',
            # Marketing — transactional (booking confirmations, reminders)
            'email_opt_in', 'sms_opt_in',
            # Marketing — promotional (campaigns + automations).
            # Per-channel consent + suppression w/ source + timestamp.
            # Suppression always wins over opt-in (ADR 0016).
            'email_marketing_opt_in', 'sms_marketing_opt_in',
            'email_marketing_consent_at', 'sms_marketing_consent_at',
            'email_marketing_consent_source', 'sms_marketing_consent_source',
            'email_marketing_suppressed_at', 'sms_marketing_suppressed_at',
            'email_marketing_suppression_source', 'sms_marketing_suppression_source',
            # Status + tags
            'status', 'tags', 'tag_ids',
            # Referral (read-only)
            'referral_code',
            # Provenance (read-only)
            'external_id', 'external_source', 'imported_at',
            # Timestamps
            'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'full_name',
            'referral_code',
            'external_id', 'external_source', 'imported_at',
            'created_at', 'updated_at',
            # Consent + suppression metadata: only set by the backend
            # (booking_form, unsubscribe_link, manual ops). The opt-in
            # booleans themselves are writable so an operator can flip
            # them in-app, but the source/timestamp companion fields
            # are stamped by the same code path that flips the boolean.
            'email_marketing_consent_at', 'sms_marketing_consent_at',
            'email_marketing_consent_source', 'sms_marketing_consent_source',
            'email_marketing_suppressed_at', 'sms_marketing_suppressed_at',
            'email_marketing_suppression_source', 'sms_marketing_suppression_source',
        ]

    def update(self, instance: Customer, validated_data: dict) -> Customer:
        """Stamp consent metadata when an operator flips a marketing
        opt-in. Suppression is left untouched here — the customer
        unsubscribe link and explicit ops actions are the only paths
        that flip suppression. ADR 0016."""
        now = djtz.now()
        if (
            validated_data.get('email_marketing_opt_in') is True
            and not instance.email_marketing_opt_in
        ):
            instance.email_marketing_consent_at = now
            instance.email_marketing_consent_source = 'manual'
        if (
            validated_data.get('sms_marketing_opt_in') is True
            and not instance.sms_marketing_opt_in
        ):
            instance.sms_marketing_consent_at = now
            instance.sms_marketing_consent_source = 'manual'
        return super().update(instance, validated_data)
