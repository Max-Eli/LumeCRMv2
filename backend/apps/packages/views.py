"""Packages API.

Endpoints under `/api/`:

    GET    /api/packages/           List (?q=, ?active=)
    POST   /api/packages/           Create with nested items
    GET    /api/packages/{id}/      Retrieve
    PATCH  /api/packages/{id}/      Update (items list replaces wholesale if provided)
    PUT    /api/packages/{id}/      Same as PATCH semantics
    DELETE /api/packages/{id}/      Delete (rejected if any PurchasedPackage references)

Sale (turning a Package into a PurchasedPackage on an invoice) and
redemption (drawing down credits) are NOT exposed here — those
flow through the invoice action endpoints in the next step.
"""

from __future__ import annotations

from django.db import models, transaction
from django.db.models import Q
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from apps.audit.models import AuditLog
from apps.audit.services import record
from apps.tenants.context import get_current_tenant

from .models import (
    Package,
    PurchasedPackage,
    PurchasedPackageItem,
)
from .permissions import PackagePermission
from .serializers import (
    BuildCustomPackageInputSerializer,
    PackageSerializer,
    PurchasedPackageSerializer,
)


class PackageViewSet(viewsets.ModelViewSet):
    """CRUD for catalog `Package` rows, scoped to the current tenant.

    Items are nested in the same payload — POSTing a package with
    its included services in one round-trip. Updating with a new
    `items_input` replaces the existing items wholesale.
    """

    serializer_class = PackageSerializer
    permission_classes = [PackagePermission]

    def get_queryset(self):
        return (
            Package.objects
            .for_current_tenant()
            .prefetch_related(
                models.Prefetch(
                    'items',
                    queryset=Package.items.rel.related_model.objects.select_related('service'),
                ),
            )
        )

    def filter_queryset(self, queryset):
        params = self.request.query_params
        q = (params.get('q') or '').strip()
        active = (params.get('active') or '').strip().lower()
        if q:
            queryset = queryset.filter(
                Q(name__icontains=q)
                | Q(sku__icontains=q)
                | Q(description__icontains=q),
            )
        if active in {'true', '1'}:
            queryset = queryset.filter(is_active=True)
        elif active in {'false', '0'}:
            queryset = queryset.filter(is_active=False)
        return queryset

    # ── Audit-logged read overrides ─────────────────────────────────

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        results = (
            response.data.get('results', response.data)
            if isinstance(response.data, dict)
            else response.data
        )
        record(
            action=AuditLog.Action.READ,
            resource_type='package_list',
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
            resource_type='package',
            resource_id=instance.id,
            request=request,
        )
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    # ── Mutations ───────────────────────────────────────────────────

    def perform_create(self, serializer):
        tenant = get_current_tenant()
        if tenant is None:
            raise PermissionDenied('No tenant context resolved for this request.')
        instance = serializer.save(tenant=tenant)
        record(
            action=AuditLog.Action.CREATE,
            resource_type='package',
            resource_id=instance.id,
            request=self.request,
            metadata={
                'name': instance.name,
                'price_cents': instance.price_cents,
                'item_count': instance.items.count(),
            },
        )

    def perform_update(self, serializer):
        instance = serializer.save()
        record(
            action=AuditLog.Action.UPDATE,
            resource_type='package',
            resource_id=instance.id,
            request=self.request,
            metadata={'fields_changed': sorted(serializer.validated_data.keys())},
        )

    def perform_destroy(self, instance):
        # Refuse to delete a package that has any PurchasedPackage
        # referencing it — that would orphan customer balance data.
        # Operator should `is_active=False` instead.
        purchased_count = instance.purchases.count()
        if purchased_count > 0:
            raise ValidationError({
                'detail': (
                    f'Cannot delete: {purchased_count} customer(s) have '
                    f'purchased this package. Mark it inactive instead.'
                ),
            })
        record(
            action=AuditLog.Action.DELETE,
            resource_type='package',
            resource_id=instance.id,
            request=self.request,
            metadata={'name': instance.name, 'sku': instance.sku},
        )
        instance.delete()


class PurchasedPackageViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only listing of customer-owned package instances.

    Drives the customer profile's Packages tab + the invoice
    redemption picker. Filters: `?customer=<id>` (most common),
    `?status=active` to show only redeemable rows.

    Mutations happen via the invoice action endpoints (sale +
    redeem-from-package) — not here.
    """

    serializer_class = PurchasedPackageSerializer
    permission_classes = [PackagePermission]

    def get_queryset(self):
        return (
            PurchasedPackage.objects
            .for_current_tenant()
            .select_related('customer', 'source_template', 'voided_by')
            .prefetch_related('items', 'redemptions', 'redemptions__by_user')
        )

    def filter_queryset(self, queryset):
        params = self.request.query_params
        customer = (params.get('customer') or '').strip()
        status_filter = (params.get('status') or '').strip().lower()
        if customer:
            queryset = queryset.filter(customer_id=customer)
        if status_filter in {'pending', 'active', 'voided'}:
            queryset = queryset.filter(status=status_filter)
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
            resource_type='purchased_package_list',
            request=request,
            metadata={
                'count': len(results) if isinstance(results, list) else None,
                'customer': request.query_params.get('customer', ''),
            },
        )
        return response

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        record(
            action=AuditLog.Action.READ,
            resource_type='purchased_package',
            resource_id=instance.id,
            request=request,
        )
        return Response(self.get_serializer(instance).data)

    @action(detail=False, methods=['post'], url_path='build-custom')
    def build_custom(self, request):
        """`POST /api/purchased-packages/build-custom/` — front-desk
        builds a one-off `PurchasedPackage` for a specific customer
        without going through a pre-existing invoice.

        Atomically creates:
          - A draft `Invoice` for the customer (no appointment FK).
          - A single `InvoiceLineItem` representing the custom bundle.
          - A `PurchasedPackage` with `source_template = NULL`.
          - One `PurchasedPackageItem` per service in the bundle.

        The new invoice starts in OPEN status; the `PurchasedPackage`
        starts in PENDING. Closing the invoice (via the existing
        `/api/invoices/<id>/close/` action) is what flips the package
        to ACTIVE and lets it be redeemed.

        Returns both the `PurchasedPackage` payload AND the new
        invoice ID — the calendar UI uses the invoice ID to deep-
        link the operator into the POS-handoff page when they want
        to take payment now.
        """
        from apps.customers.models import Customer
        from apps.invoices.models import Invoice, InvoiceLineItem
        from apps.invoices.services import assign_invoice_number
        from apps.services.models import Service

        tenant = get_current_tenant()
        if tenant is None:
            raise PermissionDenied('No tenant context resolved for this request.')

        ser = BuildCustomPackageInputSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        # Validate customer + services belong to this tenant + are
        # eligible (customer active, service active).
        try:
            customer = Customer.objects.get(
                pk=data['customer_id'], tenant=tenant,
            )
        except Customer.DoesNotExist:
            return Response(
                {'customer_id': 'Unknown customer.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        service_ids = [row['service_id'] for row in data['items']]
        services = list(
            Service.objects.for_current_tenant().filter(pk__in=service_ids)
        )
        services_by_id = {s.pk: s for s in services}
        missing = [sid for sid in service_ids if sid not in services_by_id]
        if missing:
            return Response(
                {'items': f'Unknown service id(s): {missing}.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        inactive = [s.name for s in services if not s.is_active]
        if inactive:
            return Response(
                {'items': f'Inactive service(s): {", ".join(inactive)}.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        with transaction.atomic():
            invoice = Invoice.objects.create(
                tenant=tenant,
                customer=customer,
                appointment=None,
                status=Invoice.Status.OPEN,
                created_by=request.user if request.user.is_authenticated else None,
            )
            # Number assignment uses the same retry/locking discipline
            # as the appointment-created path; safe to call here.
            assign_invoice_number(invoice)

            line = InvoiceLineItem.objects.create(
                invoice=invoice,
                service=None,
                product=None,
                package=None,
                description=data['name'],
                quantity=1,
                unit_price_cents=data['price_cents'],
                tax_rate_percent=data.get('tax_rate_percent', 0),
            )

            purchased = PurchasedPackage.objects.create(
                tenant=tenant,
                customer=customer,
                source_template=None,
                source_invoice_line=line,
                name=data['name'],
                description=data.get('description', ''),
                price_cents=data['price_cents'],
                validity_days=data.get('validity_days') or None,
                status=PurchasedPackage.Status.PENDING,
            )
            PurchasedPackageItem.objects.bulk_create([
                PurchasedPackageItem(
                    purchased_package=purchased,
                    service=services_by_id[row['service_id']],
                    service_name=services_by_id[row['service_id']].name,
                    quantity_purchased=row['quantity'],
                    quantity_remaining=row['quantity'],
                    unit_value_cents=services_by_id[row['service_id']].price_cents,
                    sort_order=index,
                )
                for index, row in enumerate(data['items'])
            ])

            # Recompute invoice totals so the POS shows the right
            # amount due. `recalculate_totals(save=True)` updates the
            # row in place; we don't need a follow-up save.
            invoice.recalculate_totals(save=True)

        record(
            action=AuditLog.Action.CREATE,
            resource_type='purchased_package',
            resource_id=purchased.id,
            request=request,
            metadata={
                'kind': 'custom_one_off',
                'customer_id': customer.id,
                'invoice_id': invoice.id,
                'price_cents': purchased.price_cents,
                'item_count': len(data['items']),
            },
        )

        payload = self.get_serializer(
            PurchasedPackage.objects.select_related('customer').prefetch_related(
                'items', 'redemptions',
            ).get(pk=purchased.pk)
        ).data
        return Response(
            {
                'purchased_package': payload,
                'invoice_id': invoice.id,
                'invoice_number': invoice.invoice_number,
                'customer_id': customer.id,
            },
            status=status.HTTP_201_CREATED,
        )
