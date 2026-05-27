"""Appointments API.

Endpoints under `/api/appointments/`:

    GET    /api/appointments/         List (filters: ?date=, ?provider=, ?status=)
    POST   /api/appointments/         Create
    GET    /api/appointments/{id}/    Retrieve
    PATCH  /api/appointments/{id}/    Partial update — reschedule / change status
    PUT    /api/appointments/{id}/    Update
    DELETE /api/appointments/{id}/    Delete (soft-delete via status=cancelled is preferred)

The `?date=YYYY-MM-DD` filter returns appointments that overlap with that day
**in the active location's timezone** — used by the day view. `?start=...&end=...`
accepts ISO-8601 datetimes and returns appointments overlapping the window.

Why location-scoped timezone (and not tenant-wide): a multi-location business
can span timezones (NY + LA), so "today's appointments" is per-site. The active
location is resolved by `LocationMiddleware` from the cookie / tenant default;
when no location is set we fall back to the tenant timezone, then UTC, so
non-tenant requests don't error.

Audit logging on every action; tenant scoping via `for_current_tenant()`.
Tenant + service price are snapshotted at create time so future price changes
don't retroactively alter quoted appointments.
"""

import datetime as dt
from zoneinfo import ZoneInfo

from django.db.models import Max
from django.utils import timezone as djtz
from django.utils.dateparse import parse_date, parse_datetime
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from apps.audit.models import AuditLog
from apps.audit.services import record
from apps.tenants.context import get_current_location, get_current_tenant

from .models import Appointment, AppointmentService, TimeBlock
from .permissions import AppointmentPermission, TimeBlockPermission
from .serializers import AppointmentSerializer, TimeBlockSerializer


class AppointmentViewSet(viewsets.ModelViewSet):
    """CRUD for appointments, scoped to the current tenant."""

    serializer_class = AppointmentSerializer
    permission_classes = [AppointmentPermission]

    def get_queryset(self):
        # Per-location scoping: when LocationMiddleware has resolved an
        # active location for the request (the normal case for any
        # authenticated tenant request — middleware falls back to the
        # tenant default), narrow the queryset to that site. Without
        # this the calendar at Brooklyn would show Manhattan's
        # appointments. Falls back to no extra filter when location
        # is None (non-tenant context — tests, scripts, edge cases)
        # so the existing tenant scoping isn't accidentally widened.
        qs = (
            Appointment.objects
            .for_current_tenant()
            .select_related(
                'customer',
                'service', 'service__category',
                'provider', 'provider__user', 'provider__job_title',
                'location',
                # Reverse OneToOne to Invoice. The AppointmentSerializer
                # exposes invoice_status off this so each calendar block
                # can render a paid / open / void pill without N+1 fetch.
                'invoice',
            )
            # Additional services on the appointment — the serializer
            # nests these; prefetch so the calendar list stays one query.
            .prefetch_related('extra_services__service__category')
        )
        location = get_current_location()
        if location is not None:
            qs = qs.filter(location=location)
        return qs

    def filter_queryset(self, queryset):
        params = self.request.query_params
        date_param = (params.get('date') or '').strip()
        start_param = (params.get('start') or '').strip()
        end_param = (params.get('end') or '').strip()
        provider_param = (params.get('provider') or '').strip()
        status_param = (params.get('status') or '').strip()
        customer_param = (params.get('customer') or '').strip()
        source_param = (params.get('source') or '').strip()

        # ?date=YYYY-MM-DD — interpreted in the tenant's timezone, returns the
        # full local-day window converted back to UTC for the query.
        if date_param:
            d = parse_date(date_param)
            if d is None:
                raise ValidationError({'date': 'Invalid date — use YYYY-MM-DD.'})
            # Day-window timezone comes from the active location.
            # `LocationMiddleware` always resolves one for any tenant
            # request (cookie → tenant default), so the only realistic
            # path to None is a non-tenant context (script / test that
            # forgot the X-Tenant-Slug header). Fall back to UTC there
            # rather than 500-ing.
            location = get_current_location()
            tz_name = location.timezone if location is not None and location.timezone else 'UTC'
            try:
                tz = ZoneInfo(tz_name)
            except Exception:  # noqa: BLE001
                tz = ZoneInfo('UTC')
            start = dt.datetime.combine(d, dt.time.min, tzinfo=tz)
            end = start + dt.timedelta(days=1)
            queryset = queryset.filter(start_time__lt=end, end_time__gt=start)
        else:
            if start_param:
                s = parse_datetime(start_param)
                if not s:
                    raise ValidationError({'start': 'Invalid datetime — use ISO-8601.'})
                queryset = queryset.filter(end_time__gt=s)
            if end_param:
                e = parse_datetime(end_param)
                if not e:
                    raise ValidationError({'end': 'Invalid datetime — use ISO-8601.'})
                queryset = queryset.filter(start_time__lt=e)

        if provider_param:
            queryset = queryset.filter(provider_id=provider_param)
        if status_param:
            queryset = queryset.filter(status=status_param)
        if customer_param:
            queryset = queryset.filter(customer_id=customer_param)
        if source_param:
            queryset = queryset.filter(source=source_param)
        return queryset

    # ── audit-logged action overrides ─────────────────────────────────────

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        results = response.data.get('results', response.data) if isinstance(response.data, dict) else response.data
        record(
            action=AuditLog.Action.READ,
            resource_type='appointment_list',
            request=request,
            metadata={
                'count': len(results) if isinstance(results, list) else None,
                'date': request.query_params.get('date', ''),
                'provider': request.query_params.get('provider', ''),
            },
        )
        return response

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        record(
            action=AuditLog.Action.READ,
            resource_type='appointment',
            resource_id=instance.id,
            request=request,
        )
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    def perform_create(self, serializer):
        from django.db import transaction

        tenant = get_current_tenant()
        if tenant is None:
            raise PermissionDenied('No tenant context resolved for this request.')

        provider = serializer.validated_data.get('provider')
        if provider is not None and not provider.is_bookable:
            raise ValidationError({
                'provider_id': 'This staff member is not bookable.',
            })

        # Pop the create-only extras before save() so the validated_data
        # passed into the model layer stays clean (the model has no such
        # field). The serializer's validate() already verified each
        # service is tenant-scoped + active, validated each provider
        # override is bookable + assigned to the location, and stashed
        # the resolved (service, provider_or_None) tuples under
        # `_resolved_extras`.
        extras = serializer.validated_data.pop('_resolved_extras', [])
        serializer.validated_data.pop('extras', None)

        # Default `location` from the active location when the caller
        # didn't supply one. The serializer field is optional + defaulted
        # here so the FE doesn't have to think about it: every booking
        # is implicitly at the location the operator is currently
        # viewing. The serializer's `validate()` already enforced that
        # any explicit location_id belongs to this tenant + that the
        # provider is assigned there, so by this point either path is
        # safe to persist.
        save_kwargs: dict = {
            'tenant': tenant,
            'quoted_price_cents': service.price_cents if (service := serializer.validated_data.get('service')) else 0,
            'created_by': self.request.user if self.request.user.is_authenticated else None,
        }
        if 'location' not in serializer.validated_data:
            active_location = get_current_location()
            if active_location is None:
                raise ValidationError({
                    'location_id': (
                        'No active location resolved for this request and none '
                        'supplied in the payload. Pass `location_id` explicitly '
                        'or set the active-location cookie.'
                    ),
                })
            save_kwargs['location'] = active_location

        # Wrap the appointment save + extras attachment so a failure on
        # either side rolls everything back — the alternative would
        # orphan an appointment with a partial invoice.
        with transaction.atomic():
            instance = serializer.save(**save_kwargs)
            if extras:
                invoice = getattr(instance, 'invoice', None)
                for i, (extra_service, extra_provider) in enumerate(
                    extras, start=1,
                ):
                    self._attach_extra_service(
                        instance, extra_service, invoice, i,
                        provider=extra_provider,
                    )

        # Auto-assign forms (intake on first ever appointment + consent
        # per service mapping). Service is in `apps.forms` to keep the
        # rules co-located with the FormSubmission model — see ADR 0011.
        # Imported lazily to avoid a top-level circular import between
        # the apps.
        from apps.forms.services import assign_forms_for_appointment
        created_submissions = assign_forms_for_appointment(instance)

        record(
            action=AuditLog.Action.CREATE,
            resource_type='appointment',
            resource_id=instance.id,
            request=self.request,
            metadata={
                'customer_id': instance.customer_id,
                'service_id': instance.service_id,
                'provider_id': instance.provider_id,
                'start': instance.start_time.isoformat(),
                'extras': [
                    {
                        'service_id': s.pk,
                        'provider_id': p.pk if p is not None else None,
                    }
                    for (s, p) in extras
                ],
                'auto_assigned_forms': [
                    {
                        'submission_id': s.id,
                        'template_id': s.form_template_id,
                        'template_version': s.template_version_at_assignment,
                    }
                    for s in created_submissions
                ],
            },
        )

    def perform_update(self, serializer):
        instance = serializer.instance
        old_status = instance.status
        new_status = serializer.validated_data.get('status', old_status)

        # Snapshot the pre-update values for the fields most worth
        # logging. We capture before/after on time + provider + status
        # so the audit log answers "when was this rescheduled and by
        # whom?" without having to diff successive rows. Status before/
        # after live in their own keys for backward compat with reports
        # that already key off `from_status` / `to_status`.
        old_start = instance.start_time
        old_end = instance.end_time
        old_provider_id = instance.provider_id

        # On a status change, auto-populate the matching workflow timestamp.
        # These fields are read-only at the serializer layer, so we set them
        # via save(**extras), which forwards to the model.
        extras: dict[str, dt.datetime | None] = {}
        if new_status != old_status:
            now = djtz.now()
            if new_status == Appointment.Status.CHECKED_IN and not instance.checked_in_at:
                extras['checked_in_at'] = now
            elif new_status == Appointment.Status.COMPLETED:
                extras['completed_at'] = now
                if not instance.checked_in_at:
                    extras['checked_in_at'] = now
            elif new_status in (Appointment.Status.CANCELLED, Appointment.Status.NO_SHOW):
                extras['cancelled_at'] = now
            # Undo check-in: clear `checked_in_at` so the field reflects
            # reality (the customer never actually checked in).
            if (
                old_status == Appointment.Status.CHECKED_IN
                and new_status == Appointment.Status.CONFIRMED
            ):
                extras['checked_in_at'] = None

        updated = serializer.save(**extras)

        # Build the audit metadata. Always include `fields_changed` for
        # quick filtering; layer in before/after snapshots when the
        # corresponding fields actually moved so reports can answer
        # "what was the previous state" without joining to history.
        fields_changed = sorted(serializer.validated_data.keys())
        metadata: dict = {'fields_changed': fields_changed}

        # Status transitions get their own dedicated keys so existing
        # reports / queries that filter on `transition`, `from_status`,
        # `to_status` keep working.
        if new_status != old_status:
            metadata['transition'] = True
            metadata['from_status'] = old_status
            metadata['to_status'] = new_status
            # Log the cancellation reason so the appointment activity
            # feed can answer "why was this cancelled" — operators
            # cancel accidental / duplicate bookings and need the trail.
            if new_status == Appointment.Status.CANCELLED and updated.cancelled_reason:
                metadata['cancelled_reason'] = updated.cancelled_reason

        # Time / provider changes: capture before/after so the activity
        # log on the appointment popover can render "Rescheduled from
        # 10:00 → 11:30" or "Provider changed from Jamie → Sarah" without
        # any extra round-trips.
        if updated.start_time != old_start or updated.end_time != old_end:
            metadata['rescheduled'] = True
            metadata['from_start'] = old_start.isoformat() if old_start else None
            metadata['to_start'] = updated.start_time.isoformat() if updated.start_time else None
            metadata['from_end'] = old_end.isoformat() if old_end else None
            metadata['to_end'] = updated.end_time.isoformat() if updated.end_time else None

        if updated.provider_id != old_provider_id:
            metadata['provider_changed'] = True
            metadata['from_provider_id'] = old_provider_id
            metadata['to_provider_id'] = updated.provider_id

        record(
            action=AuditLog.Action.UPDATE,
            resource_type='appointment',
            resource_id=updated.id,
            request=self.request,
            metadata=metadata,
        )

    @action(detail=True, methods=['get'], url_path='activity')
    def activity(self, request, pk=None):
        """Return the audit-log timeline for a single appointment.

        Used by the appointment popover on the calendar to render an activity
        feed (created → status transitions → edits). Limited to the most
        recent 50 entries to keep payloads small; full history is in admin.

        The read of the activity feed is itself audit-logged so HIPAA
        investigators can see "who looked at this appointment's audit trail"
        — required because the trail can contain PHI references in metadata.
        """
        instance = self.get_object()
        logs = (
            AuditLog.objects
            .filter(
                tenant_id=instance.tenant_id,
                resource_type='appointment',
                resource_id=str(instance.id),
            )
            .select_related('user')
            .order_by('-timestamp')[:50]
        )

        record(
            action=AuditLog.Action.READ,
            resource_type='appointment_activity',
            resource_id=instance.id,
            request=request,
            metadata={'returned_count': len(logs)},
        )

        return Response([
            {
                'id': log.id,
                'timestamp': log.timestamp.isoformat(),
                'action': log.action,
                'user_email': log.user.email if log.user else None,
                'user_first_name': log.user.first_name if log.user else None,
                'user_last_name': log.user.last_name if log.user else None,
                'metadata': log.metadata or {},
            }
            for log in logs
        ])

    # ── Service editing (add / change / remove) ──────────────────────────
    #
    # An appointment is booked with one primary `service`; the front desk
    # often needs to adjust that afterward — the customer wants an add-on,
    # or the wrong service was booked. These three actions handle it:
    #
    #   POST   /api/appointments/{id}/add-service/             {service_id}
    #   POST   /api/appointments/{id}/change-service/          {service_id}
    #   DELETE /api/appointments/{id}/extra-services/{es_id}/
    #
    # Each keeps the calendar block length and the still-open invoice in
    # sync. Once the invoice is paid (or voided) the services lock — staff
    # reopen the invoice through the existing flow to change anything.
    #
    # `perform_create` reuses the same `_attach_extra_service` helper for
    # extras supplied in the initial POST payload, so a multi-service
    # booking takes one round-trip instead of N follow-up writes.

    @staticmethod
    def _attach_extra_service(
        appointment, service, invoice, sort_order, *, provider=None,
    ):
        """Create an `AppointmentService` row plus its matching invoice
        line. Shared between the create-time bulk attach (perform_create)
        and after-the-fact add (the `add-service` action). Does NOT
        touch `appointment.end_time` — callers handle that since the
        rules differ: create trusts the caller's end time, add extends
        the block by the new service's duration.

        `provider` is the optional per-service override; None inherits
        the appointment's primary provider (the common case).
        """
        from apps.invoices.models import InvoiceLineItem
        line = None
        if invoice is not None:
            line = InvoiceLineItem.objects.create(
                invoice=invoice,
                service=service,
                description=service.name,
                quantity=1,
                unit_price_cents=service.price_cents,
                tax_rate_percent=service.tax_rate_percent or 0,
            )
        return AppointmentService.objects.create(
            appointment=appointment,
            service=service,
            provider=provider,
            price_cents=service.price_cents,
            duration_minutes=service.duration_minutes,
            invoice_line=line,
            sort_order=sort_order,
        )

    @staticmethod
    def _services_locked_response(appointment):
        """Return a 409 Response when the appointment's services are
        locked (invoice paid/void), else None. A missing invoice — the
        brief window before the creation signal commits — is treated as
        editable."""
        invoice = getattr(appointment, 'invoice', None)
        if invoice is None:
            return None
        from apps.invoices.models import Invoice
        if invoice.status != Invoice.Status.OPEN:
            return Response(
                {
                    'detail': (
                        f"This appointment's invoice is "
                        f'{invoice.get_status_display().lower()}; its '
                        f'services are locked. Reopen the invoice to '
                        f'change them.'
                    ),
                },
                status=status.HTTP_409_CONFLICT,
            )
        return None

    @staticmethod
    def _resolve_tenant_service(service_id):
        """Fetch an active service in the current tenant or raise a
        field-level 400."""
        from apps.services.models import Service
        if service_id in (None, ''):
            raise ValidationError({'service_id': 'This field is required.'})
        try:
            service = Service.objects.for_current_tenant().get(pk=service_id)
        except (Service.DoesNotExist, ValueError, TypeError):
            raise ValidationError(
                {'service_id': 'Service not found in this tenant.'},
            )
        if not service.is_active:
            raise ValidationError(
                {'service_id': f'{service.name} is no longer offered.'},
            )
        return service

    @action(detail=True, methods=['post'], url_path='add-service')
    def add_service(self, request, pk=None):
        """Add an extra service to an appointment.

        Snapshots the service's price + duration onto an
        `AppointmentService` row, extends `end_time` so the calendar
        block reflects the longer visit, and adds a matching line to the
        still-open invoice. Refused once the invoice is paid/void.
        """
        import datetime as _dt

        from django.db import transaction

        appointment = self.get_object()
        locked = self._services_locked_response(appointment)
        if locked is not None:
            return locked

        service = self._resolve_tenant_service(request.data.get('service_id'))
        invoice = getattr(appointment, 'invoice', None)

        with transaction.atomic():
            next_sort = (
                appointment.extra_services.aggregate(m=Max('sort_order'))['m']
                or 0
            ) + 1
            extra = self._attach_extra_service(
                appointment, service, invoice, next_sort,
            )
            # Grow the block so the calendar shows the real time commitment.
            appointment.end_time = appointment.end_time + _dt.timedelta(
                minutes=service.duration_minutes,
            )
            appointment.save(update_fields=['end_time', 'updated_at'])

        record(
            action=AuditLog.Action.UPDATE,
            resource_type='appointment',
            resource_id=appointment.id,
            request=request,
            metadata={
                'event': 'service_added',
                'service_id': service.pk,
                'service_name': service.name,
                'price_cents': service.price_cents,
                'appointment_service_id': extra.pk,
                'invoice_line_id': extra.invoice_line_id,
            },
        )
        appointment.refresh_from_db()
        return Response(self.get_serializer(appointment).data)

    @action(detail=True, methods=['post'], url_path='change-service')
    def change_service(self, request, pk=None):
        """Swap the primary service of an appointment.

        Re-snapshots `quoted_price_cents`, shifts `end_time` by the
        duration difference, and re-points the primary invoice line at
        the new service. Refused once the invoice is paid/void.
        """
        import datetime as _dt

        from django.db import transaction

        appointment = self.get_object()
        locked = self._services_locked_response(appointment)
        if locked is not None:
            return locked

        new_service = self._resolve_tenant_service(
            request.data.get('service_id'),
        )
        old_service = appointment.service
        if new_service.pk == old_service.pk:
            # No-op — return the appointment unchanged.
            return Response(self.get_serializer(appointment).data)

        with transaction.atomic():
            delta = (
                new_service.duration_minutes - old_service.duration_minutes
            )
            new_end = appointment.end_time + _dt.timedelta(minutes=delta)
            if new_end <= appointment.start_time:
                # A much shorter service would collapse the block — fall
                # back to just the new service's own length.
                new_end = appointment.start_time + _dt.timedelta(
                    minutes=max(new_service.duration_minutes, 5),
                )
            appointment.service = new_service
            appointment.quoted_price_cents = new_service.price_cents
            appointment.end_time = new_end
            appointment.save(update_fields=[
                'service', 'quoted_price_cents', 'end_time', 'updated_at',
            ])
            # Re-snapshot the primary invoice line when we still hold a
            # reference to it (null on pre-multi-service rows whose link
            # couldn't be backfilled, or a manually-removed line).
            line = appointment.primary_invoice_line
            invoice_synced = False
            if line is not None:
                line.service = new_service
                line.description = new_service.name
                line.unit_price_cents = new_service.price_cents
                line.tax_rate_percent = new_service.tax_rate_percent or 0
                line.save()
                invoice_synced = True

        record(
            action=AuditLog.Action.UPDATE,
            resource_type='appointment',
            resource_id=appointment.id,
            request=request,
            metadata={
                'event': 'service_changed',
                'from_service_id': old_service.pk,
                'from_service_name': old_service.name,
                'to_service_id': new_service.pk,
                'to_service_name': new_service.name,
                'invoice_synced': invoice_synced,
            },
        )
        appointment.refresh_from_db()
        return Response(self.get_serializer(appointment).data)

    @action(
        detail=True,
        methods=['delete'],
        url_path=r'extra-services/(?P<es_pk>[^/.]+)',
    )
    def remove_extra_service(self, request, pk=None, es_pk=None):
        """Remove an extra service from an appointment.

        Deletes the linked invoice line, shrinks `end_time` back, and
        drops the `AppointmentService` row. Refused once the invoice is
        paid/void.
        """
        import datetime as _dt

        from django.db import transaction

        appointment = self.get_object()
        locked = self._services_locked_response(appointment)
        if locked is not None:
            return locked

        try:
            extra = (
                appointment.extra_services
                .select_related('service')
                .get(pk=es_pk)
            )
        except (AppointmentService.DoesNotExist, ValueError, TypeError):
            return Response(
                {'detail': 'Service not found on this appointment.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        snapshot = {
            'event': 'service_removed',
            'appointment_service_id': extra.pk,
            'service_id': extra.service_id,
            'service_name': extra.service.name,
            'invoice_line_id': extra.invoice_line_id,
        }

        with transaction.atomic():
            line = extra.invoice_line
            if line is not None:
                invoice = line.invoice
                line.delete()
                invoice.recalculate_totals()
            # Shrink the block back, but never collapse it past its start.
            new_end = appointment.end_time - _dt.timedelta(
                minutes=extra.duration_minutes,
            )
            if new_end > appointment.start_time:
                appointment.end_time = new_end
                appointment.save(update_fields=['end_time', 'updated_at'])
            extra.delete()

        record(
            action=AuditLog.Action.UPDATE,
            resource_type='appointment',
            resource_id=appointment.id,
            request=request,
            metadata=snapshot,
        )
        appointment.refresh_from_db()
        return Response(self.get_serializer(appointment).data)

    def perform_destroy(self, instance):
        record(
            action=AuditLog.Action.DELETE,
            resource_type='appointment',
            resource_id=instance.id,
            request=self.request,
            metadata={
                'customer_id': instance.customer_id,
                'start': instance.start_time.isoformat(),
            },
        )
        instance.delete()


class TimeBlockViewSet(viewsets.ModelViewSet):
    """CRUD for non-bookable schedule blocks (lunch, personal time…).

    Mirrors `AppointmentViewSet` in shape — per-location filter via
    `LocationMiddleware`, `?date=YYYY-MM-DD` day-window, audit-logged
    on every mutation (HIPAA §164.312(b) — same trail an appointment
    would generate). No add-line / change-service surface because a
    block is not a billable event.
    """

    serializer_class = TimeBlockSerializer
    permission_classes = [TimeBlockPermission]

    def get_queryset(self):
        qs = (
            TimeBlock.objects
            .for_current_tenant()
            .select_related(
                'provider', 'provider__user', 'provider__job_title',
                'location', 'created_by',
            )
        )
        location = get_current_location()
        if location is not None:
            qs = qs.filter(location=location)
        return qs

    def filter_queryset(self, queryset):
        # Day-window filter matches AppointmentViewSet so the calendar
        # can fan out both queries with the same `?date=` param.
        params = self.request.query_params
        date_param = (params.get('date') or '').strip()
        start_param = (params.get('start') or '').strip()
        end_param = (params.get('end') or '').strip()
        provider_param = (params.get('provider') or '').strip()

        if date_param:
            d = parse_date(date_param)
            if d is None:
                raise ValidationError({'date': 'Invalid date — use YYYY-MM-DD.'})
            location = get_current_location()
            tz_name = (
                location.timezone
                if location is not None and location.timezone else 'UTC'
            )
            try:
                tz = ZoneInfo(tz_name)
            except Exception:  # noqa: BLE001
                tz = ZoneInfo('UTC')
            start = dt.datetime.combine(d, dt.time.min, tzinfo=tz)
            end = start + dt.timedelta(days=1)
            queryset = queryset.filter(start_time__lt=end, end_time__gt=start)
        else:
            if start_param:
                s = parse_datetime(start_param)
                if not s:
                    raise ValidationError({'start': 'Invalid datetime — use ISO-8601.'})
                queryset = queryset.filter(end_time__gt=s)
            if end_param:
                e = parse_datetime(end_param)
                if not e:
                    raise ValidationError({'end': 'Invalid datetime — use ISO-8601.'})
                queryset = queryset.filter(start_time__lt=e)
        if provider_param:
            queryset = queryset.filter(provider_id=provider_param)
        return queryset

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        results = (
            response.data.get('results', response.data)
            if isinstance(response.data, dict) else response.data
        )
        record(
            action=AuditLog.Action.READ,
            resource_type='time_block_list',
            request=request,
            metadata={
                'count': len(results) if isinstance(results, list) else None,
                'date': request.query_params.get('date', ''),
            },
        )
        return response

    def perform_create(self, serializer):
        tenant = get_current_tenant()
        if tenant is None:
            raise PermissionDenied('No tenant context resolved for this request.')

        save_kwargs: dict = {
            'tenant': tenant,
            'created_by': self.request.user if self.request.user.is_authenticated else None,
        }
        # Default location from the active site when the caller didn't
        # supply one — same UX pattern as appointment creation.
        if 'location' not in serializer.validated_data:
            active_location = get_current_location()
            if active_location is None:
                raise ValidationError({
                    'location_id': (
                        'No active location resolved for this request and '
                        'none supplied in the payload.'
                    ),
                })
            save_kwargs['location'] = active_location

        instance = serializer.save(**save_kwargs)

        record(
            action=AuditLog.Action.CREATE,
            resource_type='time_block',
            resource_id=instance.id,
            request=self.request,
            metadata={
                'provider_id': instance.provider_id,
                'reason': instance.reason,
                'start': instance.start_time.isoformat(),
                'end': instance.end_time.isoformat(),
            },
        )

    def perform_update(self, serializer):
        instance = serializer.instance
        old_start = instance.start_time
        old_end = instance.end_time
        old_reason = instance.reason

        updated = serializer.save()

        metadata: dict = {
            'fields_changed': sorted(serializer.validated_data.keys()),
        }
        if updated.start_time != old_start or updated.end_time != old_end:
            metadata['resized'] = True
            metadata['from_start'] = old_start.isoformat() if old_start else None
            metadata['to_start'] = updated.start_time.isoformat()
            metadata['from_end'] = old_end.isoformat() if old_end else None
            metadata['to_end'] = updated.end_time.isoformat()
        if updated.reason != old_reason:
            metadata['from_reason'] = old_reason
            metadata['to_reason'] = updated.reason
        record(
            action=AuditLog.Action.UPDATE,
            resource_type='time_block',
            resource_id=updated.id,
            request=self.request,
            metadata=metadata,
        )

    def perform_destroy(self, instance):
        record(
            action=AuditLog.Action.DELETE,
            resource_type='time_block',
            resource_id=instance.id,
            request=self.request,
            metadata={
                'provider_id': instance.provider_id,
                'reason': instance.reason,
                'start': instance.start_time.isoformat(),
                'end': instance.end_time.isoformat(),
            },
        )
        instance.delete()
