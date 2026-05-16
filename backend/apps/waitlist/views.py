"""Waitlist API.

Two surfaces:

  - **Public** (no auth, mounted under `/api/booking/<slug>/waitlist/`)
    — POST creates an entry from the public booking page when the
    customer hits a fully-booked day. Reuses the booking app's
    tenant resolution + customer matching so a returning customer
    keeps one record.

  - **Internal** (auth required, mounted under `/api/waitlist/`) —
    operator-side list + retrieve + status updates. Gated by tenant
    membership; default-permitted to anyone in the tenant
    (front-desk handles the list, mirrors form-submissions
    posture). Status mutations get audit-logged.

PHI handling mirrors `apps.booking`:
  - Audit log on every operation (public + internal)
  - Public payloads are minimum-necessary (confirmation echoes only
    the data the customer needs to reassure themselves they're on
    the list)
  - Tenant scoping on every FK
"""

from __future__ import annotations

from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status, viewsets
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.models import AuditLog
from apps.audit.services import record
from apps.tenants.api_permissions import IsTenantStaff
from apps.booking.permissions import PublicBookingPermission
from apps.booking.views import (
    PublicBookingViewMixin,
    _eligible_providers,
    _resolve_active_tenant,
)
from apps.services.models import Service
from apps.tenants.models import Location

from apps.customers.models import Customer

from .models import WaitlistEntry
from .serializers import (
    PublicWaitlistConfirmationSerializer,
    PublicWaitlistJoinSerializer,
    WaitlistEntryCreateSerializer,
    WaitlistEntrySerializer,
)
from .services import submit_waitlist_entry

from apps.tenants.context import get_current_tenant


# ── Public submit ────────────────────────────────────────────────────


class PublicWaitlistJoinView(PublicBookingViewMixin, APIView):
    """`POST /api/booking/<slug>/waitlist/` — join the waitlist.

    No auth, no CSRF — same posture as the booking submit endpoint.
    Tenant resolves from the URL slug. Cross-tenant FK references
    (a service from a different tenant) are rejected with 400.
    Dedupe: re-submitting an identical waiting entry returns the
    existing one (no duplicate row).
    """

    @extend_schema(
        request=PublicWaitlistJoinSerializer,
        responses={
            201: PublicWaitlistConfirmationSerializer,
            200: PublicWaitlistConfirmationSerializer,  # dedupe path
            400: OpenApiResponse(description='Invalid input or unavailable resource'),
        },
    )
    def post(self, request, tenant_slug: str):
        tenant = _resolve_active_tenant(tenant_slug)

        ser = PublicWaitlistJoinSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        # Resolve FKs against the URL's tenant.
        try:
            service = Service.objects.get(
                pk=data['service_id'],
                tenant=tenant,
                is_active=True,
                is_bookable_online=True,
                service_type=Service.ServiceType.REGULAR,
            )
        except Service.DoesNotExist:
            return Response(
                {'detail': 'Service is not available for online booking.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            location = Location.objects.get(
                pk=data['location_id'], tenant=tenant, is_active=True,
            )
        except Location.DoesNotExist:
            return Response(
                {'detail': 'Location is not available.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Provider is optional. When provided, we still validate
        # eligibility (same as booking submit) so a malicious payload
        # can't waitlist someone for a provider they're not assigned
        # to or a job-title that can't perform the service.
        provider = None
        provider_id = data.get('provider_id')
        if provider_id:
            eligible = _eligible_providers(
                tenant=tenant, service=service, location=location,
            )
            provider = next((p for p in eligible if p.pk == provider_id), None)
            if provider is None:
                return Response(
                    {'detail': 'That provider cannot perform this service at this location.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        entry, created = submit_waitlist_entry(
            tenant=tenant,
            service=service,
            location=location,
            provider=provider,
            preferred_date=data['preferred_date'],
            customer_first_name=data['customer_first_name'],
            customer_last_name=data['customer_last_name'],
            customer_email=data['customer_email'],
            customer_phone=data['customer_phone'],
            notes=data.get('notes', ''),
        )

        # Only audit-log new creates. A dedupe no-op shouldn't grow
        # the audit log every time the customer hits refresh.
        if created:
            record(
                action=AuditLog.Action.CREATE,
                resource_type='waitlist_entry',
                resource_id=entry.pk,
                tenant=tenant,
                user=None,
                request=request,
                metadata={
                    'event': 'public_waitlist_join',
                    'service_id': service.pk,
                    'location_id': location.pk,
                    'provider_id': provider.pk if provider else None,
                    'customer_id': entry.customer_id,
                    'preferred_date': data['preferred_date'].isoformat(),
                },
            )

        return Response(
            PublicWaitlistConfirmationSerializer(entry).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


# ── Internal CRUD (operator-side) ────────────────────────────────────


class WaitlistEntryViewSet(viewsets.ModelViewSet):
    """`GET / POST / PATCH /api/waitlist/` — operator-side waitlist
    management.

    List: anyone in the tenant. Default scope is `?status=waiting`
    (the inbox view) — pass `?status=` to widen.

    Retrieve: anyone in the tenant. PHI is included in the detail
    payload (phone + email) — front-desk uses these to call the
    customer back. Read writes an audit log entry per HIPAA
    §164.312(b).

    Create: anyone in the tenant can manually waitlist an existing
    customer. Different from the public submit (which matches/creates
    the customer from raw fields) — the staff path expects a
    `customer_id` already in the DB, mirroring how the appointments
    flow works. Entries created here get `source='staff'` so the
    panel can distinguish self-service entries from operator-added
    ones at a glance.

    Update: anyone in the tenant can transition status. Only the
    `status` and `notes` fields are writable. Status transitions
    auto-stamp the corresponding timestamp (contacted_at,
    declined_at, booked_at) for clean audit on the entry itself
    without needing to re-query AuditLog.

    Delete: not exposed. Soft-state via `status='declined'` instead
    — audit trail must survive entry retirement.
    """

    permission_classes = [IsTenantStaff]
    http_method_names = ['get', 'post', 'patch', 'head', 'options']

    def get_serializer_class(self):
        if self.action == 'create':
            return WaitlistEntryCreateSerializer
        return WaitlistEntrySerializer

    def get_queryset(self):
        qs = WaitlistEntry.objects.for_current_tenant().select_related(
            'customer', 'service', 'location', 'provider__user',
        )
        params = self.request.query_params
        status_param = (params.get('status') or '').strip()
        if status_param:
            qs = qs.filter(status=status_param)
        return qs

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        results = response.data.get('results', response.data) if isinstance(response.data, dict) else response.data
        record(
            action=AuditLog.Action.READ,
            resource_type='waitlist_entry_list',
            request=request,
            metadata={
                'count': len(results) if isinstance(results, list) else None,
                'status_filter': request.query_params.get('status', ''),
            },
        )
        return response

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        record(
            action=AuditLog.Action.READ,
            resource_type='waitlist_entry',
            resource_id=instance.pk,
            request=request,
            metadata={
                'customer_id': instance.customer_id,
                'service_id': instance.service_id,
                'status': instance.status,
            },
        )
        return Response(self.get_serializer(instance).data)

    def create(self, request, *args, **kwargs):  # noqa: ARG002
        tenant = get_current_tenant()
        if tenant is None:
            raise PermissionDenied('No tenant context resolved for this request.')

        ser = WaitlistEntryCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        # Customer resolution: existing-by-id, or match-or-create from
        # raw name/email/phone fields. The serializer validated that
        # exactly one path was provided.
        if data.get('customer_id'):
            try:
                customer = Customer.objects.get(pk=data['customer_id'], tenant=tenant)
            except Customer.DoesNotExist:
                raise ValidationError({'customer_id': 'Customer not found.'})
        else:
            # New-customer path. Reuses the same matching the public
            # booking flow uses — a returning client whose email or
            # phone is on file gets re-attached to their existing
            # record (silent match; no welcome-back leak).
            from apps.booking.services import find_or_create_customer
            customer, _ = find_or_create_customer(
                tenant=tenant,
                first_name=data['customer_first_name'],
                last_name=data['customer_last_name'],
                email=data['customer_email'],
                phone=data['customer_phone'],
            )
        try:
            service = Service.objects.get(
                pk=data['service_id'], tenant=tenant,
                is_active=True, service_type=Service.ServiceType.REGULAR,
            )
        except Service.DoesNotExist:
            raise ValidationError({'service_id': 'Service not found or not bookable.'})
        try:
            location = Location.objects.get(
                pk=data['location_id'], tenant=tenant, is_active=True,
            )
        except Location.DoesNotExist:
            raise ValidationError({'location_id': 'Location not found.'})

        provider = None
        provider_id = data.get('provider_id')
        if provider_id:
            # We don't enforce eligibility here as strictly as the
            # public flow — staff sometimes need to waitlist a customer
            # for a specific provider even if eligibility rules would
            # otherwise reject (e.g. the provider is the only one who
            # does this client's particular treatment plan, even though
            # the category's eligibility rules don't list their job
            # title). Just verify the provider belongs to this tenant.
            from apps.tenants.models import TenantMembership
            try:
                provider = TenantMembership.objects.get(pk=provider_id, tenant=tenant)
            except TenantMembership.DoesNotExist:
                raise ValidationError({'provider_id': 'Provider not found.'})

        entry = WaitlistEntry.objects.create(
            tenant=tenant,
            customer=customer,
            service=service,
            location=location,
            provider=provider,
            preferred_date=data['preferred_date'],
            notes=data.get('notes', ''),
            source='staff',
        )

        record(
            action=AuditLog.Action.CREATE,
            resource_type='waitlist_entry',
            resource_id=entry.pk,
            request=request,
            metadata={
                'event': 'staff_waitlist_add',
                'service_id': service.pk,
                'location_id': location.pk,
                'provider_id': provider.pk if provider else None,
                'customer_id': customer.pk,
                'preferred_date': data['preferred_date'].isoformat(),
            },
        )

        return Response(
            WaitlistEntrySerializer(entry).data,
            status=status.HTTP_201_CREATED,
        )

    def update(self, request, *args, **kwargs):
        # PATCH-only (we restrict http_method_names) — reject anything
        # but `status` and `notes` so callers can't mutate the record
        # of WHAT the customer asked for.
        ALLOWED = {'status', 'notes'}
        invalid = set(request.data.keys()) - ALLOWED
        if invalid:
            raise ValidationError({
                k: 'This field is not editable.' for k in invalid
            })

        instance = self.get_object()
        old_status = instance.status
        new_status = request.data.get('status', old_status)

        # Validate status value
        valid_statuses = {s.value for s in WaitlistEntry.Status}
        if new_status not in valid_statuses:
            raise ValidationError({'status': f'Invalid status. Must be one of {sorted(valid_statuses)}.'})

        # Apply update + auto-stamp timestamp on transition.
        if 'notes' in request.data:
            instance.notes = request.data['notes']
        if new_status != old_status:
            instance.status = new_status
            now = timezone.now()
            if new_status == WaitlistEntry.Status.CONTACTED:
                instance.contacted_at = now
            elif new_status == WaitlistEntry.Status.DECLINED:
                instance.declined_at = now
            elif new_status == WaitlistEntry.Status.BOOKED:
                instance.booked_at = now
        instance.save()

        record(
            action=AuditLog.Action.UPDATE,
            resource_type='waitlist_entry',
            resource_id=instance.pk,
            request=request,
            metadata={
                'from_status': old_status,
                'to_status': new_status,
                'notes_changed': 'notes' in request.data,
            },
        )
        return Response(self.get_serializer(instance).data)
