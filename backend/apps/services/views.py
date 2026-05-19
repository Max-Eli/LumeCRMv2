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
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.models import AuditLog
from apps.audit.services import record
from apps.tenants.context import get_current_tenant

from .models import Service, ServiceCategory, ServiceProtocol
from .permissions import ServicePermission
from .serializers import (
    ServiceCategorySerializer,
    ServiceProtocolSerializer,
    ServiceSerializer,
)


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

    # ── Hero photo upload (multipart) ───────────────────────────────
    #
    # Kept on its own endpoint so the main service form stays JSON-
    # only (the React Hook Form on the edit page doesn't have to juggle
    # multipart). POST sets the photo, DELETE clears it.
    #
    # 5 MB cap is enforced in code — Django's request body size limit
    # is set higher globally and we'd rather return a friendly 400 than
    # a 413 from the load balancer. Image-type validation is done by
    # Django's ImageField on .save() (Pillow opens + verifies the file).

    PHOTO_MAX_BYTES = 5 * 1024 * 1024

    @action(
        detail=True,
        methods=['post', 'delete'],
        url_path='photo',
        parser_classes=[MultiPartParser, FormParser],
    )
    def photo(self, request, *args, **kwargs):
        instance: Service = self.get_object()
        if request.method == 'DELETE':
            if instance.hero_photo:
                instance.hero_photo.delete(save=False)
                instance.hero_photo = None
                instance.save(update_fields=['hero_photo', 'updated_at'])
                record(
                    action=AuditLog.Action.UPDATE,
                    resource_type='service',
                    resource_id=instance.id,
                    request=request,
                    metadata={'fields_changed': ['hero_photo'], 'cleared': True},
                )
            return Response(self.get_serializer(instance).data)

        file = request.FILES.get('photo')
        if file is None:
            raise ValidationError({'photo': 'No file uploaded under the `photo` form field.'})
        if file.size > self.PHOTO_MAX_BYTES:
            raise ValidationError({
                'photo': f'Photo must be 5 MB or smaller (uploaded: {file.size // 1024} KB).',
            })

        # Replace existing photo cleanly — old object is deleted from
        # storage so we don't leak files in the bucket.
        if instance.hero_photo:
            instance.hero_photo.delete(save=False)
        instance.hero_photo = file
        try:
            instance.save(update_fields=['hero_photo', 'updated_at'])
        except Exception as exc:
            # Pillow raises on invalid image content during ImageField
            # validation; surface as a 400 instead of a 500.
            raise ValidationError({'photo': f'Could not save photo: {exc}'}) from exc

        record(
            action=AuditLog.Action.UPDATE,
            resource_type='service',
            resource_id=instance.id,
            request=request,
            metadata={'fields_changed': ['hero_photo']},
        )
        return Response(self.get_serializer(instance).data, status=status.HTTP_200_OK)


class ServiceProtocolView(APIView):
    """`/api/services/<service_id>/protocol/` — GET + PUT the
    clinical protocol document for a service.

    Singleton resource per service. The first PUT creates the row
    (we don't require an explicit POST); subsequent PUTs replace
    fields. GET returns a sensible empty-shaped payload when no
    protocol has been authored yet so the UI can render the editor
    with blank sections instead of 404-ing.

    Permissions mirror the catalog `ServicePermission`: read for
    any authenticated tenant member (providers need protocols at
    treatment time), write for `MANAGE_SERVICES`.
    """

    permission_classes = [ServicePermission]

    def _get_service(self, service_id: int) -> Service:
        try:
            return Service.objects.for_current_tenant().get(pk=service_id)
        except Service.DoesNotExist:
            raise PermissionDenied('Service not found in this tenant.')

    def get(self, request, service_id: int):
        service = self._get_service(service_id)
        # Build a non-persistent empty protocol for the response shape
        # when none exists yet — saves the frontend from juggling
        # 404-vs-empty as two distinct render paths.
        protocol = getattr(service, 'protocol', None)
        if protocol is None:
            empty = ServiceProtocol(
                tenant=service.tenant,
                service=service,
            )
            record(
                action=AuditLog.Action.READ,
                resource_type='service_protocol',
                resource_id=service.id,
                request=request,
                metadata={'state': 'empty'},
            )
            return Response(ServiceProtocolSerializer(empty).data)

        record(
            action=AuditLog.Action.READ,
            resource_type='service_protocol',
            resource_id=protocol.id,
            request=request,
        )
        return Response(ServiceProtocolSerializer(protocol).data)

    def put(self, request, service_id: int):
        # Treat PUT as upsert — if a protocol doesn't exist yet, this
        # creates it; if it does, this replaces the writeable fields.
        # PATCH semantics fall through to the same code path (replace
        # only the fields present in the payload).
        service = self._get_service(service_id)
        instance = getattr(service, 'protocol', None)
        was_new = instance is None
        if instance is None:
            instance = ServiceProtocol(tenant=service.tenant, service=service)

        ser = ServiceProtocolSerializer(instance, data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        # Manual save so we can stamp `updated_by` from the request.
        for field in ('pre_treatment', 'intra_treatment', 'post_treatment', 'notes'):
            if field in ser.validated_data:
                setattr(instance, field, ser.validated_data[field])
        instance.updated_by = request.user if request.user.is_authenticated else None
        instance.save()

        record(
            action=AuditLog.Action.CREATE if was_new else AuditLog.Action.UPDATE,
            resource_type='service_protocol',
            resource_id=instance.id,
            request=request,
            metadata={
                'service_id': service.id,
                'fields_changed': sorted(ser.validated_data.keys()),
            },
        )
        return Response(
            ServiceProtocolSerializer(instance).data,
            status=status.HTTP_201_CREATED if was_new else status.HTTP_200_OK,
        )

    # PATCH delegates to PUT — both replace fields present in the
    # body, leaving the rest untouched. Symmetry simplifies the
    # frontend client.
    patch = put
