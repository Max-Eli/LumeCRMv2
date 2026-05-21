"""Tenant-scoped reference + settings API.

Endpoints:

    GET    /api/tenant/                Current tenant detail (anyone in the tenant)
    PATCH  /api/tenant/                Update business profile + branding
                                       (gated by `MANAGE_TENANT_SETTINGS`)

    GET    /api/locations/             List the current tenant's locations
    POST   /api/locations/             Create a new location
                                       (gated by `MANAGE_TENANT_SETTINGS`)
    GET    /api/locations/{id}/        Retrieve one location's full detail
    PATCH  /api/locations/{id}/        Update fields (name, address, hours,
                                       is_default, is_active …)
                                       (gated by `MANAGE_TENANT_SETTINGS`)

    GET    /api/job-titles/            Job-title catalog (read-only for now)

    GET    /api/memberships/           Staff list (filters: `bookable`, `active`)
    PATCH  /api/memberships/{id}/      Update role / is_active / is_bookable /
                                       job_title (gated by `MANAGE_STAFF`)

The current tenant comes from the request-scoped tenant context set by
`TenantMiddleware` (resolved from subdomain in production, or the
`X-Tenant-Slug` header in dev). Location endpoints filter by current
tenant; cross-tenant retrieves return 404.
"""

import re
import secrets

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.utils.text import slugify
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.models import AuditLog
from apps.audit.services import record
from apps.tenants.api_permissions import IsTenantStaff

from .context import get_current_location, get_current_tenant
from .models import (
    Invitation,
    JobTitle,
    Location,
    MembershipLocation,
    ProviderSchedule,
    Tenant,
    TenantMembership,
)
from .permissions import P
from .services import InvitationError, accept_invitation, invite_staff

User = get_user_model()


# ── Helpers ──────────────────────────────────────────────────────────────


def _create_location_assignments(membership: TenantMembership, locations) -> None:
    """Bulk-create active MembershipLocation rows for a fresh membership.

    Used by the create-employee path. Caller is responsible for the
    transaction; this function only does the bulk_create. `locations`
    is an iterable of `Location` instances already validated to belong
    to the membership's tenant.
    """
    if not locations:
        return
    MembershipLocation.objects.bulk_create([
        MembershipLocation(
            membership=membership, location=loc, is_active=True,
        )
        for loc in locations
    ])


def _replace_location_assignments(membership: TenantMembership, target_location_ids: list[int]) -> dict:
    """Reconcile a membership's MembershipLocation rows to the target set.

    Soft-delete semantics — assignments removed from the target set get
    `is_active=False`, not a row delete. Preserves audit history of
    "Sarah used to work at Brooklyn." Re-adding a previously-removed
    location reactivates the existing row rather than creating a new
    one (so `(membership, location)` uniqueness holds).

    Returns a dict suitable for audit-log metadata showing what
    actually changed.
    """
    target_set = set(target_location_ids)
    existing = list(MembershipLocation.objects.filter(membership=membership))
    existing_by_location: dict[int, MembershipLocation] = {ml.location_id: ml for ml in existing}

    activated_ids: list[int] = []
    deactivated_ids: list[int] = []
    created_ids: list[int] = []

    # Update or deactivate existing rows.
    for ml in existing:
        should_be_active = ml.location_id in target_set
        if should_be_active and not ml.is_active:
            ml.is_active = True
            ml.save(update_fields=['is_active', 'updated_at'])
            activated_ids.append(ml.location_id)
        elif not should_be_active and ml.is_active:
            ml.is_active = False
            ml.save(update_fields=['is_active', 'updated_at'])
            deactivated_ids.append(ml.location_id)

    # Create rows for targets that have never had an assignment.
    new_targets = target_set - set(existing_by_location.keys())
    for location_id in new_targets:
        MembershipLocation.objects.create(
            membership=membership, location_id=location_id, is_active=True,
        )
        created_ids.append(location_id)

    return {
        'created_location_ids': sorted(created_ids),
        'reactivated_location_ids': sorted(activated_ids),
        'deactivated_location_ids': sorted(deactivated_ids),
    }


# ── Serializers ──────────────────────────────────────────────────────────


class TenantSettingsSerializer(serializers.ModelSerializer):
    """Read + edit shape for the current-tenant settings page.

    Tenant is now strictly account-level: identity (name + slug +
    status) plus branding (primary_color + logo_url). Per-site fields
    (address, hours, timezone, phone) moved to `Location` during the
    Phase 4E rollout — the `/org/locations/[id]` form is their editor.

    `name`, `slug`, and `status` are exposed read-only — once the tenant
    is onboarded, these are identity-level fields that appear on
    invoices, receipts, emails, and the URL the spa shares with their
    customers. Casual edits via the settings UI would silently break
    consistency across already-issued artifacts. Renames go through
    Django admin / a deliberate support flow instead.
    """

    class Meta:
        model = Tenant
        fields = [
            'id', 'name', 'slug', 'status',
            'primary_color',
            'logo_url',
            # Online booking — owner-editable from /org/online-booking.
            # See `apps.booking` for how each field gates the public
            # surface.
            'online_booking_enabled',
            'online_booking_lead_minutes',
            'online_booking_window_days',
            'online_booking_welcome_message',
            'online_booking_cancellation_policy',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'name', 'slug', 'status', 'created_at', 'updated_at']

    def validate_online_booking_lead_minutes(self, value):
        # Sanity-bound. 0 is allowed (some spas want last-minute
        # walk-in availability); the upper bound is "we'll prep a
        # week ahead" which would be absurd as a lead time.
        if value > 60 * 24 * 7:
            raise serializers.ValidationError(
                'Lead time cannot exceed 7 days (10080 minutes).',
            )
        return value

    def validate_online_booking_window_days(self, value):
        # 1 day is the minimum useful window (today only); 365 is the
        # ceiling (a year out is plenty; speculative bookings further
        # out are no-show magnets).
        if value < 1:
            raise serializers.ValidationError(
                'Booking window must allow at least 1 day.',
            )
        if value > 365:
            raise serializers.ValidationError(
                'Booking window cannot exceed 365 days.',
            )
        return value


class LocationSerializer(serializers.ModelSerializer):
    """Read + edit shape for a Location (a physical site within a tenant).

    Slug is auto-derived from `name` on create when the caller doesn't
    supply one — most operators don't think in URL slugs, and a
    deterministic default avoids a "what's a slug?" UX moment in the
    Add Location form. Slug is editable on PATCH (a typo at create time
    shouldn't be permanent); the `lume_active_location` cookie falls
    back to the tenant default when the cookie value no longer resolves,
    so renaming a slug doesn't leave the operator stranded.

    `tenant_id` is read-only — locations can't be moved across tenants
    (it would scramble payroll, audit attribution, and any FK that ever
    references this location).
    """

    tenant_id = serializers.IntegerField(read_only=True)

    class Meta:
        model = Location
        fields = [
            'id',
            'tenant_id',
            'name', 'slug',
            'is_default', 'is_active',
            'timezone',
            'phone', 'email',
            'address_line1', 'address_line2', 'city', 'state', 'zip_code',
            'business_open_time', 'business_close_time',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'tenant_id', 'created_at', 'updated_at']
        extra_kwargs = {
            # Slug is optional on create — viewset auto-derives from name
            # if missing. Required would force the form to expose it,
            # which we explicitly want to avoid in the common case.
            'slug': {'required': False, 'allow_blank': True},
        }

    def validate(self, attrs):
        # Cross-field guard: close must come after open. Read both from
        # `attrs` (incoming patch) falling back to the instance (existing
        # values) so a one-field PATCH still validates against the
        # current other side. Mirrors `TenantSettingsSerializer`.
        open_t = attrs.get('business_open_time') or getattr(self.instance, 'business_open_time', None)
        close_t = attrs.get('business_close_time') or getattr(self.instance, 'business_close_time', None)
        if open_t and close_t and close_t <= open_t:
            raise serializers.ValidationError({
                'business_close_time': 'Close time must be after open time.',
            })
        # Normalize state to uppercase so `'ny'` and `'NY'` don't both
        # round-trip into the DB as distinct values.
        if 'state' in attrs and attrs['state']:
            attrs['state'] = attrs['state'].upper()
        return attrs


class JobTitleSerializer(serializers.ModelSerializer):
    class Meta:
        model = JobTitle
        fields = ['id', 'name', 'is_clinical', 'sort_order']


class MembershipSerializer(serializers.ModelSerializer):
    """Compact representation of a TenantMembership for staff/provider lookups.

    When the request comes in with `?location=current` (or a specific
    slug) the serializer embeds two fields scoped to that location:
    `membership_location_id` (so the calendar / scheduler knows which
    join row to PUT a schedule against) and `schedule_for_location`
    (the weekly_hours dict, or null if no schedule has been set yet).

    These let the calendar render the per-provider working-hours
    overlay in one round-trip — without a separate fetch per provider.
    For unscoped requests (the `/staff/employees` org-wide view) both
    fields are omitted.
    """

    user_email = serializers.CharField(source='user.email', read_only=True)
    user_first_name = serializers.CharField(source='user.first_name', read_only=True)
    user_last_name = serializers.CharField(source='user.last_name', read_only=True)
    # Writable FK as `<field>_id` — DRF's ModelSerializer doesn't auto-
    # create this shape (it'd expose the field as `job_title`), so
    # declare it explicitly to match the conventions the calendar /
    # appointments API already use.
    job_title_id = serializers.PrimaryKeyRelatedField(
        queryset=JobTitle.objects.all(),
        source='job_title',
        required=False,
        allow_null=True,
    )
    job_title_name = serializers.SerializerMethodField()
    job_title_is_clinical = serializers.SerializerMethodField()
    # Location-scoped fields — only included when the request is
    # location-scoped (the viewset passes `_active_location` in the
    # serializer context). Omitting them on org-wide responses keeps
    # the staff list payload thin.
    membership_location_id = serializers.SerializerMethodField()
    schedule_for_location = serializers.SerializerMethodField()

    class Meta:
        model = TenantMembership
        fields = [
            'id',
            'user_email', 'user_first_name', 'user_last_name',
            'role',
            'job_title_id',
            'job_title_name', 'job_title_is_clinical',
            'is_bookable', 'is_active',
            'membership_location_id', 'schedule_for_location',
        ]
        # `role`, `job_title_id`, `is_bookable`, `is_active` are writable
        # on PATCH; user identity + derived job-title labels are read-only.
        read_only_fields = [
            'id',
            'user_email', 'user_first_name', 'user_last_name',
            'job_title_name', 'job_title_is_clinical',
            'membership_location_id', 'schedule_for_location',
        ]

    def get_job_title_name(self, obj: TenantMembership) -> str | None:
        return obj.job_title.name if obj.job_title_id else None

    def get_job_title_is_clinical(self, obj: TenantMembership) -> bool:
        return bool(obj.job_title and obj.job_title.is_clinical)

    def _get_active_assignment(self, obj: TenantMembership) -> MembershipLocation | None:
        location = self.context.get('_active_location')
        if location is None:
            return None
        # Cached on first access per object so adding both serializer
        # methods doesn't run two queries.
        cache_key = f'_assignment_{location.id}'
        if not hasattr(obj, cache_key):
            assignment = (
                obj.location_assignments
                .filter(location=location, is_active=True)
                .select_related('schedule')
                .first()
            )
            setattr(obj, cache_key, assignment)
        return getattr(obj, cache_key)

    def get_membership_location_id(self, obj: TenantMembership) -> int | None:
        assignment = self._get_active_assignment(obj)
        return assignment.id if assignment else None

    def get_schedule_for_location(self, obj: TenantMembership):
        assignment = self._get_active_assignment(obj)
        if assignment is None:
            return None
        schedule = getattr(assignment, 'schedule', None)
        # `null` rather than the empty-shape dict here — the FE
        # distinguishes "schedule never set" (no overlay; provider
        # bookable any time) from "set but every day off" (overlay
        # everything; provider bookable nowhere). Empty-shape on read
        # would conflate the two.
        return schedule.weekly_hours if schedule is not None else None


class MembershipDetailSerializer(serializers.ModelSerializer):
    """Full membership detail used by the employee profile page.

    Exposes nested user fields (personal contact + identity) alongside
    per-tenant employment + payroll fields. Updates are accepted on
    both the membership-side and user-side fields in one PATCH; nested
    user data is unpacked in `update()` and applied to the related
    User row inside the same DB transaction the serializer's caller
    runs in.

    Read-only `other_memberships` summarizes which other tenants this
    user belongs to (the "multi-center assignment" surface) without
    leaking sensitive payroll info from those other tenants.
    """

    user_email = serializers.CharField(source='user.email', read_only=True)
    user_first_name = serializers.CharField(source='user.first_name', required=False)
    user_last_name = serializers.CharField(source='user.last_name', required=False)
    user_phone = serializers.CharField(source='user.phone', required=False, allow_blank=True)
    user_address_line1 = serializers.CharField(
        source='user.address_line1', required=False, allow_blank=True,
    )
    user_address_line2 = serializers.CharField(
        source='user.address_line2', required=False, allow_blank=True,
    )
    user_city = serializers.CharField(source='user.city', required=False, allow_blank=True)
    user_state = serializers.CharField(source='user.state', required=False, allow_blank=True)
    user_zip_code = serializers.CharField(source='user.zip_code', required=False, allow_blank=True)

    job_title_id = serializers.PrimaryKeyRelatedField(
        queryset=JobTitle.objects.all(),
        source='job_title',
        required=False,
        allow_null=True,
    )
    job_title_name = serializers.SerializerMethodField()
    job_title_is_clinical = serializers.SerializerMethodField()

    other_memberships = serializers.SerializerMethodField(read_only=True)
    # Per-tenant location assignments. `location_ids` is writable: PATCH
    # a list of Location ids and the serializer reconciles to that set
    # via `_replace_location_assignments` (soft-delete semantics for
    # removed assignments — preserves the audit trail of "Sarah used
    # to work at Brooklyn"). Read shape returns the active assignments
    # only, which is what the UI cares about for the location-toggle
    # checkboxes; deactivated history is in the audit log.
    location_ids = serializers.SerializerMethodField(read_only=True)
    set_location_ids = serializers.PrimaryKeyRelatedField(
        queryset=Location.objects.all(),
        many=True,
        write_only=True,
        required=False,
    )

    class Meta:
        model = TenantMembership
        fields = [
            'id',
            'user_email',
            'user_first_name', 'user_last_name',
            'user_phone',
            'user_address_line1', 'user_address_line2',
            'user_city', 'user_state', 'user_zip_code',
            'role',
            'job_title_id', 'job_title_name', 'job_title_is_clinical',
            'is_bookable', 'is_active',
            'employment_type', 'pay_type', 'pay_rate_cents',
            'hire_date', 'employment_notes',
            'location_ids', 'set_location_ids',
            'other_memberships',
            'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id',
            'user_email',  # email is the unique identifier; rename via separate flow
            'job_title_name', 'job_title_is_clinical',
            'location_ids',
            'other_memberships',
            'created_at', 'updated_at',
        ]

    def get_location_ids(self, obj: TenantMembership):
        # Active assignments only — the UI's location-toggle checkbox
        # set should reflect "currently assigned", not "ever assigned".
        return list(
            obj.location_assignments
            .filter(is_active=True)
            .values_list('location_id', flat=True)
        )

    def validate_set_location_ids(self, value):
        # Cross-tenant guard: every supplied location must belong to
        # the membership's tenant. The PrimaryKeyRelatedField queryset
        # is unrestricted; tenant scope is enforced here.
        if not self.instance:
            return value  # Create path doesn't go through this serializer.
        for location in value:
            if location.tenant_id != self.instance.tenant_id:
                raise serializers.ValidationError(
                    'Location does not belong to this membership\'s tenant.',
                )
        return value

    def get_job_title_name(self, obj: TenantMembership) -> str | None:
        return obj.job_title.name if obj.job_title_id else None

    def get_job_title_is_clinical(self, obj: TenantMembership) -> bool:
        return bool(obj.job_title and obj.job_title.is_clinical)

    def get_other_memberships(self, obj: TenantMembership):
        # Summary only — no payroll / address fields. Belongs to the
        # employee profile so an admin can see "this person also works
        # at Spa B as an Aesthetician" without crossing tenant boundaries
        # on sensitive data.
        others = (
            obj.user.memberships
            .exclude(id=obj.id)
            .select_related('tenant', 'job_title')
        )
        return [
            {
                'id': m.id,
                'tenant_id': m.tenant_id,
                'tenant_name': m.tenant.name,
                'role': m.role,
                'job_title_name': m.job_title.name if m.job_title else None,
                'is_active': m.is_active,
            }
            for m in others
        ]

    def update(self, instance, validated_data):
        # Pop nested user fields and apply to the related User row.
        # DRF nests `source='user.X'` fields under `'user'` in validated_data.
        user_data = validated_data.pop('user', {})
        if user_data:
            for field, value in user_data.items():
                setattr(instance.user, field, value)
            instance.user.save(update_fields=list(user_data.keys()))

        # Pop location-assignment intent — it's not a model field, it's
        # a reconciliation against the join table. Skipped when absent
        # (PATCH that doesn't touch assignments leaves them alone).
        location_targets = validated_data.pop('set_location_ids', None)
        updated = super().update(instance, validated_data)
        if location_targets is not None:
            target_ids = [loc.id for loc in location_targets]
            self.context['_location_assignment_changes'] = (
                _replace_location_assignments(updated, target_ids)
            )
        return updated


class MembershipCreateSerializer(serializers.Serializer):
    """Input shape for `POST /api/memberships/`.

    Either creates a brand-new User (with a temp password returned
    one-time to the caller) or attaches an existing User as a new
    membership of this tenant. The actual create logic lives in the
    viewset because it needs to dispatch on whether the User already
    exists.

    `location_ids` is optional. When omitted, the new employee is
    auto-assigned to the active location (`request.location`) so the
    common Add-from-/staff/employees flow works without the operator
    thinking about it. When supplied, it explicitly assigns to those
    locations instead — useful when adding from /org/staff or via
    scripts. Empty list `[]` means "no auto-assignment" (the employee
    won't appear in any location until they're assigned later).
    """
    email = serializers.EmailField()
    first_name = serializers.CharField(max_length=150)
    last_name = serializers.CharField(max_length=150)
    role = serializers.ChoiceField(choices=TenantMembership.Role.choices)
    job_title_id = serializers.PrimaryKeyRelatedField(
        queryset=JobTitle.objects.all(),
        required=False, allow_null=True,
    )
    is_bookable = serializers.BooleanField(required=False, default=False)
    location_ids = serializers.PrimaryKeyRelatedField(
        queryset=Location.objects.all(),
        many=True,
        required=False,
    )


# Time-block regex for schedule validation.
_HHMM_RE = re.compile(r'^\d{1,2}:\d{2}$')


def _parse_hhmm(s: str) -> int:
    """Convert 'HH:MM' to minutes-since-midnight. Caller has validated format."""
    h, m = s.split(':')
    return int(h) * 60 + int(m)


class ScheduleSerializer(serializers.Serializer):
    """Read + write shape for a `ProviderSchedule`.

    Not a `ModelSerializer` because we want the response shape to be
    consistent regardless of whether a schedule row exists yet — when
    the operator GETs the schedule for a brand-new MembershipLocation
    that hasn't been edited, we return `weekly_hours` filled with the
    canonical "every day off" empty arrays. The view materializes a
    real row on PUT.

    Validation enforces the structure the calendar / online booking
    will rely on:

      - `weekly_hours` keys are exactly the 7 lowercase weekday names.
      - Each value is an array of `{start, end}` blocks.
      - `start` and `end` are HH:MM strings (24-hour).
      - `end > start` per block.
      - Within a day, blocks don't overlap.

    Cross-block validation lives here, not in the model, because it
    can't be expressed as a DB constraint cleanly. The trade-off: the
    DB allows technically invalid schedules if a script bypasses the
    serializer. Adding a Postgres trigger is on the polish backlog.
    """

    weekly_hours = serializers.JSONField()

    def validate_weekly_hours(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError('weekly_hours must be an object keyed by weekday.')

        # Exact 7-key set — accept missing days from older clients by
        # filling them in with empty arrays, but reject unknown keys
        # (typos like "tueday" should surface clearly).
        unknown = set(value.keys()) - set(ProviderSchedule.WEEKDAYS)
        if unknown:
            raise serializers.ValidationError(
                f'Unknown weekday key(s): {sorted(unknown)}. Use lowercase '
                f'monday/tuesday/.../sunday.',
            )

        normalized: dict = {}
        for day in ProviderSchedule.WEEKDAYS:
            blocks = value.get(day, [])
            if not isinstance(blocks, list):
                raise serializers.ValidationError({
                    day: 'Must be an array of {start, end} blocks (empty array = off).',
                })

            normalized_blocks: list[dict] = []
            for i, block in enumerate(blocks):
                if not isinstance(block, dict) or 'start' not in block or 'end' not in block:
                    raise serializers.ValidationError({
                        day: f'Block {i} must be an object with "start" and "end" keys.',
                    })
                start, end = block['start'], block['end']
                if not isinstance(start, str) or not _HHMM_RE.match(start):
                    raise serializers.ValidationError({
                        day: f'Block {i} start "{start}" must be HH:MM (24-hour).',
                    })
                if not isinstance(end, str) or not _HHMM_RE.match(end):
                    raise serializers.ValidationError({
                        day: f'Block {i} end "{end}" must be HH:MM (24-hour).',
                    })
                start_min, end_min = _parse_hhmm(start), _parse_hhmm(end)
                if end_min <= start_min:
                    raise serializers.ValidationError({
                        day: f'Block {i}: end ({end}) must be after start ({start}).',
                    })
                normalized_blocks.append({'start': start, 'end': end})

            # No-overlap: sort by start and verify each block's start is
            # >= the previous block's end. Catches "9-12 + 11-14" which
            # would let two appointments be booked simultaneously.
            normalized_blocks.sort(key=lambda b: _parse_hhmm(b['start']))
            for i in range(1, len(normalized_blocks)):
                prev_end = _parse_hhmm(normalized_blocks[i - 1]['end'])
                this_start = _parse_hhmm(normalized_blocks[i]['start'])
                if this_start < prev_end:
                    raise serializers.ValidationError({
                        day: (
                            f'Blocks overlap: {normalized_blocks[i - 1]["start"]}–'
                            f'{normalized_blocks[i - 1]["end"]} and '
                            f'{normalized_blocks[i]["start"]}–{normalized_blocks[i]["end"]}.'
                        ),
                    })

            normalized[day] = normalized_blocks

        return normalized


# ── Tenant settings ──────────────────────────────────────────────────────


class TenantSettingsView(APIView):
    """Singleton endpoint for the *current* tenant.

    GET returns the tenant detail; PATCH updates the business profile +
    branding fields (gated by `MANAGE_TENANT_SETTINGS` — owners by default).

    Modeled as an `APIView` (not a ViewSet) because the resource is a
    singleton from the caller's point of view: there's exactly one
    "current tenant" per request, identified by subdomain. No collection
    listing, no detail-by-pk, no create/destroy — those would only make
    sense for platform-admin operations, which live in Django admin.
    """

    permission_classes = [IsTenantStaff]

    def get_object(self) -> Tenant:
        tenant = get_current_tenant()
        if tenant is None:
            raise PermissionDenied('No tenant context resolved for this request.')
        return tenant

    def get(self, request, *args, **kwargs):
        tenant = self.get_object()
        record(
            action=AuditLog.Action.READ,
            resource_type='tenant',
            resource_id=tenant.id,
            request=request,
        )
        return Response(TenantSettingsSerializer(tenant).data)

    def patch(self, request, *args, **kwargs):
        tenant = self.get_object()
        membership = getattr(request, 'tenant_membership', None)
        if not request.user.is_superuser:
            if not membership or not membership.has(P.MANAGE_TENANT_SETTINGS):
                raise PermissionDenied('You do not have permission to edit tenant settings.')

        serializer = TenantSettingsSerializer(tenant, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        updated = serializer.save()

        record(
            action=AuditLog.Action.UPDATE,
            resource_type='tenant',
            resource_id=updated.id,
            request=request,
            metadata={'fields_changed': sorted(serializer.validated_data.keys())},
        )
        return Response(TenantSettingsSerializer(updated).data)


# ── Job titles ───────────────────────────────────────────────────────────


class JobTitleViewSet(viewsets.ReadOnlyModelViewSet):
    """List the current tenant's job titles.

    Read-only — mutations happen through Django admin during onboarding for
    now. UI for managing job titles will land in a future tenant-settings
    iteration.
    """

    serializer_class = JobTitleSerializer
    permission_classes = [IsTenantStaff]

    def get_queryset(self):
        tenant = get_current_tenant()
        if tenant is None:
            return JobTitle.objects.none()
        return JobTitle.objects.filter(tenant=tenant)


# ── Memberships ──────────────────────────────────────────────────────────


class MembershipViewSet(viewsets.ModelViewSet):
    """List + retrieve + create + edit staff memberships for the current tenant.

    Filters on list: `?bookable=true`, `?active=true`. Create + update
    gated by `MANAGE_STAFF` (owner + manager by default). Destroy stays
    explicitly disallowed — removing access goes through `is_active=false`
    so the audit trail isn't lost.

    Two serializer shapes:
      - `MembershipSerializer` (compact) — used by list (calendar provider
        columns + the staff roster). No payroll / address — those are
        sensitive and shouldn't leak to a frontend that just wants names.
      - `MembershipDetailSerializer` (full) — used by retrieve / update,
        with nested user contact + employment + payroll + multi-center
        summary. Used by the `/staff/employees/[id]` profile page.

    Create flow (`POST /api/memberships/`) takes the
    `MembershipCreateSerializer` input shape, dispatches to existing-
    user-attach vs new-user-create, and returns the detail shape PLUS a
    one-time `temp_password` field if it created a new user.
    """

    permission_classes = [IsTenantStaff]
    http_method_names = ['get', 'post', 'patch', 'head', 'options']

    def get_serializer_class(self):
        if self.action in {'retrieve', 'update', 'partial_update'}:
            return MembershipDetailSerializer
        if self.action == 'create':
            return MembershipCreateSerializer
        return MembershipSerializer

    def get_queryset(self):
        tenant = get_current_tenant()
        if tenant is None:
            return TenantMembership.objects.none()
        qs = TenantMembership.objects.filter(tenant=tenant).select_related(
            'user', 'job_title',
        )
        params = self.request.query_params
        if params.get('bookable', '').lower() in {'true', '1'}:
            qs = qs.filter(is_bookable=True)
        if params.get('active', '').lower() in {'true', '1'}:
            qs = qs.filter(is_active=True)

        # `?location=` opt-in scoping. Used by the calendar's
        # bookable-providers query so the LA day-view only shows
        # providers actually assigned to LA. Two accepted forms:
        #
        #   ?location=current  → use the active location (cookie /
        #                        tenant default via LocationMiddleware)
        #   ?location=<slug>   → use a specific site within the tenant
        #
        # Omitted (today's behavior) → no location filter, returns
        # every matching tenant membership. The /staff/employees page
        # depends on this — its roster is org-wide, not site-scoped.
        # An unknown slug or `current` with no resolved location
        # returns an empty queryset (safer than silently widening to
        # the org-wide list, which would surface providers the operator
        # didn't expect on that calendar).
        location_param = (params.get('location') or '').strip().lower()
        if location_param:
            if location_param == 'current':
                location = get_current_location()
            else:
                location = (
                    Location.objects
                    .filter(tenant=tenant, slug=location_param, is_active=True)
                    .first()
                )
            if location is None:
                # Stash a sentinel so `get_serializer_context` knows
                # not to embed location-scoped fields when scope was
                # requested but couldn't resolve.
                self._active_location = None
                return qs.none()
            self._active_location = location
            qs = qs.filter(
                location_assignments__location=location,
                location_assignments__is_active=True,
            ).distinct()
        else:
            self._active_location = None

        return qs.order_by('user__last_name', 'user__first_name')

    def get_serializer_context(self):
        # The list serializer reads `_active_location` from context to
        # decide whether to embed `membership_location_id` +
        # `schedule_for_location` per row. Stays None for org-wide
        # views (the /staff/employees roster).
        ctx = super().get_serializer_context()
        ctx['_active_location'] = getattr(self, '_active_location', None)
        return ctx

    def perform_update(self, serializer):
        membership = getattr(self.request, 'tenant_membership', None)
        if not self.request.user.is_superuser:
            if not membership or not membership.has(P.MANAGE_STAFF):
                raise PermissionDenied('You do not have permission to edit staff.')

        instance = serializer.instance
        old_role = instance.role
        old_active = instance.is_active
        old_bookable = instance.is_bookable
        old_job_title = instance.job_title_id

        # Guardrail: don't let an admin demote / deactivate the last
        # remaining owner. Without this, a tenant could lose all admin
        # access if the only owner accidentally edits themselves.
        new_role = serializer.validated_data.get('role', old_role)
        new_active = serializer.validated_data.get('is_active', old_active)
        if instance.role == TenantMembership.Role.OWNER and (
            new_role != TenantMembership.Role.OWNER or not new_active
        ):
            owner_count = TenantMembership.objects.filter(
                tenant=instance.tenant,
                role=TenantMembership.Role.OWNER,
                is_active=True,
            ).count()
            if owner_count <= 1:
                raise PermissionDenied(
                    'Cannot demote or deactivate the last active owner. '
                    'Promote another member to Owner first.',
                )

        updated = serializer.save()

        # Audit — capture before/after on the four mutable fields so the
        # log answers "who changed Sarah's role from manager to owner."
        metadata: dict = {
            'fields_changed': sorted(serializer.validated_data.keys()),
        }
        if updated.role != old_role:
            metadata['from_role'] = old_role
            metadata['to_role'] = updated.role
        if updated.is_active != old_active:
            metadata['from_is_active'] = old_active
            metadata['to_is_active'] = updated.is_active
        if updated.is_bookable != old_bookable:
            metadata['from_is_bookable'] = old_bookable
            metadata['to_is_bookable'] = updated.is_bookable
        if updated.job_title_id != old_job_title:
            metadata['from_job_title_id'] = old_job_title
            metadata['to_job_title_id'] = updated.job_title_id

        # Location-assignment changes (created / reactivated /
        # deactivated location ids) ride into the audit metadata when
        # the PATCH touched assignments — answers "who moved Sarah
        # from Brooklyn to Manhattan and when".
        assignment_changes = serializer.context.get('_location_assignment_changes')
        if assignment_changes:
            metadata['location_assignments'] = assignment_changes

        record(
            action=AuditLog.Action.UPDATE,
            resource_type='membership',
            resource_id=updated.id,
            request=self.request,
            metadata=metadata,
        )

    # ── Create (Add employee) ───────────────────────────────────────────
    #
    # Not exposed via `serializer.save()` because the create flow is
    # bigger than a single model write: it has to (a) check whether a
    # User with this email already exists, (b) either attach as a new
    # membership or create a new User with a temp password, and (c)
    # surface that temp password back to the caller exactly once for the
    # owner to share until the email-invite flow lands (Phase 1F polish).

    def create(self, request, *args, **kwargs):  # noqa: ARG002
        # Permission gate — same as edit.
        membership = getattr(request, 'tenant_membership', None)
        if not request.user.is_superuser:
            if not membership or not membership.has(P.MANAGE_STAFF):
                raise PermissionDenied('You do not have permission to add employees.')

        tenant = get_current_tenant()
        if tenant is None:
            raise PermissionDenied('No tenant context resolved for this request.')

        input_serializer = MembershipCreateSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        data = input_serializer.validated_data

        email_norm = data['email'].strip().lower()
        existing_user = User.objects.filter(email__iexact=email_norm).first()
        temp_password: str | None = None

        # Resolve which locations to assign to. Three precedence levels:
        #   1. Explicit `location_ids` in the payload — assigns those.
        #   2. Empty `[]` payload — assigns none (operator opts out;
        #      employee will appear in no location until assigned later).
        #   3. Field omitted — auto-assigns to the active location so
        #      "Add employee from a calendar" Just Works without the
        #      operator thinking about it.
        if 'location_ids' in data:
            assignment_locations = list(data['location_ids'])
            # Cross-tenant guard: every supplied location must belong
            # to this tenant. The PrimaryKeyRelatedField queryset is
            # unrestricted (matches the existing customer/service
            # pattern); we enforce tenant scope here.
            for loc in assignment_locations:
                if loc.tenant_id != tenant.id:
                    return Response(
                        {'location_ids': ['Location does not belong to this tenant.']},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
        else:
            active_location = get_current_location()
            assignment_locations = [active_location] if active_location else []

        if existing_user:
            # Already a member of this tenant? Reject — it'd be a duplicate.
            if TenantMembership.objects.filter(user=existing_user, tenant=tenant).exists():
                return Response(
                    {'email': ['This person is already an employee at this tenant.']},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            with transaction.atomic():
                # If their name fields are empty (e.g. they were a
                # customer-only user before), fill them from this form.
                if not existing_user.first_name and data.get('first_name'):
                    existing_user.first_name = data['first_name']
                if not existing_user.last_name and data.get('last_name'):
                    existing_user.last_name = data['last_name']
                existing_user.save(update_fields=['first_name', 'last_name'])
                new_membership = TenantMembership.objects.create(
                    user=existing_user,
                    tenant=tenant,
                    role=data['role'],
                    job_title=data.get('job_title_id'),
                    is_bookable=data.get('is_bookable', False),
                    is_active=True,
                )
                _create_location_assignments(new_membership, assignment_locations)
        else:
            # Brand-new user — generate a one-time temp password the
            # owner shares with the new employee until the invite-email
            # flow lands. ~128 bits of entropy; Django hashes it.
            temp_password = secrets.token_urlsafe(12)
            try:
                with transaction.atomic():
                    new_user = User.objects.create_user(
                        email=email_norm,
                        password=temp_password,
                        first_name=data['first_name'],
                        last_name=data['last_name'],
                    )
                    new_membership = TenantMembership.objects.create(
                        user=new_user,
                        tenant=tenant,
                        role=data['role'],
                        job_title=data.get('job_title_id'),
                        is_bookable=data.get('is_bookable', False),
                        is_active=True,
                    )
                    _create_location_assignments(new_membership, assignment_locations)
            except IntegrityError:
                # Race — another request created the user between our
                # lookup and our insert. Bounce the caller to retry.
                return Response(
                    {'email': ['A user with this email was just created. Please retry.']},
                    status=status.HTTP_409_CONFLICT,
                )

        record(
            action=AuditLog.Action.CREATE,
            resource_type='membership',
            resource_id=new_membership.id,
            request=request,
            metadata={
                'user_id': new_membership.user_id,
                'role': new_membership.role,
                'attached_existing_user': existing_user is not None,
                'location_ids': sorted(loc.id for loc in assignment_locations),
            },
        )

        # Build the detail response, optionally including the temp password
        # one-time. The frontend MUST display + clear it immediately —
        # the password is not stored anywhere queryable after this.
        detail = MembershipDetailSerializer(new_membership, context={'request': request}).data
        if temp_password:
            detail['temp_password'] = temp_password
        return Response(detail, status=status.HTTP_201_CREATED)

    def destroy(self, request, *args, **kwargs):  # noqa: ARG002
        return Response(
            {'detail': 'Set `is_active=false` instead of deleting — preserves the audit trail.'},
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    # ── Invitation flow ──────────────────────────────────────────────────

    @action(detail=False, methods=['post'], url_path='invite')
    def invite(self, request):
        """Send an email invitation to a prospective staff member.

        Replaces the legacy temp-password reveal (the existing `create`
        action stays around to attach existing-user accounts who can't
        get an emailed link — e.g. they already use Lumè at another spa).

        Payload mirrors `create`: email + role + job_title_id + is_bookable.
        On success returns 201 with the invitation row so the frontend
        can show "Invitation sent to {email}" with the expiry date.

        Audit-logged with the recipient email + invited_by user. The
        Invitation row itself carries the same metadata for posterity.
        """
        if not request.user.is_superuser:
            membership = getattr(request, 'tenant_membership', None)
            if not membership or not membership.has(P.MANAGE_STAFF):
                raise PermissionDenied('You do not have permission to invite employees.')

        tenant = get_current_tenant()
        if tenant is None:
            raise PermissionDenied('No tenant context resolved for this request.')

        input_serializer = MembershipInviteInputSerializer(
            data=request.data, context={'tenant': tenant},
        )
        input_serializer.is_valid(raise_exception=True)
        data = input_serializer.validated_data

        try:
            invitation = invite_staff(
                tenant,
                email=data['email'],
                role=data['role'],
                job_title=data.get('job_title'),
                is_bookable=data.get('is_bookable', False),
                invited_by=request.user,
            )
        except InvitationError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        record(
            action=AuditLog.Action.CREATE,
            resource_type='invitation',
            resource_id=invitation.id,
            request=request,
            metadata={
                'email': invitation.email,
                'role': invitation.role,
                'is_bookable': invitation.is_bookable,
            },
        )

        return Response(
            InvitationSerializer(invitation).data,
            status=status.HTTP_201_CREATED,
        )


# ── Invitation serializers ───────────────────────────────────────────────


class MembershipInviteInputSerializer(serializers.Serializer):
    """Input shape for POST /api/memberships/invite/."""

    email = serializers.EmailField()
    role = serializers.ChoiceField(choices=TenantMembership.Role.choices)
    is_bookable = serializers.BooleanField(required=False, default=False)
    job_title_id = serializers.IntegerField(required=False, allow_null=True)

    def validate_job_title_id(self, value):
        if value is None:
            return None
        tenant = self.context.get('tenant')
        try:
            jt = JobTitle.objects.get(pk=value, tenant=tenant)
        except JobTitle.DoesNotExist:
            raise serializers.ValidationError('Job title not found in this tenant.')
        return jt

    def to_internal_value(self, data):
        ret = super().to_internal_value(data)
        # Surface the JobTitle instance under `job_title` for the
        # service-layer signature (which expects an instance, not an id).
        if 'job_title_id' in ret:
            ret['job_title'] = ret.pop('job_title_id')
        return ret


class InvitationSerializer(serializers.ModelSerializer):
    """Read shape returned by the invite endpoint + invitations list."""

    invited_by_email = serializers.CharField(
        source='invited_by.email', read_only=True, allow_null=True,
    )
    job_title_name = serializers.CharField(
        source='job_title.name', read_only=True, allow_null=True,
    )
    role_label = serializers.SerializerMethodField()
    is_pending = serializers.BooleanField(read_only=True)
    is_expired = serializers.BooleanField(read_only=True)

    class Meta:
        model = Invitation
        fields = [
            'id', 'email', 'role', 'role_label', 'job_title_name',
            'is_bookable',
            'invited_by_email',
            'expires_at', 'accepted_at',
            'is_pending', 'is_expired',
            'created_at',
        ]
        read_only_fields = fields

    def get_role_label(self, obj: Invitation) -> str:
        return dict(TenantMembership.Role.choices).get(obj.role, obj.role)


# ── Locations ────────────────────────────────────────────────────────────


class LocationViewSet(viewsets.ModelViewSet):
    """List + create + retrieve + update locations within the current tenant.

    Permission model: read is open to anyone in the tenant (front-desk
    needs to know which locations exist for the location switcher);
    write is gated by `MANAGE_TENANT_SETTINGS` (owners by default —
    same gate as the rest of the business profile).

    Two invariants `LocationMiddleware` depends on are enforced here on
    every write, not just at the DB layer, so the UI gets a clear 400
    instead of a 500:

      1. **A tenant always has at least one active location.** Cannot
         deactivate the only one.
      2. **A tenant always has exactly one default location.** Cannot
         deactivate the current default; cannot un-set `is_default=True`
         on the current default. To "change defaults," PATCH another
         location with `is_default=true` — the viewset atomically
         demotes the previous default in the same transaction (the DB
         constraint would otherwise reject the second `is_default=True`
         row).

    Hard delete is intentionally not exposed — Location FK lands on
    Appointment + payroll records in later sessions, and a hard delete
    would orphan or cascade them. Soft-delete via `is_active=False`
    keeps the audit trail intact.
    """

    serializer_class = LocationSerializer
    permission_classes = [IsTenantStaff]
    http_method_names = ['get', 'post', 'patch', 'head', 'options']

    def get_queryset(self):
        tenant = get_current_tenant()
        if tenant is None:
            return Location.objects.none()
        return Location.objects.filter(tenant=tenant)

    # ── Permission gate (write-only) ────────────────────────────────────

    def _check_write_permission(self, request):
        if request.user.is_superuser:
            return
        membership = getattr(request, 'tenant_membership', None)
        if not membership or not membership.has(P.MANAGE_TENANT_SETTINGS):
            raise PermissionDenied('You do not have permission to manage locations.')

    # ── Create ──────────────────────────────────────────────────────────

    def create(self, request, *args, **kwargs):  # noqa: ARG002
        self._check_write_permission(request)
        tenant = get_current_tenant()
        if tenant is None:
            raise PermissionDenied('No tenant context resolved for this request.')

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Auto-derive slug from name if the caller didn't supply one.
        # `slugify('Manhattan Studio')` → `'manhattan-studio'`.
        provided_slug = (serializer.validated_data.get('slug') or '').strip()
        slug = provided_slug.lower() if provided_slug else slugify(serializer.validated_data['name'])
        if not slug:
            raise serializers.ValidationError({
                'slug': 'Could not derive a URL-safe slug from the name. Provide one explicitly.',
            })
        if Location.objects.filter(tenant=tenant, slug=slug).exists():
            raise serializers.ValidationError({
                'slug': f'A location with slug "{slug}" already exists for this tenant.',
            })

        wants_default = serializer.validated_data.get('is_default', False)

        with transaction.atomic():
            if wants_default:
                # Atomically demote the existing default so the partial
                # unique index doesn't reject the new row.
                Location.objects.filter(tenant=tenant, is_default=True).update(is_default=False)

            instance = Location.objects.create(
                tenant=tenant,
                slug=slug,
                **{
                    k: v
                    for k, v in serializer.validated_data.items()
                    if k not in {'slug'}
                },
            )

        record(
            action=AuditLog.Action.CREATE,
            resource_type='location',
            resource_id=instance.id,
            request=request,
            metadata={
                'name': instance.name,
                'slug': instance.slug,
                'is_default': instance.is_default,
            },
        )
        return Response(
            self.get_serializer(instance).data,
            status=status.HTTP_201_CREATED,
        )

    # ── Update ──────────────────────────────────────────────────────────

    def update(self, request, *args, **kwargs):
        self._check_write_permission(request)
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)

        old_is_default = instance.is_default
        old_is_active = instance.is_active
        new_is_default = serializer.validated_data.get('is_default', old_is_default)
        new_is_active = serializer.validated_data.get('is_active', old_is_active)
        new_slug = serializer.validated_data.get('slug', instance.slug)

        # Slug is editable but stay tenant-unique. The DB constraint
        # would catch this too; raising here gives the form a friendly
        # field-level error instead of a 500.
        if new_slug and new_slug != instance.slug:
            new_slug = new_slug.strip().lower()
            serializer.validated_data['slug'] = new_slug
            if Location.objects.filter(
                tenant=instance.tenant, slug=new_slug,
            ).exclude(pk=instance.pk).exists():
                raise serializers.ValidationError({
                    'slug': f'A location with slug "{new_slug}" already exists for this tenant.',
                })

        # Guardrail 1: can't un-set `is_default=True` on the current
        # default (would leave the tenant defaultless). Promote another
        # location to default instead — we'll auto-demote this one.
        if old_is_default and not new_is_default:
            raise serializers.ValidationError({
                'is_default': (
                    'Cannot un-set the default flag on the current default location. '
                    'Set another location as default and this one is demoted automatically.'
                ),
            })

        # Guardrail 2: can't deactivate the current default. Promote
        # another to default first, then deactivate.
        if old_is_active and not new_is_active and instance.is_default:
            raise serializers.ValidationError({
                'is_active': (
                    'Cannot deactivate the default location. '
                    'Set another active location as default first.'
                ),
            })

        # Guardrail 3: can't deactivate the only remaining active location.
        if old_is_active and not new_is_active:
            other_active = Location.objects.filter(
                tenant=instance.tenant, is_active=True,
            ).exclude(pk=instance.pk).count()
            if other_active == 0:
                raise serializers.ValidationError({
                    'is_active': (
                        'Cannot deactivate the only active location. '
                        'Add another location first.'
                    ),
                })

        with transaction.atomic():
            if new_is_default and not old_is_default:
                # Atomically demote the current default so the partial
                # unique index accepts our new is_default=True.
                Location.objects.filter(
                    tenant=instance.tenant, is_default=True,
                ).exclude(pk=instance.pk).update(is_default=False)
            updated = serializer.save()

        record(
            action=AuditLog.Action.UPDATE,
            resource_type='location',
            resource_id=updated.id,
            request=request,
            metadata={
                'fields_changed': sorted(serializer.validated_data.keys()),
                **(
                    {'from_is_default': old_is_default, 'to_is_default': updated.is_default}
                    if updated.is_default != old_is_default else {}
                ),
                **(
                    {'from_is_active': old_is_active, 'to_is_active': updated.is_active}
                    if updated.is_active != old_is_active else {}
                ),
            },
        )
        return Response(self.get_serializer(updated).data)

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        record(
            action=AuditLog.Action.READ,
            resource_type='location',
            resource_id=instance.id,
            request=request,
        )
        return Response(self.get_serializer(instance).data)


# ── Provider schedules ─────────────────────────────────────────────────


class ScheduleView(APIView):
    """`GET / PUT /api/schedules/{membership_location_id}/`.

    Singleton-per-MembershipLocation surface. GET returns the
    canonical schedule shape (always 7 weekday keys, even when no
    schedule row exists yet — empty arrays for "off"). PUT replaces
    the weekly template entirely; the row is materialized on first
    write. Owner + manager only via `MANAGE_STAFF`.

    Cross-tenant: `MembershipLocation` lives under its tenant via
    `membership.tenant_id`. The view filters by `request.tenant` so
    a malformed URL pointing at another tenant's id 404s.
    """

    permission_classes = [IsTenantStaff]

    def _get_membership_location(self, pk: int) -> MembershipLocation:
        tenant = get_current_tenant()
        if tenant is None:
            raise PermissionDenied('No tenant context resolved for this request.')
        try:
            return (
                MembershipLocation.objects
                .select_related('schedule', 'membership__user', 'location')
                .get(pk=pk, membership__tenant=tenant)
            )
        except MembershipLocation.DoesNotExist:
            from django.http import Http404
            raise Http404('Membership location not found.')

    def get(self, request, pk, *args, **kwargs):
        ml = self._get_membership_location(pk)
        schedule = getattr(ml, 'schedule', None)
        weekly = (
            schedule.weekly_hours
            if schedule is not None
            else ProviderSchedule.empty_weekly_hours()
        )
        record(
            action=AuditLog.Action.READ,
            resource_type='schedule',
            resource_id=ml.id,
            request=request,
        )
        return Response({'membership_location_id': ml.id, 'weekly_hours': weekly})

    def put(self, request, pk, *args, **kwargs):
        ml = self._get_membership_location(pk)

        # Permission check: MANAGE_STAFF (owners + managers) can edit
        # anyone's schedule. A CONTRACTOR may additionally edit their
        # OWN schedule — they set the days they're available to work.
        # Full/part-time staff schedules stay manager-managed.
        if not request.user.is_superuser:
            membership = getattr(request, 'tenant_membership', None)
            is_manager = membership is not None and membership.has(P.MANAGE_STAFF)
            is_own_contractor_schedule = (
                membership is not None
                and ml.membership_id == membership.id
                and membership.employment_type
                == TenantMembership.EmploymentType.CONTRACTOR
            )
            if not (is_manager or is_own_contractor_schedule):
                raise PermissionDenied(
                    'You do not have permission to edit this schedule.'
                )

        serializer = ScheduleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        weekly = serializer.validated_data['weekly_hours']

        # Capture before-image for audit. Empty dict means "no schedule
        # yet"; record that explicitly so the diff reads cleanly.
        old_schedule = getattr(ml, 'schedule', None)
        old_weekly = old_schedule.weekly_hours if old_schedule else {}

        with transaction.atomic():
            schedule, created = ProviderSchedule.objects.update_or_create(
                membership_location=ml,
                defaults={'weekly_hours': weekly},
            )

        record(
            action=AuditLog.Action.CREATE if created else AuditLog.Action.UPDATE,
            resource_type='schedule',
            resource_id=ml.id,
            request=request,
            metadata={
                'membership_id': ml.membership_id,
                'location_id': ml.location_id,
                'days_with_hours': sorted(d for d, blocks in weekly.items() if blocks),
                'previous_days_with_hours': sorted(
                    d for d, blocks in old_weekly.items() if blocks
                ) if old_weekly else None,
            },
        )

        return Response({'membership_location_id': ml.id, 'weekly_hours': weekly})


class MyScheduleView(APIView):
    """`GET /api/schedules/mine/` — the current user's own weekly
    schedules, one entry per location they're assigned to.

    Self-scoped: resolved off `request.tenant_membership`, so it needs
    no `MANAGE_STAFF` — a contractor can load their own availability
    in order to edit it. `can_edit` is true only for contractors (they
    set the days they want to work); other staff get a read-only view
    of their own schedule.
    """

    permission_classes = [IsTenantStaff]

    def get(self, request, *args, **kwargs):
        membership = getattr(request, 'tenant_membership', None)
        if membership is None:
            raise PermissionDenied('No tenant membership resolved for this request.')

        membership_locations = (
            MembershipLocation.objects
            .select_related('schedule', 'location')
            .filter(membership=membership, is_active=True)
            .order_by('location__name')
        )
        record(
            action=AuditLog.Action.READ,
            resource_type='schedule',
            request=request,
            metadata={'event': 'own_schedule_read'},
        )
        return Response({
            'can_edit': (
                membership.employment_type
                == TenantMembership.EmploymentType.CONTRACTOR
            ),
            'locations': [
                {
                    'membership_location_id': ml.id,
                    'location_name': ml.location.name,
                    'weekly_hours': (
                        ml.schedule.weekly_hours
                        if getattr(ml, 'schedule', None) is not None
                        else ProviderSchedule.empty_weekly_hours()
                    ),
                }
                for ml in membership_locations
            ],
        })


# ── Public invitation accept endpoints ───────────────────────────────────


class InvitationLookupView(APIView):
    """`GET /api/auth/invitation/<token>/` — public.

    Returns the basic details a recipient needs to render the accept
    page (tenant name, role, who invited them) without revealing
    membership details of other staff or anything PHI-bearing. We
    don't surface the recipient's email here — the accept form
    requires the recipient to type their first + last name + password,
    not their email; the token IS the identifier.
    """

    permission_classes = [AllowAny]
    authentication_classes: list = []  # Public — no CSRF / session needed.

    def get(self, request, token: str):  # noqa: ARG002
        try:
            invitation = (
                Invitation.objects
                .select_related('tenant', 'invited_by', 'job_title')
                .get(token=token)
            )
        except Invitation.DoesNotExist:
            return Response(
                {'detail': 'Invitation not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        invited_by_name = ''
        if invitation.invited_by_id:
            u = invitation.invited_by
            invited_by_name = f'{u.first_name} {u.last_name}'.strip() or u.email

        return Response({
            'tenant_name': invitation.tenant.name,
            'tenant_slug': invitation.tenant.slug,
            'role': invitation.role,
            'role_label': dict(TenantMembership.Role.choices).get(
                invitation.role, invitation.role,
            ),
            'job_title_name': invitation.job_title.name if invitation.job_title_id else None,
            'invited_by_name': invited_by_name,
            'expires_at': invitation.expires_at,
            'accepted_at': invitation.accepted_at,
            'is_pending': invitation.is_pending,
            'is_expired': invitation.is_expired,
        })


class InvitationAcceptView(APIView):
    """`POST /api/auth/invitation/accept/` — public.

    Accepts a pending invitation by creating a new User + new
    TenantMembership. Token + password + first_name + last_name in
    the body. On success, the user is logged into the new tenant
    (Django session set on this response) and the response carries
    a redirect target so the SPA knows where to land.

    For "I already have an account" — out of scope here. That path
    is the legacy attach-existing flow (POST /api/memberships/) and
    requires the spa owner to add the user directly.
    """

    permission_classes = [AllowAny]
    authentication_classes: list = []

    def post(self, request):
        from django.contrib.auth import login

        payload = request.data or {}
        token = (payload.get('token') or '').strip()
        password = payload.get('password') or ''
        first_name = (payload.get('first_name') or '').strip()
        last_name = (payload.get('last_name') or '').strip()

        if not token:
            return Response({'detail': 'Token is required.'}, status=status.HTTP_400_BAD_REQUEST)
        if len(password) < 12:
            return Response(
                {'password': 'Password must be at least 12 characters.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not first_name or not last_name:
            return Response(
                {'detail': 'First name and last name are required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            user, membership = accept_invitation(
                token, password=password,
                first_name=first_name, last_name=last_name,
            )
        except InvitationError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        login(request, user)
        record(
            action=AuditLog.Action.UPDATE,
            resource_type='invitation_accept',
            resource_id=membership.id,
            request=request,
            metadata={
                'tenant_slug': membership.tenant.slug,
                'role': membership.role,
            },
        )

        return Response({
            'tenant_slug': membership.tenant.slug,
            'redirect': '/dashboard',
        }, status=status.HTTP_200_OK)


# ── Public branding (login / portal / booking landing pages) ───────────


class PublicBrandingView(APIView):
    """`GET /api/public/branding/` — public, subdomain-resolved.

    Returns the minimum tenant identity needed to brand
    unauthenticated surfaces (login page, customer portal login,
    booking landing) so they show the spa's name + logo rather than
    the Lumè default. The tenant is resolved by
    ``TenantMiddleware`` from the request subdomain — no slug in
    the URL — so this endpoint is safe to cache at the edge per host.

    Returns 204 (not 404) when no tenant resolves: a bare host like
    ``lumècrm.com`` is a legitimate marketing-surface request, not
    an error, and the frontend falls back to its default branding.
    """

    permission_classes = [AllowAny]
    authentication_classes: list = []

    def get(self, request):
        tenant = getattr(request, 'tenant', None)
        if tenant is None or tenant.status != Tenant.Status.ACTIVE:
            return Response(status=status.HTTP_204_NO_CONTENT)
        return Response({
            'name': tenant.name,
            'slug': tenant.slug,
            'logo_url': tenant.logo_url or None,
            'primary_color': tenant.primary_color or None,
        })
