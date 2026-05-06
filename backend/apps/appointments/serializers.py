"""DRF serializers for the appointments API.

`AppointmentSerializer` is one shape used for list + detail. List payloads need
enough context to render a calendar block without an N+1 round-trip, so we
include nested summaries of the customer, provider, and service rather than
just IDs. Mutations accept `customer_id`, `provider_id`, and `service_id`.
"""

from rest_framework import serializers

from apps.customers.models import Customer
from apps.services.models import Service
from apps.tenants.models import Location, MembershipLocation, TenantMembership

from .models import Appointment


class _CustomerSummary(serializers.ModelSerializer):
    full_name = serializers.CharField(read_only=True)

    class Meta:
        model = Customer
        fields = ['id', 'first_name', 'last_name', 'preferred_name', 'full_name', 'phone']
        read_only_fields = fields


class _ServiceSummary(serializers.ModelSerializer):
    category_id = serializers.IntegerField(read_only=True)
    category_name = serializers.SerializerMethodField()
    category_color = serializers.SerializerMethodField()

    class Meta:
        model = Service
        fields = [
            'id', 'name', 'code',
            'duration_minutes', 'buffer_minutes',
            'price_cents',
            'category_id', 'category_name', 'category_color',
        ]
        read_only_fields = fields

    def get_category_name(self, obj: Service) -> str | None:
        return obj.category.name if obj.category else None

    def get_category_color(self, obj: Service) -> str | None:
        return obj.category.color if obj.category else None


class _ProviderSummary(serializers.ModelSerializer):
    """Compact representation of a TenantMembership in the provider role context."""
    user_email = serializers.CharField(source='user.email', read_only=True)
    user_first_name = serializers.CharField(source='user.first_name', read_only=True)
    user_last_name = serializers.CharField(source='user.last_name', read_only=True)
    job_title_name = serializers.SerializerMethodField()

    class Meta:
        model = TenantMembership
        fields = [
            'id',
            'user_email', 'user_first_name', 'user_last_name',
            'job_title_id',
            'job_title_name',
            'role',
            'is_bookable',
        ]
        read_only_fields = fields

    def get_job_title_name(self, obj: TenantMembership) -> str | None:
        return obj.job_title.name if obj.job_title_id else None


class AppointmentSerializer(serializers.ModelSerializer):
    customer = _CustomerSummary(read_only=True)
    service = _ServiceSummary(read_only=True)
    provider = _ProviderSummary(read_only=True)

    customer_id = serializers.PrimaryKeyRelatedField(
        queryset=Customer.objects.all(),
        write_only=True,
        source='customer',
    )
    service_id = serializers.PrimaryKeyRelatedField(
        queryset=Service.objects.all(),
        write_only=True,
        source='service',
    )
    provider_id = serializers.PrimaryKeyRelatedField(
        queryset=TenantMembership.objects.all(),
        write_only=True,
        source='provider',
    )
    # Location: writable on create (defaulted from `request.location` in
    # the view if omitted), readable on every response so multi-location
    # frontends can disambiguate cross-location result sets without an
    # extra round-trip to /api/locations/. Read-only on update — moving
    # an existing appointment between sites is a non-trivial action that
    # would need a deliberate flow (it affects the location's calendar
    # density, the booked staff member's location assignment, and any
    # site-specific reporting). Not exposed today.
    location_id = serializers.PrimaryKeyRelatedField(
        queryset=Location.objects.all(),
        source='location',
        required=False,
    )

    duration_minutes = serializers.IntegerField(read_only=True)

    class Meta:
        model = Appointment
        fields = [
            'id',
            'customer', 'customer_id',
            'provider', 'provider_id',
            'service', 'service_id',
            'location_id',
            'start_time', 'end_time', 'duration_minutes',
            'status',
            'notes',
            'source',
            'checked_in_at', 'completed_at', 'cancelled_at', 'cancelled_reason',
            'quoted_price_cents',
            'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id',
            'customer', 'provider', 'service',
            'duration_minutes',
            'checked_in_at', 'completed_at', 'cancelled_at',
            'created_at', 'updated_at',
        ]

    # Status state machine — each entry maps from-status → set of allowed
    # to-statuses. Terminal states accept no further transitions; the
    # appointment's history is closed.
    #
    # NOTE: `COMPLETED` is intentionally absent from every transition set.
    # The only code path that may write `Appointment.status = COMPLETED`
    # is `Invoice.close()`, which runs inside a transaction with the
    # invoice update so the financial event and the appointment-side
    # state change are atomic and audit-logged together. See ADR 0007.
    _STATUS_TRANSITIONS: dict[str, frozenset[str]] = {
        Appointment.Status.BOOKED: frozenset({
            Appointment.Status.CONFIRMED,
            Appointment.Status.CHECKED_IN,
            Appointment.Status.CANCELLED,
            Appointment.Status.NO_SHOW,
        }),
        Appointment.Status.CONFIRMED: frozenset({
            Appointment.Status.CHECKED_IN,
            Appointment.Status.CANCELLED,
            Appointment.Status.NO_SHOW,
        }),
        Appointment.Status.CHECKED_IN: frozenset({
            # COMPLETED removed — see note above.
            # CONFIRMED allowed so the front desk can undo a mistaken
            # check-in (e.g. wrong customer button); when this transition
            # is taken, `checked_in_at` is cleared on the model side
            # since the customer never actually checked in.
            Appointment.Status.CONFIRMED,
            Appointment.Status.CANCELLED,
            Appointment.Status.NO_SHOW,
        }),
        Appointment.Status.COMPLETED: frozenset(),
        Appointment.Status.CANCELLED: frozenset(),
        Appointment.Status.NO_SHOW: frozenset(),
    }

    def validate_location_id(self, value):
        # Cross-tenant guard: a malicious caller can't pass a location
        # id from a different tenant. The PrimaryKeyRelatedField queryset
        # is unrestricted (matches the existing pattern for customer /
        # provider / service); we enforce tenant scope here so the
        # validation error is field-level and friendly.
        from apps.tenants.context import get_current_tenant
        tenant = get_current_tenant()
        if tenant is None:
            raise serializers.ValidationError(
                'No tenant context resolved; cannot validate location.',
            )
        if value.tenant_id != tenant.id:
            raise serializers.ValidationError(
                'Location does not belong to this tenant.',
            )
        if not value.is_active:
            raise serializers.ValidationError(
                'Cannot book at an inactive location.',
            )
        return value

    def validate(self, attrs):
        start = attrs.get('start_time') or getattr(self.instance, 'start_time', None)
        end = attrs.get('end_time') or getattr(self.instance, 'end_time', None)
        if start and end and end <= start:
            raise serializers.ValidationError({'end_time': 'Must be after start_time.'})

        new_status = attrs.get('status')
        if new_status and self.instance and new_status != self.instance.status:
            # Special-case `completed`: never reachable through this
            # serializer. Surface a guidance message that points the
            # caller at the correct flow instead of a generic transition
            # error, since this is the most likely place to confuse a
            # new integrator.
            if new_status == Appointment.Status.COMPLETED:
                raise serializers.ValidationError({
                    'status': (
                        'Appointments cannot be marked completed directly. '
                        'Completion happens automatically when the invoice is '
                        'closed (payment taken). POST '
                        '/api/invoices/<invoice_id>/close/ instead.'
                    ),
                })

            allowed = self._STATUS_TRANSITIONS.get(self.instance.status, frozenset())
            if new_status not in allowed:
                allowed_list = sorted(allowed)
                detail = (
                    f'Cannot transition from "{self.instance.status}" to "{new_status}". '
                    + (
                        f'Allowed transitions: {", ".join(allowed_list)}.'
                        if allowed_list
                        else 'This appointment is in a terminal state — no further transitions allowed.'
                    )
                )
                raise serializers.ValidationError({'status': detail})

        # Eligibility — provider's job_title must be allowed by the service
        # category's `eligible_job_titles` (or category has no rules). Defense
        # in depth: the frontend filters drop targets, but the API enforces.
        provider = attrs.get('provider') or getattr(self.instance, 'provider', None)
        service = attrs.get('service') or getattr(self.instance, 'service', None)
        if provider and service and service.category_id:
            category = service.category
            eligible_ids = list(
                category.eligible_job_titles.values_list('id', flat=True),
            )
            if eligible_ids:  # empty = no restriction
                if not provider.job_title_id or provider.job_title_id not in eligible_ids:
                    raise serializers.ValidationError({
                        'provider_id': (
                            f'{provider.user.first_name or provider.user.email} cannot perform '
                            f'services in the "{category.name}" category. Configure eligibility '
                            f'in Services → category settings.'
                        ),
                    })

        # Provider-at-location guard. The chosen provider must be
        # assigned (via MembershipLocation) to the appointment's
        # location and that assignment must be active. Without this
        # check, a multi-location business could accidentally (or
        # maliciously) book a Manhattan-only provider on the Brooklyn
        # calendar, which would surface in payroll, scheduling, and
        # the calendar density in confusing ways.
        #
        # Resolution order for the location to validate against:
        #   1. The location supplied in the payload (if any).
        #   2. The instance's existing location (on update / partial).
        #   3. The active location from `request.location` (defaulted
        #      in the view's perform_create when not in attrs).
        # If none of those resolve we skip the check — perform_create
        # will raise a clearer error when it can't find a location.
        location = attrs.get('location') or getattr(self.instance, 'location', None)
        if location is None:
            from apps.tenants.context import get_current_location
            location = get_current_location()
        if provider and location:
            assignment_exists = MembershipLocation.objects.filter(
                membership=provider, location=location, is_active=True,
            ).exists()
            if not assignment_exists:
                provider_label = (
                    provider.user.first_name
                    or provider.user.last_name
                    or provider.user.email
                )
                raise serializers.ValidationError({
                    'provider_id': (
                        f'{provider_label} is not assigned to {location.name}. '
                        f'Assign them to this location first '
                        f'(/staff/employees/{provider.id}) or pick a provider '
                        f'who works at this site.'
                    ),
                })

        # Schedule-fit guard. If the provider has a `ProviderSchedule`
        # at this location, the appointment must fit entirely within
        # one of that day's working blocks. Skipped when there's no
        # schedule (provider treated as available all day — same as
        # before scheduling shipped). Skipped on cancellation /
        # no-show transitions because those just close out the
        # appointment record without changing its time.
        #
        # Defense in depth: the calendar's drag-drop UX shows the
        # working-hours overlay as a visual hint, but the API enforces
        # — a buggy or scripted client can't book outside hours.
        new_status_for_check = attrs.get('status') or (
            self.instance.status if self.instance else None
        )
        if (
            provider and location and start and end
            and new_status_for_check not in {
                Appointment.Status.CANCELLED,
                Appointment.Status.NO_SHOW,
            }
        ):
            self._validate_schedule_fit(provider, location, start, end)

        return attrs

    @staticmethod
    def _validate_schedule_fit(provider, location, start_dt, end_dt):
        """Reject if the appointment falls outside the provider's
        working blocks for the day. Quietly accepts when the provider
        has no schedule yet (matches "no constraint" semantics).

        Times come in as UTC `datetime`s (DRF's parsed value); we
        convert to the location's timezone to derive the local
        weekday + HH:MM window.
        """
        from zoneinfo import ZoneInfo

        from apps.tenants.models import MembershipLocation

        # Look up the provider's schedule at this specific location.
        # If no MembershipLocation row OR no schedule on that row,
        # we treat the provider as unconstrained.
        try:
            ml = MembershipLocation.objects.select_related('schedule').get(
                membership=provider, location=location, is_active=True,
            )
        except MembershipLocation.DoesNotExist:
            return  # earlier guard already rejects this case
        schedule = getattr(ml, 'schedule', None)
        if schedule is None:
            return

        # Convert UTC → location-local for weekday + HH:MM lookup.
        try:
            tz = ZoneInfo(location.timezone or 'UTC')
        except Exception:  # noqa: BLE001
            tz = ZoneInfo('UTC')
        local_start = start_dt.astimezone(tz)
        local_end = end_dt.astimezone(tz)

        # Cross-midnight guard — appointments crossing local midnight
        # would span two weekdays. Disallowed for v1 (matches the spa
        # workflow; overnight bookings are a future concern).
        if local_start.date() != local_end.date():
            raise serializers.ValidationError({
                'start_time': (
                    'Appointment crosses local midnight, which the '
                    'scheduler does not support. Split it into two bookings.'
                ),
            })

        weekday_keys = (
            'monday', 'tuesday', 'wednesday', 'thursday',
            'friday', 'saturday', 'sunday',
        )
        weekday = weekday_keys[local_start.weekday()]
        blocks = schedule.weekly_hours.get(weekday, [])

        if not blocks:
            # Empty list = explicitly off this day.
            day_label = weekday.title()
            provider_label = (
                provider.user.first_name
                or provider.user.last_name
                or provider.user.email
            )
            raise serializers.ValidationError({
                'start_time': (
                    f'{provider_label} is not scheduled to work on {day_label} at '
                    f'{location.name}. Update the schedule at /staff/schedule '
                    f'or pick a different provider / time.'
                ),
            })

        # Convert appointment local times to minutes-since-midnight
        # for comparison against the block ranges.
        appt_start_min = local_start.hour * 60 + local_start.minute
        appt_end_min = local_end.hour * 60 + local_end.minute

        for block in blocks:
            try:
                bs_h, bs_m = block['start'].split(':')
                be_h, be_m = block['end'].split(':')
                block_start_min = int(bs_h) * 60 + int(bs_m)
                block_end_min = int(be_h) * 60 + int(be_m)
            except (KeyError, ValueError, AttributeError):
                continue  # corrupted block — skip rather than 500
            if block_start_min <= appt_start_min and appt_end_min <= block_end_min:
                return  # fits entirely within this block

        # No block contained the appointment.
        provider_label = (
            provider.user.first_name
            or provider.user.last_name
            or provider.user.email
        )
        block_summary = ', '.join(
            f"{b.get('start', '?')}–{b.get('end', '?')}" for b in blocks
        )
        raise serializers.ValidationError({
            'start_time': (
                f'Time falls outside {provider_label}\'s working hours '
                f'({block_summary}) at {location.name}. Adjust the time or '
                f'update the schedule at /staff/schedule.'
            ),
        })
