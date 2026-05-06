"""Service catalog API.

Endpoints under `/api/services/`:

    GET    /api/services/         List (search via ?q=, filter via ?category= / ?active=)
    POST   /api/services/         Create
    GET    /api/services/{id}/    Retrieve
    PATCH  /api/services/{id}/    Partial update
    PUT    /api/services/{id}/    Update
    DELETE /api/services/{id}/    Delete

Tenant scoping is automatic via `Service.objects.for_current_tenant()`.
Audit logging on every mutation, plus a single `read service_list` entry per
list call (not per individual service in the result, which would flood the log).
"""

from django.db.models import Q
from rest_framework import viewsets
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from apps.audit.models import AuditLog
from apps.audit.services import record
from apps.tenants.context import get_current_tenant

from .models import Service, ServiceCategory
from .permissions import ServicePermission
from .serializers import ServiceCategorySerializer, ServiceSerializer


class ServiceCategoryViewSet(viewsets.ModelViewSet):
    """CRUD for service categories. Read for any authenticated tenant member,
    write for users with `MANAGE_SERVICES`."""

    serializer_class = ServiceCategorySerializer
    permission_classes = [ServicePermission]

    def get_queryset(self):
        return ServiceCategory.objects.for_current_tenant()

    def perform_create(self, serializer):
        tenant = get_current_tenant()
        if tenant is None:
            raise PermissionDenied('No tenant context resolved for this request.')
        serializer.save(tenant=tenant)


class ServiceViewSet(viewsets.ModelViewSet):
    """CRUD endpoints for the service catalog, scoped to the current tenant."""

    serializer_class = ServiceSerializer
    permission_classes = [ServicePermission]

    def get_queryset(self):
        return Service.objects.for_current_tenant().select_related('category')

    def filter_queryset(self, queryset):
        params = self.request.query_params
        q = (params.get('q') or '').strip()
        category = (params.get('category') or '').strip()
        active = (params.get('active') or '').strip().lower()

        if q:
            queryset = queryset.filter(
                Q(name__icontains=q) | Q(description__icontains=q),
            )
        if category:
            queryset = queryset.filter(category_id=category)
        if active in {'true', '1'}:
            queryset = queryset.filter(is_active=True)
        elif active in {'false', '0'}:
            queryset = queryset.filter(is_active=False)
        return queryset

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        results = response.data.get('results', response.data) if isinstance(response.data, dict) else response.data
        record(
            action=AuditLog.Action.READ,
            resource_type='service_list',
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
            resource_type='service',
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
            resource_type='service',
            resource_id=instance.id,
            request=self.request,
        )

    def perform_update(self, serializer):
        instance = serializer.save()
        record(
            action=AuditLog.Action.UPDATE,
            resource_type='service',
            resource_id=instance.id,
            request=self.request,
            metadata={'fields_changed': sorted(serializer.validated_data.keys())},
        )

    def perform_destroy(self, instance):
        record(
            action=AuditLog.Action.DELETE,
            resource_type='service',
            resource_id=instance.id,
            request=self.request,
            metadata={'name': instance.name},
        )
        instance.delete()
