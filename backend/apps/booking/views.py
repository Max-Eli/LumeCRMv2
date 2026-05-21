"""Public-facing booking API.

URL surface (under `/api/booking/`):

    GET   <tenant_slug>/info/                       Spa branding + locations
    GET   <tenant_slug>/services/                   Bookable services
    GET   <tenant_slug>/providers/?service=&location= Eligible providers
    GET   <tenant_slug>/slots/?service=&date=&location=&provider= Available slots
    POST  <tenant_slug>/book/                       Submit a booking
    GET   manage/<token>/                           Lookup by booking_token
    POST  manage/<token>/cancel/                    Customer-initiated cancel

No auth — `PublicBookingPermission` allows any caller and
`authentication_classes = []` keeps DRF from trying to validate a
session that doesn't exist (also drops CSRF, since CSRF only fires
when SessionAuthentication is in use).

Tenant resolution: the slug is in the URL path. We don't trust the
subdomain or `X-Tenant-Slug` header for these endpoints because the
public booking flow runs from the spa's own subdomain (where the
slug is in the URL) AND from cross-origin marketing pages (where it
isn't). Path-based resolution is the single source of truth.

Audit posture: every endpoint records an audit log entry with
`tenant=tenant` and `user=None`. PHI lookups (book + manage) capture
IP + user-agent; READ endpoints capture parameters but no PHI. See
ADR 0011 for the tokenized-no-auth pattern; ADR 0012 for the
HIPAA framing of audit logging on public surfaces.
"""

from __future__ import annotations

import datetime as dt

from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.appointments.models import Appointment
from apps.audit.models import AuditLog
from apps.audit.services import record
from apps.services.models import Service
from apps.tenants.models import (
    Location,
    MembershipLocation,
    Tenant,
    TenantMembership,
)

from .availability import compute_any_provider_slots, compute_provider_slots
from .permissions import (
    BookingRescheduleThrottle,
    BookingSubmitThrottle,
    PublicBookingPermission,
)
from .serializers import (
    AvailableSlotSerializer,
    BookableServiceSerializer,
    BookingConfirmationSerializer,
    EligibleProviderSerializer,
    ManageBookingSerializer,
    RescheduleBookingInputSerializer,
    SubmitBookingInputSerializer,
    TenantInfoSerializer,
)
from .services import send_booking_confirmation, submit_booking


# ── Mixin: public auth posture ───────────────────────────────────────


class PublicBookingViewMixin:
    """Disable session auth + CSRF; allow any client.

    Centralized so every booking view declares the same posture and
    a future audit can grep for "where do we drop auth on the public
    surface" in one place.
    """

    permission_classes = [PublicBookingPermission]
    authentication_classes = []


# ── Tenant info ──────────────────────────────────────────────────────


class BookingTenantInfoView(PublicBookingViewMixin, APIView):
    """`GET /api/booking/<tenant_slug>/info/` — spa branding + locations.

    First request the booking page makes. Drives the theme + the
    location picker. Caches well at the CDN layer (Phase 0c) since
    branding rarely changes.
    """

    @extend_schema(
        responses={
            200: TenantInfoSerializer,
            404: OpenApiResponse(description='Tenant not found or not accepting online bookings'),
        },
    )
    def get(self, request, tenant_slug: str):
        tenant = _resolve_active_tenant(tenant_slug)
        record(
            action=AuditLog.Action.READ,
            resource_type='booking_tenant_info',
            tenant=tenant,
            user=None,
            request=request,
            metadata={'tenant_slug': tenant_slug},
        )
        return Response(TenantInfoSerializer(tenant).data)


# ── Services catalog ─────────────────────────────────────────────────


class BookingServiceListView(PublicBookingViewMixin, APIView):
    """`GET /api/booking/<tenant_slug>/services/` — bookable services."""

    @extend_schema(
        responses={200: BookableServiceSerializer(many=True)},
    )
    def get(self, request, tenant_slug: str):
        tenant = _resolve_active_tenant(tenant_slug)
        services = (
            Service.objects
            .filter(
                tenant=tenant,
                is_active=True,
                is_bookable_online=True,
                # Add-ons attach to a regular service; they're not
                # individually bookable from the public flow. The
                # frontend can surface them after a regular service
                # is picked (out of scope for v1).
                service_type=Service.ServiceType.REGULAR,
            )
            .select_related('category')
            .order_by('sort_order', 'name')
        )
        record(
            action=AuditLog.Action.READ,
            resource_type='booking_service_list',
            tenant=tenant,
            user=None,
            request=request,
            metadata={'service_count': services.count()},
        )
        return Response(BookableServiceSerializer(services, many=True).data)


# ── Providers eligible for a service at a location ───────────────────


class BookingProviderListView(PublicBookingViewMixin, APIView):
    """`GET /api/booking/<tenant_slug>/providers/?service=&location=`

    Eligible = bookable + active + assigned to the location + job
    title in the service's category eligibility set (or category has
    no eligibility rules).

    Response is intentionally first-name-plus-last-initial. Public
    flow doesn't need full last names plastered around the page.
    """

    @extend_schema(
        parameters=[
            OpenApiParameter(name='service', required=True, type=int),
            OpenApiParameter(name='location', required=True, type=int),
        ],
        responses={200: EligibleProviderSerializer(many=True)},
    )
    def get(self, request, tenant_slug: str):
        tenant = _resolve_active_tenant(tenant_slug)
        service = _resolve_bookable_service(request, tenant)
        location = _resolve_active_location(request, tenant)

        providers = _eligible_providers(tenant=tenant, service=service, location=location)

        payload = [
            {
                'id': p.pk,
                'display_name': _provider_display_name(p),
                'job_title': p.job_title.name if p.job_title else '',
            }
            for p in providers
        ]
        record(
            action=AuditLog.Action.READ,
            resource_type='booking_provider_list',
            tenant=tenant,
            user=None,
            request=request,
            metadata={
                'service_id': service.pk,
                'location_id': location.pk,
                'provider_count': len(payload),
            },
        )
        return Response(EligibleProviderSerializer(payload, many=True).data)


# ── Available slots for (service, location, date, optional provider) ─


class BookingSlotListView(PublicBookingViewMixin, APIView):
    """`GET /api/booking/<tenant_slug>/slots/?service=&location=&date=&provider=`

    `provider` accepts an integer (specific provider) OR the literal
    string `any` (return the union across eligible providers, with a
    `provider_id` on each slot so submit can pin to a specific one).
    """

    @extend_schema(
        parameters=[
            OpenApiParameter(name='service', required=True, type=int),
            OpenApiParameter(name='location', required=True, type=int),
            OpenApiParameter(name='date', required=True, type=str, description='YYYY-MM-DD'),
            OpenApiParameter(name='provider', required=False, type=str, description='id or "any"'),
            OpenApiParameter(
                name='include_unavailable', required=False, type=bool,
                description='Return all working-hour slots, marking conflicting/lead-time-blocked ones as available=false (default false → only available slots).',
            ),
        ],
        responses={200: AvailableSlotSerializer(many=True)},
    )
    def get(self, request, tenant_slug: str):
        tenant = _resolve_active_tenant(tenant_slug)
        service = _resolve_bookable_service(request, tenant)
        location = _resolve_active_location(request, tenant)
        on_date = _resolve_date(request)
        provider_param = (request.query_params.get('provider') or 'any').strip().lower()
        include_unavailable = (
            (request.query_params.get('include_unavailable') or '').strip().lower()
            in {'1', 'true', 'yes'}
        )

        # Window-days guard: dates beyond `today + window_days` return
        # an empty list rather than 400. Reasoning: the frontend may
        # cache a wider date range and a hard error every time the
        # customer scrolls past the window is annoying. Empty list is
        # the correct semantic ("no slots available") and the UI
        # already handles it gracefully.
        from django.utils import timezone as djtz
        max_date = djtz.localdate() + dt.timedelta(days=tenant.online_booking_window_days)
        if on_date > max_date:
            payload: list = []
        elif provider_param == 'any':
            providers = _eligible_providers(tenant=tenant, service=service, location=location)
            payload = compute_any_provider_slots(
                eligible_providers=providers,
                service=service,
                location=location,
                on_date=on_date,
                lead_minutes=tenant.online_booking_lead_minutes,
                include_unavailable=include_unavailable,
            )
        else:
            try:
                provider_id = int(provider_param)
            except ValueError:
                return Response(
                    {'detail': 'provider must be an integer id or "any".'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            provider = _resolve_eligible_provider(
                tenant=tenant, service=service, location=location,
                provider_id=provider_id,
            )
            slots = compute_provider_slots(
                provider=provider, service=service, location=location,
                on_date=on_date,
                lead_minutes=tenant.online_booking_lead_minutes,
                include_unavailable=include_unavailable,
            )
            payload = [
                {
                    **s.to_payload(),
                    'provider_id': provider.pk if s.available else None,
                }
                for s in slots
            ]

        record(
            action=AuditLog.Action.READ,
            resource_type='booking_slot_list',
            tenant=tenant,
            user=None,
            request=request,
            metadata={
                'service_id': service.pk,
                'location_id': location.pk,
                'date': on_date.isoformat(),
                'provider_param': provider_param,
                'slot_count': len(payload),
            },
        )
        return Response(AvailableSlotSerializer(payload, many=True).data)


# ── Submit a booking ─────────────────────────────────────────────────


class BookingSubmitView(PublicBookingViewMixin, APIView):
    """`POST /api/booking/<tenant_slug>/book/` — create the appointment.

    Per-IP rate limited (10/hour) to curb scraping + spam-posting
    without breaking legitimate retries after a slot conflict.
    """

    throttle_classes = [BookingSubmitThrottle]

    @extend_schema(
        request=SubmitBookingInputSerializer,
        responses={
            201: BookingConfirmationSerializer,
            400: OpenApiResponse(description='Invalid input or eligibility/availability rejection'),
            409: OpenApiResponse(description='Slot taken between availability fetch and submit'),
        },
    )
    def post(self, request, tenant_slug: str):
        tenant = _resolve_active_tenant(tenant_slug)

        ser = SubmitBookingInputSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        # Resolve all FKs against the URL's tenant — never trust the
        # client to tell us which tenant a service/location belongs to.
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
                pk=data['location_id'],
                tenant=tenant,
                is_active=True,
            )
        except Location.DoesNotExist:
            return Response(
                {'detail': 'Location is not available for online booking.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            provider = _resolve_eligible_provider(
                tenant=tenant, service=service, location=location,
                provider_id=data['provider_id'],
            )
        except _BookingError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        # Availability re-check inside the request — between when the
        # frontend fetched slots and now, another customer may have
        # grabbed the same start. Re-running the calculator is cheap
        # (one query) and keeps the race window to "between this
        # check and the appointment INSERT below."
        start_time = data['start_time']
        end_time = start_time + dt.timedelta(
            minutes=service.duration_minutes + service.buffer_minutes,
        )
        on_date = timezone.localtime(start_time).date()
        free_starts = {
            s.start
            for s in compute_provider_slots(
                provider=provider, service=service, location=location,
                on_date=on_date,
                lead_minutes=tenant.online_booking_lead_minutes,
            )
        }
        if start_time not in free_starts:
            record(
                action=AuditLog.Action.CREATE,
                resource_type='booking_submit_rejected',
                tenant=tenant,
                user=None,
                request=request,
                metadata={
                    'reason': 'slot_unavailable',
                    'service_id': service.pk,
                    'provider_id': provider.pk,
                    'location_id': location.pk,
                    'start_time': start_time.isoformat(),
                },
            )
            return Response(
                {'detail': 'That time is no longer available. Please pick another slot.'},
                status=status.HTTP_409_CONFLICT,
            )

        appointment = submit_booking(
            tenant=tenant,
            service=service,
            provider=provider,
            location=location,
            start_time=start_time,
            end_time=end_time,
            customer_first_name=data['customer_first_name'],
            customer_last_name=data['customer_last_name'],
            customer_email=data['customer_email'],
            customer_phone=data['customer_phone'],
            email_marketing_opt_in=data.get('email_marketing_opt_in', False),
            sms_marketing_opt_in=data.get('sms_marketing_opt_in', False),
        )

        # Internal "from the customer" notes get stamped on the
        # appointment so staff see them at calendar-prep time.
        notes = data.get('notes') or ''
        if notes:
            Appointment.objects.filter(pk=appointment.pk).update(
                notes=f'[Customer note]\n{notes}',
            )
            appointment.refresh_from_db()

        record(
            action=AuditLog.Action.CREATE,
            resource_type='appointment',
            resource_id=appointment.pk,
            tenant=tenant,
            user=None,
            request=request,
            metadata={
                'event': 'online_booking_submitted',
                'service_id': service.pk,
                'provider_id': provider.pk,
                'location_id': location.pk,
                'customer_id': appointment.customer_id,
                'has_customer_note': bool(notes),
                # Email + phone deliberately NOT logged — captured on
                # the customer row itself; logs aggregate query-able
                # data and shouldn't accumulate raw PHI.
            },
        )

        # Confirmation email — best-effort. Send failures don't break
        # the response (the customer can still see + use the manage
        # link from the JSON body). Audit log captures only the
        # recipient domain, not the full address (ADR 0012).
        recipient = send_booking_confirmation(appointment)
        if recipient:
            domain = recipient.split('@')[1].lower() if '@' in recipient else 'unknown'
            record(
                action=AuditLog.Action.UPDATE,
                resource_type='appointment',
                resource_id=appointment.pk,
                tenant=tenant,
                user=None,
                request=request,
                metadata={
                    'event': 'confirmation_email_sent',
                    'recipient_email_domain': domain,
                },
            )

        return Response(
            BookingConfirmationSerializer(appointment).data,
            status=status.HTTP_201_CREATED,
        )


# ── Manage by token (no auth, token IS the boundary) ────────────────


class BookingManageView(PublicBookingViewMixin, APIView):
    """`GET /api/booking/manage/<token>/` — appointment detail by token.

    Mirrors the form-fill tokenized flow (see apps.forms). The token
    is the security boundary — 256-bit entropy, single-purpose. No
    enumeration risk (tokens aren't sequential or predictable).
    """

    @extend_schema(
        responses={
            200: ManageBookingSerializer,
            404: OpenApiResponse(description='No such booking'),
        },
    )
    def get(self, request, token: str):
        appointment = _resolve_appointment_by_token(token)
        record(
            action=AuditLog.Action.READ,
            resource_type='appointment',
            resource_id=appointment.pk,
            tenant=appointment.tenant,
            user=None,
            request=request,
            metadata={
                'event': 'manage_booking_viewed',
                'status': appointment.status,
            },
        )
        return Response(ManageBookingSerializer(appointment).data)


class BookingManageCancelView(PublicBookingViewMixin, APIView):
    """`POST /api/booking/manage/<token>/cancel/` — customer cancel.

    Idempotent on already-cancelled. Rejects terminal states (completed,
    no-show) since those are staff-controlled outcomes and cancelling
    them through the public surface would corrupt history.
    """

    @extend_schema(
        responses={
            200: ManageBookingSerializer,
            400: OpenApiResponse(description='Cannot cancel from current status'),
        },
    )
    def post(self, request, token: str):
        appointment = _resolve_appointment_by_token(token)

        if appointment.status == Appointment.Status.CANCELLED:
            return Response(ManageBookingSerializer(appointment).data)

        cancellable = {
            Appointment.Status.BOOKED,
            Appointment.Status.CONFIRMED,
        }
        if appointment.status not in cancellable:
            return Response(
                {
                    'detail': (
                        f'This booking can no longer be cancelled '
                        f'(status: {appointment.status}). Please call the spa.'
                    ),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        previous_status = appointment.status
        appointment.status = Appointment.Status.CANCELLED
        appointment.cancelled_at = timezone.now()
        appointment.cancelled_reason = 'Cancelled by customer via booking link'
        appointment.save(update_fields=[
            'status', 'cancelled_at', 'cancelled_reason', 'updated_at',
        ])

        record(
            action=AuditLog.Action.UPDATE,
            resource_type='appointment',
            resource_id=appointment.pk,
            tenant=appointment.tenant,
            user=None,
            request=request,
            metadata={
                'event': 'customer_cancelled_via_token',
                'from_status': previous_status,
                'to_status': Appointment.Status.CANCELLED,
            },
        )
        return Response(ManageBookingSerializer(appointment).data)


class BookingManageRescheduleView(PublicBookingViewMixin, APIView):
    """`POST /api/booking/manage/<token>/reschedule/` — customer reschedule.

    Accepts a new `start_time` for the existing appointment. Provider,
    location, and service stay the same — a reschedule is a time
    move, not a re-shop. The new time has to be a real available
    slot for the same provider, validated server-side against the
    same calculator the public picker uses (so the customer can't
    inject a "10pm Tuesday" outside working hours by hand-editing
    the URL).

    Allowed states: BOOKED + CONFIRMED only. Terminal states
    (completed, no-show, cancelled) cannot be rescheduled — the
    booking has already played out one way or the other. Tenant-
    level booking-window-days cap applies.

    On success: emits a reschedule confirmation email (kind='reschedule')
    so the customer gets the updated calendar invite info.

    Per-IP rate limited (20/hour) — slightly higher than the
    submit endpoint because customers may iterate through the slot
    picker before settling.
    """

    throttle_classes = [BookingRescheduleThrottle]

    @extend_schema(
        request=RescheduleBookingInputSerializer,
        responses={
            200: ManageBookingSerializer,
            400: OpenApiResponse(description='Invalid time or unreschedulable status'),
            409: OpenApiResponse(description='Slot taken between fetch and submit'),
        },
    )
    def post(self, request, token: str):
        appointment = _resolve_appointment_by_token(token)

        # State guard. Cancelled / completed / no-show are terminal;
        # rescheduling them through the public surface would corrupt
        # history. Customer who needs an appointment after one of
        # those states should book fresh.
        reschedulable = {
            Appointment.Status.BOOKED,
            Appointment.Status.CONFIRMED,
        }
        if appointment.status not in reschedulable:
            return Response(
                {
                    'detail': (
                        f'This booking can no longer be rescheduled '
                        f'(status: {appointment.status}). Please book a '
                        f'new appointment instead.'
                    ),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Killswitch passthrough: if the tenant has flipped online
        # booking off, no further self-service moves either.
        tenant = appointment.tenant
        if not tenant.online_booking_enabled:
            return Response(
                {
                    'detail': (
                        'Online booking is currently paused for this spa. '
                        'Please contact them directly to reschedule.'
                    ),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        ser = RescheduleBookingInputSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        new_start = ser.validated_data['start_time']

        # Window-days guard. Same logic as the slots endpoint —
        # stay inside the operator-configured booking window.
        max_date = timezone.localdate() + dt.timedelta(
            days=tenant.online_booking_window_days,
        )
        if timezone.localtime(new_start).date() > max_date:
            return Response(
                {
                    'detail': (
                        f'That date is past this spa\'s booking window '
                        f'({tenant.online_booking_window_days} days out).'
                    ),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Slot validity. Re-runs the same availability calculator the
        # public picker uses. The current appointment's existing slot
        # would otherwise show as a conflict-with-itself, so we
        # exclude it from the conflict set by checking against
        # `compute_provider_slots(...)` AFTER excluding `appointment`
        # from the existing-appointments query.
        from .availability import compute_provider_slots
        from apps.appointments.models import Appointment as ApptModel
        # Build the available-slots set, but pretend the current
        # appointment doesn't exist so its old slot doesn't block
        # itself when the customer picks the same time (no-op
        # reschedule) or an overlapping nearby slot. We do this by
        # temporarily excluding it from the queryset the calculator
        # walks; the simplest approach is to compute against a
        # tweaked QuerySet via a context-manager-style escape.
        # Cleanest: pass an `exclude_appointment_id` to the calculator.
        # For v1, we open a small specialized path: call the
        # calculator, then if the new_start matches the current
        # appointment's start, accept it as a no-op; otherwise
        # require it in the freshly-computed free set with the
        # current appointment temporarily soft-excluded by status.
        on_date = timezone.localtime(new_start).date()
        provider = appointment.provider
        service = appointment.service
        location = appointment.location

        # Soft-exclude the current appointment from the conflict set
        # by temporarily flipping its status to CANCELLED-equivalent
        # in-memory. Since `compute_provider_slots` reads from the
        # DB (not the in-memory instance), we instead use a status
        # mark+rollback inside a transaction, OR add an
        # `exclude_appointment_id` knob. The latter is the right
        # API; ship it as a tiny additive change.
        free_starts = {
            s.start
            for s in compute_provider_slots(
                provider=provider, service=service, location=location,
                on_date=on_date,
                lead_minutes=tenant.online_booking_lead_minutes,
                exclude_appointment_id=appointment.pk,
            )
        }
        if new_start not in free_starts:
            record(
                action=AuditLog.Action.UPDATE,
                resource_type='booking_reschedule_rejected',
                resource_id=appointment.pk,
                tenant=tenant,
                user=None,
                request=request,
                metadata={
                    'event': 'reschedule_slot_unavailable',
                    'from_start': appointment.start_time.isoformat(),
                    'to_start': new_start.isoformat(),
                },
            )
            return Response(
                {'detail': 'That time is no longer available. Please pick another slot.'},
                status=status.HTTP_409_CONFLICT,
            )

        # Apply the move. Status stays BOOKED|CONFIRMED — this is
        # a time change, not a state transition. The signal layer
        # picks up updated_at; the existing invoice + form
        # assignments stay attached to the same appointment row.
        previous_start = appointment.start_time
        previous_end = appointment.end_time
        new_end = new_start + dt.timedelta(
            minutes=service.duration_minutes + service.buffer_minutes,
        )
        appointment.start_time = new_start
        appointment.end_time = new_end
        appointment.save(update_fields=['start_time', 'end_time', 'updated_at'])

        record(
            action=AuditLog.Action.UPDATE,
            resource_type='appointment',
            resource_id=appointment.pk,
            tenant=tenant,
            user=None,
            request=request,
            metadata={
                'event': 'customer_rescheduled_via_token',
                'from_start': previous_start.isoformat(),
                'to_start': new_start.isoformat(),
                'from_end': previous_end.isoformat(),
                'to_end': new_end.isoformat(),
            },
        )

        # Confirmation email — best-effort, kind='reschedule' so the
        # subject + headline reflect a move not a fresh booking.
        recipient = send_booking_confirmation(appointment, kind='reschedule')
        if recipient:
            domain = recipient.split('@')[1].lower() if '@' in recipient else 'unknown'
            record(
                action=AuditLog.Action.UPDATE,
                resource_type='appointment',
                resource_id=appointment.pk,
                tenant=tenant,
                user=None,
                request=request,
                metadata={
                    'event': 'reschedule_email_sent',
                    'recipient_email_domain': domain,
                },
            )

        return Response(ManageBookingSerializer(appointment).data)


# ── Helpers ──────────────────────────────────────────────────────────


class _BookingError(Exception):
    """Internal sentinel for known-rejection cases that map to 400."""


def _resolve_active_tenant(slug: str) -> Tenant:
    """Look up the tenant by URL slug. 404 if missing, inactive, or
    online booking is paused.

    We don't reveal "exists but inactive" vs "exists but online
    booking off" vs "doesn't exist" — they all return the same
    generic 404. Rationale: the public surface should not leak which
    slugs are taken, and a paused booking page should look the same
    to outsiders as a non-existent one (the operator gets a clean
    "off" toggle without any awkward middle state).
    """
    return get_object_or_404(
        Tenant,
        slug=slug,
        status=Tenant.Status.ACTIVE,
        online_booking_enabled=True,
    )


def _resolve_bookable_service(request, tenant: Tenant) -> Service:
    raw = request.query_params.get('service')
    if not raw:
        raise _query_param_error('service is required.')
    try:
        service_id = int(raw)
    except ValueError:
        raise _query_param_error('service must be an integer id.')
    try:
        return Service.objects.get(
            pk=service_id, tenant=tenant,
            is_active=True, is_bookable_online=True,
            service_type=Service.ServiceType.REGULAR,
        )
    except Service.DoesNotExist:
        raise _query_param_error('Service is not available for online booking.')


def _resolve_active_location(request, tenant: Tenant) -> Location:
    raw = request.query_params.get('location')
    if not raw:
        # No explicit `?location=` → fall back to the tenant's default
        # site. The portal booking flow (single-location-implicit)
        # doesn't pick a location, so it omits the param; the public
        # multi-location flow always passes it explicitly. Mirrors the
        # default-location fallback the booking submit already uses.
        try:
            return Location.objects.get(
                tenant=tenant, is_default=True, is_active=True,
            )
        except Location.DoesNotExist:
            raise _query_param_error('No active location to book against.')
    try:
        location_id = int(raw)
    except ValueError:
        raise _query_param_error('location must be an integer id.')
    try:
        return Location.objects.get(pk=location_id, tenant=tenant, is_active=True)
    except Location.DoesNotExist:
        raise _query_param_error('Location is not available.')


def _resolve_date(request) -> dt.date:
    raw = (request.query_params.get('date') or '').strip()
    if not raw:
        raise _query_param_error('date is required (YYYY-MM-DD).')
    try:
        return dt.date.fromisoformat(raw)
    except ValueError:
        raise _query_param_error('date must be in YYYY-MM-DD format.')


def _eligible_providers(
    *, tenant: Tenant, service: Service, location: Location,
) -> list[TenantMembership]:
    """Bookable + active + assigned to location + job-title-eligible.

    Single query against MembershipLocation. Job-title eligibility is
    checked in Python because the category may have zero eligible
    titles (= "no restriction"); expressing that as SQL makes the
    query unreadable.
    """
    assignments = (
        MembershipLocation.objects
        .filter(
            location=location,
            is_active=True,
            membership__tenant=tenant,
            membership__is_active=True,
            membership__is_bookable=True,
        )
        .select_related('membership__user', 'membership__job_title')
    )
    eligible_title_ids = (
        list(service.category.eligible_job_titles.values_list('id', flat=True))
        if service.category_id else []
    )
    out: list[TenantMembership] = []
    for asn in assignments:
        membership = asn.membership
        if eligible_title_ids:
            if not membership.job_title_id or membership.job_title_id not in eligible_title_ids:
                continue
        out.append(membership)
    out.sort(key=lambda m: (m.user.first_name or m.user.email))
    return out


def _resolve_eligible_provider(
    *, tenant: Tenant, service: Service, location: Location, provider_id: int,
) -> TenantMembership:
    for p in _eligible_providers(tenant=tenant, service=service, location=location):
        if p.pk == provider_id:
            return p
    raise _BookingError('That provider cannot perform this service at this location.')


def _resolve_appointment_by_token(token: str) -> Appointment:
    if not token:
        from django.http import Http404
        raise Http404('No such booking.')
    return get_object_or_404(
        Appointment.objects
        .select_related('tenant', 'service', 'provider__user', 'location', 'customer'),
        booking_token=token,
    )


def _provider_display_name(provider: TenantMembership) -> str:
    user = provider.user
    first = (user.first_name or '').strip() or user.email.split('@')[0]
    last = (user.last_name or '').strip()
    if last:
        return f'{first} {last[0]}.'
    return first


def _query_param_error(message: str):
    """Raise a DRF ValidationError for a query-string problem.

    Wrapped in a function so each helper raises consistently and the
    caller doesn't have to import DRF exceptions everywhere.
    """
    from rest_framework.exceptions import ValidationError as DRFValidationError
    return DRFValidationError({'detail': message})
