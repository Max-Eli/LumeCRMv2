"""DRF serializers for the memberships API.

`MembershipPlanSerializer` writes nested `items` in one round-trip
with a wholesale-replace semantic on update — same shape as
`PackageSerializer`. `SubscriptionSerializer` is read-only;
mutations go through invoice action endpoints (sale + redemption)
or the cancel action.
"""

from __future__ import annotations

from django.db import transaction
from rest_framework import serializers

from apps.services.models import Service

from .models import (
    MembershipPlan,
    MembershipPlanItem,
    Subscription,
    SubscriptionItem,
    SubscriptionRedemption,
)


# ── Catalog ─────────────────────────────────────────────────────────


class MembershipPlanItemInputSerializer(serializers.Serializer):
    """One inclusion line on the plan: service + per-cycle quantity."""

    service_id = serializers.IntegerField()
    quantity_per_cycle = serializers.IntegerField(min_value=1)
    sort_order = serializers.IntegerField(default=0, required=False)


class MembershipPlanItemOutputSerializer(serializers.ModelSerializer):
    """Read shape — denormalizes service name + a-la-carte price."""

    service_id = serializers.IntegerField(source='service.id', read_only=True)
    service_name = serializers.CharField(source='service.name', read_only=True)
    service_price_cents = serializers.IntegerField(
        source='service.price_cents', read_only=True,
    )

    class Meta:
        model = MembershipPlanItem
        fields = [
            'id',
            'service_id',
            'service_name',
            'service_price_cents',
            'quantity_per_cycle',
            'sort_order',
        ]


class MembershipPlanSerializer(serializers.ModelSerializer):
    """Plan read + write with nested items."""

    items = MembershipPlanItemOutputSerializer(many=True, read_only=True)
    items_input = MembershipPlanItemInputSerializer(
        many=True, write_only=True, required=False,
    )
    price_dollars = serializers.CharField(read_only=True)
    a_la_carte_total_cents = serializers.SerializerMethodField()
    implicit_discount_cents = serializers.SerializerMethodField()

    class Meta:
        model = MembershipPlan
        fields = [
            'id',
            'name',
            'sku',
            'description',
            'price_cents',
            'price_dollars',
            'tax_rate_percent',
            'billing_interval',
            'member_discount_percent',
            'is_active',
            'sort_order',
            'items',
            'items_input',
            'a_la_carte_total_cents',
            'implicit_discount_cents',
            'created_at',
            'updated_at',
        ]
        read_only_fields = [
            'id', 'price_dollars', 'items',
            'a_la_carte_total_cents', 'implicit_discount_cents',
            'created_at', 'updated_at',
        ]

    def get_a_la_carte_total_cents(self, obj: MembershipPlan) -> int:
        """Per-cycle a-la-carte value of the included credits — used
        to surface "$X value for $Y/mo" copy in the catalog UI."""
        total = 0
        for it in obj.items.all():
            total += it.service.price_cents * it.quantity_per_cycle
        return total

    def get_implicit_discount_cents(self, obj: MembershipPlan) -> int:
        return self.get_a_la_carte_total_cents(obj) - obj.price_cents

    def validate(self, attrs: dict) -> dict:
        items_input = attrs.get('items_input')
        if items_input is None:
            return attrs

        from apps.tenants.context import get_current_tenant
        tenant = get_current_tenant()

        if not items_input:
            raise serializers.ValidationError(
                {'items_input': 'A plan needs at least one service item.'},
            )

        service_ids = [row['service_id'] for row in items_input]
        if len(set(service_ids)) != len(service_ids):
            raise serializers.ValidationError(
                {'items_input': 'Each service may only appear once per plan.'},
            )

        valid_services = set(
            Service.objects
            .filter(tenant=tenant, pk__in=service_ids)
            .values_list('pk', flat=True)
        )
        invalid = [sid for sid in service_ids if sid not in valid_services]
        if invalid:
            raise serializers.ValidationError(
                {'items_input': f'Unknown service id(s): {invalid}.'},
            )

        return attrs

    def _save_items(
        self, plan: MembershipPlan, items_input: list[dict],
    ) -> None:
        plan.items.all().delete()
        rows = [
            MembershipPlanItem(
                plan=plan,
                service_id=row['service_id'],
                quantity_per_cycle=row['quantity_per_cycle'],
                sort_order=row.get('sort_order', 0),
            )
            for row in items_input
        ]
        MembershipPlanItem.objects.bulk_create(rows)

    def create(self, validated_data: dict) -> MembershipPlan:
        items_input = validated_data.pop('items_input', None)
        if not items_input:
            raise serializers.ValidationError(
                {'items_input': 'A plan needs at least one service item.'},
            )
        with transaction.atomic():
            plan = MembershipPlan.objects.create(**validated_data)
            self._save_items(plan, items_input)
        return plan

    def update(
        self, instance: MembershipPlan, validated_data: dict,
    ) -> MembershipPlan:
        items_input = validated_data.pop('items_input', None)
        with transaction.atomic():
            for attr, val in validated_data.items():
                setattr(instance, attr, val)
            instance.save()
            if items_input is not None:
                self._save_items(instance, items_input)
        return instance


# ── Per-customer (read-only) ────────────────────────────────────────


class SubscriptionItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = SubscriptionItem
        fields = [
            'id',
            'service',
            'service_name',
            'quantity_per_cycle',
            'quantity_remaining',
            'unit_value_cents',
            'sort_order',
        ]
        read_only_fields = fields


class SubscriptionRedemptionSerializer(serializers.ModelSerializer):
    by_user_email = serializers.EmailField(
        source='by_user.email', read_only=True, allow_null=True,
    )
    service_name = serializers.CharField(
        source='item.service_name', read_only=True,
    )

    class Meta:
        model = SubscriptionRedemption
        fields = [
            'id',
            'subscription',
            'item',
            'service_name',
            'quantity',
            'invoice_line',
            'appointment',
            'by_user_email',
            'note',
            'redeemed_at',
        ]
        read_only_fields = fields


class SubscriptionSerializer(serializers.ModelSerializer):
    """Per-customer subscription with current-period balance + recent
    redemption history. Drives the customer profile Memberships tab."""

    items = SubscriptionItemSerializer(many=True, read_only=True)
    redemptions = SubscriptionRedemptionSerializer(many=True, read_only=True)
    is_in_period = serializers.BooleanField(read_only=True)
    is_redeemable = serializers.BooleanField(read_only=True)
    total_credits_remaining = serializers.IntegerField(read_only=True)
    customer_first_name = serializers.CharField(
        source='customer.first_name', read_only=True,
    )
    customer_last_name = serializers.CharField(
        source='customer.last_name', read_only=True,
    )
    plan_name = serializers.CharField(
        source='plan.name', read_only=True, default=None,
    )
    cancelled_by_email = serializers.EmailField(
        source='cancelled_by.email', read_only=True, allow_null=True,
    )

    class Meta:
        model = Subscription
        fields = [
            'id',
            'customer',
            'customer_first_name',
            'customer_last_name',
            'plan',
            'plan_name',
            'source_invoice_line',
            'name',
            'description',
            'price_cents',
            'billing_interval',
            'member_discount_percent',
            'started_at',
            'current_period_starts_at',
            'current_period_ends_at',
            'status',
            'auto_renew',
            'cancelled_at',
            'cancelled_by_email',
            'cancel_reason',
            'is_in_period',
            'is_redeemable',
            'total_credits_remaining',
            'items',
            'redemptions',
            'created_at',
            'updated_at',
        ]
        read_only_fields = fields


class CancelSubscriptionInputSerializer(serializers.Serializer):
    """Body for `POST /api/subscriptions/<id>/cancel/`."""

    reason = serializers.CharField(
        max_length=200,
        help_text='Why the subscription is being cancelled. Required.',
    )
