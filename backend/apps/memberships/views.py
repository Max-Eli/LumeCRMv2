"""Memberships API.

Endpoints under `/api/`:

    GET    /api/membership-plans/           List (?q=, ?active=)
    POST   /api/membership-plans/           Create with nested items
    GET    /api/membership-plans/{id}/      Retrieve
    PATCH  /api/membership-plans/{id}/      Update (items list replaces wholesale if provided)
    DELETE /api/membership-plans/{id}/      Delete (rejected if any Subscription references)

    GET    /api/subscriptions/              List (?customer=<id>, ?status=...)
    GET    /api/subscriptions/{id}/         Retrieve
    POST   /api/subscriptions/{id}/cancel/  Cancel (requires reason)

Sale + redemption flow through invoice action endpoints in
`apps.invoices.views` (next step).
"""

from __future__ import annotations

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from apps.audit.models import AuditLog
from apps.audit.services import record
from apps.tenants.context import get_current_tenant

from .models import MembershipPlan, Subscription
from .permissions import MembershipPlanPermission, SubscriptionPermission
from .serializers import (
    CancelSubscriptionInputSerializer,
    MembershipPlanSerializer,
    SubscriptionSerializer,
)


class MembershipPlanViewSet(viewsets.ModelViewSet):
    """CRUD for catalog `MembershipPlan` rows, scoped to the current
    tenant. Items are nested in the same payload, replaced wholesale
    on update — same shape as `PackageViewSet`."""

    serializer_class = MembershipPlanSerializer
    permission_classes = [MembershipPlanPermission]

    def get_queryset(self):
        return (
            MembershipPlan.objects
            .for_current_tenant()
            .prefetch_related('items', 'items__service')
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
            resource_type='membership_plan_list',
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
            resource_type='membership_plan',
            resource_id=instance.id,
            request=request,
        )
        return Response(self.get_serializer(instance).data)

    # ── Mutations ───────────────────────────────────────────────────

    def perform_create(self, serializer):
        tenant = get_current_tenant()
        if tenant is None:
            raise PermissionDenied('No tenant context resolved for this request.')
        instance = serializer.save(tenant=tenant)
        record(
            action=AuditLog.Action.CREATE,
            resource_type='membership_plan',
            resource_id=instance.id,
            request=self.request,
            metadata={
                'name': instance.name,
                'price_cents': instance.price_cents,
                'billing_interval': instance.billing_interval,
                'item_count': instance.items.count(),
            },
        )

    def perform_update(self, serializer):
        instance = serializer.save()
        record(
            action=AuditLog.Action.UPDATE,
            resource_type='membership_plan',
            resource_id=instance.id,
            request=self.request,
            metadata={'fields_changed': sorted(serializer.validated_data.keys())},
        )

    def perform_destroy(self, instance):
        # Refuse if any Subscription references this plan — would
        # orphan customer-facing rows. Operator should set
        # `is_active=False` instead.
        sub_count = instance.subscriptions.count()
        if sub_count > 0:
            raise ValidationError({
                'detail': (
                    f'Cannot delete: {sub_count} customer(s) have purchased '
                    f'this plan. Mark it inactive instead.'
                ),
            })
        record(
            action=AuditLog.Action.DELETE,
            resource_type='membership_plan',
            resource_id=instance.id,
            request=self.request,
            metadata={'name': instance.name, 'sku': instance.sku},
        )
        instance.delete()


class SubscriptionViewSet(viewsets.ReadOnlyModelViewSet):
    """Per-customer subscription read endpoints + cancel action.

    List/retrieve drive the customer profile Memberships tab and
    the invoice page's redemption picker. Cancel is the only
    mutation here — sale + redemption go through invoice actions.

    Filters: `?customer=<id>` (most common), `?status=active` to
    show only redeemable rows.
    """

    serializer_class = SubscriptionSerializer
    permission_classes = [SubscriptionPermission]

    def get_queryset(self):
        return (
            Subscription.objects
            .for_current_tenant()
            .select_related('customer', 'plan', 'cancelled_by')
            .prefetch_related('items', 'redemptions', 'redemptions__by_user')
        )

    def filter_queryset(self, queryset):
        params = self.request.query_params
        customer = (params.get('customer') or '').strip()
        status_filter = (params.get('status') or '').strip().lower()
        if customer:
            queryset = queryset.filter(customer_id=customer)
        if status_filter in {'pending', 'active', 'expired', 'cancelled'}:
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
            resource_type='subscription_list',
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
            resource_type='subscription',
            resource_id=instance.id,
            request=request,
        )
        return Response(self.get_serializer(instance).data)

    @action(detail=True, methods=['post'], url_path='cancel')
    def cancel(self, request, pk=None):
        """Cancel an ACTIVE or PENDING subscription. Refuses on
        already-CANCELLED or EXPIRED rows. Audit-logged with the
        operator-supplied reason; `cancelled_at`, `cancelled_by`,
        and `cancel_reason` are persisted."""
        subscription = self.get_object()
        ser = CancelSubscriptionInputSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        reason = ser.validated_data['reason']

        if subscription.status in (
            Subscription.Status.CANCELLED,
            Subscription.Status.EXPIRED,
        ):
            return Response(
                {
                    'detail': (
                        f'Subscription is {subscription.get_status_display().lower()}; '
                        f'no action.'
                    ),
                },
                status=status.HTTP_409_CONFLICT,
            )

        with transaction.atomic():
            locked = (
                Subscription.objects.select_for_update()
                .get(pk=subscription.pk)
            )
            previous_status = locked.status
            now = timezone.now()
            locked.status = Subscription.Status.CANCELLED
            locked.cancelled_at = now
            locked.cancelled_by = request.user
            locked.cancel_reason = reason
            locked.save(update_fields=[
                'status', 'cancelled_at', 'cancelled_by', 'cancel_reason',
                'updated_at',
            ])

        record(
            action=AuditLog.Action.UPDATE,
            resource_type='subscription',
            resource_id=subscription.pk,
            request=request,
            metadata={
                'event': 'cancelled',
                'from_status': previous_status,
                'reason': reason,
            },
        )
        subscription.refresh_from_db()
        return Response(self.get_serializer(subscription).data)
