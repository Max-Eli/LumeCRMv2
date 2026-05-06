"""Platform admin tenant management endpoints.

URL surface (under `/api/platform/`):

    GET    /tenants/                       List all tenants
    POST   /tenants/                       Create a new tenant + owner
    GET    /tenants/<slug>/                Tenant detail (incl. members)
    PATCH  /tenants/<slug>/                Edit name / branding
    POST   /tenants/<slug>/suspend/        Suspend a tenant (with reason)
    POST   /tenants/<slug>/reactivate/     Move a suspended tenant back to active
    GET    /summary/                       Counts + recent signups for the index dashboard

Every endpoint is gated by `PlatformPermission` (is_superuser only).
Every state-changing action writes an audit log entry with
`resource_type='platform_tenant'` so platform-side activity can be
filtered apart from per-tenant work.

Slug is the primary routing key (not PK) because slugs are stable
URLs the platform operator already memorizes ("acmespa") and the
tenant detail URL doubles as a quick way to verify the right account.
"""

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import ViewSet

from apps.audit.models import AuditLog
from apps.audit.services import record
from apps.tenants.models import Tenant, TenantMembership
from apps.tenants.services import create_tenant_with_defaults

from .permissions import PlatformPermission
from .serializers import (
    CreateTenantInputSerializer,
    PlatformTenantDetailSerializer,
    PlatformTenantListSerializer,
    SuspendTenantInputSerializer,
    UpdateTenantInputSerializer,
)

User = get_user_model()


def _annotate_tenant_queryset(qs):
    """Attach member_count + location_count + owner email to a tenant
    queryset so list responses don't N+1 on those fields.

    Owner email is fetched in a separate prefetch step rather than as
    an annotation because Postgres doesn't support correlated
    subqueries that return a string field cleanly inside Django's
    ORM. The list serializer reads `_owner_email` if present.
    """
    return qs.annotate(
        member_count=Count('memberships', filter=Q(memberships__is_active=True), distinct=True),
        location_count=Count('locations', filter=Q(locations__is_active=True), distinct=True),
    )


def _attach_owner_emails(tenants):
    """Pre-fetch owner emails in one query for a list of tenants."""
    tenant_ids = [t.pk for t in tenants]
    owner_emails: dict[int, str] = {}
    for m in (
        TenantMembership.objects
        .filter(
            tenant_id__in=tenant_ids,
            role=TenantMembership.Role.OWNER,
            is_active=True,
        )
        .select_related('user')
        .order_by('tenant_id', 'created_at')
    ):
        # First active owner per tenant wins. Multiple owners are
        # allowed but the platform list shows the founder.
        owner_emails.setdefault(m.tenant_id, m.user.email)
    for t in tenants:
        t._owner_email = owner_emails.get(t.pk)


# ── Tenants viewset ──────────────────────────────────────────────────────


class PlatformTenantViewSet(ViewSet):
    """Cross-tenant management surface — superuser-only."""

    permission_classes = [PlatformPermission]
    lookup_field = 'slug'
    lookup_value_regex = r'[a-z0-9-]+'

    @extend_schema(responses={200: PlatformTenantListSerializer(many=True)})
    def list(self, request):
        qs = (
            _annotate_tenant_queryset(Tenant.objects.all())
            .order_by('name')
        )
        tenants = list(qs)
        _attach_owner_emails(tenants)
        return Response(PlatformTenantListSerializer(tenants, many=True).data)

    @extend_schema(responses={200: PlatformTenantDetailSerializer})
    def retrieve(self, request, slug=None):
        tenant = get_object_or_404(_annotate_tenant_queryset(Tenant.objects.all()), slug=slug)
        _attach_owner_emails([tenant])
        # Prefetch members for the detail serializer's nested output.
        tenant.memberships_list = list(
            tenant.memberships
            .select_related('user')
            .order_by('-created_at'),
        )
        # Override `memberships` lookup on the serializer source so the
        # nested PlatformTenantMemberSerializer reads the prefetched
        # list rather than re-querying.
        tenant.memberships  # eager load via select_related already
        return Response(PlatformTenantDetailSerializer(tenant).data)

    @extend_schema(
        request=CreateTenantInputSerializer,
        responses={
            201: PlatformTenantDetailSerializer,
            400: OpenApiResponse(description='Validation error (e.g. slug taken).'),
        },
    )
    def create(self, request):
        serializer = CreateTenantInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        with transaction.atomic():
            # Find or create the owner user. New users get a random
            # temp password they'll reset on first login.
            owner_user, owner_was_created, temp_password = self._get_or_create_owner(
                email=data['owner_email'],
                first_name=data.get('owner_first_name', ''),
                last_name=data.get('owner_last_name', ''),
            )

            tenant = create_tenant_with_defaults(
                name=data['name'],
                slug=data['slug'],
                owner_user=owner_user,
                status=data['status'],
            )

            record(
                action=AuditLog.Action.CREATE,
                resource_type='platform_tenant',
                resource_id=tenant.pk,
                request=request,
                metadata={
                    'event': 'tenant_created',
                    'tenant_slug': tenant.slug,
                    'tenant_name': tenant.name,
                    'owner_email_domain': self._email_domain(owner_user.email),
                    'owner_was_new_user': owner_was_created,
                    'initial_status': tenant.status,
                },
            )

        # Hydrate the response with annotations + owner email.
        annotated = _annotate_tenant_queryset(Tenant.objects.filter(pk=tenant.pk)).first()
        _attach_owner_emails([annotated])
        body = PlatformTenantDetailSerializer(annotated).data
        # Surface the temp password ONCE in the response if we
        # provisioned a new user. Operator copies it to the owner
        # over a secure channel; never persisted in any audit log
        # or stored elsewhere.
        if owner_was_created:
            body['owner_temp_password'] = temp_password
        return Response(body, status=status.HTTP_201_CREATED)

    @extend_schema(
        request=UpdateTenantInputSerializer,
        responses={200: PlatformTenantDetailSerializer},
    )
    def partial_update(self, request, slug=None):
        tenant = get_object_or_404(Tenant, slug=slug)
        serializer = UpdateTenantInputSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)

        changes = {}
        for field, value in serializer.validated_data.items():
            old = getattr(tenant, field)
            if old != value:
                changes[field] = {'from': old, 'to': value}
                setattr(tenant, field, value)

        if changes:
            tenant.save(update_fields=list(changes.keys()) + ['updated_at'])
            record(
                action=AuditLog.Action.UPDATE,
                resource_type='platform_tenant',
                resource_id=tenant.pk,
                request=request,
                metadata={
                    'event': 'tenant_updated',
                    'tenant_slug': tenant.slug,
                    'fields_changed': list(changes.keys()),
                },
            )

        return self.retrieve(request, slug=tenant.slug)

    @extend_schema(
        request=SuspendTenantInputSerializer,
        responses={
            200: PlatformTenantDetailSerializer,
            409: OpenApiResponse(description='Tenant is already in the suspended state.'),
        },
    )
    @action(detail=True, methods=['post'], url_path='suspend')
    def suspend(self, request, slug=None):
        tenant = get_object_or_404(Tenant, slug=slug)
        serializer = SuspendTenantInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        if tenant.status == Tenant.Status.SUSPENDED:
            return Response(
                {'detail': 'Tenant is already suspended.'},
                status=status.HTTP_409_CONFLICT,
            )

        previous_status = tenant.status
        tenant.status = Tenant.Status.SUSPENDED
        tenant.save(update_fields=['status', 'updated_at'])

        record(
            action=AuditLog.Action.UPDATE,
            resource_type='platform_tenant',
            resource_id=tenant.pk,
            request=request,
            metadata={
                'event': 'tenant_suspended',
                'tenant_slug': tenant.slug,
                'previous_status': previous_status,
                'reason': serializer.validated_data['reason'],
            },
        )

        return self.retrieve(request, slug=tenant.slug)

    @extend_schema(
        responses={
            200: PlatformTenantDetailSerializer,
            409: OpenApiResponse(description='Tenant is not currently suspended.'),
        },
    )
    @action(detail=True, methods=['post'], url_path='reactivate')
    def reactivate(self, request, slug=None):
        tenant = get_object_or_404(Tenant, slug=slug)
        if tenant.status != Tenant.Status.SUSPENDED:
            return Response(
                {'detail': 'Only suspended tenants can be reactivated.'},
                status=status.HTTP_409_CONFLICT,
            )

        tenant.status = Tenant.Status.ACTIVE
        tenant.save(update_fields=['status', 'updated_at'])

        record(
            action=AuditLog.Action.UPDATE,
            resource_type='platform_tenant',
            resource_id=tenant.pk,
            request=request,
            metadata={
                'event': 'tenant_reactivated',
                'tenant_slug': tenant.slug,
            },
        )

        return self.retrieve(request, slug=tenant.slug)

    # ── Helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _get_or_create_owner(*, email, first_name, last_name):
        """Find an existing user by email or create one with a temp password."""
        import secrets
        existing = User.objects.filter(email__iexact=email).first()
        if existing:
            return existing, False, None
        temp_password = secrets.token_urlsafe(12)
        new_user = User.objects.create_user(
            email=email,
            password=temp_password,
            first_name=first_name,
            last_name=last_name,
        )
        return new_user, True, temp_password

    @staticmethod
    def _email_domain(email):
        return email.split('@', 1)[1].lower() if '@' in email else 'unknown'


# ── Platform summary (index dashboard) ──────────────────────────────────


class PlatformSummaryView(APIView):
    """Index dashboard data — counts + recent signups."""

    permission_classes = [PlatformPermission]

    def get(self, request):
        from datetime import timedelta
        from django.utils import timezone

        # Counts by lifecycle state.
        by_status = dict(
            Tenant.objects
            .values_list('status')
            .annotate(c=Count('id'))
        )

        # Recent signups (last 30 days, most recent first, capped at 8).
        cutoff = timezone.now() - timedelta(days=30)
        recent_qs = (
            _annotate_tenant_queryset(Tenant.objects.filter(created_at__gte=cutoff))
            .order_by('-created_at')[:8]
        )
        recent = list(recent_qs)
        _attach_owner_emails(recent)

        # Recent platform-side activity (last 5 entries from the audit log
        # filtered to platform_tenant resource type).
        recent_audit = list(
            AuditLog.objects
            .filter(resource_type='platform_tenant')
            .select_related('user')
            .order_by('-timestamp')[:8]
        )

        return Response({
            'total_tenants': sum(by_status.values()),
            'by_status': {
                s.value: by_status.get(s.value, 0)
                for s in Tenant.Status
            },
            'recent_signups': PlatformTenantListSerializer(recent, many=True).data,
            'recent_activity': [
                {
                    'timestamp': a.timestamp.isoformat(),
                    'action': a.action,
                    'user_email': a.user.email if a.user else None,
                    'event': (a.metadata or {}).get('event'),
                    'tenant_slug': (a.metadata or {}).get('tenant_slug'),
                }
                for a in recent_audit
            ],
        })
