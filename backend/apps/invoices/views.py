"""Invoices API.

Endpoints under `/api/invoices/`:

    GET    /api/invoices/                List (filters: ?customer=, ?status=, ?appointment=)
    GET    /api/invoices/{id}/           Retrieve
    POST   /api/invoices/{id}/close/     Close (take payment) — gated by PROCESS_PAYMENT
    POST   /api/invoices/{id}/reopen/    Reopen — gated by REOPEN_INVOICE; ≤ 60 days from closed_at
    POST   /api/invoices/{id}/void/      Void — gated by VOID_INVOICE

Generic `POST/PUT/PATCH/DELETE` on the collection is intentionally
disallowed (see `permissions.InvoicePermission`). Invoices come into
existence via the appointment-creation signal and only mutate through
the named action endpoints, so every state change writes a structured
audit log entry.

Audit logging on every action; tenant scoping via
`for_current_tenant()`. State transitions use `transaction.atomic` +
`select_for_update` inside the model methods themselves.
"""

from django.db import transaction
from django.http import HttpResponse
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from apps.audit.models import AuditLog
from apps.audit.services import record
from apps.tenants.context import get_current_tenant

from .models import (
    Invoice,
    InvoiceLineItem,
    InvoiceReopenWindowError,
    InvoiceStateError,
)
from .permissions import InvoicePermission
from .serializers import (
    AddCustomPackageInputSerializer,
    AddGiftCardSaleInputSerializer,
    AddLineInputSerializer,
    ApplyGiftCardInputSerializer,
    CloseInvoiceInputSerializer,
    CreateStandaloneInvoiceInputSerializer,
    InvoiceSerializer,
    RedeemFromMembershipInputSerializer,
    RedeemFromPackageInputSerializer,
    ReopenInvoiceInputSerializer,
    VoidInvoiceInputSerializer,
)


class InvoiceViewSet(viewsets.ReadOnlyModelViewSet):
    """List + retrieve invoices, plus close/reopen/void actions.

    Inherits from `ReadOnlyModelViewSet` rather than `ModelViewSet` so
    DRF doesn't auto-generate the create/update/destroy routes — those
    are explicitly disallowed by `InvoicePermission`. Belt + suspenders:
    even if a future refactor accidentally widens the viewset, the
    permission layer still rejects the actions.
    """

    serializer_class = InvoiceSerializer
    permission_classes = [InvoicePermission]

    def get_queryset(self):
        from django.db.models import Prefetch

        # Local import to avoid a hard module-load coupling between
        # invoices and payments — the apps install in either order.
        from apps.payments.models import Charge, Refund

        return (
            Invoice.objects
            .for_current_tenant()
            .select_related(
                'customer',
                'appointment', 'appointment__service', 'appointment__provider', 'appointment__provider__user',
                'closed_by', 'reopened_by', 'voided_by', 'created_by',
            )
            .prefetch_related(
                'line_items',
                # Order charges newest-first to match the
                # serializer's payment-history rendering. Nested
                # prefetch on refunds + created_by so the serializer
                # never falls back to a per-row query.
                Prefetch(
                    'charges',
                    queryset=(
                        Charge.objects
                        .order_by('-created_at')
                        .select_related('created_by')
                        .prefetch_related(
                            Prefetch(
                                'refunds',
                                queryset=(
                                    Refund.objects
                                    .order_by('-created_at')
                                    .select_related('created_by')
                                ),
                            ),
                        )
                    ),
                ),
            )
        )

    def filter_queryset(self, queryset):
        params = self.request.query_params
        customer = (params.get('customer') or '').strip()
        status_param = (params.get('status') or '').strip()
        appointment = (params.get('appointment') or '').strip()
        if customer:
            queryset = queryset.filter(customer_id=customer)
        if status_param:
            queryset = queryset.filter(status=status_param)
        if appointment:
            queryset = queryset.filter(appointment_id=appointment)
        return queryset

    # ── Audit-logged read overrides ──────────────────────────────────────

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        results = response.data.get('results', response.data) if isinstance(response.data, dict) else response.data
        record(
            action=AuditLog.Action.READ,
            resource_type='invoice_list',
            request=request,
            metadata={
                'count': len(results) if isinstance(results, list) else None,
                'customer': request.query_params.get('customer', ''),
                'status': request.query_params.get('status', ''),
            },
        )
        return response

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        record(
            action=AuditLog.Action.READ,
            resource_type='invoice',
            resource_id=instance.id,
            request=request,
        )
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    # ── Standalone invoice creation ──────────────────────────────────────

    @extend_schema(
        request=CreateStandaloneInvoiceInputSerializer,
        responses={
            201: InvoiceSerializer,
            400: OpenApiResponse(description='Unknown customer'),
            403: OpenApiResponse(description='Missing PROCESS_PAYMENT permission'),
        },
    )
    @action(detail=False, methods=['post'], url_path='create-standalone')
    def create_standalone(self, request):
        """`POST /api/invoices/create-standalone/` — open a blank
        invoice for a walk-in sale with no appointment.

        Backs the calendar "New sale" tool: a customer wants to buy a
        product, gift card, or membership without booking. The invoice
        is created OPEN with no line items; the operator then adds
        lines and takes payment on the take-payment page. Mirrors the
        invoice-creation discipline of the appointment-booked path —
        same `assign_invoice_number` locking, same OPEN start state.
        """
        from apps.customers.models import Customer

        from .services import assign_invoice_number

        tenant = get_current_tenant()
        if tenant is None:
            raise PermissionDenied('No tenant context resolved for this request.')

        ser = CreateStandaloneInvoiceInputSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        try:
            customer = Customer.objects.get(
                pk=ser.validated_data['customer_id'], tenant=tenant,
            )
        except Customer.DoesNotExist:
            return Response(
                {'customer_id': 'Unknown customer.'},
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
            assign_invoice_number(invoice)

        record(
            action=AuditLog.Action.CREATE,
            resource_type='invoice',
            resource_id=invoice.id,
            request=request,
            metadata={
                'event': 'standalone_invoice_created',
                'customer_id': customer.id,
            },
        )

        invoice.refresh_from_db()
        return Response(
            self.get_serializer(invoice).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(
        responses={
            200: OpenApiResponse(
                response={'type': 'string', 'format': 'binary'},
                description='application/pdf — the rendered invoice. Generated on demand from the current invoice row.',
            ),
            404: OpenApiResponse(description='Invoice not found in this tenant.'),
        },
    )
    @action(detail=True, methods=['get'], url_path='pdf')
    def pdf(self, request, pk=None):
        """Render this invoice as a PDF and stream it as an attachment.

        The PDF is **a projection of the invoice row at request time** —
        we don't cache or store the rendered bytes. PAID + VOID invoices
        have immutable totals (state machine + CheckConstraints), so the
        projection is stable for the invoice's lifetime; OPEN invoices
        reflect the current line-item state. See ADR 0018.
        """
        from .services import render_invoice_pdf

        instance = self.get_object()
        pdf_bytes = render_invoice_pdf(instance)

        record(
            action=AuditLog.Action.READ,
            resource_type='invoice_pdf',
            resource_id=instance.id,
            request=request,
            metadata={'bytes': len(pdf_bytes)},
        )

        filename = f'{instance.invoice_number or f"invoice-{instance.pk}"}.pdf'
        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response

    @extend_schema(
        request=None,
        responses={
            200: OpenApiResponse(description='Email sent. Returns the recipient address used.'),
            400: OpenApiResponse(description='Customer has no email on file.'),
            403: OpenApiResponse(description='Caller lacks PROCESS_PAYMENT.'),
            502: OpenApiResponse(description='Mail backend rejected the send.'),
        },
    )
    @action(detail=True, methods=['post'], url_path='email')
    def email(self, request, pk=None):
        """Email the invoice (PDF attached) to the customer of record.

        Same recipient resolution as every other transactional email
        in the system: `invoice.customer.email`. We do not let the
        operator override the To address — it's the customer's record
        of file. If the customer has no email, we 400 with a clear
        message so the operator can update the profile first.

        Idempotency: each call sends a fresh email. We do not
        deduplicate; the audit log carries the trail. Future polish
        could add a `last_emailed_at` field + a "Last sent X min ago"
        affordance in the UI to prevent accidental spam.
        """
        from django.core.mail import BadHeaderError

        from .services import InvoiceEmailError, send_invoice_email

        instance = self.get_object()

        try:
            recipient = send_invoice_email(instance, sender_user=request.user)
        except InvoiceEmailError as e:
            record(
                action=AuditLog.Action.UPDATE,
                resource_type='invoice_email',
                resource_id=instance.id,
                request=request,
                metadata={'outcome': 'failed_missing_email'},
            )
            raise ValidationError({'detail': str(e)})
        except BadHeaderError:
            # Malformed header → almost always means a stale email
            # field with embedded newlines. Treat as a validation
            # failure on the customer record, not a system error.
            raise ValidationError({'detail': 'Recipient email is malformed.'})
        # Any other exception from msg.send() (SES rejection, SMTP
        # connection error, etc.) bubbles to DRF's default handler
        # which returns a 500. We do not want to swallow these —
        # the operator needs to know the email did not go out.

        record(
            action=AuditLog.Action.UPDATE,
            resource_type='invoice_email',
            resource_id=instance.id,
            request=request,
            metadata={'recipient': recipient, 'outcome': 'sent'},
        )
        return Response({'recipient': recipient}, status=status.HTTP_200_OK)

    # ── State-changing actions ───────────────────────────────────────────

    @extend_schema(
        request=CloseInvoiceInputSerializer,
        responses={
            200: InvoiceSerializer,
            400: OpenApiResponse(description='Validation error'),
            409: OpenApiResponse(description='Invoice not in a closable state'),
        },
    )
    @action(detail=True, methods=['post'], url_path='close')
    def close(self, request, pk=None):
        """Close (take payment). Transitions the linked appointment to
        `completed` atomically with the invoice update."""
        invoice = self.get_object()
        input_serializer = CloseInvoiceInputSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)

        try:
            invoice.close(
                by_user=request.user,
                payment_method=input_serializer.validated_data['payment_method'],
                payment_reference=input_serializer.validated_data.get('payment_reference', ''),
                notes=input_serializer.validated_data.get('notes', ''),
            )
        except InvoiceStateError as e:
            # Surface state errors as 409 so clients can distinguish them
            # from input-validation failures (which are 400).
            return Response({'detail': str(e)}, status=status.HTTP_409_CONFLICT)

        return Response(self.get_serializer(invoice).data)

    @extend_schema(
        request=ReopenInvoiceInputSerializer,
        responses={
            200: InvoiceSerializer,
            400: OpenApiResponse(description='Validation error'),
            403: OpenApiResponse(description='Missing REOPEN_INVOICE permission'),
            409: OpenApiResponse(description='Wrong state or 60-day window expired'),
        },
    )
    @action(detail=True, methods=['post'], url_path='reopen')
    def reopen(self, request, pk=None):
        """Reopen a paid invoice. Permission gated to owner/manager
        (`REOPEN_INVOICE` is in `LOCKED_PERMISSIONS`); time gated to 60
        days from `closed_at`. The linked appointment reverts to
        `checked_in`."""
        invoice = self.get_object()
        input_serializer = ReopenInvoiceInputSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)

        try:
            invoice.reopen(
                by_user=request.user,
                reason=input_serializer.validated_data['reason'],
            )
        except InvoiceReopenWindowError as e:
            return Response(
                {'detail': str(e), 'window_expired': True},
                status=status.HTTP_409_CONFLICT,
            )
        except InvoiceStateError as e:
            return Response({'detail': str(e)}, status=status.HTTP_409_CONFLICT)

        return Response(self.get_serializer(invoice).data)

    @extend_schema(
        request=VoidInvoiceInputSerializer,
        responses={
            200: InvoiceSerializer,
            400: OpenApiResponse(description='Validation error'),
            403: OpenApiResponse(description='Missing VOID_INVOICE permission'),
            409: OpenApiResponse(description='Invoice not in a voidable state'),
        },
    )
    @action(detail=True, methods=['post'], url_path='void')
    def void(self, request, pk=None):
        """Void an open invoice. Cannot void a paid invoice directly —
        reopen first (within the 60-day window, requires owner/manager)."""
        invoice = self.get_object()
        input_serializer = VoidInvoiceInputSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)

        try:
            invoice.void(
                by_user=request.user,
                reason=input_serializer.validated_data['reason'],
            )
        except InvoiceStateError as e:
            return Response({'detail': str(e)}, status=status.HTTP_409_CONFLICT)

        return Response(self.get_serializer(invoice).data)

    @extend_schema(
        request=AddLineInputSerializer,
        responses={
            200: InvoiceSerializer,
            400: OpenApiResponse(description='Validation error'),
            403: OpenApiResponse(description='Missing PROCESS_PAYMENT permission'),
            409: OpenApiResponse(description='Invoice not OPEN'),
        },
    )
    @action(detail=True, methods=['post'], url_path='add-line')
    def add_line(self, request, pk=None):
        """Append a line item to an OPEN invoice from the catalog.

        Caller supplies exactly one of `service_id` / `product_id`.
        Snapshots `description`, `unit_price_cents`, and
        `tax_rate_percent` from the source row so subsequent catalog
        edits don't drift this line. Optional overrides for
        `quantity` / `unit_price_cents` / `description` for member
        discounts and ad-hoc rates.

        Refuses to add to PAID or VOID invoices (409). Stock is NOT
        decremented here — that happens at close-time. Adding a
        product line to an OPEN invoice is just a reservation; the
        physical decrement only fires when payment is taken.
        """
        invoice = self.get_object()
        if invoice.status != Invoice.Status.OPEN:
            return Response(
                {
                    'detail': (
                        f'Cannot add a line to a {invoice.get_status_display().lower()} '
                        f'invoice. Reopen it first if needed.'
                    ),
                },
                status=status.HTTP_409_CONFLICT,
            )

        ser = AddLineInputSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        from django.db import transaction

        from apps.memberships.models import (
            MembershipPlan,
            Subscription,
            SubscriptionItem,
        )
        from apps.packages.models import (
            Package,
            PurchasedPackage,
            PurchasedPackageItem,
        )
        from apps.products.models import Product
        from apps.services.models import Service

        if data.get('service_id') is not None:
            try:
                service_source = Service.objects.for_current_tenant().get(
                    pk=data['service_id'],
                )
            except Service.DoesNotExist:
                return Response(
                    {'service_id': 'Service not found in this tenant.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if not service_source.is_active:
                return Response(
                    {'service_id': f'{service_source.name} is inactive.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            line_kwargs = {
                'service': service_source,
                'product': None,
                'package': None,
                'description': data.get('description') or service_source.name,
                'quantity': data.get('quantity', 1),
                'unit_price_cents': (
                    data['unit_price_cents']
                    if data.get('unit_price_cents') is not None
                    else service_source.price_cents
                ),
                'tax_rate_percent': service_source.tax_rate_percent,
            }
            audit_event = 'service_line_added'
            audit_payload = {
                'service_id': service_source.pk,
                'service_name': service_source.name,
            }
            line = InvoiceLineItem.objects.create(invoice=invoice, **line_kwargs)
        elif data.get('product_id') is not None:
            try:
                product_source = Product.objects.for_current_tenant().get(
                    pk=data['product_id'],
                )
            except Product.DoesNotExist:
                return Response(
                    {'product_id': 'Product not found in this tenant.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if not product_source.is_active:
                return Response(
                    {'product_id': f'{product_source.name} is inactive.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            line_kwargs = {
                'service': None,
                'product': product_source,
                'package': None,
                'description': data.get('description') or product_source.name,
                'quantity': data.get('quantity', 1),
                'unit_price_cents': (
                    data['unit_price_cents']
                    if data.get('unit_price_cents') is not None
                    else product_source.price_cents
                ),
                'tax_rate_percent': product_source.tax_rate_percent,
            }
            audit_event = 'product_line_added'
            audit_payload = {
                'product_id': product_source.pk,
                'product_sku': product_source.sku,
                'product_name': product_source.name,
            }
            line = InvoiceLineItem.objects.create(invoice=invoice, **line_kwargs)
        elif data.get('package_id') is not None:
            try:
                package_source = (
                    Package.objects.for_current_tenant()
                    .prefetch_related('items', 'items__service')
                    .get(pk=data['package_id'])
                )
            except Package.DoesNotExist:
                return Response(
                    {'package_id': 'Package not found in this tenant.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if not package_source.is_active:
                return Response(
                    {'package_id': f'{package_source.name} is inactive.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if not package_source.items.exists():
                return Response(
                    {'package_id': 'Package has no included services.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            # Packages always go on the invoice as qty=1; the included
            # service quantities live on the PurchasedPackage rows.
            line_unit_price = (
                data['unit_price_cents']
                if data.get('unit_price_cents') is not None
                else package_source.price_cents
            )
            line_kwargs = {
                'service': None,
                'product': None,
                'package': package_source,
                'description': data.get('description') or package_source.name,
                'quantity': 1,
                'unit_price_cents': line_unit_price,
                'tax_rate_percent': package_source.tax_rate_percent,
            }
            with transaction.atomic():
                line = InvoiceLineItem.objects.create(
                    invoice=invoice, **line_kwargs,
                )
                purchased = PurchasedPackage.objects.create(
                    tenant=invoice.tenant,
                    customer=invoice.customer,
                    source_template=package_source,
                    source_invoice_line=line,
                    name=package_source.name,
                    description=package_source.description,
                    price_cents=line_unit_price,
                    validity_days=package_source.validity_days,
                    status=PurchasedPackage.Status.PENDING,
                )
                PurchasedPackageItem.objects.bulk_create([
                    PurchasedPackageItem(
                        purchased_package=purchased,
                        service=item.service,
                        service_name=item.service.name,
                        quantity_purchased=item.quantity,
                        quantity_remaining=item.quantity,
                        unit_value_cents=item.service.price_cents,
                        sort_order=item.sort_order,
                    )
                    for item in package_source.items.all()
                ])
            audit_event = 'package_line_added'
            audit_payload = {
                'package_id': package_source.pk,
                'package_name': package_source.name,
                'purchased_package_id': purchased.pk,
                'item_count': package_source.items.count(),
            }
        else:
            # membership_plan_id branch — analogous to packages but
            # creates a Subscription instead of a PurchasedPackage.
            try:
                plan_source = (
                    MembershipPlan.objects.for_current_tenant()
                    .prefetch_related(
                        'items', 'items__service', 'items__category',
                    )
                    .get(pk=data['membership_plan_id'])
                )
            except MembershipPlan.DoesNotExist:
                return Response(
                    {'membership_plan_id': 'Plan not found in this tenant.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if not plan_source.is_active:
                return Response(
                    {'membership_plan_id': f'{plan_source.name} is inactive.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if not plan_source.items.exists():
                return Response(
                    {
                        'membership_plan_id': (
                            'Plan has no included items.'
                        ),
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            line_unit_price = (
                data['unit_price_cents']
                if data.get('unit_price_cents') is not None
                else plan_source.price_cents
            )
            line_kwargs = {
                'service': None,
                'product': None,
                'package': None,
                'membership_plan': plan_source,
                'description': data.get('description') or plan_source.name,
                'quantity': 1,
                'unit_price_cents': line_unit_price,
                'tax_rate_percent': plan_source.tax_rate_percent,
            }
            with transaction.atomic():
                line = InvoiceLineItem.objects.create(
                    invoice=invoice, **line_kwargs,
                )
                subscription = Subscription.objects.create(
                    tenant=invoice.tenant,
                    customer=invoice.customer,
                    plan=plan_source,
                    source_invoice_line=line,
                    name=plan_source.name,
                    description=plan_source.description,
                    price_cents=line_unit_price,
                    billing_interval=plan_source.billing_interval,
                    member_discount_percent=plan_source.member_discount_percent,
                    status=Subscription.Status.PENDING,
                )
                sub_items = []
                for item in plan_source.items.select_related(
                    'service', 'category',
                ):
                    if item.category_id:
                        # Category credit — redeemable against any
                        # service in the category. Value depends on
                        # which service is redeemed, so no snapshot.
                        sub_items.append(SubscriptionItem(
                            subscription=subscription,
                            service=None,
                            service_name='',
                            category=item.category,
                            category_name=item.category.name,
                            quantity_per_cycle=item.quantity_per_cycle,
                            quantity_remaining=item.quantity_per_cycle,
                            unit_value_cents=0,
                            sort_order=item.sort_order,
                        ))
                    else:
                        sub_items.append(SubscriptionItem(
                            subscription=subscription,
                            service=item.service,
                            service_name=item.service.name,
                            category=None,
                            category_name='',
                            quantity_per_cycle=item.quantity_per_cycle,
                            quantity_remaining=item.quantity_per_cycle,
                            unit_value_cents=item.service.price_cents,
                            sort_order=item.sort_order,
                        ))
                SubscriptionItem.objects.bulk_create(sub_items)
            audit_event = 'membership_line_added'
            audit_payload = {
                'membership_plan_id': plan_source.pk,
                'plan_name': plan_source.name,
                'subscription_id': subscription.pk,
                'billing_interval': plan_source.billing_interval,
                'item_count': plan_source.items.count(),
            }

        record(
            action=AuditLog.Action.UPDATE,
            resource_type='invoice',
            resource_id=invoice.pk,
            request=request,
            metadata={
                'event': audit_event,
                'line_id': line.pk,
                'qty': line.quantity,
                'unit_price_cents': line.unit_price_cents,
                'line_subtotal_cents': line.line_subtotal_cents,
                **audit_payload,
            },
        )
        invoice.refresh_from_db()
        return Response(self.get_serializer(invoice).data)

    @extend_schema(
        request=RedeemFromPackageInputSerializer,
        responses={
            200: InvoiceSerializer,
            400: OpenApiResponse(description='Validation error'),
            403: OpenApiResponse(description='Missing PROCESS_PAYMENT permission'),
            409: OpenApiResponse(description='Invoice not OPEN or package not redeemable'),
        },
    )
    @action(detail=True, methods=['post'], url_path='redeem-from-package')
    def redeem_from_package(self, request, pk=None):
        """Draw down one credit from a customer's PurchasedPackage.

        Validates: invoice OPEN, package ACTIVE + not expired,
        package belongs to this invoice's customer, the requested
        service is in the package, and there's at least one credit
        remaining for that service. Atomically:

          - Decrements `quantity_remaining` on the matching
            `PurchasedPackageItem` (with `select_for_update`).
          - Creates a $0 `InvoiceLineItem` with the service set
            and a description tagged with the source package.
          - Writes a `PackageRedemption` ledger row pointing at
            both the line and the package.

        The line is $0 because the customer already paid for the
        credit when they bought the package; financial reports
        attribute the revenue to the original sale, not the
        redeem.
        """
        from django.db import transaction

        from apps.packages.models import (
            PackageRedemption,
            PurchasedPackage,
            PurchasedPackageItem,
        )

        invoice = self.get_object()
        if invoice.status != Invoice.Status.OPEN:
            return Response(
                {
                    'detail': (
                        f'Cannot redeem against a '
                        f'{invoice.get_status_display().lower()} invoice.'
                    ),
                },
                status=status.HTTP_409_CONFLICT,
            )

        ser = RedeemFromPackageInputSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        with transaction.atomic():
            try:
                pp = (
                    PurchasedPackage.objects.select_for_update()
                    .for_current_tenant()
                    .get(pk=data['purchased_package_id'])
                )
            except PurchasedPackage.DoesNotExist:
                return Response(
                    {'purchased_package_id': 'Package not found.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if pp.customer_id != invoice.customer_id:
                return Response(
                    {
                        'purchased_package_id': (
                            "Package belongs to a different customer."
                        ),
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if pp.status != PurchasedPackage.Status.ACTIVE:
                return Response(
                    {
                        'detail': (
                            f'Package is {pp.get_status_display().lower()}, '
                            f'not redeemable.'
                        ),
                    },
                    status=status.HTTP_409_CONFLICT,
                )
            if pp.is_expired:
                return Response(
                    {'detail': 'Package has expired.'},
                    status=status.HTTP_409_CONFLICT,
                )

            try:
                pp_item = (
                    PurchasedPackageItem.objects.select_for_update()
                    .get(
                        purchased_package=pp,
                        service_id=data['service_id'],
                    )
                )
            except PurchasedPackageItem.DoesNotExist:
                return Response(
                    {
                        'service_id': (
                            "This service isn't included in the package."
                        ),
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if pp_item.quantity_remaining < 1:
                return Response(
                    {'detail': 'No credits remaining for this service.'},
                    status=status.HTTP_409_CONFLICT,
                )

            pp_item.quantity_remaining -= 1
            pp_item.save(update_fields=['quantity_remaining'])

            # Create the $0 line on the appointment invoice.
            line = InvoiceLineItem.objects.create(
                invoice=invoice,
                service_id=pp_item.service_id,
                product=None,
                package=None,
                description=f'{pp_item.service_name} (redeemed from package #{pp.pk})',
                quantity=1,
                unit_price_cents=0,
                tax_rate_percent=0,
            )

            # Ledger row.
            PackageRedemption.objects.create(
                tenant=invoice.tenant,
                purchased_package=pp,
                item=pp_item,
                quantity=1,
                invoice_line=line,
                appointment=invoice.appointment,
                by_user=request.user,
                note=data.get('note', ''),
            )

        record(
            action=AuditLog.Action.UPDATE,
            resource_type='invoice',
            resource_id=invoice.pk,
            request=request,
            metadata={
                'event': 'package_redeemed',
                'purchased_package_id': pp.pk,
                'service_id': pp_item.service_id,
                'service_name': pp_item.service_name,
                'remaining_after': pp_item.quantity_remaining,
                'line_id': line.pk,
            },
        )
        invoice.refresh_from_db()
        return Response(self.get_serializer(invoice).data)

    @extend_schema(
        request=RedeemFromMembershipInputSerializer,
        responses={
            200: InvoiceSerializer,
            400: OpenApiResponse(description='Validation error'),
            403: OpenApiResponse(description='Missing PROCESS_PAYMENT permission'),
            409: OpenApiResponse(description='Invoice not OPEN or subscription not redeemable'),
        },
    )
    @action(detail=True, methods=['post'], url_path='redeem-from-membership')
    def redeem_from_membership(self, request, pk=None):
        """Draw down one credit from a customer's Subscription.

        Validates: invoice OPEN, subscription ACTIVE + in-period,
        belongs to this invoice's customer, the requested service
        is in the plan, and there's at least one credit remaining
        for that service. Atomically:

          - Decrements `quantity_remaining` on the matching
            `SubscriptionItem` (with `select_for_update`).
          - Creates a $0 `InvoiceLineItem` with the service set
            and a description tagged with the source subscription.
          - Writes a `SubscriptionRedemption` ledger row pointing
            at both the line and the subscription.

        The line is $0 because the customer already paid for the
        credit when they bought the membership cycle; financial
        reports attribute the revenue to the original sale.
        """
        from django.db import transaction

        from apps.memberships.models import (
            Subscription,
            SubscriptionItem,
            SubscriptionRedemption,
        )

        invoice = self.get_object()
        if invoice.status != Invoice.Status.OPEN:
            return Response(
                {
                    'detail': (
                        f'Cannot redeem against a '
                        f'{invoice.get_status_display().lower()} invoice.'
                    ),
                },
                status=status.HTTP_409_CONFLICT,
            )

        ser = RedeemFromMembershipInputSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        with transaction.atomic():
            try:
                sub = (
                    Subscription.objects.select_for_update()
                    .for_current_tenant()
                    .get(pk=data['subscription_id'])
                )
            except Subscription.DoesNotExist:
                return Response(
                    {'subscription_id': 'Subscription not found.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if sub.customer_id != invoice.customer_id:
                return Response(
                    {
                        'subscription_id': (
                            'Subscription belongs to a different customer.'
                        ),
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if sub.status != Subscription.Status.ACTIVE:
                return Response(
                    {
                        'detail': (
                            f'Subscription is {sub.get_status_display().lower()}, '
                            f'not redeemable.'
                        ),
                    },
                    status=status.HTTP_409_CONFLICT,
                )
            if not sub.is_in_period:
                return Response(
                    {'detail': 'Subscription is outside its current period.'},
                    status=status.HTTP_409_CONFLICT,
                )

            from apps.services.models import Service

            try:
                redeemed_service = (
                    Service.objects.for_current_tenant()
                    .get(pk=data['service_id'])
                )
            except Service.DoesNotExist:
                return Response(
                    {'service_id': 'Service not found.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Find a credit with capacity: a direct service credit
            # first, then a category credit that covers the service.
            sub_item = (
                SubscriptionItem.objects.select_for_update()
                .filter(
                    subscription=sub,
                    service_id=redeemed_service.pk,
                    quantity_remaining__gte=1,
                )
                .first()
            )
            if sub_item is None and redeemed_service.category_id:
                sub_item = (
                    SubscriptionItem.objects.select_for_update()
                    .filter(
                        subscription=sub,
                        category_id=redeemed_service.category_id,
                        quantity_remaining__gte=1,
                    )
                    .first()
                )
            if sub_item is None:
                # Distinguish "not in the plan" from "in the plan but
                # depleted" so the operator gets an accurate message.
                in_plan = (
                    SubscriptionItem.objects.filter(
                        subscription=sub, service_id=redeemed_service.pk,
                    ).exists()
                    or (
                        redeemed_service.category_id is not None
                        and SubscriptionItem.objects.filter(
                            subscription=sub,
                            category_id=redeemed_service.category_id,
                        ).exists()
                    )
                )
                if in_plan:
                    return Response(
                        {'detail': 'No credits remaining for this service.'},
                        status=status.HTTP_409_CONFLICT,
                    )
                return Response(
                    {
                        'service_id': (
                            "This service isn't included in the membership."
                        ),
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            sub_item.quantity_remaining -= 1
            sub_item.save(update_fields=['quantity_remaining'])

            line = InvoiceLineItem.objects.create(
                invoice=invoice,
                service_id=redeemed_service.pk,
                product=None,
                package=None,
                membership_plan=None,
                description=(
                    f'{redeemed_service.name} '
                    f'(redeemed from membership #{sub.pk})'
                ),
                quantity=1,
                unit_price_cents=0,
                tax_rate_percent=0,
            )

            SubscriptionRedemption.objects.create(
                tenant=invoice.tenant,
                subscription=sub,
                item=sub_item,
                quantity=1,
                invoice_line=line,
                appointment=invoice.appointment,
                by_user=request.user,
                note=data.get('note', ''),
            )

        record(
            action=AuditLog.Action.UPDATE,
            resource_type='invoice',
            resource_id=invoice.pk,
            request=request,
            metadata={
                'event': 'membership_redeemed',
                'subscription_id': sub.pk,
                'service_id': redeemed_service.pk,
                'service_name': redeemed_service.name,
                'credit_kind': 'category' if sub_item.category_id else 'service',
                'remaining_after': sub_item.quantity_remaining,
                'line_id': line.pk,
            },
        )
        invoice.refresh_from_db()
        return Response(self.get_serializer(invoice).data)

    # ── Price + discount editing (with manager override) ────────────
    #
    # Owner + manager can edit a line's `unit_price_cents` and set a
    # per-line or invoice-level discount directly (they have the
    # `EDIT_INVOICE_PRICE` permission). Lower roles (front-desk in
    # particular) need to obtain a manager override on the API call by
    # including `authorized_by_email` + `authorized_by_password` in the
    # payload — verified against the tenant's owner / manager roster.
    # Every change is audit-logged with before + after values, the
    # acting user, the authorizing manager (if override), and an
    # optional `reason` so financial review can answer "why was this
    # $20 taken off?" — SOC 2 PI1.1 + HIPAA §164.312(b).

    @staticmethod
    def _verify_price_authorization(request, invoice):
        """Return (acting_user, authorizer_or_none) when the request is
        authorized to edit prices/discounts on `invoice`, else raise
        a 403-equivalent ValidationError.

        Three paths:
          1. Acting user already has EDIT_INVOICE_PRICE → no override
             needed; authorizer is None.
          2. Override creds provided + valid against an owner/manager
             on this tenant → authorizer is that user.
          3. Anything else → 403.
        """
        from apps.tenants.permissions import P
        from apps.tenants.models import TenantMembership

        membership = getattr(request, 'tenant_membership', None)
        acting = request.user
        if membership and membership.has(P.EDIT_INVOICE_PRICE):
            return acting, None

        email = (request.data.get('authorized_by_email') or '').strip().lower()
        password = request.data.get('authorized_by_password') or ''
        if not email or not password:
            raise ValidationError({
                'authorized_by_email': (
                    'A manager or owner must authorize this change. '
                    'Re-submit with `authorized_by_email` and '
                    '`authorized_by_password`.'
                ),
            })
        # Match against an active owner/manager TenantMembership on the
        # CURRENT tenant — credentials from a manager at another tenant
        # don't carry over. iexact on the email mirrors how login works.
        candidates = TenantMembership.objects.filter(
            tenant_id=invoice.tenant_id,
            role__in=[
                TenantMembership.Role.OWNER,
                TenantMembership.Role.MANAGER,
            ],
            is_active=True,
            user__email__iexact=email,
        ).select_related('user')
        for cand in candidates:
            if cand.user.check_password(password):
                return acting, cand.user
        raise ValidationError({
            'authorized_by_email': (
                'No active owner or manager on this tenant matches the '
                'provided credentials.'
            ),
        })

    @extend_schema(
        responses={
            200: InvoiceSerializer,
            400: OpenApiResponse(description='Validation error / bad override creds'),
            403: OpenApiResponse(description='Missing PROCESS_PAYMENT permission'),
            404: OpenApiResponse(description='Line not on this invoice'),
            409: OpenApiResponse(description='Invoice not OPEN'),
        },
    )
    @action(
        detail=True,
        methods=['patch'],
        # Distinct sub-path so it doesn't collide with the existing
        # DELETE `lines/{pk}/` handler (router-level URL resolution
        # ignores HTTP method when picking a pattern, so two @actions
        # at the same path are a foot-gun).
        url_path=r'lines/(?P<line_pk>[^/.]+)/edit',
        url_name='edit-line',
    )
    def edit_line(self, request, pk=None, line_pk=None):
        """Edit `unit_price_cents` and/or the per-line discount on a
        single OPEN invoice line. Body fields (all optional, only
        provided ones are changed):

          - `unit_price_cents`  (int, ≥ 0)
          - `discount_kind`     ('amount' | 'percent')
          - `discount_input`    (decimal — dollars off OR percent off)
          - `discount_reason`   (string, ≤ 200 chars)
          - `authorized_by_email` + `authorized_by_password`
            (required when the caller lacks `EDIT_INVOICE_PRICE`)

        Returns the updated invoice payload. Recalculates the invoice
        header totals (subtotal, line_discounts_total, invoice_discount
        share distribution, tax, total) in the same transaction.
        """
        from decimal import Decimal, InvalidOperation

        from django.db import transaction

        invoice = self.get_object()
        if invoice.status != Invoice.Status.OPEN:
            return Response(
                {
                    'detail': (
                        f'Cannot edit a line on a '
                        f'{invoice.get_status_display().lower()} invoice.'
                    ),
                },
                status=status.HTTP_409_CONFLICT,
            )
        try:
            line = invoice.line_items.get(pk=line_pk)
        except InvoiceLineItem.DoesNotExist:
            return Response(
                {'detail': 'Line not found on this invoice.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        acting, authorizer = self._verify_price_authorization(request, invoice)

        data = request.data
        before = {
            'unit_price_cents': line.unit_price_cents,
            'discount_kind': line.discount_kind,
            'discount_input': str(line.discount_input),
            'discount_cents': line.discount_cents,
            'discount_reason': line.discount_reason,
        }

        changes: dict = {}
        if 'unit_price_cents' in data:
            try:
                new_price = int(data['unit_price_cents'])
            except (TypeError, ValueError):
                raise ValidationError({
                    'unit_price_cents': 'Must be a whole number of cents.',
                })
            if new_price < 0:
                raise ValidationError({
                    'unit_price_cents': 'Cannot be negative.',
                })
            line.unit_price_cents = new_price
            changes['unit_price_cents'] = new_price

        # Discount fields move together. Accepting just `discount_input`
        # without `discount_kind` keeps the current kind; accepting
        # `discount_kind` alone is a kind-switch with the existing
        # input. Clearing requires explicit `discount_input=0`.
        if 'discount_kind' in data:
            kind = data['discount_kind']
            valid_kinds = [k for k, _ in InvoiceLineItem.LineDiscountKind.choices]
            if kind not in valid_kinds:
                raise ValidationError({
                    'discount_kind': f"Must be one of {valid_kinds}.",
                })
            line.discount_kind = kind
            changes['discount_kind'] = kind
        if 'discount_input' in data:
            try:
                line.discount_input = Decimal(str(data['discount_input']))
            except (InvalidOperation, TypeError, ValueError):
                raise ValidationError({
                    'discount_input': 'Must be a number.',
                })
            if line.discount_input < 0:
                raise ValidationError({
                    'discount_input': 'Cannot be negative.',
                })
            changes['discount_input'] = str(line.discount_input)
        if 'discount_reason' in data:
            line.discount_reason = (data['discount_reason'] or '').strip()[:200]
            changes['discount_reason'] = line.discount_reason

        with transaction.atomic():
            line.save()
            # line.save() already calls invoice.recalculate_totals().
            invoice.refresh_from_db()

        after = {
            'unit_price_cents': line.unit_price_cents,
            'discount_kind': line.discount_kind,
            'discount_input': str(line.discount_input),
            'discount_cents': line.discount_cents,
            'discount_reason': line.discount_reason,
        }
        record(
            action=AuditLog.Action.UPDATE,
            resource_type='invoice',
            resource_id=invoice.pk,
            request=request,
            metadata={
                'event': 'line_edited',
                'line_id': line.pk,
                'fields_changed': sorted(changes.keys()),
                'before': before,
                'after': after,
                'authorized_by_email': authorizer.email if authorizer else None,
                'reason': line.discount_reason or None,
            },
        )
        return Response(self.get_serializer(invoice).data)

    @extend_schema(
        responses={
            200: InvoiceSerializer,
            400: OpenApiResponse(description='Validation error / bad override creds'),
            403: OpenApiResponse(description='Missing PROCESS_PAYMENT permission'),
            409: OpenApiResponse(description='Invoice not OPEN'),
        },
    )
    @action(
        detail=True,
        methods=['patch'],
        url_path='discount',
        url_name='set-discount',
    )
    def set_discount(self, request, pk=None):
        """Set / change / clear the invoice-level discount (distributed
        pro-rata across lines by `recalculate_totals`). Body:

          - `invoice_discount_kind`  ('amount' | 'percent')
          - `invoice_discount_input` (decimal — dollars off OR % off)
          - `invoice_discount_reason` (string, ≤ 200 chars)
          - `authorized_by_email` + `authorized_by_password`
            (required when the caller lacks `EDIT_INVOICE_PRICE`)

        Pass `invoice_discount_input=0` to clear an existing discount.
        """
        from decimal import Decimal, InvalidOperation

        from django.db import transaction

        invoice = self.get_object()
        if invoice.status != Invoice.Status.OPEN:
            return Response(
                {
                    'detail': (
                        f'Cannot change the discount on a '
                        f'{invoice.get_status_display().lower()} invoice.'
                    ),
                },
                status=status.HTTP_409_CONFLICT,
            )

        acting, authorizer = self._verify_price_authorization(request, invoice)

        data = request.data
        before = {
            'invoice_discount_kind': invoice.invoice_discount_kind,
            'invoice_discount_input': str(invoice.invoice_discount_input),
            'invoice_discount_cents': invoice.invoice_discount_cents,
            'invoice_discount_reason': invoice.invoice_discount_reason,
        }

        changes: dict = {}
        if 'invoice_discount_kind' in data:
            kind = data['invoice_discount_kind']
            valid = [k for k, _ in Invoice.InvoiceDiscountKind.choices]
            if kind not in valid:
                raise ValidationError({
                    'invoice_discount_kind': f'Must be one of {valid}.',
                })
            invoice.invoice_discount_kind = kind
            changes['invoice_discount_kind'] = kind
        if 'invoice_discount_input' in data:
            try:
                invoice.invoice_discount_input = Decimal(str(data['invoice_discount_input']))
            except (InvalidOperation, TypeError, ValueError):
                raise ValidationError({
                    'invoice_discount_input': 'Must be a number.',
                })
            if invoice.invoice_discount_input < 0:
                raise ValidationError({
                    'invoice_discount_input': 'Cannot be negative.',
                })
            changes['invoice_discount_input'] = str(invoice.invoice_discount_input)
        if 'invoice_discount_reason' in data:
            invoice.invoice_discount_reason = (
                data['invoice_discount_reason'] or ''
            ).strip()[:200]
            changes['invoice_discount_reason'] = invoice.invoice_discount_reason

        with transaction.atomic():
            # We only need a partial save here — recalculate_totals
            # will overwrite invoice_discount_cents + the rollup fields
            # based on kind + input.
            invoice.save(update_fields=[
                'invoice_discount_kind',
                'invoice_discount_input',
                'invoice_discount_reason',
                'updated_at',
            ])
            invoice.recalculate_totals()
            invoice.refresh_from_db()

        after = {
            'invoice_discount_kind': invoice.invoice_discount_kind,
            'invoice_discount_input': str(invoice.invoice_discount_input),
            'invoice_discount_cents': invoice.invoice_discount_cents,
            'invoice_discount_reason': invoice.invoice_discount_reason,
        }
        record(
            action=AuditLog.Action.UPDATE,
            resource_type='invoice',
            resource_id=invoice.pk,
            request=request,
            metadata={
                'event': 'invoice_discount_changed',
                'fields_changed': sorted(changes.keys()),
                'before': before,
                'after': after,
                'authorized_by_email': authorizer.email if authorizer else None,
                'reason': invoice.invoice_discount_reason or None,
            },
        )
        return Response(self.get_serializer(invoice).data)

    @extend_schema(
        responses={
            200: InvoiceSerializer,
            403: OpenApiResponse(description='Missing PROCESS_PAYMENT permission'),
            404: OpenApiResponse(description='Line not on this invoice'),
            409: OpenApiResponse(description='Invoice not OPEN'),
        },
    )
    @action(
        detail=True,
        methods=['delete'],
        url_path=r'lines/(?P<line_pk>[^/.]+)',
    )
    def remove_line(self, request, pk=None, line_pk=None):
        """Remove a line item from an OPEN invoice.

        Refuses on PAID / VOID. Audit logs the removed line so the
        delete is reconstructable. Used by the POS surface to back
        out a mistakenly-added retail line before payment is taken.
        """
        invoice = self.get_object()
        if invoice.status != Invoice.Status.OPEN:
            return Response(
                {
                    'detail': (
                        f'Cannot remove a line from a '
                        f'{invoice.get_status_display().lower()} invoice.'
                    ),
                },
                status=status.HTTP_409_CONFLICT,
            )
        try:
            line = invoice.line_items.get(pk=line_pk)
        except InvoiceLineItem.DoesNotExist:
            return Response(
                {'detail': 'Line not found on this invoice.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        snapshot = {
            'line_id': line.pk,
            'description': line.description,
            'qty': line.quantity,
            'unit_price_cents': line.unit_price_cents,
            'service_id': line.service_id,
            'product_id': line.product_id,
        }
        line.delete()
        invoice.recalculate_totals()
        record(
            action=AuditLog.Action.UPDATE,
            resource_type='invoice',
            resource_id=invoice.pk,
            request=request,
            metadata={'event': 'line_removed', **snapshot},
        )
        invoice.refresh_from_db()
        return Response(self.get_serializer(invoice).data)

    @extend_schema(
        request=AddCustomPackageInputSerializer,
        responses={
            200: InvoiceSerializer,
            400: OpenApiResponse(description='Validation error'),
            403: OpenApiResponse(description='Missing PROCESS_PAYMENT permission'),
            409: OpenApiResponse(description='Invoice not OPEN'),
        },
    )
    @action(detail=True, methods=['post'], url_path='add-custom-package')
    def add_custom_package(self, request, pk=None):
        """Build a one-off package for this customer + add it to the
        invoice as a single line.

        Same end shape as `add-line` with `package_id`, but the
        bundle is constructed inline rather than referenced from
        the catalog. `source_template` on the resulting
        `PurchasedPackage` is null. Lifecycle is identical:
        PENDING until invoice close, then ACTIVE; redeemable via
        `redeem-from-package`.
        """
        from django.db import transaction

        from apps.packages.models import (
            PurchasedPackage,
            PurchasedPackageItem,
        )
        from apps.services.models import Service

        invoice = self.get_object()
        if invoice.status != Invoice.Status.OPEN:
            return Response(
                {
                    'detail': (
                        f'Cannot add a line to a '
                        f'{invoice.get_status_display().lower()} invoice.'
                    ),
                },
                status=status.HTTP_409_CONFLICT,
            )

        ser = AddCustomPackageInputSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        # Validate every service belongs to this tenant + is active.
        service_ids = [row['service_id'] for row in data['items']]
        services = list(
            Service.objects.for_current_tenant()
            .filter(pk__in=service_ids)
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
                tenant=invoice.tenant,
                customer=invoice.customer,
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

        record(
            action=AuditLog.Action.UPDATE,
            resource_type='invoice',
            resource_id=invoice.pk,
            request=request,
            metadata={
                'event': 'custom_package_line_added',
                'line_id': line.pk,
                'purchased_package_id': purchased.pk,
                'name': data['name'],
                'price_cents': data['price_cents'],
                'item_count': len(data['items']),
            },
        )
        invoice.refresh_from_db()
        return Response(self.get_serializer(invoice).data)

    # ── Gift cards ─────────────────────────────────────────────────────

    @extend_schema(
        request=AddGiftCardSaleInputSerializer,
        responses={
            200: InvoiceSerializer,
            400: OpenApiResponse(description='Validation error'),
            403: OpenApiResponse(description='Missing PROCESS_PAYMENT permission'),
            409: OpenApiResponse(description='Invoice not OPEN'),
        },
    )
    @action(detail=True, methods=['post'], url_path='add-gift-card-sale')
    def add_gift_card_sale(self, request, pk=None):
        """Sell a gift card on this OPEN invoice.

        Creates a positive-priced line for the card's face value
        plus a PENDING `GiftCard` tied 1:1 to the line. On invoice
        close, the card flips ACTIVE and the ISSUE ledger row
        carries the initial balance.

        The line itself is service/product/package/membership all
        null — the existing XOR constraint allows that ad-hoc
        shape. The GiftCard.source_invoice_line OneToOne is the
        canonical link.
        """
        from django.db import transaction

        from apps.customers.models import Customer
        from apps.giftcards.models import GiftCard

        invoice = self.get_object()
        if invoice.status != Invoice.Status.OPEN:
            return Response(
                {
                    'detail': (
                        f'Cannot sell a gift card on a '
                        f'{invoice.get_status_display().lower()} invoice.'
                    ),
                },
                status=status.HTTP_409_CONFLICT,
            )

        ser = AddGiftCardSaleInputSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        recipient_customer = None
        if data.get('recipient_customer_id'):
            try:
                recipient_customer = Customer.objects.for_current_tenant().get(
                    pk=data['recipient_customer_id'],
                )
            except Customer.DoesNotExist:
                return Response(
                    {'recipient_customer_id': 'Customer not found in this tenant.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        # Description for the invoice line — short + recognizable.
        recipient_label = (
            recipient_customer.full_name
            if recipient_customer
            else (data.get('recipient_name') or 'Gift recipient')
        )
        description = f'Gift card · ${data["value_cents"] / 100:.2f} for {recipient_label}'

        with transaction.atomic():
            line = InvoiceLineItem.objects.create(
                invoice=invoice,
                service=None,
                product=None,
                package=None,
                membership_plan=None,
                description=description,
                quantity=1,
                unit_price_cents=data['value_cents'],
                tax_rate_percent=0,
            )
            card = GiftCard.objects.create(
                tenant=invoice.tenant,
                issued_to_customer=recipient_customer,
                issued_to_name=data.get('recipient_name', '').strip()
                    or (recipient_customer.full_name if recipient_customer else ''),
                issued_to_email=data.get('recipient_email', '').strip(),
                purchaser_customer=invoice.customer,
                source_invoice_line=line,
                initial_value_cents=data['value_cents'],
                # Balance starts at 0 in PENDING; ISSUE ledger row at
                # close brings it to the full value. This keeps the
                # invariant `balance == sum(ledger)` clean.
                balance_cents=0,
                status=GiftCard.Status.PENDING,
                expires_at=data.get('expires_at'),
                notes=data.get('notes', ''),
            )

        record(
            action=AuditLog.Action.UPDATE,
            resource_type='invoice',
            resource_id=invoice.pk,
            request=request,
            metadata={
                'event': 'gift_card_sale_added',
                'line_id': line.pk,
                'gift_card_id': card.pk,
                'gift_card_code': card.code,
                'value_cents': card.initial_value_cents,
                'recipient_customer_id': (
                    recipient_customer.pk if recipient_customer else None
                ),
            },
        )
        invoice.refresh_from_db()
        return Response(self.get_serializer(invoice).data)

    @extend_schema(
        request=ApplyGiftCardInputSerializer,
        responses={
            200: InvoiceSerializer,
            400: OpenApiResponse(description='Validation error'),
            403: OpenApiResponse(description='Missing PROCESS_PAYMENT permission'),
            404: OpenApiResponse(description='Code not found'),
            409: OpenApiResponse(description='Invoice not OPEN or card not redeemable'),
        },
    )
    @action(detail=True, methods=['post'], url_path='apply-gift-card')
    def apply_gift_card(self, request, pk=None):
        """Apply some of a gift card's balance toward this invoice.

        Operator types the code the customer presents + the amount
        to apply. Validates: invoice OPEN, card ACTIVE + not
        expired, balance ≥ amount, amount ≤ amount_due. Atomically:

          - Decrements `gift_card.balance_cents`.
          - Writes a REDEEM ledger row tied to this invoice.
          - Bumps `invoice.gift_card_credits_cents`.

        The residual `amount_due_cents` is what `payment_method`
        covers at close. If the customer's gift card covers the
        whole invoice, `amount_due_cents` becomes 0 and close still
        requires a `payment_method` choice — operator picks
        `gift_card` for that case (see PaymentMethod choices).
        """
        from django.db import transaction

        from apps.giftcards.models import GiftCard, GiftCardLedger

        invoice = self.get_object()
        if invoice.status != Invoice.Status.OPEN:
            return Response(
                {
                    'detail': (
                        f'Cannot apply a gift card to a '
                        f'{invoice.get_status_display().lower()} invoice.'
                    ),
                },
                status=status.HTTP_409_CONFLICT,
            )

        ser = ApplyGiftCardInputSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        code = ser.validated_data['code'].strip().upper()
        amount = ser.validated_data['amount_cents']

        with transaction.atomic():
            # Lookup + lock the card.
            try:
                card = (
                    GiftCard.objects.select_for_update()
                    .for_current_tenant()
                    .get(code__iexact=code)
                )
            except GiftCard.DoesNotExist:
                return Response(
                    {'code': 'No gift card with that code in this spa.'},
                    status=status.HTTP_404_NOT_FOUND,
                )
            if card.status != GiftCard.Status.ACTIVE:
                return Response(
                    {
                        'detail': (
                            f'Card is {card.get_status_display().lower()}, '
                            f'not redeemable.'
                        ),
                    },
                    status=status.HTTP_409_CONFLICT,
                )
            if card.is_expired:
                return Response(
                    {'detail': 'Card has expired.'},
                    status=status.HTTP_409_CONFLICT,
                )
            if amount > card.balance_cents:
                return Response(
                    {
                        'detail': (
                            f'Amount exceeds card balance '
                            f'(${card.balance_cents / 100:.2f}).'
                        ),
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            # Don't apply more than what's actually owed — keeps the
            # invoice's amount_due ≥ 0 invariant safe.
            if amount > invoice.amount_due_cents:
                return Response(
                    {
                        'detail': (
                            f'Amount exceeds amount due '
                            f'(${invoice.amount_due_cents / 100:.2f}).'
                        ),
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            card.balance_cents -= amount
            card.save(update_fields=['balance_cents', 'updated_at'])
            ledger = GiftCardLedger.objects.create(
                tenant=invoice.tenant,
                gift_card=card,
                kind=GiftCardLedger.Kind.REDEEM,
                amount_cents=-amount,
                invoice=invoice,
                by_user=request.user,
            )
            invoice.gift_card_credits_cents = (
                invoice.gift_card_credits_cents + amount
            )
            invoice.save(update_fields=[
                'gift_card_credits_cents', 'updated_at',
            ])

        record(
            action=AuditLog.Action.UPDATE,
            resource_type='invoice',
            resource_id=invoice.pk,
            request=request,
            metadata={
                'event': 'gift_card_applied',
                'gift_card_id': card.pk,
                'gift_card_code': card.code,
                'amount_cents': amount,
                'card_balance_after': card.balance_cents,
                'ledger_id': ledger.pk,
            },
        )
        invoice.refresh_from_db()
        return Response(self.get_serializer(invoice).data)

    @extend_schema(
        responses={
            200: InvoiceSerializer,
            403: OpenApiResponse(description='Missing PROCESS_PAYMENT permission'),
            404: OpenApiResponse(description='Ledger entry not on this invoice'),
            409: OpenApiResponse(description='Invoice not OPEN'),
        },
    )
    @action(
        detail=True,
        methods=['delete'],
        url_path=r'gift-card-redemptions/(?P<ledger_pk>[^/.]+)',
    )
    def reverse_gift_card_redemption(self, request, pk=None, ledger_pk=None):
        """Reverse a previously-applied gift card credit.

        Used when the operator misapplied a card or the customer
        wants the credit returned. Atomic: writes a REVERSAL ledger
        row (positive amount), restores `balance_cents`, decrements
        `invoice.gift_card_credits_cents`. The original REDEEM row
        is left in place — the ledger is append-only.
        """
        from django.db import transaction

        from apps.giftcards.models import GiftCard, GiftCardLedger

        invoice = self.get_object()
        if invoice.status != Invoice.Status.OPEN:
            return Response(
                {
                    'detail': (
                        f'Cannot reverse on a '
                        f'{invoice.get_status_display().lower()} invoice.'
                    ),
                },
                status=status.HTTP_409_CONFLICT,
            )
        try:
            ledger = GiftCardLedger.objects.select_for_update().get(
                pk=ledger_pk,
                invoice=invoice,
                kind=GiftCardLedger.Kind.REDEEM,
            )
        except GiftCardLedger.DoesNotExist:
            return Response(
                {'detail': 'Redemption not found on this invoice.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Look at all subsequent ledger rows for this card to make
        # sure we're not reversing a row that's already been
        # reversed (idempotency).
        already_reversed = GiftCardLedger.objects.filter(
            gift_card=ledger.gift_card,
            kind=GiftCardLedger.Kind.REVERSAL,
            note__contains=f'reverses #{ledger.pk}',
        ).exists()
        if already_reversed:
            return Response(
                {'detail': 'Already reversed.'},
                status=status.HTTP_409_CONFLICT,
            )

        amount_to_restore = abs(ledger.amount_cents)
        with transaction.atomic():
            card = (
                GiftCard.objects.select_for_update()
                .get(pk=ledger.gift_card_id)
            )
            card.balance_cents += amount_to_restore
            card.save(update_fields=['balance_cents', 'updated_at'])
            GiftCardLedger.objects.create(
                tenant=invoice.tenant,
                gift_card=card,
                kind=GiftCardLedger.Kind.REVERSAL,
                amount_cents=amount_to_restore,
                invoice=invoice,
                by_user=request.user,
                note=f'reverses #{ledger.pk}',
            )
            invoice.gift_card_credits_cents = max(
                0, invoice.gift_card_credits_cents - amount_to_restore,
            )
            invoice.save(update_fields=[
                'gift_card_credits_cents', 'updated_at',
            ])

        record(
            action=AuditLog.Action.UPDATE,
            resource_type='invoice',
            resource_id=invoice.pk,
            request=request,
            metadata={
                'event': 'gift_card_redemption_reversed',
                'gift_card_id': card.pk,
                'gift_card_code': card.code,
                'reversed_ledger_id': ledger.pk,
                'amount_cents': amount_to_restore,
                'card_balance_after': card.balance_cents,
            },
        )
        invoice.refresh_from_db()
        return Response(self.get_serializer(invoice).data)

    # ── Disallowed mutations explicitly blocked ──────────────────────────

    def create(self, request, *args, **kwargs):  # noqa: ARG002
        raise ValidationError(
            'Direct invoice creation is not supported. Invoices are '
            'created automatically when an appointment is booked, or via '
            'the (future) standalone-invoice endpoint.',
            code='not_allowed',
        )

    def update(self, request, *args, **kwargs):  # noqa: ARG002
        raise ValidationError(
            'Direct invoice updates are not supported. Use the close/'
            'reopen/void action endpoints so the audit trail is consistent.',
            code='not_allowed',
        )

    partial_update = update
