"""Commissions API.

Endpoints under `/api/`:

    GET    /api/commission-rules/        List
    POST   /api/commission-rules/        Create (Owner / Manager)
    GET    /api/commission-rules/{id}/   Retrieve
    PATCH  /api/commission-rules/{id}/   Update + replace overrides wholesale
    DELETE /api/commission-rules/{id}/   Delete (rule only — entries stay)

    GET    /api/commission-entries/      Filter ?membership=, ?from=, ?to=, ?invoice=
    GET    /api/commission-entries/{id}/ Retrieve
    GET    /api/commission-entries/totals/  Aggregate per membership over a date range

The entry endpoints are read-only. Mutations happen via the
invoice action endpoints (close → accrue, reopen → reverse),
which call the service layer.
"""

from __future__ import annotations

from django.db.models import Q, Sum
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from apps.audit.models import AuditLog
from apps.audit.services import record
from apps.tenants.context import get_current_tenant
from apps.tenants.permissions import P

from .models import CommissionEntry, CommissionRule
from .permissions import CommissionEntryPermission, CommissionRulePermission
from .serializers import CommissionEntrySerializer, CommissionRuleSerializer

from apps.tenants.plan_permissions import PlanFeatureRequired
from apps.tenants.plans import F_COMMISSIONS

# Plan gate: commission tracking is Pro+. Starter tenants get a 402
# with feature='commissions' so the frontend renders the right
# upsell instead of a generic permission-denied.
_COMMISSIONS_GATE = PlanFeatureRequired(F_COMMISSIONS)


class CommissionRuleViewSet(viewsets.ModelViewSet):
    """CRUD on per-staff commission rules.

    Setup happens once or rarely: typical pattern is owner creates
    a rule per provider when they're hired, plus per-category
    overrides for high-margin services. Rate changes touch this
    endpoint; existing accruals are unaffected (snapshot is on the
    entry).
    """

    serializer_class = CommissionRuleSerializer
    permission_classes = [CommissionRulePermission, _COMMISSIONS_GATE]
    http_method_names = ['get', 'post', 'patch', 'delete', 'head', 'options']

    def get_queryset(self):
        return (
            CommissionRule.objects
            .for_current_tenant()
            .select_related('membership', 'membership__user')
            .prefetch_related('overrides', 'overrides__category')
        )

    def filter_queryset(self, queryset):
        params = self.request.query_params
        membership = (params.get('membership') or '').strip()
        active = (params.get('active') or '').strip().lower()
        if membership:
            queryset = queryset.filter(membership_id=membership)
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
            resource_type='commission_rule_list',
            request=request,
            metadata={
                'count': len(results) if isinstance(results, list) else None,
            },
        )
        return response

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        record(
            action=AuditLog.Action.READ,
            resource_type='commission_rule',
            resource_id=instance.id,
            request=request,
        )
        return Response(self.get_serializer(instance).data)

    # ── Mutations ───────────────────────────────────────────────────

    def perform_create(self, serializer):
        tenant = get_current_tenant()
        if tenant is None:
            raise PermissionDenied('No tenant context resolved.')
        instance = serializer.save(tenant=tenant)
        record(
            action=AuditLog.Action.CREATE,
            resource_type='commission_rule',
            resource_id=instance.id,
            request=self.request,
            metadata={
                'membership_id': instance.membership_id,
                'base_rate_percent': str(instance.base_rate_percent),
                'override_count': instance.overrides.count(),
            },
        )

    def perform_update(self, serializer):
        instance = serializer.save()
        record(
            action=AuditLog.Action.UPDATE,
            resource_type='commission_rule',
            resource_id=instance.id,
            request=self.request,
            metadata={
                'membership_id': instance.membership_id,
                'fields_changed': sorted(serializer.validated_data.keys()),
            },
        )

    def perform_destroy(self, instance):
        record(
            action=AuditLog.Action.DELETE,
            resource_type='commission_rule',
            resource_id=instance.id,
            request=self.request,
            metadata={
                'membership_id': instance.membership_id,
            },
        )
        instance.delete()


class CommissionEntryViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only ledger.

    Entries get created/reversed by the invoice transition path
    (`Invoice.close()` → accrue, `Invoice.reopen()` → reverse).
    Direct mutations are intentionally not supported.

    Filter scope:
      - Own membership: any tenant member with VIEW_STAFF_PAYROLL_OWN.
      - Other memberships / tenant-wide: requires VIEW_STAFF_REPORTS.

    The view enforces this at the queryset level so list responses
    can't leak.
    """

    serializer_class = CommissionEntrySerializer
    permission_classes = [CommissionEntryPermission, _COMMISSIONS_GATE]

    def get_queryset(self):
        membership = getattr(self.request, 'tenant_membership', None)
        if membership is None and not self.request.user.is_superuser:
            return CommissionEntry.objects.none()

        qs = (
            CommissionEntry.objects
            .for_current_tenant()
            .select_related(
                'membership', 'membership__user',
                'invoice', 'invoice_line', 'by_user',
            )
        )

        if self.request.user.is_superuser:
            return qs

        # Tenant-wide access: VIEW_STAFF_REPORTS.
        if membership.has(P.VIEW_STAFF_REPORTS):
            return qs

        # Else: own membership only.
        return qs.filter(membership=membership)

    def filter_queryset(self, queryset):
        params = self.request.query_params
        membership = (params.get('membership') or '').strip()
        invoice = (params.get('invoice') or '').strip()
        date_from = (params.get('from') or '').strip()
        date_to = (params.get('to') or '').strip()
        kind = (params.get('kind') or '').strip().lower()

        if membership:
            queryset = queryset.filter(membership_id=membership)
        if invoice:
            queryset = queryset.filter(invoice_id=invoice)
        if date_from:
            queryset = queryset.filter(accrued_at__gte=date_from)
        if date_to:
            queryset = queryset.filter(accrued_at__lt=date_to)
        if kind in {'accrual', 'reversal'}:
            queryset = queryset.filter(kind=kind)
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
            resource_type='commission_entry_list',
            request=request,
            metadata={
                'count': len(results) if isinstance(results, list) else None,
                'membership': request.query_params.get('membership', ''),
                'from': request.query_params.get('from', ''),
                'to': request.query_params.get('to', ''),
            },
        )
        return response

    @action(detail=False, methods=['get'], url_path='totals')
    def totals(self, request):
        """Aggregate per membership over a date range.

        Drives the per-staff "you've earned $X this period" tile +
        the manager-side payroll prep view. Returns one row per
        membership with: net amount (sum of signed cents), accrual
        count, reversal count.

        Filter params:
          ?from=ISO ?to=ISO ?membership=<id>
        """
        qs = self.get_queryset()
        # Apply date / membership filters.
        params = request.query_params
        date_from = (params.get('from') or '').strip()
        date_to = (params.get('to') or '').strip()
        membership = (params.get('membership') or '').strip()
        if membership:
            qs = qs.filter(membership_id=membership)
        if date_from:
            qs = qs.filter(accrued_at__gte=date_from)
        if date_to:
            qs = qs.filter(accrued_at__lt=date_to)

        rows = (
            qs
            .values(
                'membership_id',
                'membership__user__first_name',
                'membership__user__last_name',
                'membership__user__email',
                'membership__role',
            )
            .annotate(
                net_cents=Sum('amount_cents'),
                accrual_count=Sum(
                    'amount_cents',
                    filter=Q(kind=CommissionEntry.Kind.ACCRUAL),
                ),
                reversal_count=Sum(
                    'amount_cents',
                    filter=Q(kind=CommissionEntry.Kind.REVERSAL),
                ),
            )
            .order_by('membership__user__last_name', 'membership__user__first_name')
        )

        out = [
            {
                'membership_id': row['membership_id'],
                'first_name': row['membership__user__first_name'],
                'last_name': row['membership__user__last_name'],
                'email': row['membership__user__email'],
                'role': row['membership__role'],
                'net_cents': int(row['net_cents'] or 0),
                # The accrual_count / reversal_count above are
                # actually sums; rename for clarity.
                'accrual_total_cents': int(row['accrual_count'] or 0),
                'reversal_total_cents': int(row['reversal_count'] or 0),
            }
            for row in rows
        ]

        record(
            action=AuditLog.Action.READ,
            resource_type='commission_totals',
            request=request,
            metadata={
                'membership_count': len(out),
                'from': date_from,
                'to': date_to,
            },
        )
        return Response(out)
