"""Read/write shapes for the portal API.

Designed for customer self-service — fields are deliberately narrower
than the staff-facing equivalents. No PHI that the customer doesn't
already know about themselves (we don't return chart notes, treatment
history, internal staff notes, etc.).
"""

from __future__ import annotations

from rest_framework import serializers

from apps.appointments.models import Appointment


class TenantBrandingSerializer(serializers.Serializer):
    """Slice of Tenant we expose to the public portal — name, primary
    color, logo URL. No revenue figures, no internal state."""

    name = serializers.CharField()
    slug = serializers.CharField()
    primary_color = serializers.CharField()
    logo_url = serializers.CharField(allow_blank=True)


class CustomerMeSerializer(serializers.Serializer):
    """The signed-in customer's own profile + their tenant's branding.

    Marketing-consent toggles are writable via the profile-update
    endpoint; everything else is read-only here (an edit-profile flow
    that lets the customer change name + DOB would be its own
    endpoint with stronger audit semantics)."""

    id = serializers.IntegerField()
    first_name = serializers.CharField()
    last_name = serializers.CharField()
    email = serializers.CharField()
    phone = serializers.CharField()
    email_marketing_opt_in = serializers.BooleanField()
    sms_marketing_opt_in = serializers.BooleanField()
    sms_opt_in = serializers.BooleanField()
    tenant = TenantBrandingSerializer()


class ProfileUpdateInputSerializer(serializers.Serializer):
    """Customer-editable profile fields. Constrained to non-PHI,
    non-identity fields so the customer can't impersonate someone
    else by changing their own name/DOB and asking for a magic link
    again. Name + DOB changes go through staff for that reason."""

    phone = serializers.CharField(
        max_length=20, required=False, allow_blank=True, trim_whitespace=True,
    )
    email_marketing_opt_in = serializers.BooleanField(required=False)
    sms_marketing_opt_in = serializers.BooleanField(required=False)


class PortalAppointmentSerializer(serializers.Serializer):
    """Single appointment row for the portal's appointment list.

    No internal `notes`, no provider commission info, no source
    metadata — just what the customer needs to recognise + manage
    the appointment."""

    id = serializers.IntegerField()
    start_time = serializers.DateTimeField()
    end_time = serializers.DateTimeField()
    status = serializers.CharField()
    status_display = serializers.SerializerMethodField()
    service_name = serializers.CharField(source='service.name')
    service_duration_minutes = serializers.IntegerField(source='service.duration_minutes')
    provider_name = serializers.SerializerMethodField()
    location_name = serializers.CharField(source='location.name')
    location_timezone = serializers.CharField(source='location.timezone')
    cancellable = serializers.SerializerMethodField()

    def get_status_display(self, obj: Appointment) -> str:
        return obj.get_status_display()

    def get_provider_name(self, obj: Appointment) -> str:
        membership = obj.provider
        user = getattr(membership, 'user', None)
        if user is None:
            return ''
        full = f'{user.first_name} {user.last_name}'.strip()
        return full or user.email

    def get_cancellable(self, obj: Appointment) -> bool:
        # Customer can self-cancel a booked/confirmed future appointment.
        # Past appointments + already-cancelled/no-show/completed rows
        # are not actionable from the portal.
        from django.utils import timezone as djtz
        if obj.start_time <= djtz.now():
            return False
        return obj.status in (
            Appointment.Status.BOOKED,
            Appointment.Status.CONFIRMED,
        )


class RequestMagicLinkInputSerializer(serializers.Serializer):
    """Login form input. Email-only; we don't ask for a password."""

    email = serializers.EmailField(max_length=254)
