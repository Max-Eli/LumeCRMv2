"""Products API.

Endpoints under `/api/`:

    GET    /api/products/                 List (?q=, ?category=, ?active=, ?low_stock=)
    POST   /api/products/                 Create (auto-gen SKU if missing)
    GET    /api/products/{id}/            Retrieve
    PATCH  /api/products/{id}/            Partial update
    PUT    /api/products/{id}/            Update
    DELETE /api/products/{id}/            Delete
    POST   /api/products/{id}/adjust-stock/  Manual stock delta with audit-required note

    GET    /api/product-categories/       List
    POST   /api/product-categories/       Create
    GET    /api/product-categories/{id}/  Retrieve
    PATCH  /api/product-categories/{id}/  Update
    DELETE /api/product-categories/{id}/  Delete

Tenant scoping via `for_current_tenant()`. Audit logging on every
mutation; list calls write a single `read product_list` entry rather
than one per row. Stock adjustments are audit-logged with the
operator-supplied `note` so HIPAA-adjacent traceability is preserved
for "who shrank inventory by 5 and why."
"""

from django.db import transaction
from django.db.models import F, Q
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from apps.audit.models import AuditLog
from apps.audit.services import record
from apps.tenants.context import get_current_tenant

from .models import Product, ProductCategory
from .permissions import ProductPermission
from .serializers import (
    ProductCategorySerializer,
    ProductSerializer,
    StockAdjustmentInputSerializer,
)


class ProductCategoryViewSet(viewsets.ModelViewSet):
    """CRUD for product categories. Read for any authenticated tenant
    member; write requires `MANAGE_SERVICES`."""

    serializer_class = ProductCategorySerializer
    permission_classes = [ProductPermission]

    def get_queryset(self):
        return ProductCategory.objects.for_current_tenant()

    def perform_create(self, serializer):
        tenant = get_current_tenant()
        if tenant is None:
            raise PermissionDenied('No tenant context resolved for this request.')
        serializer.save(tenant=tenant)


class ProductViewSet(viewsets.ModelViewSet):
    """CRUD endpoints for the product catalog, scoped to the current tenant."""

    serializer_class = ProductSerializer
    permission_classes = [ProductPermission]

    def get_queryset(self):
        return Product.objects.for_current_tenant().select_related('category')

    def filter_queryset(self, queryset):
        params = self.request.query_params
        q = (params.get('q') or '').strip()
        category = (params.get('category') or '').strip()
        active = (params.get('active') or '').strip().lower()
        low_stock = (params.get('low_stock') or '').strip().lower()

        if q:
            queryset = queryset.filter(
                Q(name__icontains=q)
                | Q(sku__icontains=q)
                | Q(description__icontains=q),
            )
        if category:
            queryset = queryset.filter(category_id=category)
        if active in {'true', '1'}:
            queryset = queryset.filter(is_active=True)
        elif active in {'false', '0'}:
            queryset = queryset.filter(is_active=False)
        if low_stock in {'true', '1'}:
            # Threshold>0 + tracked + at/below threshold. SQL-side so
            # we don't paginate then re-filter in Python.
            queryset = queryset.filter(
                track_inventory=True,
                low_stock_threshold__gt=0,
                stock_quantity__lte=F('low_stock_threshold'),
            )
        return queryset

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        results = (
            response.data.get('results', response.data)
            if isinstance(response.data, dict)
            else response.data
        )
        record(
            action=AuditLog.Action.READ,
            resource_type='product_list',
            request=request,
            metadata={
                'count': len(results) if isinstance(results, list) else None,
                'q': request.query_params.get('q', ''),
            },
        )
        return response

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        record(
            action=AuditLog.Action.READ,
            resource_type='product',
            resource_id=instance.id,
            request=request,
        )
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    def perform_create(self, serializer):
        tenant = get_current_tenant()
        if tenant is None:
            raise PermissionDenied('No tenant context resolved for this request.')
        instance = serializer.save(tenant=tenant)
        record(
            action=AuditLog.Action.CREATE,
            resource_type='product',
            resource_id=instance.id,
            request=self.request,
        )

    def perform_update(self, serializer):
        instance = serializer.save()
        record(
            action=AuditLog.Action.UPDATE,
            resource_type='product',
            resource_id=instance.id,
            request=self.request,
            metadata={'fields_changed': sorted(serializer.validated_data.keys())},
        )

    def perform_destroy(self, instance):
        record(
            action=AuditLog.Action.DELETE,
            resource_type='product',
            resource_id=instance.id,
            request=self.request,
            metadata={'name': instance.name, 'sku': instance.sku},
        )
        instance.delete()

    @action(detail=True, methods=['post'], url_path='adjust-stock')
    def adjust_stock(self, request, pk=None):
        """Apply a manual stock delta with an audit-required note.

        Sale-time decrements happen automatically when an invoice
        closes (the invoice → product line path); this endpoint is
        for everything else: receiving inventory, damage write-offs,
        physical count corrections.

        The delta + note + before/after counts are persisted to the
        audit log so a year-end reconciliation can answer "why did
        SKU X drop by 12 in October?"
        """
        product = self.get_object()
        ser = StockAdjustmentInputSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        delta = ser.validated_data['delta']
        note = ser.validated_data['note']

        with transaction.atomic():
            # Lock the row so concurrent adjustments serialize.
            locked = (
                Product.objects.select_for_update()
                .filter(pk=product.pk)
                .first()
            )
            before = locked.stock_quantity
            locked.stock_quantity = before + delta
            locked.save(update_fields=['stock_quantity', 'updated_at'])

        record(
            action=AuditLog.Action.UPDATE,
            resource_type='product',
            resource_id=product.pk,
            request=request,
            metadata={
                'event': 'stock_adjusted',
                'delta': delta,
                'before': before,
                'after': before + delta,
                'note': note,
            },
        )
        product.refresh_from_db()
        return Response(self.get_serializer(product).data, status=status.HTTP_200_OK)
