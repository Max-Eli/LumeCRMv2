"""Appointment booking model — the centerpiece of the CRM.

An `Appointment` ties a customer to a provider, a service, a `Location`,
and a time block. Provider is a `TenantMembership` (the staff member
assigned, must be bookable AND assigned to the appointment's location);
service is what's being performed; customer is who's receiving it.

Multi-location: every appointment belongs to one site within the
tenant. The calendar at the LA location only shows LA appointments;
booking creates an appointment at the active location. Provider
eligibility for a location is enforced via `MembershipLocation` —
the API rejects bookings where the chosen provider isn't assigned to
the site (defense in depth: the FE only offers location-eligible
providers via `?location=current`, but the API enforces it).

Status lifecycle:

    booked  ─►  confirmed  ─►  checked_in  ─►  completed
        │           │             │
        ▼           ▼             ▼
    cancelled   cancelled    no_show

Times are stored in UTC (`USE_TZ=True`); display layer renders in the
location's timezone (`Location.timezone`). The model enforces that
`end_time > start_time` via a check constraint. Conflict detection
(overlap with another appointment for the same provider) lives in the
validation layer of `perform_create`, not in the database — see
Phase 1C session 3.

Eligibility (whether the chosen provider's `job_title` is allowed to
perform the service's `category`) is enforced at the API layer, not
in the database.
"""

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.tenants.abstract_models import TenantedModel


class Appointment(TenantedModel):
    """A scheduled service booking for a single customer + provider + time block."""

    class Status(models.TextChoices):
        BOOKED = 'booked', 'Booked'
        CONFIRMED = 'confirmed', 'Confirmed'
        CHECKED_IN = 'checked_in', 'Checked in'
        COMPLETED = 'completed', 'Completed'
        NO_SHOW = 'no_show', 'No-show'
        CANCELLED = 'cancelled', 'Cancelled'

    customer = models.ForeignKey(
        'customers.Customer',
        on_delete=models.PROTECT,
        related_name='appointments',
    )
    provider = models.ForeignKey(
        'tenants.TenantMembership',
        on_delete=models.PROTECT,
        related_name='appointments',
        help_text=(
            'Staff member performing the service. Must have is_bookable=True '
            'AND be assigned (via MembershipLocation) to the appointment\'s '
            'location.'
        ),
    )
    service = models.ForeignKey(
        'services.Service',
        on_delete=models.PROTECT,
        related_name='appointments',
    )
    # Site where this appointment happens. Per-tenant data is split by
    # location (calendar, reports, day-window timezone all scope here).
    # Required: API defaults it from `request.location` when the caller
    # doesn't provide one, so the FE doesn't have to think about it. The
    # column was added across three migrations (0002 nullable add, 0003
    # backfill from tenant default, 0004 alter to non-null) — see those
    # migrations for the rollout discipline.
    #
    # PROTECT (not CASCADE) because deleting a location with appointments
    # would orphan financial / audit history. Soft-delete via
    # `is_active=False` is the only path; the API doesn't expose hard
    # delete, and Django admin requires manual reassignment first.
    location = models.ForeignKey(
        'tenants.Location',
        on_delete=models.PROTECT,
        related_name='appointments',
    )

    start_time = models.DateTimeField(db_index=True)
    end_time = models.DateTimeField()
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.BOOKED,
        db_index=True,
    )
    notes = models.TextField(blank=True, help_text='Internal notes visible to staff.')

    # Provenance — set when an appointment is auto-created by online booking,
    # imported from Zenoti, etc. Free-form for now.
    source = models.CharField(
        max_length=50,
        blank=True,
        help_text="e.g. 'staff', 'online', 'zenoti_import'",
    )

    # Importer-set provenance. `external_id` is the upstream system's
    # unique identifier (e.g. Zenoti's Invoice No on the appointment
    # row). The importer uses `(tenant, external_source, external_id)`
    # for idempotent upsert. Mirrors the pattern on Customer + Service
    # + PurchasedPackage.
    external_id = models.CharField(max_length=100, blank=True, db_index=True)
    external_source = models.CharField(
        max_length=50, blank=True,
        help_text="e.g. 'zenoti', 'vagaro'",
    )
    imported_at = models.DateTimeField(null=True, blank=True)

    # Tokenized public-manage URL — set when source='online' so the
    # confirmation email can link to /book/manage/<token> for
    # reschedule + cancel WITHOUT login. 256-bit entropy via
    # secrets.token_urlsafe(32). Empty for staff-created appointments
    # (no public manage flow there). Single-use semantics aren't
    # enforced — multiple lookups are fine; state transitions are
    # what matter (status flips). Tokens never expire (a customer
    # might reschedule months out); revocation = setting status to
    # CANCELLED, which the manage page handles.
    booking_token = models.CharField(
        max_length=64,
        blank=True,
        default='',
        db_index=True,
    )

    # When the customer checked in / completed / no-show'd — useful for SLAs and
    # audit. Nullable; populated by status transitions.
    checked_in_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_reason = models.CharField(max_length=200, blank=True)

    # Transactional SMS tracking. `*_sent_at` is the timestamp the send
    # request was handed to Twilio; `*_provider_id` stores the Twilio
    # Message SID so a future status-callback path can correlate
    # delivery / failure updates back to this row. Idempotency: the
    # signal handler + reminder command both check `*_sent_at IS NULL`
    # before sending, so a redeploy + race + retry never double-sends
    # the same notification. ADR 0021.
    confirmation_sms_sent_at = models.DateTimeField(null=True, blank=True)
    confirmation_sms_provider_id = models.CharField(max_length=64, blank=True, default='')
    reminder_sms_sent_at = models.DateTimeField(null=True, blank=True)
    reminder_sms_provider_id = models.CharField(max_length=64, blank=True, default='')
    # Post-appointment review-request SMS. Sent N hours after
    # completion (`Tenant.review_request_hours_after`) when the tenant
    # has explicitly enabled the automation and set a Google review
    # URL. Idempotency posture identical to confirmation + reminder.
    review_request_sms_sent_at = models.DateTimeField(null=True, blank=True)
    review_request_sms_provider_id = models.CharField(max_length=64, blank=True, default='')

    # Snapshot of price at booking time so subsequent service price changes
    # don't retroactively alter quoted appointments. Cents. This is the
    # PRIMARY service's price — additional services live on
    # `AppointmentService` rows, each carrying their own snapshot.
    quoted_price_cents = models.PositiveIntegerField(default=0)

    # The invoice line that bills the primary service. Set by the
    # invoice-creation signal so the "change service" action can update
    # the exact line without guessing. Nullable: rows created before
    # multi-service support, or whose line was manually removed on the
    # invoice page, simply skip invoice sync. SET_NULL so deleting a
    # line never cascades into the appointment.
    primary_invoice_line = models.OneToOneField(
        'invoices.InvoiceLineItem',
        on_delete=models.SET_NULL,
        related_name='+',
        null=True,
        blank=True,
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='appointments_created',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['start_time']
        indexes = [
            models.Index(fields=['tenant', 'start_time']),
            models.Index(fields=['tenant', 'provider', 'start_time']),
            models.Index(fields=['tenant', 'customer', '-start_time']),
            models.Index(fields=['tenant', 'status', 'start_time']),
            # Hot path for the per-location calendar query: every day
            # view filters by tenant + location + start_time window.
            models.Index(fields=['tenant', 'location', 'start_time']),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(end_time__gt=models.F('start_time')),
                name='appointments_end_after_start',
            ),
        ]

    def __str__(self):
        when = timezone.localtime(self.start_time).strftime('%Y-%m-%d %H:%M')
        return f'{self.customer.full_name} · {self.service.name} · {when}'

    @property
    def duration_minutes(self) -> int:
        """Compute the booking length in whole minutes."""
        delta = self.end_time - self.start_time
        return int(delta.total_seconds() // 60)

    @property
    def total_price_cents(self) -> int:
        """Primary service price plus every additional service. Used by
        the calendar to show the full quote for a multi-service visit."""
        extras = sum(es.price_cents for es in self.extra_services.all())
        return self.quoted_price_cents + extras


class AppointmentService(models.Model):
    """An additional service performed at an appointment, beyond the
    primary `Appointment.service`.

    A single visit often covers more than one service — a Facial plus
    a Botox touch-up. The primary service stays on the `Appointment`
    row (so the booking flow, imports, and reports are untouched);
    these rows are the extras the front desk adds afterward.

    `price_cents` / `duration_minutes` are snapshotted at add time so a
    later catalog edit can't move a booked appointment. `invoice_line`
    links to the line this service generated on the still-open invoice,
    so removing the service also backs the charge out cleanly.
    """

    appointment = models.ForeignKey(
        Appointment,
        on_delete=models.CASCADE,
        related_name='extra_services',
    )
    service = models.ForeignKey(
        'services.Service',
        on_delete=models.PROTECT,
        related_name='+',
    )
    # Optional per-service provider override. NULL means "performed by
    # the appointment's primary provider" — the common case for a
    # single-room visit. Set when an extra service is performed by a
    # different staff member (e.g. Botox by the NP, facial right after
    # by an esthetician). Stored as `TenantMembership` (same shape as
    # `Appointment.provider`) so commissions / per-provider reports can
    # attribute the line correctly.
    provider = models.ForeignKey(
        'tenants.TenantMembership',
        on_delete=models.PROTECT,
        related_name='+',
        null=True,
        blank=True,
        help_text=(
            'Staff member performing this service. Null inherits the '
            "appointment's primary provider."
        ),
    )
    price_cents = models.PositiveIntegerField(
        default=0,
        help_text='Snapshot of the service price when it was added.',
    )
    duration_minutes = models.PositiveIntegerField(
        default=0,
        help_text='Snapshot of the service duration when it was added.',
    )
    invoice_line = models.OneToOneField(
        'invoices.InvoiceLineItem',
        on_delete=models.SET_NULL,
        related_name='+',
        null=True,
        blank=True,
        help_text=(
            'The invoice line this service generated. Null once the '
            'line is removed, or when the invoice could not be synced.'
        ),
    )
    sort_order = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def effective_provider(self):
        """The staff member actually performing this service — the
        per-service override if set, else the appointment's primary
        provider. Reads cleanly in templates / serializers without the
        caller having to remember the fallback."""
        return self.provider or self.appointment.provider

    class Meta:
        ordering = ['sort_order', 'id']
        indexes = [
            models.Index(fields=['appointment', 'sort_order']),
        ]

    def __str__(self):
        return f'{self.appointment_id} · +{self.service.name}'


class TimeBlock(TenantedModel):
    """A non-bookable period on a provider's calendar — lunch break,
    personal time, training. Visually shaded on the day view; the
    booking-availability engine treats the slot as taken the same way
    an appointment does, so the public booking page won't offer it.

    Distinct from `Appointment` because there's no customer, service,
    or invoice — a block is operational scheduling, not a billable
    event. The provider + location + time-window shape is identical
    so we reuse the same per-location calendar filter.

    ## Compliance posture

    ### HIPAA
    A block is not PHI on its own (no patient identifier), but it
    appears on the same calendar that displays PHI and is therefore
    audit-logged on create/update/delete — HIPAA §164.312(b). The
    audit trail answers "who hid time on whose calendar and when",
    which we'd be asked for during a compliance review of any
    appointment that fell behind because of a hidden block.
    """

    provider = models.ForeignKey(
        'tenants.TenantMembership',
        on_delete=models.PROTECT,
        related_name='time_blocks',
        help_text='The staff member whose calendar is being blocked.',
    )
    # Same per-site scoping as Appointment — a block lives at one
    # location even when the provider works at several.
    location = models.ForeignKey(
        'tenants.Location',
        on_delete=models.PROTECT,
        related_name='time_blocks',
    )
    start_time = models.DateTimeField(db_index=True)
    end_time = models.DateTimeField()
    # Free-form text so the frontend can offer presets ("Lunch",
    # "Personal time") and an "Other" fallback without us having to
    # extend a Django TextChoices every time a tenant invents a new
    # category.
    reason = models.CharField(
        max_length=200,
        help_text=(
            'Why the time is blocked. Frontend offers presets '
            '(Lunch, Personal time, Training, Meeting, Admin, Out of '
            'office) plus a free-form Other.'
        ),
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='time_blocks_created',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['start_time']
        indexes = [
            models.Index(fields=['tenant', 'location', 'start_time']),
            models.Index(fields=['tenant', 'provider', 'start_time']),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(end_time__gt=models.F('start_time')),
                name='time_blocks_end_after_start',
            ),
        ]

    def __str__(self):
        when = timezone.localtime(self.start_time).strftime('%Y-%m-%d %H:%M')
        return f'{self.provider} · {self.reason} · {when}'

    @property
    def duration_minutes(self) -> int:
        """Block length in whole minutes — same shape the calendar uses
        for appointments so the day-view block component can size both
        the same way."""
        delta = self.end_time - self.start_time
        return int(delta.total_seconds() // 60)
