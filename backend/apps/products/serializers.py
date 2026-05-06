"""DRF serializers for the products API.

Mirrors the services serializer split: nested category for read,
`category_id` PK for write. `sku` is editable but auto-generated
on create when the operator leaves it blank.
"""

from rest_framework import serializers

from apps.tenants.context import get_current_tenant

from .models import Product, ProductCategory


class ProductCategorySerializer(serializers.ModelSerializer):
    """Read/write serializer for `ProductCategory`.

    Pre-validates `(tenant, name)` uniqueness so duplicate-name
    requests return a clean 400 with a useful message instead of a
    bare 500 from the DB-level constraint.
    """

    product_count = serializers.IntegerField(source='products.count', read_only=True)

    class Meta:
        model = ProductCategory
        fields = [
            'id',
            'name',
            'color',
            'sort_order',
            'product_count',
        ]
        read_only_fields = ['id', 'product_count']

    def validate_name(self, value: str) -> str:
        tenant = get_current_tenant()
        if tenant is None:
            return value
        qs = ProductCategory.objects.filter(tenant=tenant, name__iexact=value)
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(
                f'A product category named "{value}" already exists.'
            )
        return value


class _NestedProductCategorySerializer(serializers.ModelSerializer):
    """Slim category shape inlined on the Product payload."""

    class Meta:
        model = ProductCategory
        fields = ['id', 'name', 'color', 'sort_order']


class ProductSerializer(serializers.ModelSerializer):
    """One serializer for both list and detail views.

    `category` is the nested read shape; `category_id` is the writable
    PK input. `is_low_stock` + `price_dollars` are computed; never
    accept them as input.
    """

    category = _NestedProductCategorySerializer(read_only=True)
    category_id = serializers.PrimaryKeyRelatedField(
        queryset=ProductCategory.objects.all(),
        write_only=True,
        required=False,
        allow_null=True,
        source='category',
    )
    price_dollars = serializers.CharField(read_only=True)
    is_low_stock = serializers.BooleanField(read_only=True)

    class Meta:
        model = Product
        fields = [
            'id',
            'name',
            'sku',
            'description',
            'category',
            'category_id',
            'price_cents',
            'price_dollars',
            'cost_cents',
            'tax_rate_percent',
            'track_inventory',
            'stock_quantity',
            'low_stock_threshold',
            'is_low_stock',
            'is_active',
            'sort_order',
            'created_at',
            'updated_at',
        ]
        read_only_fields = [
            'id',
            'category',
            'price_dollars',
            'is_low_stock',
            'created_at',
            'updated_at',
        ]


class StockAdjustmentInputSerializer(serializers.Serializer):
    """Input for the `/products/<id>/adjust-stock/` action.

    `delta` is signed: +5 for receiving inventory, -1 for damaged
    write-off. The note is required so the audit log captures *why*
    each adjustment happened — sale-time decrements have their own
    audit path via the invoice line; this surface is for manual
    adjustments only.
    """

    delta = serializers.IntegerField()
    note = serializers.CharField(max_length=200)

    def validate_delta(self, value: int) -> int:
        if value == 0:
            raise serializers.ValidationError('Delta must be non-zero.')
        return value
