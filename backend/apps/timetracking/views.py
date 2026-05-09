"""Time tracking API.

Endpoints under `/api/`:

    GET    /api/time-entries/                List (?membership=, ?from=, ?to=, ?open=)
    GET    /api/time-entries/{id}/           Retrieve
    PATCH  /api/time-entries/{id}/           Manager-only correction
    DELETE /api/time-entries/{id}/           Manager-only delete (audit-logged)

    POST   /api/time-entries/clock-in/       Open a shift
    POST   /api/time-entries/clock-out/      Close the open shift
    GET    /api/time-entries/active/         List of currently-open shifts
    GET    /api/time-entries/me/             Current user's open entry (if any)
                                              + most recent N closed entries

For "self," `membership_id` is omitted in the body — the view
resolves the calling user's membership for the current tenant.
For "front-desk punches someone else," `membership_id` is provided
and `MANAGE_STAFF` is required.
"""

from __future__ import annotations

import datetime as dt

from django.db import transaction
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from apps.audit.models import AuditLog
from apps.audit.services import record
from apps.tenants.models import TenantMembership
from apps.tenants.permissions import P

from .models import TimeEntry
from .permissions import TimeEntryPermission
from .serializers import (
    ClockInInputSerializer,
    ClockOutInputSerializer,
    TimeEntryEditInputSerializer,
    TimeEntrySerializer,
)
from .services import TimeTrackingError, clock_in, clock_out


def _resolve_target_membership(
    *, request, raw_membership_id: int | None,
) -> TenantMembership:
    """Resolve which membership the caller is acting on.

    Returns the caller's own membership when `raw_membership_id` is
    omitted. Otherwise verifies the requested membership belongs
    to the current tenant AND the caller has MANAGE_STAFF (you
    can't punch your boss's clock without permission).

    Raises `PermissionDenied` / `ValidationError` on misuse.
    """
    own = getattr(request, 'tenant_membership', None)
    if own is None:
        raise PermissionDenied('No tenant membership for this request.')

    if not raw_membership_id or int(raw_membership_id) == own.pk:
        return own

    # Cross-membership punches require MANAGE_STAFF.
    if not own.has(P.MANAGE_STAFF):
        raise PermissionDenied(
            'Only managers can clock other staff in or out.',
        )
    try:
        target = TenantMembership.objects.get(
            pk=raw_membership_id, tenant=own.tenant,
        )
    except TenantMembership.DoesNotExist as exc:
        raise ValidationError(
            {'membership_id': 'Not a staff member of this tenant.'},
        ) from exc
    return target


class TimeEntryViewSet(viewsets.ModelViewSet):
    """CRUD + clock-in/out actions on time entries."""

    serializer_class = TimeEntrySerializer
    permission_classes = [TimeEntryPermission]
    http_method_names = ['get', 'post', 'patch', 'delete', 'head', 'options']

    def get_queryset(self):
        membership = getattr(self.request, 'tenant_membership', None)
        if membership is None:
            return TimeEntry.objects.none()

        qs = (
            TimeEntry.objects
            .for_current_tenant()
            .select_related(
                'membership', 'membership__user',
                'created_by', 'edited_by',
            )
        )

        # Non-managers see only their own entries — enforced at the
        # queryset level so list endpoints don't leak.
        if not membership.has(P.MANAGE_STAFF) and not (
            self.request.user.is_superuser
        ):
            qs = qs.filter(membership=membership)

        return qs

    def filter_queryset(self, queryset):
        params = self.request.query_params
        membership_id = (params.get('membership') or '').strip()
        date_from = (params.get('from') or '').strip()
        date_to = (params.get('to') or '').strip()
        open_only = (params.get('open') or '').strip().lower()

        if membership_id:
            queryset = queryset.filter(membership_id=membership_id)
        if date_from:
            queryset = queryset.filter(clock_in_at__gte=date_from)
        if date_to:
            queryset = queryset.filter(clock_in_at__lt=date_to)
        if open_only in {'true', '1'}:
            queryset = queryset.filter(clock_out_at__isnull=True)
        elif open_only in {'false', '0'}:
            queryset = queryset.filter(clock_out_at__isnull=False)
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
            resource_type='time_entry_list',
            request=request,
            metadata={
                'count': len(results) if isinstance(results, list) else None,
                'membership': request.query_params.get('membership', ''),
                'open': request.query_params.get('open', ''),
            },
        )
        return response

    # ── Manager edit / delete ───────────────────────────────────────

    def perform_update(self, serializer):
        # Use the strict edit serializer — `serializer` is the
        # default model one, but we re-validate with
        # TimeEntryEditInputSerializer to enforce the cross-field rule.
        edit_ser = TimeEntryEditInputSerializer(data=self.request.data)
        edit_ser.is_valid(raise_exception=True)
        data = edit_ser.validated_data

        instance = self.get_object()
        new_clock_in = data.get('clock_in_at', instance.clock_in_at)
        new_clock_out = (
            data['clock_out_at']
            if 'clock_out_at' in data
            else instance.clock_out_at
        )
        # Validate the resulting state, not just the patch payload —
        # PATCHing only `clock_out_at` could still leave clock_out
        # before the existing clock_in.
        if new_clock_out is not None and new_clock_out <= new_clock_in:
            raise ValidationError({
                'clock_out_at': 'Must be after clock_in_at.',
            })

        if 'clock_in_at' in data:
            instance.clock_in_at = data['clock_in_at']
        if 'clock_out_at' in data:
            instance.clock_out_at = data['clock_out_at']
        if 'notes' in data:
            instance.notes = data['notes']
        instance.edited_at = timezone.now()
        instance.edited_by = self.request.user
        instance.save()

        record(
            action=AuditLog.Action.UPDATE,
            resource_type='time_entry',
            resource_id=instance.id,
            request=self.request,
            metadata={
                'event': 'manager_edit',
                'fields_changed': sorted(data.keys()),
                'membership_id': instance.membership_id,
            },
        )

    def perform_destroy(self, instance):
        record(
            action=AuditLog.Action.DELETE,
            resource_type='time_entry',
            resource_id=instance.id,
            request=self.request,
            metadata={
                'membership_id': instance.membership_id,
                'clock_in_at': instance.clock_in_at.isoformat(),
                'clock_out_at': (
                    instance.clock_out_at.isoformat()
                    if instance.clock_out_at else None
                ),
            },
        )
        instance.delete()

    # ── Clock-in ────────────────────────────────────────────────────

    @action(detail=False, methods=['post'], url_path='clock-in')
    def clock_in_action(self, request):
        """Open a new shift. Refuses if the target membership
        already has an open shift."""
        ser = ClockInInputSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        target = _resolve_target_membership(
            request=request,
            raw_membership_id=data.get('membership_id'),
        )

        own = getattr(request, 'tenant_membership', None)
        is_self = target.pk == (own.pk if own else None)
        # Default source: SELF for own punches, FRONT_DESK when
        # someone else with MANAGE_STAFF is punching for a staff
        # member from a counter device.
        source = data.get('source')
        if source is None or source == TimeEntry.Source.SELF:
            source = (
                TimeEntry.Source.SELF if is_self
                else TimeEntry.Source.FRONT_DESK
            )

        try:
            entry = clock_in(
                membership=target,
                by_user=request.user,
                source=source,
                notes=data.get('notes', ''),
            )
        except TimeTrackingError as exc:
            return Response(
                {'detail': str(exc)},
                status=status.HTTP_409_CONFLICT,
            )

        record(
            action=AuditLog.Action.CREATE,
            resource_type='time_entry',
            resource_id=entry.id,
            request=request,
            metadata={
                'event': 'clock_in',
                'membership_id': target.pk,
                'source': source,
                'self_punch': is_self,
            },
        )
        return Response(
            TimeEntrySerializer(entry).data,
            status=status.HTTP_201_CREATED,
        )

    # ── Clock-out ───────────────────────────────────────────────────

    @action(detail=False, methods=['post'], url_path='clock-out')
    def clock_out_action(self, request):
        """Close the open shift for the target membership. Returns
        409 if there's no open shift."""
        ser = ClockOutInputSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        target = _resolve_target_membership(
            request=request,
            raw_membership_id=data.get('membership_id'),
        )

        try:
            entry = clock_out(
                membership=target,
                by_user=request.user,
                notes_append=data.get('notes', ''),
            )
        except TimeTrackingError as exc:
            return Response(
                {'detail': str(exc)},
                status=status.HTTP_409_CONFLICT,
            )

        own = getattr(request, 'tenant_membership', None)
        record(
            action=AuditLog.Action.UPDATE,
            resource_type='time_entry',
            resource_id=entry.id,
            request=request,
            metadata={
                'event': 'clock_out',
                'membership_id': target.pk,
                'self_punch': target.pk == (own.pk if own else None),
                'duration_seconds': entry.duration_seconds,
            },
        )
        return Response(TimeEntrySerializer(entry).data)

    # ── "Who's clocked in right now" ────────────────────────────────

    @action(detail=False, methods=['get'], url_path='active')
    def active(self, request):
        """List of currently-open shifts in the tenant.

        Open to any tenant member — useful for the front-desk
        "who's working" panel and the upcoming dashboards.
        """
        membership = getattr(request, 'tenant_membership', None)
        if membership is None:
            raise PermissionDenied('No tenant membership.')

        # Override the get_queryset() filter — "active" is allowed
        # for non-managers too because it doesn't expose hours
        # detail (just who's clocked in right now).
        qs = (
            TimeEntry.objects
            .for_current_tenant()
            .select_related('membership', 'membership__user')
            .filter(clock_out_at__isnull=True)
            .order_by('-clock_in_at')
        )
        return Response(TimeEntrySerializer(qs, many=True).data)

    # ── "Me" — own current state + recent shifts ────────────────────

    @action(detail=False, methods=['get'], url_path='me')
    def me(self, request):
        """Current user's open entry (if any) + recent closed shifts.

        Drives the mobile clock-in panel — one round-trip gets
        everything the UI needs to render "Clock in" or "Clock
        out" + recent history.
        """
        membership = getattr(request, 'tenant_membership', None)
        if membership is None:
            return Response(
                {'open_entry': None, 'recent': []},
                status=status.HTTP_200_OK,
            )

        base = TimeEntry.objects.for_current_tenant().filter(
            membership=membership,
        )
        open_entry = base.filter(clock_out_at__isnull=True).first()
        recent = list(
            base.filter(clock_out_at__isnull=False)
            .order_by('-clock_in_at')[:5]
        )

        return Response({
            'open_entry': (
                TimeEntrySerializer(open_entry).data if open_entry else None
            ),
            'recent': TimeEntrySerializer(recent, many=True).data,
        })
