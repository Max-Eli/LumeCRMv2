"""DRF serializers for the commissions API."""

from __future__ import annotations

from django.db import transaction
from rest_framework import serializers

from apps.services.models import ServiceCategory
from apps.tenants.models import TenantMembership

from .models import CommissionEntry, CommissionRule, CommissionRuleOverride


# ── CommissionRule ──────────────────────────────────────────────────


class CommissionOverrideOutputSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(
        source='category.name', read_only=True,
    )
    category_color = serializers.CharField(
        source='category.color', read_only=True,
    )

    class Meta:
        model = CommissionRuleOverride
        fields = [
            'id', 'category', 'category_name', 'category_color',
            'rate_percent',
        ]
        read_only_fields = ['id', 'category_name', 'category_color']


class CommissionOverrideInputSerializer(serializers.Serializer):
    """One override row in the rule's nested `overrides_input` list."""

    category_id = serializers.IntegerField()
    rate_percent = serializers.DecimalField(max_digits=5, decimal_places=2)


class CommissionRuleSerializer(serializers.ModelSerializer):
    """Rule with nested overrides. PATCHes that include `overrides_input`
    replace the override list wholesale (atomic), matching the
    package-form pattern used elsewhere."""

    membership_user_email = serializers.EmailField(
        source='membership.user.email', read_only=True,
    )
    membership_user_first_name = serializers.CharField(
        source='membership.user.first_name', read_only=True,
    )
    membership_user_last_name = serializers.CharField(
        source='membership.user.last_name', read_only=True,
    )
    membership_role = serializers.CharField(
        source='membership.role', read_only=True,
    )
    overrides = CommissionOverrideOutputSerializer(many=True, read_only=True)
    overrides_input = CommissionOverrideInputSerializer(
        many=True, write_only=True, required=False,
    )

    class Meta:
        model = CommissionRule
        fields = [
            'id',
            'membership',
            'membership_user_email',
            'membership_user_first_name',
            'membership_user_last_name',
            'membership_role',
            'base_rate_percent',
            'is_active',
            'notes',
            'overrides',
            'overrides_input',
            'created_at',
            'updated_at',
        ]
        read_only_fields = [
            'id',
            'membership_user_email',
            'membership_user_first_name',
            'membership_user_last_name',
            'membership_role',
            'overrides',
            'created_at',
            'updated_at',
        ]

    def validate_membership(self, value: TenantMembership) -> TenantMembership:
        from apps.tenants.context import get_current_tenant
        tenant = get_current_tenant()
        if tenant is None:
            return value
        if value.tenant_id != tenant.pk:
            raise serializers.ValidationError(
                'Staff member is not in this tenant.'
            )
        return value

    def validate_base_rate_percent(self, value):
        if value < 0 or value > 100:
            raise serializers.ValidationError('Must be 0-100.')
        return value

    def validate(self, attrs):
        overrides_input = attrs.get('overrides_input')
        if overrides_input is None:
            return attrs
        from apps.tenants.context import get_current_tenant
        tenant = get_current_tenant()
        if tenant is None:
            return attrs

        category_ids = [row['category_id'] for row in overrides_input]
        if len(set(category_ids)) != len(category_ids):
            raise serializers.ValidationError(
                {'overrides_input': 'Each category can only appear once.'},
            )
        valid = set(
            ServiceCategory.objects
            .filter(tenant=tenant, pk__in=category_ids)
            .values_list('pk', flat=True)
        )
        invalid = [c for c in category_ids if c not in valid]
        if invalid:
            raise serializers.ValidationError(
                {'overrides_input': f'Unknown category id(s): {invalid}.'},
            )
        for row in overrides_input:
            if row['rate_percent'] < 0 or row['rate_percent'] > 100:
                raise serializers.ValidationError(
                    {'overrides_input': 'Each override rate must be 0-100.'},
                )
        return attrs

    def _save_overrides(
        self, rule: CommissionRule, overrides_input: list[dict],
    ) -> None:
        rule.overrides.all().delete()
        rows = [
            CommissionRuleOverride(
                rule=rule,
                category_id=row['category_id'],
                rate_percent=row['rate_percent'],
            )
            for row in overrides_input
        ]
        CommissionRuleOverride.objects.bulk_create(rows)

    def create(self, validated_data: dict) -> CommissionRule:
        overrides_input = validated_data.pop('overrides_input', None) or []
        with transaction.atomic():
            rule = CommissionRule.objects.create(**validated_data)
            if overrides_input:
                self._save_overrides(rule, overrides_input)
        return rule

    def update(
        self, instance: CommissionRule, validated_data: dict,
    ) -> CommissionRule:
        overrides_input = validated_data.pop('overrides_input', None)
        with transaction.atomic():
            for attr, val in validated_data.items():
                setattr(instance, attr, val)
            instance.save()
            if overrides_input is not None:
                self._save_overrides(instance, overrides_input)
        return instance


# ── CommissionEntry (read-only) ─────────────────────────────────────


class CommissionEntrySerializer(serializers.ModelSerializer):
    """Append-only ledger row. Mutations happen via service layer
    triggered by invoice transitions, never via this endpoint."""

    membership_user_email = serializers.EmailField(
        source='membership.user.email', read_only=True,
    )
    membership_user_first_name = serializers.CharField(
        source='membership.user.first_name', read_only=True,
    )
    membership_user_last_name = serializers.CharField(
        source='membership.user.last_name', read_only=True,
    )
    invoice_number = serializers.CharField(
        source='invoice.invoice_number', read_only=True,
    )
    line_description = serializers.CharField(
        source='invoice_line.description', read_only=True,
    )
    by_user_email = serializers.EmailField(
        source='by_user.email', read_only=True, allow_null=True,
    )

    class Meta:
        model = CommissionEntry
        fields = [
            'id',
            'membership',
            'membership_user_email',
            'membership_user_first_name',
            'membership_user_last_name',
            'invoice',
            'invoice_number',
            'invoice_line',
            'line_description',
            'kind',
            'rate_percent',
            'line_subtotal_cents',
            'amount_cents',
            'reverses',
            'note',
            'by_user_email',
            'accrued_at',
        ]
        read_only_fields = fields
