"""DRF serializers for the memberships API.

`MembershipPlanSerializer` writes nested `items` in one round-trip
with a wholesale-replace semantic on update — same shape as
`PackageSerializer`. `SubscriptionSerializer` is read-only;
mutations go through invoice action endpoints (sale + redemption)
or the cancel action.
"""

from __future__ import annotations

from django.db import transaction
from django.db.models import Avg
from rest_framework import serializers

from apps.services.models import Service, ServiceCategory

from .models import (
    MembershipPlan,
    MembershipPlanItem,
    Subscription,
    SubscriptionItem,
    SubscriptionRedemption,
)


# ── Catalog ─────────────────────────────────────────────────────────


class MembershipPlanItemInputSerializer(serializers.Serializer):
    """One inclusion line on the plan — a specific service OR a whole
    category — plus the per-cycle quantity. Exactly one of
    `service_id` / `category_id` must be supplied."""

    service_id = serializers.IntegerField(required=False, allow_null=True)
    category_id = serializers.IntegerField(required=False, allow_null=True)
    quantity_per_cycle = serializers.IntegerField(min_value=1)
    sort_order = serializers.IntegerField(default=0, required=False)

    def validate(self, attrs: dict) -> dict:
        has_service = attrs.get('service_id') is not None
        has_category = attrs.get('category_id') is not None
        if has_service == has_category:
            raise serializers.ValidationError(
                'Each line must reference exactly one of a service or a '
                'category.',
            )
        return attrs


class MembershipPlanItemOutputSerializer(serializers.ModelSerializer):
    """Read shape — a service line or a category line. `item_type`
    discriminates; only the matching id/name fields are populated."""

    item_type = serializers.SerializerMethodField()
    service_id = serializers.IntegerField(read_only=True)
    service_name = serializers.SerializerMethodField()
    service_price_cents = serializers.SerializerMethodField()
    category_id = serializers.IntegerField(read_only=True)
    category_name = serializers.SerializerMethodField()

    class Meta:
        model = MembershipPlanItem
        fields = [
            'id',
            'item_type',
            'service_id',
            'service_name',
            'service_price_cents',
            'category_id',
            'category_name',
            'quantity_per_cycle',
            'sort_order',
        ]

    def get_item_type(self, obj: MembershipPlanItem) -> str:
        return 'category' if obj.category_id else 'service'

    def get_service_name(self, obj: MembershipPlanItem) -> str:
        return obj.service.name if obj.service_id else ''

    def get_service_price_cents(self, obj: MembershipPlanItem) -> int:
        return obj.service.price_cents if obj.service_id else 0

    def get_category_name(self, obj: MembershipPlanItem) -> str:
        return obj.category.name if obj.category_id else ''


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
        to surface "$X value for $Y/mo" copy in the catalog UI.

        A category line has no single price, so it's valued at the
        average à-la-carte price of the active services in it."""
        total = 0
        for it in obj.items.all():
            if it.service_id:
                total += it.service.price_cents * it.quantity_per_cycle
            elif it.category_id:
                avg = (
                    Service.objects
                    .filter(category_id=it.category_id, is_active=True)
                    .aggregate(a=Avg('price_cents'))['a']
                )
                total += int(avg or 0) * it.quantity_per_cycle
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
                {'items_input': 'A plan needs at least one item.'},
            )

        service_ids = [
            r['service_id'] for r in items_input
            if r.get('service_id') is not None
        ]
        category_ids = [
            r['category_id'] for r in items_input
            if r.get('category_id') is not None
        ]

        if len(set(service_ids)) != len(service_ids):
            raise serializers.ValidationError(
                {'items_input': 'Each service may only appear once per plan.'},
            )
        if len(set(category_ids)) != len(category_ids):
            raise serializers.ValidationError(
                {'items_input': 'Each category may only appear once per plan.'},
            )

        if service_ids:
            valid_services = set(
                Service.objects
                .filter(tenant=tenant, pk__in=service_ids)
                .values_list('pk', flat=True)
            )
            invalid = [s for s in service_ids if s not in valid_services]
            if invalid:
                raise serializers.ValidationError(
                    {'items_input': f'Unknown service id(s): {invalid}.'},
                )
        if category_ids:
            valid_categories = set(
                ServiceCategory.objects
                .filter(tenant=tenant, pk__in=category_ids)
                .values_list('pk', flat=True)
            )
            invalid = [c for c in category_ids if c not in valid_categories]
            if invalid:
                raise serializers.ValidationError(
                    {'items_input': f'Unknown category id(s): {invalid}.'},
                )

        return attrs

    def _save_items(
        self, plan: MembershipPlan, items_input: list[dict],
    ) -> None:
        plan.items.all().delete()
        rows = [
            MembershipPlanItem(
                plan=plan,
                service_id=row.get('service_id'),
                category_id=row.get('category_id'),
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
                {'items_input': 'A plan needs at least one item.'},
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
    """A single credit on a subscription — a service credit or a
    category credit. `item_type` discriminates."""

    item_type = serializers.SerializerMethodField()

    class Meta:
        model = SubscriptionItem
        fields = [
            'id',
            'item_type',
            'service',
            'service_name',
            'category',
            'category_name',
            'quantity_per_cycle',
            'quantity_remaining',
            'unit_value_cents',
            'sort_order',
        ]
        read_only_fields = fields

    def get_item_type(self, obj: SubscriptionItem) -> str:
        return 'category' if obj.category_id else 'service'


class SubscriptionRedemptionSerializer(serializers.ModelSerializer):
    by_user_email = serializers.EmailField(
        source='by_user.email', read_only=True, allow_null=True,
    )
    service_name = serializers.SerializerMethodField()
    credit_kind = serializers.SerializerMethodField()
    category_name = serializers.SerializerMethodField()

    class Meta:
        model = SubscriptionRedemption
        fields = [
            'id',
            'subscription',
            'item',
            'service_name',
            'credit_kind',
            'category_name',
            'quantity',
            'invoice_line',
            'appointment',
            'by_user_email',
            'note',
            'redeemed_at',
        ]
        read_only_fields = fields

    def get_service_name(self, obj: SubscriptionRedemption) -> str:
        """What was actually redeemed. A direct-service credit carries
        the name on its item snapshot; a category credit does not, so
        fall back to the service captured on the $0 invoice line, then
        finally the category name."""
        line = obj.invoice_line
        if line is not None and line.service_id:
            return line.service.name
        if obj.item.service_name:
            return obj.item.service_name
        return obj.item.category_name or ''

    def get_credit_kind(self, obj: SubscriptionRedemption) -> str:
        return 'category' if obj.item.category_id else 'service'

    def get_category_name(self, obj: SubscriptionRedemption) -> str:
        return obj.item.category_name or ''


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
