"""Customer API ViewSet — first PHI-bearing endpoint set.

Endpoints (all under `/api/customers/`):

    GET    /api/customers/         List (search via ?q=, status filter via ?status=)
    POST   /api/customers/         Create
    GET    /api/customers/{id}/    Retrieve
    PATCH  /api/customers/{id}/    Partial update
    PUT    /api/customers/{id}/    Update
    DELETE /api/customers/{id}/    Delete

Every action is audit-logged via `apps.audit.services.record(...)` so HIPAA
audit reports can answer "who looked at / changed customer X." Permission
gating per action is in `permissions.CustomerPermission`.

Tenant scoping is automatic via `Customer.objects.for_current_tenant()` —
the request's tenant comes from `TenantMiddleware`. New rows have their
tenant set from the same source on create.
"""

from django.db.models import Q
from rest_framework import viewsets
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from apps.audit.models import AuditLog
from apps.audit.services import record
from apps.tenants.context import get_current_tenant

from .models import Customer
from .permissions import CustomerPermission
from .serializers import CustomerDetailSerializer, CustomerListSerializer


class CustomerViewSet(viewsets.ModelViewSet):
    """CRUD endpoints for Customer records, scoped to the current tenant."""

    permission_classes = [CustomerPermission]

    def get_queryset(self):
        return (
            Customer.objects
            .for_current_tenant()
            .prefetch_related('tags')
        )

    def get_serializer_class(self):
        if self.action == 'list':
            return CustomerListSerializer
        return CustomerDetailSerializer

    def filter_queryset(self, queryset):
        params = self.request.query_params
        q = (params.get('q') or '').strip()
        status_filter = (params.get('status') or '').strip()

        if q:
            queryset = queryset.filter(
                Q(first_name__icontains=q)
                | Q(last_name__icontains=q)
                | Q(preferred_name__icontains=q)
                | Q(email__icontains=q)
                | Q(phone__icontains=q)
            )
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        return queryset

    # --- audit-logged action overrides -------------------------------------

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        # Lightweight aggregate audit — we don't log every individual ID viewed
        # in a list, but we do record that the user accessed the customer index.
        results = response.data.get('results', response.data) if isinstance(response.data, dict) else response.data
        record(
            action=AuditLog.Action.READ,
            resource_type='customer_list',
            request=request,
            metadata={
                'count': len(results) if isinstance(results, list) else None,
                'q': request.query_params.get('q', ''),
                'status_filter': request.query_params.get('status', ''),
            },
        )
        return response

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        record(
            action=AuditLog.Action.READ,
            resource_type='customer',
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
            resource_type='customer',
            resource_id=instance.id,
            request=self.request,
        )

    def perform_update(self, serializer):
        instance = serializer.save()
        record(
            action=AuditLog.Action.UPDATE,
            resource_type='customer',
            resource_id=instance.id,
            request=self.request,
            metadata={'fields_changed': sorted(serializer.validated_data.keys())},
        )

    def perform_destroy(self, instance):
        record(
            action=AuditLog.Action.DELETE,
            resource_type='customer',
            resource_id=instance.id,
            request=self.request,
            metadata={'last_name': instance.last_name},
        )
        instance.delete()
