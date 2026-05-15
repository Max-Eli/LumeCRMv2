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


# ── Memberships ─────────────────────────────────────────────────────


class PortalSubscriptionSerializer(serializers.Serializer):
    """One row of the customer's membership history. Read-only — the
    portal never lets a customer change subscription state."""

    id = serializers.IntegerField()
    name = serializers.CharField()
    description = serializers.CharField(allow_blank=True)
    status = serializers.CharField()
    status_display = serializers.SerializerMethodField()
    price_cents = serializers.IntegerField()
    billing_interval = serializers.CharField()
    member_discount_percent = serializers.DecimalField(
        max_digits=5, decimal_places=2,
    )
    started_at = serializers.DateTimeField(allow_null=True)
    current_period_starts_at = serializers.DateTimeField(allow_null=True)
    current_period_ends_at = serializers.DateTimeField(allow_null=True)
    cancelled_at = serializers.DateTimeField(allow_null=True)
    auto_renew = serializers.BooleanField()

    def get_status_display(self, obj) -> str:
        return obj.get_status_display()


# ── Packages ────────────────────────────────────────────────────────


class PortalPackageItemSerializer(serializers.Serializer):
    """One service line of a purchased package + remaining sessions."""

    service_name = serializers.CharField()
    quantity_purchased = serializers.IntegerField()
    quantity_remaining = serializers.IntegerField()


class PortalPackageSerializer(serializers.Serializer):
    """One row of the customer's packages. Strictly the customer-
    facing slice — no internal pricing snapshots, no redemption
    ledger, just what the client needs to know about their own
    sessions."""

    id = serializers.IntegerField()
    name = serializers.CharField()
    description = serializers.CharField(allow_blank=True)
    status = serializers.CharField()
    price_cents = serializers.IntegerField()
    purchased_at = serializers.DateTimeField(allow_null=True)
    expires_at = serializers.DateTimeField(allow_null=True)
    is_expired = serializers.BooleanField()
    total_credits_remaining = serializers.IntegerField()
    items = PortalPackageItemSerializer(many=True)


# ── Forms ───────────────────────────────────────────────────────────


class PortalFormSubmissionSerializer(serializers.Serializer):
    """One row of the customer's form history. Lists status +
    template name + the tokenized sign URL for pending forms.

    Answers and signature data are PHI — they are NOT included in
    the list view, even though it's the customer's own data. A
    future detail endpoint can return them with the same audit
    posture as the staff path."""

    id = serializers.IntegerField()
    template_name = serializers.CharField()
    template_form_type = serializers.CharField()
    status = serializers.CharField()
    status_display = serializers.SerializerMethodField()
    sign_url = serializers.SerializerMethodField()
    signed_at = serializers.DateTimeField(allow_null=True)
    voided_at = serializers.DateTimeField(allow_null=True)
    created_at = serializers.DateTimeField()

    def get_status_display(self, obj) -> str:
        return obj.get_status_display()

    def get_sign_url(self, obj) -> str | None:
        """Frontend route for the tokenized fill flow. Only emitted
        for pending submissions — completed or voided forms don't
        need a sign link."""
        if obj.status != obj.Status.PENDING:
            return None
        return f'/sign/{obj.token}'


# ── Book appointment (portal-authed) ───────────────────────────────


class PortalBookingInputSerializer(serializers.Serializer):
    """Payload for the portal-authed booking submit endpoint.

    Distinct from the public booking submit:
      - No customer name/email/phone/marketing consent — the
        customer is already authenticated via portal session, so
        we use `request.customer` instead.
      - No CAPTCHA / rate-limit-extras — session cookie is the
        identity gate; we still rely on view-level rate limiting.
    """

    service_id = serializers.IntegerField()
    provider_id = serializers.IntegerField()
    location_id = serializers.IntegerField(required=False)
    start_time = serializers.DateTimeField()
    notes = serializers.CharField(required=False, allow_blank=True, default='')
