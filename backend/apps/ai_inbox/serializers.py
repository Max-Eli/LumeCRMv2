"""Serializers for the AI inbox HTTP surface.

Three shapes:

  - ``AIConversationStatusSerializer`` — read-only view of one
    AIConversation's lifecycle state. Driven by the inbox UI banner.
  - ``AIConfigSerializer`` — full read + partial-update CRUD for the
    Settings page. Enforces the "can't enable without a TFN" gate at
    validation time.
  - ``EscalationAlertSerializer`` — list shape for the dashboard
    widget, embeds customer summary.

The PHI rule (ADR 0032) applies here too — no chart notes, no
medical history. Everything serialized below is administrative
metadata (status enums, timestamps, customer first/last name +
phone) which is normal CRM access scope, NOT PHI gated to the
AI tool layer.
"""

from __future__ import annotations

from rest_framework import serializers

from .models import AIConfig, AIConversation, EscalationAlert


class AIConversationStatusSerializer(serializers.ModelSerializer):
    paused_by_email = serializers.CharField(
        source='paused_by.email', read_only=True, default=None,
    )

    class Meta:
        model = AIConversation
        fields = [
            'id',
            'customer_id',
            'status',
            'paused_at',
            'paused_by_email',
            'escalated_at',
            'escalation_reason',
            'last_ai_at',
            'last_inbound_at',
            'message_count',
            'exchange_count',
            'pending_proposal_expires_at',
            'updated_at',
        ]
        read_only_fields = fields


class AIConfigSerializer(serializers.ModelSerializer):
    """Read + partial update for the per-tenant AIConfig.

    Validation rules (enforced here, not at the model layer, because
    they're operator-policy not data-integrity):

      - enabled=True requires tenant.twilio_from_number to be non-empty
      - enabled=True with test_mode=True requires test_mode_number
      - propose_slot_count clamped to 1..9 (matches the SMS reply
        digit pattern)
      - daily_send_cap clamped to a sane range (>=1)
    """

    class Meta:
        model = AIConfig
        fields = [
            'enabled',
            'test_mode',
            'test_mode_number',
            'persona',
            'business_hours_json',
            'booking_lead_minutes',
            'propose_slot_count',
            'daily_send_cap',
            'monthly_exchange_cap',
            'escalation_keywords',
            'platform_disabled_at',
            'platform_disabled_reason',
            'created_at',
            'updated_at',
        ]
        read_only_fields = [
            'platform_disabled_at',
            'platform_disabled_reason',
            'created_at',
            'updated_at',
        ]

    def validate(self, attrs):
        tenant = self.context.get('tenant') or (
            self.instance.tenant if self.instance else None
        )
        # Merge proposed values with current instance state so partial
        # updates can reference any field.
        merged = {**(self._instance_dict() or {}), **attrs}

        if merged.get('enabled'):
            tfn = (getattr(tenant, 'twilio_from_number', '') or '').strip()
            if not tfn:
                raise serializers.ValidationError({
                    'enabled': (
                        'Cannot enable AI without a Twilio toll-free number '
                        'on the tenant. Provision a TFN first.'
                    ),
                })
            if merged.get('test_mode'):
                test_num = (merged.get('test_mode_number') or '').strip()
                if not test_num:
                    raise serializers.ValidationError({
                        'test_mode_number': (
                            'Required when enabling AI in test mode — only '
                            'this number will be answered.'
                        ),
                    })

        if 'propose_slot_count' in attrs:
            n = attrs['propose_slot_count']
            if n < 1 or n > 9:
                raise serializers.ValidationError({
                    'propose_slot_count': 'Must be between 1 and 9.',
                })

        if 'daily_send_cap' in attrs and attrs['daily_send_cap'] < 1:
            raise serializers.ValidationError({
                'daily_send_cap': 'Must be at least 1.',
            })

        return attrs

    def _instance_dict(self) -> dict:
        if self.instance is None:
            return {}
        return {
            field: getattr(self.instance, field, None)
            for field in self.Meta.fields
        }


class EscalationAlertSerializer(serializers.ModelSerializer):
    customer_first_name = serializers.CharField(
        source='customer.first_name', read_only=True,
    )
    customer_last_name = serializers.CharField(
        source='customer.last_name', read_only=True,
    )
    customer_phone = serializers.CharField(
        source='customer.phone', read_only=True,
    )
    customer_id = serializers.IntegerField(source='customer.id', read_only=True)
    acknowledged_by_email = serializers.CharField(
        source='acknowledged_by.email', read_only=True, default=None,
    )

    class Meta:
        model = EscalationAlert
        fields = [
            'id',
            'customer_id',
            'customer_first_name',
            'customer_last_name',
            'customer_phone',
            'reason',
            'reason_detail',
            'acknowledged_at',
            'acknowledged_by_email',
            'resolved_at',
            'created_at',
        ]
        read_only_fields = fields
