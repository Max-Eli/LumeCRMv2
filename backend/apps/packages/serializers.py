"""DRF serializers for the packages API.

`PackageSerializer` writes nested `items` in one round-trip — the
operator builds "5 facials + 1 lash consult" as a single payload
rather than POSTing the package then PATCHing items in. Updates
replace the items list wholesale (transactional, atomic).
"""

from __future__ import annotations

from django.db import transaction
from rest_framework import serializers

from apps.services.models import Service

from .models import (
    Package,
    PackageItem,
    PackageRedemption,
    PurchasedPackage,
    PurchasedPackageItem,
)


class PackageItemInputSerializer(serializers.Serializer):
    """One item in a package: which service + how many credits."""

    service_id = serializers.IntegerField()
    quantity = serializers.IntegerField(min_value=1)
    sort_order = serializers.IntegerField(default=0, required=False)


class PackageItemOutputSerializer(serializers.ModelSerializer):
    """Read shape — denormalizes service name + a-la-carte price so
    the catalog list doesn't need a separate services round-trip."""

    service_id = serializers.IntegerField(source='service.id', read_only=True)
    service_name = serializers.CharField(source='service.name', read_only=True)
    service_price_cents = serializers.IntegerField(
        source='service.price_cents', read_only=True,
    )

    class Meta:
        model = PackageItem
        fields = [
            'id',
            'service_id',
            'service_name',
            'service_price_cents',
            'quantity',
            'sort_order',
        ]


class PackageSerializer(serializers.ModelSerializer):
    """Catalog package read + write.

    On write, `items` is the canonical input — a list of
    `{service_id, quantity, sort_order?}`. The save path replaces
    the existing items wholesale (no diffing) inside an atomic
    transaction; PRESERVES rows that are referenced by historical
    PurchasedPackageItem snapshots automatically because the
    snapshot lives on PurchasedPackageItem, not here.
    """

    items = PackageItemOutputSerializer(many=True, read_only=True)
    items_input = PackageItemInputSerializer(
        many=True, write_only=True, required=False,
    )
    price_dollars = serializers.CharField(read_only=True)
    a_la_carte_total_cents = serializers.SerializerMethodField()
    implicit_discount_cents = serializers.SerializerMethodField()

    class Meta:
        model = Package
        fields = [
            'id',
            'name',
            'sku',
            'description',
            'price_cents',
            'price_dollars',
            'tax_rate_percent',
            'validity_days',
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

    def get_a_la_carte_total_cents(self, obj: Package) -> int:
        """Sum of (service.price_cents × item.quantity) — the price
        the customer would pay buying these services individually."""
        total = 0
        for it in obj.items.all():
            total += it.service.price_cents * it.quantity
        return total

    def get_implicit_discount_cents(self, obj: Package) -> int:
        """How much the customer saves vs. a la carte. Negative
        result means the package is more expensive than a la carte
        (rare but legal — e.g. a "VIP package" with bonus services
        bundled in)."""
        return self.get_a_la_carte_total_cents(obj) - obj.price_cents

    # ── Validation ──────────────────────────────────────────────────

    def validate(self, attrs: dict) -> dict:
        """Items list (when provided) must reference services that
        belong to this tenant."""
        items_input = attrs.get('items_input')
        if items_input is None:
            return attrs

        from apps.tenants.context import get_current_tenant
        tenant = get_current_tenant()

        # Empty list is allowed at validation time but rejected at
        # save time — DRF doesn't easily express "required only on
        # CREATE." Keeping this lenient lets a PATCH that omits
        # items leave the existing list alone.
        if not items_input:
            raise serializers.ValidationError(
                {'items_input': 'A package needs at least one service item.'},
            )

        service_ids = [row['service_id'] for row in items_input]
        if len(set(service_ids)) != len(service_ids):
            raise serializers.ValidationError(
                {'items_input': 'Each service may only appear once per package.'},
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

    # ── Persistence ─────────────────────────────────────────────────

    def _save_items(self, package: Package, items_input: list[dict]) -> None:
        """Replace the package's items with the supplied list. Wholesale
        rewrite inside an atomic block — caller wraps in a transaction."""
        package.items.all().delete()
        rows = [
            PackageItem(
                package=package,
                service_id=row['service_id'],
                quantity=row['quantity'],
                sort_order=row.get('sort_order', 0),
            )
            for row in items_input
        ]
        PackageItem.objects.bulk_create(rows)

    def create(self, validated_data: dict) -> Package:
        items_input = validated_data.pop('items_input', None)
        if not items_input:
            raise serializers.ValidationError(
                {'items_input': 'A package needs at least one service item.'},
            )
        with transaction.atomic():
            package = Package.objects.create(**validated_data)
            self._save_items(package, items_input)
        return package

    def update(self, instance: Package, validated_data: dict) -> Package:
        items_input = validated_data.pop('items_input', None)
        with transaction.atomic():
            for attr, val in validated_data.items():
                setattr(instance, attr, val)
            instance.save()
            if items_input is not None:
                self._save_items(instance, items_input)
        return instance


# ── PurchasedPackage (read-only) ────────────────────────────────────


class PurchasedPackageItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = PurchasedPackageItem
        fields = [
            'id',
            'service',
            'service_name',
            'quantity_purchased',
            'quantity_remaining',
            'unit_value_cents',
            'sort_order',
        ]
        read_only_fields = fields


class PackageRedemptionSerializer(serializers.ModelSerializer):
    """Read-only ledger row. Surfaces enough to render a per-package
    history list on the customer profile."""

    by_user_email = serializers.EmailField(
        source='by_user.email', read_only=True, allow_null=True,
    )
    service_name = serializers.CharField(
        source='item.service_name', read_only=True,
    )

    class Meta:
        model = PackageRedemption
        fields = [
            'id',
            'purchased_package',
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


class BuildCustomPackageItemInputSerializer(serializers.Serializer):
    """One service line in a customer-built one-off package."""

    service_id = serializers.IntegerField()
    quantity = serializers.IntegerField(min_value=1)


class BuildCustomPackageInputSerializer(serializers.Serializer):
    """Body for `POST /api/purchased-packages/build-custom/`.

    Builds a one-off `PurchasedPackage` for a single customer + the
    backing draft Invoice in one atomic call. Distinct from
    `add_custom_package` (which appends to an *existing* invoice) —
    this is the standalone calendar-tile workflow where the operator
    doesn't have an invoice context yet, just a customer.

    Returns the created `PurchasedPackage` plus the invoice ID so
    the frontend can deep-link to the POS-handoff page when the
    operator chooses to take payment now.
    """

    customer_id = serializers.IntegerField()
    name = serializers.CharField(max_length=200)
    description = serializers.CharField(
        required=False, allow_blank=True, default='',
    )
    price_cents = serializers.IntegerField(min_value=0)
    tax_rate_percent = serializers.DecimalField(
        max_digits=6, decimal_places=3, required=False, default=0,
    )
    validity_days = serializers.IntegerField(
        required=False, allow_null=True, min_value=0,
    )
    items = BuildCustomPackageItemInputSerializer(many=True)

    def validate_items(self, value: list[dict]) -> list[dict]:
        if not value:
            raise serializers.ValidationError(
                'A custom package needs at least one service item.'
            )
        ids = [row['service_id'] for row in value]
        if len(set(ids)) != len(ids):
            raise serializers.ValidationError(
                'Each service may only appear once per package.'
            )
        return value


class PurchasedPackageSerializer(serializers.ModelSerializer):
    """Per-customer instance + per-service balance + recent
    redemption ledger. Drives the customer profile Packages tab."""

    items = PurchasedPackageItemSerializer(many=True, read_only=True)
    redemptions = PackageRedemptionSerializer(many=True, read_only=True)
    is_expired = serializers.BooleanField(read_only=True)
    is_redeemable = serializers.BooleanField(read_only=True)
    total_credits_remaining = serializers.IntegerField(read_only=True)
    customer_first_name = serializers.CharField(
        source='customer.first_name', read_only=True,
    )
    customer_last_name = serializers.CharField(
        source='customer.last_name', read_only=True,
    )
    voided_by_email = serializers.EmailField(
        source='voided_by.email', read_only=True, allow_null=True,
    )

    class Meta:
        model = PurchasedPackage
        fields = [
            'id',
            'customer',
            'customer_first_name',
            'customer_last_name',
            'source_template',
            'source_invoice_line',
            'name',
            'description',
            'price_cents',
            'validity_days',
            'purchased_at',
            'expires_at',
            'status',
            'voided_at',
            'voided_by_email',
            'void_reason',
            'is_expired',
            'is_redeemable',
            'total_credits_remaining',
            'items',
            'redemptions',
            'created_at',
            'updated_at',
        ]
        read_only_fields = fields
