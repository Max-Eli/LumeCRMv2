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


# ── Cross-tenant audit log search (Platform Logs page) ───────────────────


class PlatformAuditLogPagination:
    """Cursor pagination over `-timestamp, -id`.

    Audit log can grow to millions of rows; offset pagination on a
    table this hot becomes catastrophic. Cursors keep page-N queries
    cheap regardless of N. Standard pattern: encode the (timestamp, id)
    of the last seen row, filter the next query with `(timestamp, id) <
    cursor`.

    Implemented inline (not DRF's CursorPagination) so we can return
    extra metadata in the response shape — total-on-page count for
    the operator UI — without subclassing fights.
    """

    DEFAULT_LIMIT = 50
    MAX_LIMIT = 200

    def __init__(self, request):
        try:
            self.limit = min(
                int(request.query_params.get('limit', self.DEFAULT_LIMIT)),
                self.MAX_LIMIT,
            )
        except (TypeError, ValueError):
            self.limit = self.DEFAULT_LIMIT
        if self.limit < 1:
            self.limit = self.DEFAULT_LIMIT

        self.cursor_raw = request.query_params.get('cursor', '')

    def paginate(self, queryset):
        """Apply cursor filter, slice limit+1, return (page, next_cursor)."""
        if self.cursor_raw:
            cursor = _parse_cursor(self.cursor_raw)
            if cursor is not None:
                ts, last_id = cursor
                queryset = queryset.filter(
                    Q(timestamp__lt=ts)
                    | Q(timestamp=ts, id__lt=last_id),
                )

        # Fetch one extra row to detect if there's a next page.
        rows = list(queryset[: self.limit + 1])
        has_more = len(rows) > self.limit
        page = rows[: self.limit]
        next_cursor = (
            _encode_cursor(page[-1].timestamp, page[-1].id)
            if has_more and page else None
        )
        return page, next_cursor


def _encode_cursor(timestamp, row_id):
    import base64
    raw = f'{timestamp.isoformat()}|{row_id}'
    return base64.urlsafe_b64encode(raw.encode('ascii', errors='ignore')).decode('ascii').rstrip('=')


def _parse_cursor(token: str):
    import base64
    try:
        padding = '=' * (-len(token) % 4)
        decoded = base64.urlsafe_b64decode((token + padding).encode('ascii')).decode('ascii')
        ts_str, id_str = decoded.split('|', 1)
        from datetime import datetime
        from django.utils.timezone import make_aware, is_naive
        ts = datetime.fromisoformat(ts_str)
        if is_naive(ts):
            ts = make_aware(ts)
        return ts, int(id_str)
    except Exception:
        return None


class PlatformAuditLogView(APIView):
    """Cross-tenant audit log search for the platform-admin /logs page.

    Filters (all optional, AND-combined):

      - `q`              — free-text. Matches resource_id, resource_type,
                           user email, tenant slug/name, and event metadata.
      - `tenant`         — comma-separated tenant slugs.
      - `action`         — comma-separated action enum values.
      - `resource_type`  — comma-separated resource types.
      - `from` / `to`    — ISO datetime bounds (inclusive / exclusive).

    Pagination:
      - `limit`          — page size (default 50, max 200).
      - `cursor`         — opaque, returned as `next_cursor` in
                           previous response.

    Response shape:
      {
        "results": [ { ...audit entry... } ],
        "next_cursor": "..."  | null,
      }
    """

    permission_classes = [PlatformPermission]

    def get(self, request):
        qs = (
            AuditLog.objects
            .select_related('tenant', 'user')
            .order_by('-timestamp', '-id')
        )

        q = (request.query_params.get('q') or '').strip()
        if q:
            qs = qs.filter(
                Q(resource_id__icontains=q)
                | Q(resource_type__icontains=q)
                | Q(user__email__icontains=q)
                | Q(tenant__slug__icontains=q)
                | Q(tenant__name__icontains=q)
            )

        tenant_slugs = _split_csv(request.query_params.get('tenant'))
        if tenant_slugs:
            qs = qs.filter(tenant__slug__in=tenant_slugs)

        actions = _split_csv(request.query_params.get('action'))
        if actions:
            qs = qs.filter(action__in=actions)

        resource_types = _split_csv(request.query_params.get('resource_type'))
        if resource_types:
            qs = qs.filter(resource_type__in=resource_types)

        date_from = (request.query_params.get('from') or '').strip()
        if date_from:
            parsed = _parse_iso(date_from)
            if parsed is None:
                raise ValidationError({'from': 'Invalid ISO datetime'})
            qs = qs.filter(timestamp__gte=parsed)

        date_to = (request.query_params.get('to') or '').strip()
        if date_to:
            parsed = _parse_iso(date_to)
            if parsed is None:
                raise ValidationError({'to': 'Invalid ISO datetime'})
            qs = qs.filter(timestamp__lt=parsed)

        paginator = PlatformAuditLogPagination(request)
        page, next_cursor = paginator.paginate(qs)

        return Response({
            'results': [_serialise_audit_entry(entry) for entry in page],
            'next_cursor': next_cursor,
        })


def _split_csv(raw):
    if not raw:
        return []
    return [x.strip() for x in raw.split(',') if x.strip()]


def _parse_iso(s):
    from datetime import datetime
    from django.utils.timezone import make_aware, is_naive
    try:
        d = datetime.fromisoformat(s.replace('Z', '+00:00'))
        if is_naive(d):
            d = make_aware(d)
        return d
    except (TypeError, ValueError):
        return None


def _serialise_audit_entry(entry):
    """Compact JSON shape for the logs page. PII-conscious — we
    intentionally DO include user email + tenant slug because
    platform admins need both to identify the actor + scope. PHI
    inside metadata is already redacted at write time by the
    `apps.audit.services.record()` helper."""
    return {
        'id': entry.id,
        'timestamp': entry.timestamp.isoformat(),
        'action': entry.action,
        'resource_type': entry.resource_type or '',
        'resource_id': entry.resource_id or '',
        'ip_address': entry.ip_address,
        'metadata': entry.metadata or {},
        'tenant': (
            {
                'id': entry.tenant_id,
                'slug': entry.tenant.slug,
                'name': entry.tenant.name,
            }
            if entry.tenant_id and entry.tenant
            else None
        ),
        'user': (
            {
                'id': entry.user_id,
                'email': entry.user.email,
                'full_name': entry.user.get_full_name(),
            }
            if entry.user_id and entry.user
            else None
        ),
    }
