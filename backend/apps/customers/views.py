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

from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from apps.audit.models import AuditLog
from apps.audit.services import record
from apps.tenants.context import get_current_tenant
from apps.tenants.permissions import P

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

    @action(
        detail=True,
        methods=['post'],
        url_path='merge-into/(?P<target_pk>[^/.]+)',
    )
    def merge_into(self, request, pk=None, target_pk=None):
        """Merge this social-guest customer INTO an existing real
        customer. ADR 0027 §8b.

        Use case: an inbound IG DM created a placeholder ("Instagram
        visitor 1a2b3c") that the operator later confirms is in fact
        Jane Smith, an existing client. Click "Merge into Jane Smith"
        on the guest row → social messages + instagram_handle move to
        Jane; the guest row is soft-deleted via status=archived.

        Rules:
          - Source MUST be `is_social_guest=True` (we don't auto-merge
            real customers — that's a dedicated dedupe flow).
          - Target MUST be in the same tenant and NOT itself a guest.
          - Caller needs EDIT_CLIENT_RECORD.
          - acquisition_source on the target is preserved if already
            set to something other than MANUAL; otherwise we copy it
            from the guest so reports retain the IG attribution.
        """
        membership = getattr(request, 'tenant_membership', None)
        if not request.user.is_superuser:
            if not membership or not membership.has(P.EDIT_CLIENT_RECORD):
                raise PermissionDenied(
                    'Merging client records requires the EDIT_CLIENT_RECORD permission.'
                )

        source = self.get_object()  # tenant-filtered via get_queryset
        if not source.is_social_guest:
            raise ValidationError({
                'detail': (
                    'Only social-guest customer records can be merged. '
                    'Use the deduplication flow for two real-customer rows.'
                ),
                'code': 'source_not_guest',
            })

        target = get_object_or_404(
            Customer.objects.for_current_tenant(),
            pk=target_pk,
        )
        if target.id == source.id:
            raise ValidationError({
                'detail': 'Cannot merge a record into itself.',
                'code': 'same_customer',
            })
        if target.is_social_guest:
            raise ValidationError({
                'detail': (
                    'Cannot merge into another social-guest record. Pick '
                    'a real customer as the merge target.'
                ),
                'code': 'target_is_guest',
            })

        from apps.integrations.models import SocialThread, SocialMessage

        with transaction.atomic():
            # Move every thread + message to the target customer.
            thread_count = SocialThread.objects.filter(
                tenant=source.tenant, customer=source,
            ).update(customer=target)
            message_count = SocialMessage.objects.filter(
                tenant=source.tenant,
                thread__customer=target,
            ).count()  # post-thread-move count, used for audit only

            # Preserve attribution on the target.
            updates: dict = {}
            if target.acquisition_source == Customer.AcquisitionSource.MANUAL:
                updates['acquisition_source'] = source.acquisition_source
            if not target.instagram_handle and source.instagram_handle:
                updates['instagram_handle'] = source.instagram_handle
            if updates:
                for k, v in updates.items():
                    setattr(target, k, v)
                target.save(update_fields=[*updates.keys(), 'updated_at'])

            # Soft-delete the source guest. We flip to INACTIVE
            # (no ARCHIVED state in v1) and clear `is_social_guest`
            # so neither the directory nor the social inbox shows
            # this placeholder row again.
            source.status = Customer.Status.INACTIVE
            source.is_social_guest = False
            source.save(update_fields=['status', 'is_social_guest', 'updated_at'])

        record(
            action=AuditLog.Action.UPDATE,
            resource_type='customer',
            resource_id=target.id,
            request=request,
            metadata={
                'event': 'social_guest_merged',
                'source_customer_id': source.id,
                'threads_moved': thread_count,
                'messages_attached': message_count,
                'attribution_inherited': bool(updates),
            },
        )

        serializer = self.get_serializer(target)
        return Response(serializer.data, status=status.HTTP_200_OK)
