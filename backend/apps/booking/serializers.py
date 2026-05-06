"""Serializers for the public booking API.

Two flavors:

  - Read serializers (TenantInfoSerializer, BookableServiceSerializer,
    EligibleProviderSerializer, AvailableSlotSerializer) shape the
    payloads the public booking page consumes. They expose the
    minimum a stranger should see — name, duration, price, photos —
    NEVER staff-internal flags, payroll, or PHI.

  - Write serializer (SubmitBookingInputSerializer) validates the
    submit-booking POST. Lightweight here: required-fields + format
    checks. Cross-field correctness (service belongs to tenant,
    provider eligible, slot still free) lives in the view because
    it needs DB lookups against the resolved tenant.

The manage-by-token endpoint uses ManageBookingSerializer to render
the customer-facing detail. Same minimum-disclosure posture: no
internal notes, no audit fields.
"""

from __future__ import annotations

from rest_framework import serializers

from apps.appointments.models import Appointment
from apps.services.models import Service
from apps.tenants.models import Location, Tenant, TenantMembership


class BookingLocationSerializer(serializers.ModelSerializer):
    """Public-safe location summary (the customer-facing branding view).

    Excludes internal flags, employee email, etc. Address + hours +
    timezone are public information already (Google Maps lists them).
    """

    class Meta:
        model = Location
        fields = [
            'id', 'name', 'slug', 'timezone',
            'address_line1', 'address_line2', 'city', 'state', 'zip_code',
            'phone', 'business_open_time', 'business_close_time',
        ]


class TenantInfoSerializer(serializers.ModelSerializer):
    """Top-of-funnel payload: spa name + branding + bookable locations
    + customer-facing copy.

    The booking page renders the spa's primary color + logo around the
    flow so the customer feels like they're on the spa's site, not a
    generic Lumè page. Locations array drives the multi-site picker
    (single-location spas get the picker auto-resolved). Welcome
    message + cancellation policy come from the operator-edited
    settings — both optional, both shown only when populated.
    """

    locations = serializers.SerializerMethodField()
    welcome_message = serializers.CharField(
        source='online_booking_welcome_message', read_only=True,
    )
    cancellation_policy = serializers.CharField(
        source='online_booking_cancellation_policy', read_only=True,
    )
    # Window in days, surfaced to the public so the frontend calendar
    # can disable dates beyond what the slots endpoint will honor —
    # avoids the customer clicking far-out dates and getting "no
    # availability" with no explanation.
    booking_window_days = serializers.IntegerField(
        source='online_booking_window_days', read_only=True,
    )

    class Meta:
        model = Tenant
        fields = [
            'name', 'slug', 'primary_color', 'logo_url',
            'welcome_message', 'cancellation_policy',
            'booking_window_days',
            'locations',
        ]

    def get_locations(self, tenant: Tenant) -> list[dict]:
        qs = tenant.locations.filter(is_active=True).order_by('-is_default', 'name')
        return BookingLocationSerializer(qs, many=True).data


class BookableServiceSerializer(serializers.ModelSerializer):
    """Catalog entry shown to a customer picking a service.

    `duration_minutes` is what the customer sees — the buffer is
    internal scheduling and stays out of public payloads. `price_cents`
    is exposed so the page can render "from $X" style copy; tax is
    layered on at booking confirmation, not here.
    """

    category_name = serializers.CharField(source='category.name', default='', read_only=True)
    category_color = serializers.CharField(source='category.color', default='', read_only=True)

    class Meta:
        model = Service
        fields = [
            'id', 'name', 'description',
            'duration_minutes', 'price_cents',
            'category_name', 'category_color',
        ]


class EligibleProviderSerializer(serializers.Serializer):
    """Provider summary for the public picker.

    Membership-shaped because that's what the rest of the booking
    flow uses as the canonical "provider" reference. Only first name +
    last initial — the public flow doesn't need (or want) full last
    names plastered on the page.
    """

    id = serializers.IntegerField()
    display_name = serializers.CharField()
    job_title = serializers.CharField()


class AvailableSlotSerializer(serializers.Serializer):
    """One slot in the customer's view of the day.

    `available=False` means the slot is taken (existing booking
    overlaps) or sits inside the lead-time buffer ("too soon"). The
    UI renders these grayed-out instead of hiding them, so customers
    can see the full availability picture rather than confusing gaps.

    The backend re-validates the picked slot at submit-time, so a
    stale UI sneaking in an unavailable start_time still loses to
    409 cleanly.
    """

    start = serializers.DateTimeField()
    end = serializers.DateTimeField()
    available = serializers.BooleanField(default=True)
    provider_id = serializers.IntegerField(required=False, allow_null=True)


class SubmitBookingInputSerializer(serializers.Serializer):
    """Body validation for `POST /api/booking/<slug>/book/`.

    Cross-field validation (service in tenant, provider eligibility,
    slot still free) happens in the view — this serializer only
    enforces required-fields + basic format. Keeps the serializer
    side-effect-free and the view's authority over availability
    re-verification clear.
    """

    service_id = serializers.IntegerField()
    provider_id = serializers.IntegerField()
    location_id = serializers.IntegerField()
    start_time = serializers.DateTimeField()

    customer_first_name = serializers.CharField(max_length=100)
    customer_last_name = serializers.CharField(max_length=100)
    customer_email = serializers.EmailField(max_length=254)
    customer_phone = serializers.CharField(max_length=20)

    notes = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=500,
        help_text='Optional message to the spa from the customer.',
    )

    # Marketing consent capture (Phase 1L, ADR 0016). Both default
    # False; the booking page renders explicit checkboxes per channel.
    # Setting either True triggers the corresponding consent_at +
    # consent_source fields on the Customer record so we have the
    # legally-defensible record of WHEN + HOW the customer opted in.
    email_marketing_opt_in = serializers.BooleanField(default=False, required=False)
    sms_marketing_opt_in = serializers.BooleanField(default=False, required=False)


class RescheduleBookingInputSerializer(serializers.Serializer):
    """Body validation for `POST /api/booking/manage/<token>/reschedule/`.

    Customer picks a new `start_time` (UTC ISO datetime). Provider +
    location + service are inherited from the existing appointment —
    they don't change in a reschedule. The new start must be a real
    available slot for the same provider, validated server-side
    against the same calculator the public picker uses.
    """

    start_time = serializers.DateTimeField()


class BookingConfirmationSerializer(serializers.ModelSerializer):
    """Post-submit response — what the confirmation page renders.

    Includes the `booking_token` so the client can deep-link straight
    to `/book/manage/<token>` after submit (no email roundtrip
    required for the immediate UX). The token also lands in the
    confirmation email.
    """

    service_name = serializers.CharField(source='service.name', read_only=True)
    duration_minutes = serializers.IntegerField(source='service.duration_minutes', read_only=True)
    location_name = serializers.CharField(source='location.name', read_only=True)
    provider_display_name = serializers.SerializerMethodField()

    class Meta:
        model = Appointment
        fields = [
            'id',
            'booking_token',
            'start_time', 'end_time',
            'service_name', 'duration_minutes',
            'location_name',
            'provider_display_name',
            'quoted_price_cents',
            'status',
        ]

    def get_provider_display_name(self, appointment: Appointment) -> str:
        return _provider_display_name(appointment.provider)


class ManageBookingSerializer(serializers.ModelSerializer):
    """`GET /api/booking/manage/<token>/` payload.

    Same shape as confirmation but adds tenant branding so the manage
    page can render in the spa's theme without a separate fetch.
    Customer fields included so the page can show "Hi, Jane —" without
    requiring login. Internal `notes` is NOT exposed — that's staff-only.
    """

    service_id = serializers.IntegerField(source='service.id', read_only=True)
    service_name = serializers.CharField(source='service.name', read_only=True)
    duration_minutes = serializers.IntegerField(source='service.duration_minutes', read_only=True)
    location = BookingLocationSerializer(read_only=True)
    provider_id = serializers.IntegerField(source='provider.id', read_only=True)
    provider_display_name = serializers.SerializerMethodField()
    customer_first_name = serializers.CharField(source='customer.first_name', read_only=True)
    customer_last_name = serializers.CharField(source='customer.last_name', read_only=True)
    customer_email = serializers.EmailField(source='customer.email', read_only=True)
    tenant = serializers.SerializerMethodField()

    class Meta:
        model = Appointment
        fields = [
            'id',
            'booking_token',
            'start_time', 'end_time',
            'service_id', 'service_name', 'duration_minutes',
            'location',
            'provider_id', 'provider_display_name',
            'customer_first_name', 'customer_last_name', 'customer_email',
            'quoted_price_cents',
            'status',
            'tenant',
        ]

    def get_provider_display_name(self, appointment: Appointment) -> str:
        return _provider_display_name(appointment.provider)

    def get_tenant(self, appointment: Appointment) -> dict:
        t = appointment.tenant
        return {
            'name': t.name,
            'slug': t.slug,
            'primary_color': t.primary_color,
            'logo_url': t.logo_url,
            # Policy travels alongside the booking detail so the manage
            # page renders it without a second tenant-info fetch (and
            # without coupling the manage page to whether the booking
            # surface is currently enabled — the policy is still
            # informative even after the killswitch flips).
            'cancellation_policy': t.online_booking_cancellation_policy,
        }


# ── Helpers ──────────────────────────────────────────────────────────


def _provider_display_name(provider: TenantMembership) -> str:
    """First name + last initial. Public flow doesn't show full last
    names — friendlier and a small data-minimization win."""
    user = provider.user
    first = (user.first_name or '').strip() or user.email.split('@')[0]
    last = (user.last_name or '').strip()
    if last:
        return f'{first} {last[0]}.'
    return first
