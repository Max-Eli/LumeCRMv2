"""Appointments API tests.

Today's coverage focuses on the day-window filter — that's where the
multi-location work touches the appointments API. The `?date=YYYY-MM-DD`
filter must interpret the date in the **active location's** timezone,
not the tenant's, so a multi-location business that spans timezones
(e.g. NY + LA) gets the right window per site.

Without this, picking 2026-05-02 from the date picker on the LA site's
calendar would silently return the NY site's day window — wrong by 3
hours, which routinely shifts which appointments belong to "today".
"""

from __future__ import annotations

import datetime as dt
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone as djtz
from rest_framework import status
from rest_framework.test import APIClient

from apps.appointments.models import Appointment
from apps.audit.models import AuditLog
from apps.customers.models import Customer
from apps.services.models import Service, ServiceCategory
from apps.tenants.middleware import ACTIVE_LOCATION_COOKIE
from apps.tenants.models import Location, Tenant, TenantMembership
from apps.tenants.services import create_tenant_with_defaults

User = get_user_model()


# ── Helpers (mirror the pattern used in apps/invoices/tests.py) ─────


def _make_user(email: str, **kwargs):
    return User.objects.create_user(email=email, password='test-pw', **kwargs)


def _make_tenant(slug: str, *, timezone: str = 'America/New_York') -> tuple[Tenant, User]:
    owner = _make_user(f'{slug}-owner@test.local')
    tenant = create_tenant_with_defaults(
        name=slug.title(),
        slug=slug,
        owner_user=owner,
        status=Tenant.Status.ACTIVE,
        timezone=timezone,
    )
    return tenant, owner


def _make_provider(tenant: Tenant, *, location=None) -> TenantMembership:
    """Create a bookable provider AND assign them to a location.

    Mirrors the runtime Add-Employee flow (Session 5) where every
    membership has at least one MembershipLocation entry — without
    that, `AppointmentSerializer.validate()` rejects bookings.
    Defaults to the tenant's default location.
    """
    from apps.tenants.models import MembershipLocation

    user = _make_user(f'provider-{tenant.slug}-{TenantMembership.objects.filter(tenant=tenant).count()}@test.local')
    membership = TenantMembership.objects.create(
        user=user, tenant=tenant,
        role=TenantMembership.Role.PROVIDER,
        is_bookable=True, is_active=True,
    )
    if location is None:
        location = tenant.locations.get(is_default=True)
    MembershipLocation.objects.create(
        membership=membership, location=location, is_active=True,
    )
    return membership


def _make_service(tenant: Tenant) -> Service:
    cat = ServiceCategory.objects.create(tenant=tenant, name='Cat')
    return Service.objects.create(
        tenant=tenant, category=cat,
        name='Service', code='SVC30',
        duration_minutes=30, buffer_minutes=0,
        price_cents=10000,
        service_type=Service.ServiceType.REGULAR,
    )


def _make_customer(tenant: Tenant) -> Customer:
    return Customer.objects.create(
        tenant=tenant, first_name='Pat', last_name='Patient',
        email=f'pat-{tenant.slug}@test.local',
    )


def _make_appointment(*, tenant, customer, provider, service, start_utc: dt.datetime, location=None):
    end_utc = start_utc + dt.timedelta(minutes=service.duration_minutes)
    if location is None:
        location = tenant.locations.get(is_default=True)
    return Appointment.objects.create(
        tenant=tenant, customer=customer, provider=provider, service=service,
        location=location,
        start_time=start_utc, end_time=end_utc,
        status=Appointment.Status.BOOKED,
        quoted_price_cents=service.price_cents,
    )


# ── Day-window filter respects the active location's timezone ───────


class DayWindowAndLocationScopingTests(TestCase):
    """The day-view query is scoped both ways:

      - **Timezone**: `?date=YYYY-MM-DD` resolves to the active location's
        timezone, so the same date parameter on the LA calendar covers a
        different UTC window than the NY calendar.
      - **Location**: only appointments AT the active location appear.
        The Brooklyn calendar never sees Manhattan's bookings.

    Both invariants are tested together because they're the two halves
    of "the calendar belongs to the location, not the tenant".
    """

    @classmethod
    def setUpTestData(cls):
        cls.tenant, cls.owner = _make_tenant('tz-tenant', timezone='America/New_York')
        # Default location 'main' is NY tz (inherited from Tenant via
        # Session 1's data migration). Add LA as a second site.
        cls.main_location = cls.tenant.locations.get(is_default=True)
        cls.la_location = Location.objects.create(
            tenant=cls.tenant,
            name='Los Angeles', slug='la',
            is_default=False, is_active=True,
            timezone='America/Los_Angeles',
        )

        # Two providers — one assigned to NY only, one to LA only — to
        # exercise the per-location bookable filter elsewhere AND to
        # satisfy the validation that booking provider must be
        # location-assigned.
        cls.ny_provider = _make_provider(cls.tenant, location=cls.main_location)
        cls.la_provider = _make_provider(cls.tenant, location=cls.la_location)
        cls.service = _make_service(cls.tenant)
        cls.customer = _make_customer(cls.tenant)

        # Both appointments at 2026-05-03 04:00 UTC.
        #   NY (EDT, UTC-4) → 2026-05-03 00:00 — start of May 3 in NY.
        #   LA (PDT, UTC-7) → 2026-05-02 21:00 — late May 2 in LA.
        cls.ny_appointment = _make_appointment(
            tenant=cls.tenant, customer=cls.customer, provider=cls.ny_provider,
            service=cls.service, location=cls.main_location,
            start_utc=dt.datetime(2026, 5, 3, 4, 0, tzinfo=dt.timezone.utc),
        )
        cls.la_appointment = _make_appointment(
            tenant=cls.tenant, customer=cls.customer, provider=cls.la_provider,
            service=cls.service, location=cls.la_location,
            start_utc=dt.datetime(2026, 5, 3, 4, 0, tzinfo=dt.timezone.utc),
        )

    def setUp(self):
        self.client = APIClient()
        self.client.force_login(self.owner)
        self.url = reverse('appointment-list')

    def _list_for_date(self, date_str: str, *, location_slug: str | None = None):
        if location_slug is not None:
            self.client.cookies[ACTIVE_LOCATION_COOKIE] = location_slug
        else:
            self.client.cookies.pop(ACTIVE_LOCATION_COOKIE, None)
        return self.client.get(
            f'{self.url}?date={date_str}',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )

    # ── Location scoping ────────────────────────────────────────────

    def test_default_location_returns_only_default_locations_appointments(self):
        # No cookie → 'main' is the active location. The LA appointment
        # is invisible regardless of its timezone-shifted day.
        response = self._list_for_date('2026-05-03')
        ids = {row['id'] for row in response.data}
        self.assertIn(self.ny_appointment.id, ids)
        self.assertNotIn(self.la_appointment.id, ids)

    def test_la_cookie_returns_only_la_appointments(self):
        # LA cookie → only the LA appointment visible, no matter the date.
        response = self._list_for_date('2026-05-02', location_slug='la')
        ids = {row['id'] for row in response.data}
        self.assertIn(self.la_appointment.id, ids)
        self.assertNotIn(self.ny_appointment.id, ids)

    # ── Timezone shifting ───────────────────────────────────────────

    def test_la_window_for_may_2_includes_appointment_at_4am_utc_may_3(self):
        # 04:00 UTC May 3 = 21:00 PDT May 2 — IS in the LA May-2 window.
        response = self._list_for_date('2026-05-02', location_slug='la')
        ids = {row['id'] for row in response.data}
        self.assertIn(self.la_appointment.id, ids)

    def test_la_window_for_may_3_excludes_appointment_at_4am_utc_may_3(self):
        # The same appointment (04:00 UTC May 3) is at 21:00 PDT May 2 —
        # NOT in the LA May-3 window. Mirror invariant of the test above.
        response = self._list_for_date('2026-05-03', location_slug='la')
        ids = {row['id'] for row in response.data}
        self.assertNotIn(self.la_appointment.id, ids)

    def test_ny_window_for_may_3_includes_appointment_at_4am_utc_may_3(self):
        # 04:00 UTC May 3 = 00:00 EDT May 3 — start of May 3 in NY.
        response = self._list_for_date('2026-05-03')
        ids = {row['id'] for row in response.data}
        self.assertIn(self.ny_appointment.id, ids)

    def test_ny_window_for_may_2_excludes_appointment_at_4am_utc_may_3(self):
        # 04:00 UTC May 3 falls exactly at the end of the May-2-NY window
        # (the query uses `start_time__lt=end`, exclusive). NOT included.
        response = self._list_for_date('2026-05-02')
        ids = {row['id'] for row in response.data}
        self.assertNotIn(self.ny_appointment.id, ids)

    # ── Edge cases ───────────────────────────────────────────────────

    def test_unknown_cookie_value_falls_back_to_default(self):
        # Stale cookie → middleware ignores it and returns the default
        # location's appointments. Same set as the no-cookie case.
        response = self._list_for_date('2026-05-03', location_slug='nonexistent')
        ids = {row['id'] for row in response.data}
        self.assertIn(self.ny_appointment.id, ids)
        self.assertNotIn(self.la_appointment.id, ids)


# ── Booking creates pin to the active location ──────────────────────


class AppointmentCreateLocationTests(TestCase):
    """`POST /api/appointments/` defaults `location` from the active
    location when the caller doesn't provide one — operators booking
    from the calendar shouldn't have to think about which site they're
    on, the calendar IS the site. Explicit `location_id` in the payload
    is also honoured (for scripts / tests / future cross-location flows)
    after validation that the location belongs to this tenant.

    Provider-at-location is enforced server-side: a malicious client
    can't book a Manhattan-only provider on the Brooklyn calendar even
    by passing both `provider_id` and `location_id` directly.
    """

    @classmethod
    def setUpTestData(cls):
        cls.tenant, cls.owner = _make_tenant('create-tenant')
        cls.main = cls.tenant.locations.get(is_default=True)
        cls.brooklyn = Location.objects.create(
            tenant=cls.tenant, name='Brooklyn', slug='brooklyn',
            is_default=False, is_active=True,
            timezone='America/New_York',
        )
        cls.main_provider = _make_provider(cls.tenant, location=cls.main)
        cls.brooklyn_provider = _make_provider(cls.tenant, location=cls.brooklyn)
        cls.service = _make_service(cls.tenant)
        cls.customer = _make_customer(cls.tenant)
        # The owner needs BOOK_APPOINTMENT — owners do by default; just
        # making it explicit here that the test client has perms.

    def setUp(self):
        self.client = APIClient()
        self.client.force_login(self.owner)
        self.url = reverse('appointment-list')

    def _post(self, body, *, cookie: str | None = None):
        if cookie is not None:
            self.client.cookies[ACTIVE_LOCATION_COOKIE] = cookie
        else:
            self.client.cookies.pop(ACTIVE_LOCATION_COOKIE, None)
        return self.client.post(
            self.url,
            data=body,
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )

    def _payload(self, *, provider, start_iso='2026-06-01T13:00:00Z'):
        return {
            'customer_id': self.customer.id,
            'service_id': self.service.id,
            'provider_id': provider.id,
            'start_time': start_iso,
            'end_time': '2026-06-01T13:30:00Z',
        }

    def test_create_defaults_location_from_active_cookie(self):
        response = self._post(
            self._payload(provider=self.brooklyn_provider),
            cookie='brooklyn',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        appt = Appointment.objects.get(id=response.data['id'])
        self.assertEqual(appt.location, self.brooklyn)

    def test_create_defaults_location_from_default_when_no_cookie(self):
        response = self._post(self._payload(provider=self.main_provider))
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        appt = Appointment.objects.get(id=response.data['id'])
        self.assertEqual(appt.location, self.main)

    def test_explicit_location_id_in_payload_overrides_active_location(self):
        body = self._payload(provider=self.brooklyn_provider)
        body['location_id'] = self.brooklyn.id
        # Active cookie says 'main' but payload pins 'brooklyn' — payload wins.
        response = self._post(body)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        appt = Appointment.objects.get(id=response.data['id'])
        self.assertEqual(appt.location, self.brooklyn)

    def test_provider_not_assigned_to_location_is_rejected(self):
        # Brooklyn provider, but cookie + no override → location='main'.
        # Brooklyn provider has no MembershipLocation at 'main'.
        response = self._post(self._payload(provider=self.brooklyn_provider))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('provider_id', response.data)
        # The error message names the location for actionable feedback.
        self.assertIn('Main', str(response.data['provider_id']))

    def test_cross_tenant_location_id_rejected(self):
        other_tenant, _ = _make_tenant('other-create')
        other_location = other_tenant.locations.get(is_default=True)
        body = self._payload(provider=self.main_provider)
        body['location_id'] = other_location.id
        response = self._post(body)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('location_id', response.data)

    def test_inactive_location_id_rejected(self):
        # Make brooklyn inactive, then try to book at it.
        self.brooklyn.is_active = False
        self.brooklyn.save()
        body = self._payload(provider=self.brooklyn_provider)
        body['location_id'] = self.brooklyn.id
        response = self._post(body)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('location_id', response.data)


# ── Bookable memberships filter by ?location= ───────────────────────


class BookableMembershipsLocationFilterTests(TestCase):
    """`/api/memberships/?bookable=true&location=<slug>` returns only
    providers assigned (via MembershipLocation) to the requested site.
    The calendar uses this on every load so the day-view at LA only
    shows providers who actually work at LA."""

    @classmethod
    def setUpTestData(cls):
        cls.tenant, cls.owner = _make_tenant('bm-tenant')
        cls.main = cls.tenant.locations.get(is_default=True)
        cls.la = Location.objects.create(
            tenant=cls.tenant, name='LA', slug='la',
            is_default=False, is_active=True,
            timezone='America/Los_Angeles',
        )
        cls.main_only = _make_provider(cls.tenant, location=cls.main)
        cls.la_only = _make_provider(cls.tenant, location=cls.la)
        # A provider assigned to BOTH sites — should appear in both filters.
        cls.both = _make_provider(cls.tenant, location=cls.main)
        from apps.tenants.models import MembershipLocation
        MembershipLocation.objects.create(
            membership=cls.both, location=cls.la, is_active=True,
        )

    def setUp(self):
        self.client = APIClient()
        self.client.force_login(self.owner)
        self.url = reverse('membership-list')

    def _list(self, *, params: str = '', cookie: str | None = None):
        if cookie is not None:
            self.client.cookies[ACTIVE_LOCATION_COOKIE] = cookie
        else:
            self.client.cookies.pop(ACTIVE_LOCATION_COOKIE, None)
        return self.client.get(
            f'{self.url}?{params}',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )

    def test_no_location_filter_returns_all_bookable(self):
        # Backwards compat: omitting `?location=` returns all bookable
        # providers (the staff list at /staff/employees uses this shape).
        response = self._list(params='bookable=true&active=true')
        ids = {row['id'] for row in response.data}
        # Owner is also a membership; we filter only on the providers we
        # care about by intersection.
        self.assertEqual(
            {self.main_only.id, self.la_only.id, self.both.id} & ids,
            {self.main_only.id, self.la_only.id, self.both.id},
        )

    def test_location_current_filters_to_active_location(self):
        # Cookie='la' → only la_only + both should appear.
        response = self._list(
            params='bookable=true&active=true&location=current',
            cookie='la',
        )
        ids = {row['id'] for row in response.data}
        self.assertIn(self.la_only.id, ids)
        self.assertIn(self.both.id, ids)
        self.assertNotIn(self.main_only.id, ids)

    def test_location_specific_slug_filters_correctly(self):
        # Explicit slug works the same way regardless of cookie.
        response = self._list(params='bookable=true&active=true&location=main')
        ids = {row['id'] for row in response.data}
        self.assertIn(self.main_only.id, ids)
        self.assertIn(self.both.id, ids)
        self.assertNotIn(self.la_only.id, ids)

    def test_unknown_location_slug_returns_empty(self):
        # Safer than silently widening to the org-wide list — a typo or
        # stale cookie shouldn't surface providers the operator didn't
        # expect on that calendar.
        response = self._list(params='bookable=true&active=true&location=nonexistent')
        self.assertEqual(response.data, [])

    def test_location_does_not_leak_inactive_assignments(self):
        # Mark the 'both' provider's LA assignment inactive — they
        # disappear from LA but remain at main.
        from apps.tenants.models import MembershipLocation
        MembershipLocation.objects.filter(
            membership=self.both, location=self.la,
        ).update(is_active=False)
        response = self._list(params='bookable=true&active=true&location=la')
        ids = {row['id'] for row in response.data}
        self.assertIn(self.la_only.id, ids)
        self.assertNotIn(self.both.id, ids)


# ── Schedule-fit validation on appointment create/update ────────────


class ScheduleFitValidationTests(TestCase):
    """Appointments must fit within the provider's `ProviderSchedule`
    blocks for the day at the appointment's location. Defense in depth
    — the calendar's drag-drop UX shows the working-hours overlay as
    a visual hint, but the API enforces."""

    @classmethod
    def setUpTestData(cls):
        # Tenant in NY tz so the test times are easy to reason about
        # without DST surprises (May = EDT, UTC-4).
        cls.tenant, cls.owner = _make_tenant('sched-fit', timezone='America/New_York')
        cls.location = cls.tenant.locations.get(is_default=True)
        cls.provider = _make_provider(cls.tenant, location=cls.location)
        cls.service = _make_service(cls.tenant)
        cls.customer = _make_customer(cls.tenant)
        cls.assignment = cls.provider.location_assignments.first()

        # Schedule: Mon 09:00-12:00 + 13:00-17:00 (split shift), Tue off.
        from apps.tenants.models import ProviderSchedule
        ProviderSchedule.objects.create(
            membership_location=cls.assignment,
            weekly_hours={
                'monday': [
                    {'start': '09:00', 'end': '12:00'},
                    {'start': '13:00', 'end': '17:00'},
                ],
                'tuesday': [],  # explicitly off
                'wednesday': [],
                'thursday': [],
                'friday': [],
                'saturday': [],
                'sunday': [],
            },
        )

    def setUp(self):
        self.client = APIClient()
        self.client.force_login(self.owner)
        self.url = reverse('appointment-list')

    def _post(self, *, start_iso, end_iso):
        return self.client.post(
            self.url,
            data={
                'customer_id': self.customer.id,
                'service_id': self.service.id,
                'provider_id': self.provider.id,
                'start_time': start_iso,
                'end_time': end_iso,
            },
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )

    # 2026-05-04 is a Monday in NY; UTC-4 (EDT). Local 10:00 = 14:00 UTC.

    def test_appointment_inside_block_accepted(self):
        # Mon 10:00-10:30 NY local = 14:00-14:30 UTC. Within 09-12 block.
        response = self._post(
            start_iso='2026-05-04T14:00:00Z',
            end_iso='2026-05-04T14:30:00Z',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_appointment_in_split_shift_gap_rejected(self):
        # Mon 12:30-13:00 NY = 16:30-17:00 UTC. Falls in the 12-13 lunch gap.
        response = self._post(
            start_iso='2026-05-04T16:30:00Z',
            end_iso='2026-05-04T17:00:00Z',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('start_time', response.data)
        self.assertIn('working hours', str(response.data['start_time']).lower())

    def test_appointment_partially_outside_block_rejected(self):
        # Mon 11:30-12:30 NY = 15:30-16:30 UTC. Starts inside 09-12, ends in gap.
        response = self._post(
            start_iso='2026-05-04T15:30:00Z',
            end_iso='2026-05-04T16:30:00Z',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('start_time', response.data)

    def test_appointment_on_off_day_rejected(self):
        # Tuesday 2026-05-05 — schedule says off. Local 10:00 = 14:00 UTC.
        response = self._post(
            start_iso='2026-05-05T14:00:00Z',
            end_iso='2026-05-05T14:30:00Z',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('start_time', response.data)
        self.assertIn('not scheduled', str(response.data['start_time']).lower())

    def test_provider_with_no_schedule_unconstrained(self):
        # Spin up a second provider with no ProviderSchedule row at all
        # — they should be bookable any time within business hours.
        unconstrained = _make_provider(self.tenant, location=self.location)
        response = self.client.post(
            self.url,
            data={
                'customer_id': self.customer.id,
                'service_id': self.service.id,
                'provider_id': unconstrained.id,
                'start_time': '2026-05-05T14:00:00Z',  # Tuesday — off for the scheduled provider
                'end_time': '2026-05-05T14:30:00Z',
            },
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_cancelling_existing_appointment_outside_hours_still_allowed(self):
        # Pre-create an appointment in-hours, then move it (PATCH status
        # to cancelled). The validator must skip the schedule check on
        # cancel — closing out an existing booking shouldn't fight a
        # later schedule change.
        from apps.appointments.models import Appointment
        appt = _make_appointment(
            tenant=self.tenant, customer=self.customer, provider=self.provider,
            service=self.service, location=self.location,
            start_utc=dt.datetime(2026, 5, 4, 14, 0, tzinfo=dt.timezone.utc),
        )
        # Now mutate the schedule so the existing appointment is "outside
        # hours" — then cancel via PATCH. Should succeed.
        from apps.tenants.models import ProviderSchedule
        ProviderSchedule.objects.filter(
            membership_location=self.assignment,
        ).update(weekly_hours={
            'monday': [], 'tuesday': [], 'wednesday': [], 'thursday': [],
            'friday': [], 'saturday': [], 'sunday': [],
        })
        response = self.client.patch(
            reverse('appointment-detail', args=[appt.pk]),
            data={'status': 'cancelled'},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        appt.refresh_from_db()
        self.assertEqual(appt.status, Appointment.Status.CANCELLED)

    def test_cancel_with_reason_is_stored_and_logged(self):
        # Cancelling with a reason persists it on the appointment AND
        # records it in the audit metadata so the activity log can
        # answer "why was this cancelled".
        from apps.appointments.models import Appointment
        from apps.audit.models import AuditLog

        appt = _make_appointment(
            tenant=self.tenant, customer=self.customer, provider=self.provider,
            service=self.service, location=self.location,
            start_utc=dt.datetime(2026, 5, 4, 14, 0, tzinfo=dt.timezone.utc),
        )
        response = self.client.patch(
            reverse('appointment-detail', args=[appt.pk]),
            data={'status': 'cancelled', 'cancelled_reason': 'Duplicate appointment'},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        appt.refresh_from_db()
        self.assertEqual(appt.status, Appointment.Status.CANCELLED)
        self.assertEqual(appt.cancelled_reason, 'Duplicate appointment')

        log = (
            AuditLog.objects
            .filter(
                resource_type='appointment', resource_id=str(appt.pk),
                action=AuditLog.Action.UPDATE,
            )
            .order_by('-timestamp')
            .first()
        )
        self.assertIsNotNone(log)
        self.assertEqual(log.metadata.get('to_status'), 'cancelled')
        self.assertEqual(
            log.metadata.get('cancelled_reason'), 'Duplicate appointment',
        )


# ── Appointment SMS (confirmation + reminder) ────────────────────────


class AppointmentConfirmationSMSTests(TestCase):
    """Covers the post_save signal that fires the SMS confirmation.

    The Twilio API call is patched out — we verify our code does the
    right thing (consent gate, idempotency, audit log, row stamping)
    without actually hitting the network. Real Twilio behavior is
    out of our test scope."""

    @classmethod
    def setUpTestData(cls):
        cls.tenant, cls.owner = _make_tenant('sms-conf')
        cls.provider = _make_provider(cls.tenant)
        cls.service = _make_service(cls.tenant)

    def _make_consenting_customer(self):
        return Customer.objects.create(
            tenant=self.tenant,
            first_name='Pat', last_name='Patient',
            email='pat-consent@test.local',
            phone='+15551234567',
            sms_opt_in=True,
        )

    def _make_no_consent_customer(self):
        return Customer.objects.create(
            tenant=self.tenant,
            first_name='Pat', last_name='NoConsent',
            email='pat-noconsent@test.local',
            phone='+15551234567',
            sms_opt_in=False,
        )

    def _create_appointment(self, customer):
        start = djtz.now() + dt.timedelta(days=2)
        return _make_appointment(
            tenant=self.tenant, customer=customer,
            provider=self.provider, service=self.service,
            start_utc=start,
        )

    @override_settings(
        TWILIO_ACCOUNT_SID='ACtest',
        TWILIO_AUTH_TOKEN='test-token',
        TWILIO_FROM_NUMBER='+18885550000',
    )
    def test_confirmation_fires_on_create_with_consenting_customer(self):
        customer = self._make_consenting_customer()
        fake_message = MagicMock(sid='SMconf123')
        fake_client = MagicMock()
        fake_client.messages.create.return_value = fake_message

        with patch('twilio.rest.Client', return_value=fake_client):
            appt = self._create_appointment(customer)

        fake_client.messages.create.assert_called_once()
        kwargs = fake_client.messages.create.call_args.kwargs
        self.assertEqual(kwargs['to'], '+15551234567')
        self.assertIn('Pat', kwargs['body'])
        self.assertIn(self.tenant.name, kwargs['body'])

        appt.refresh_from_db()
        self.assertIsNotNone(appt.confirmation_sms_sent_at)
        self.assertEqual(appt.confirmation_sms_provider_id, 'SMconf123')

    def test_confirmation_skipped_when_customer_has_no_sms_consent(self):
        customer = self._make_no_consent_customer()
        with patch('twilio.rest.Client') as fake_client_cls:
            appt = self._create_appointment(customer)
        fake_client_cls.assert_not_called()
        appt.refresh_from_db()
        self.assertIsNone(appt.confirmation_sms_sent_at)
        # Audit log entry recorded the skip reason.
        log = AuditLog.objects.filter(
            resource_type='appointment_sms',
            resource_id=str(appt.pk),
            metadata__kind='confirmation',
        ).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.metadata.get('outcome'), 'skipped')
        self.assertEqual(log.metadata.get('reason'), 'no_consent_transactional')

    def test_confirmation_skipped_when_customer_has_no_phone(self):
        customer = Customer.objects.create(
            tenant=self.tenant,
            first_name='Pat', last_name='NoPhone',
            email='pat-nophone@test.local',
            phone='',
            sms_opt_in=True,
        )
        with patch('twilio.rest.Client') as fake_client_cls:
            appt = self._create_appointment(customer)
        fake_client_cls.assert_not_called()
        appt.refresh_from_db()
        self.assertIsNone(appt.confirmation_sms_sent_at)

    @override_settings(
        TWILIO_ACCOUNT_SID='ACtest',
        TWILIO_AUTH_TOKEN='test-token',
        TWILIO_FROM_NUMBER='+18885550000',
    )
    def test_confirmation_swallows_twilio_error_so_appointment_save_succeeds(self):
        from twilio.base.exceptions import TwilioRestException
        customer = self._make_consenting_customer()
        fake_client = MagicMock()
        fake_client.messages.create.side_effect = TwilioRestException(
            uri='/test', msg='Number temporarily unreachable', code=30003, status=400,
        )
        # The signal handler catches the SMSDispatchError; the
        # appointment commit should succeed regardless. This is
        # critical — a Twilio outage shouldn't fail a booking.
        with patch('twilio.rest.Client', return_value=fake_client):
            appt = self._create_appointment(customer)
        appt.refresh_from_db()
        self.assertEqual(appt.status, Appointment.Status.BOOKED)
        # confirmation_sms_sent_at stays None because send_sms raised
        # before the row update happened.
        self.assertIsNone(appt.confirmation_sms_sent_at)

    def test_confirmation_not_sent_when_appointment_created_cancelled(self):
        # Historical/seed import path: someone creating an appointment
        # already-cancelled shouldn't trigger a confirmation.
        customer = self._make_consenting_customer()
        with patch('twilio.rest.Client') as fake_client_cls:
            appt = Appointment.objects.create(
                tenant=self.tenant, customer=customer,
                provider=self.provider, service=self.service,
                location=self.tenant.locations.get(is_default=True),
                start_time=djtz.now() + dt.timedelta(days=2),
                end_time=djtz.now() + dt.timedelta(days=2, hours=1),
                status=Appointment.Status.CANCELLED,
                quoted_price_cents=self.service.price_cents,
            )
        fake_client_cls.assert_not_called()
        self.assertIsNone(appt.confirmation_sms_sent_at)


class AppointmentReminderSMSTests(TestCase):
    """`send_appointment_reminders` management command — finds
    appointments 24h out, sends reminder, stamps the row."""

    @classmethod
    def setUpTestData(cls):
        cls.tenant, cls.owner = _make_tenant('sms-rem')
        cls.provider = _make_provider(cls.tenant)
        cls.service = _make_service(cls.tenant)

    def _make_appt_at(self, hours_from_now: int, *, sms_opt_in=True, phone='+15551234567'):
        customer = Customer.objects.create(
            tenant=self.tenant,
            first_name='Pat', last_name='Patient',
            email=f'pat-{hours_from_now}h@test.local',
            phone=phone,
            sms_opt_in=sms_opt_in,
        )
        start = djtz.now() + dt.timedelta(hours=hours_from_now)
        # Avoid firing the create-signal's Twilio call during setup —
        # the test asserts on the reminder path. Patch the Client
        # with a fake whose `messages.create` returns a fake_message
        # carrying a real string `sid` so the row update doesn't
        # blow up trying to store a MagicMock in a CharField.
        fake_setup_client = MagicMock()
        fake_setup_client.messages.create.return_value = MagicMock(sid='setup-noop-sid')
        with patch('twilio.rest.Client', return_value=fake_setup_client):
            return _make_appointment(
                tenant=self.tenant, customer=customer,
                provider=self.provider, service=self.service,
                start_utc=start,
            )

    @override_settings(
        TWILIO_ACCOUNT_SID='ACtest',
        TWILIO_AUTH_TOKEN='test-token',
        TWILIO_FROM_NUMBER='+18885550000',
    )
    def test_reminder_fires_for_appointment_in_24h_window(self):
        appt = self._make_appt_at(24)
        fake_message = MagicMock(sid='SMrem456')
        fake_client = MagicMock()
        fake_client.messages.create.return_value = fake_message

        with patch('twilio.rest.Client', return_value=fake_client):
            call_command('send_appointment_reminders')

        fake_client.messages.create.assert_called_once()
        body = fake_client.messages.create.call_args.kwargs['body']
        self.assertIn('reminder', body.lower())
        appt.refresh_from_db()
        self.assertIsNotNone(appt.reminder_sms_sent_at)
        self.assertEqual(appt.reminder_sms_provider_id, 'SMrem456')

    @override_settings(
        TWILIO_ACCOUNT_SID='ACtest',
        TWILIO_AUTH_TOKEN='test-token',
        TWILIO_FROM_NUMBER='+18885550000',
    )
    def test_reminder_idempotent_across_runs(self):
        appt = self._make_appt_at(24)
        fake_client = MagicMock()
        fake_client.messages.create.return_value = MagicMock(sid='SMidem1')

        with patch('twilio.rest.Client', return_value=fake_client):
            call_command('send_appointment_reminders')
        self.assertEqual(fake_client.messages.create.call_count, 1)

        # Re-run — should be a no-op because reminder_sms_sent_at is now set.
        with patch('twilio.rest.Client', return_value=fake_client):
            call_command('send_appointment_reminders')
        self.assertEqual(fake_client.messages.create.call_count, 1)

        appt.refresh_from_db()
        self.assertEqual(appt.reminder_sms_provider_id, 'SMidem1')

    @override_settings(
        TWILIO_ACCOUNT_SID='ACtest',
        TWILIO_AUTH_TOKEN='test-token',
        TWILIO_FROM_NUMBER='+18885550000',
    )
    def test_reminder_skips_outside_window(self):
        # Appointment 5 days out — well outside the 23-25h window.
        self._make_appt_at(120)
        fake_client = MagicMock()
        with patch('twilio.rest.Client', return_value=fake_client):
            call_command('send_appointment_reminders')
        fake_client.messages.create.assert_not_called()

    @override_settings(
        TWILIO_ACCOUNT_SID='ACtest',
        TWILIO_AUTH_TOKEN='test-token',
        TWILIO_FROM_NUMBER='+18885550000',
    )
    def test_reminder_skips_cancelled_appointments(self):
        appt = self._make_appt_at(24)
        appt.status = Appointment.Status.CANCELLED
        appt.save()
        fake_client = MagicMock()
        with patch('twilio.rest.Client', return_value=fake_client):
            call_command('send_appointment_reminders')
        fake_client.messages.create.assert_not_called()

    def test_reminder_dry_run_makes_no_twilio_call(self):
        self._make_appt_at(24)
        fake_client = MagicMock()
        with override_settings(
            TWILIO_ACCOUNT_SID='ACtest',
            TWILIO_AUTH_TOKEN='test-token',
            TWILIO_FROM_NUMBER='+18885550000',
        ), patch('twilio.rest.Client', return_value=fake_client):
            call_command('send_appointment_reminders', '--dry-run')
        fake_client.messages.create.assert_not_called()


# ── Editable templates + review-request automation ──────────────────


class EditableTemplateRenderTests(TestCase):
    """Verifies that tenant-customized templates override the platform
    defaults and that token substitution covers all three surfaces."""

    @classmethod
    def setUpTestData(cls):
        cls.tenant, cls.owner = _make_tenant('tpl')
        cls.provider = _make_provider(cls.tenant)
        cls.service = _make_service(cls.tenant)
        cls.customer = Customer.objects.create(
            tenant=cls.tenant, first_name='Alex', last_name='Test',
            email='alex@test.local', phone='+15559990000', sms_opt_in=True,
        )

    def _make_appt(self):
        start = djtz.now() + dt.timedelta(days=2)
        return _make_appointment(
            tenant=self.tenant, customer=self.customer,
            provider=self.provider, service=self.service,
            start_utc=start,
        )

    def test_default_confirmation_used_when_template_blank(self):
        from apps.appointments.sms import render_confirmation_body

        appt = self._make_appt()
        body = render_confirmation_body(appt)
        self.assertIn('Alex', body)
        self.assertIn(self.tenant.name, body)
        self.assertIn('Reply STOP', body)

    def test_tenant_confirmation_template_overrides_default(self):
        from apps.appointments.sms import render_confirmation_body

        self.tenant.confirmation_sms_template = (
            'Hey {{first_name}}! You\'re booked at {{spa_name}} for {{appointment_time}}.'
        )
        self.tenant.save(update_fields=['confirmation_sms_template'])

        appt = self._make_appt()
        body = render_confirmation_body(appt)
        self.assertTrue(body.startswith('Hey Alex!'))
        self.assertIn(self.tenant.name, body)
        # The default's "Reply STOP" tail is gone — tenant owns the body now.
        self.assertNotIn('Reply STOP', body)

    def test_review_request_template_substitutes_review_url(self):
        from apps.appointments.sms import render_review_request_body

        self.tenant.review_request_sms_template = (
            'Hi {{first_name}}, leave us a review: {{review_url}}'
        )
        self.tenant.google_review_url = 'https://g.page/r/CXXXXX/review'
        self.tenant.save(update_fields=[
            'review_request_sms_template', 'google_review_url',
        ])

        appt = self._make_appt()
        body = render_review_request_body(appt)
        self.assertIn('Alex', body)
        self.assertIn('https://g.page/r/CXXXXX/review', body)

    def test_unknown_token_left_as_is(self):
        from apps.appointments.sms import render_template

        appt = self._make_appt()
        body = render_template(
            'Hi {{first_name}}, your code is {{my_typo}}.', appointment=appt,
        )
        # Recognised token substituted, unknown token preserved literally.
        self.assertIn('Hi Alex', body)
        self.assertIn('{{my_typo}}', body)


class ReviewRequestSendTests(TestCase):
    """Covers the consent + opt-in gating on the review-request
    automation. Twilio is patched out."""

    @classmethod
    def setUpTestData(cls):
        cls.tenant, cls.owner = _make_tenant('rev-spa')
        cls.tenant.twilio_from_number = '+18445550000'
        cls.tenant.save(update_fields=['twilio_from_number'])
        cls.provider = _make_provider(cls.tenant)
        cls.service = _make_service(cls.tenant)
        cls.customer = Customer.objects.create(
            tenant=cls.tenant, first_name='Riley', last_name='Test',
            email='riley@test.local', phone='+15558887777', sms_opt_in=True,
        )

    def _make_completed_appointment(self):
        start = djtz.now() - dt.timedelta(hours=26)
        appt = _make_appointment(
            tenant=self.tenant, customer=self.customer,
            provider=self.provider, service=self.service,
            start_utc=start,
        )
        # Force completed status + completed_at outside the post_save
        # signal (which already ran for confirmation).
        appt.status = Appointment.Status.COMPLETED
        appt.completed_at = djtz.now() - dt.timedelta(hours=24)
        appt.save(update_fields=['status', 'completed_at'])
        return appt

    @override_settings(
        TWILIO_ACCOUNT_SID='ACtest',
        TWILIO_AUTH_TOKEN='test-token',
    )
    def test_send_review_request_fires_when_enabled(self):
        from apps.appointments.sms import send_review_request_sms
        from apps.messaging.models import Direction, Message, MessageKind

        self.tenant.review_request_enabled = True
        self.tenant.google_review_url = 'https://g.page/r/Cabc/review'
        self.tenant.save(update_fields=[
            'review_request_enabled', 'google_review_url',
        ])
        appt = self._make_completed_appointment()

        fake_message = MagicMock(sid='SMrev1')
        fake_client = MagicMock()
        fake_client.messages.create.return_value = fake_message

        with patch('twilio.rest.Client', return_value=fake_client):
            fired = send_review_request_sms(appt)

        self.assertTrue(fired)
        fake_client.messages.create.assert_called_once()
        kwargs = fake_client.messages.create.call_args.kwargs
        self.assertIn('Riley', kwargs['body'])
        self.assertIn('https://g.page/r/Cabc/review', kwargs['body'])

        appt.refresh_from_db()
        self.assertIsNotNone(appt.review_request_sms_sent_at)
        self.assertEqual(appt.review_request_sms_provider_id, 'SMrev1')

        # Mirror into the inbox: a Message row tagged as review_request
        # should exist for this customer.
        mirrored = Message.objects.get(
            tenant=self.tenant, customer=self.customer,
            kind=MessageKind.REVIEW_REQUEST,
        )
        self.assertEqual(mirrored.direction, Direction.OUTBOUND)
        self.assertEqual(mirrored.provider_message_id, 'SMrev1')
        self.assertIn('https://g.page/r/Cabc/review', mirrored.body)

    def test_send_skipped_when_tenant_not_enabled(self):
        from apps.appointments.sms import send_review_request_sms

        # tenant.review_request_enabled defaults False.
        appt = self._make_completed_appointment()
        fake_client = MagicMock()
        with patch('twilio.rest.Client', return_value=fake_client):
            fired = send_review_request_sms(appt)
        self.assertFalse(fired)
        fake_client.messages.create.assert_not_called()

    def test_send_skipped_when_no_review_url(self):
        from apps.appointments.sms import send_review_request_sms

        self.tenant.review_request_enabled = True
        self.tenant.save(update_fields=['review_request_enabled'])
        appt = self._make_completed_appointment()
        fake_client = MagicMock()
        with patch('twilio.rest.Client', return_value=fake_client):
            fired = send_review_request_sms(appt)
        self.assertFalse(fired)
        fake_client.messages.create.assert_not_called()

    def test_send_skipped_when_appointment_not_completed(self):
        from apps.appointments.sms import send_review_request_sms

        self.tenant.review_request_enabled = True
        self.tenant.google_review_url = 'https://g.page/r/C/review'
        self.tenant.save(update_fields=[
            'review_request_enabled', 'google_review_url',
        ])
        appt = self._make_completed_appointment()
        appt.status = Appointment.Status.CHECKED_IN
        appt.save(update_fields=['status'])

        fake_client = MagicMock()
        with patch('twilio.rest.Client', return_value=fake_client):
            fired = send_review_request_sms(appt)
        self.assertFalse(fired)


class AutomatedTemplatesEndpointTests(TestCase):
    """The `/api/messaging/automated-templates/` settings API.

    Covers GET shape, PATCH, the enabled-requires-URL validation, and
    tenant scoping (one tenant can't read or write another's row)."""

    @classmethod
    def setUpTestData(cls):
        cls.tenant, cls.owner = _make_tenant('tpl-api')
        cls.other_tenant, _ = _make_tenant('tpl-api-other')

    def setUp(self):
        self.client = APIClient()
        self.client.force_login(self.owner)

    def test_get_returns_defaults_when_blank(self):
        response = self.client.get(
            '/api/messaging/automated-templates/',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['confirmation_sms_template'], '')
        self.assertIn('{{first_name}}', response.data['default_confirmation_body'])
        self.assertFalse(response.data['review_request_enabled'])

    def test_patch_persists_custom_template(self):
        response = self.client.patch(
            '/api/messaging/automated-templates/',
            data={'confirmation_sms_template': 'Custom {{first_name}}'},
            format='json', HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.confirmation_sms_template, 'Custom {{first_name}}')

    def test_enabling_review_without_url_rejected(self):
        response = self.client.patch(
            '/api/messaging/automated-templates/',
            data={'review_request_enabled': True},
            format='json', HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('google_review_url', response.data)

    def test_enabling_review_with_url_accepted(self):
        response = self.client.patch(
            '/api/messaging/automated-templates/',
            data={
                'review_request_enabled': True,
                'google_review_url': 'https://g.page/r/C/review',
            },
            format='json', HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.tenant.refresh_from_db()
        self.assertTrue(self.tenant.review_request_enabled)
        self.assertEqual(self.tenant.google_review_url, 'https://g.page/r/C/review')

    def test_requires_auth(self):
        from rest_framework.test import APIClient
        response = APIClient().get(
            '/api/messaging/automated-templates/',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertIn(response.status_code, (401, 403))


# ── Editing services on a booked appointment ───────────────────────


class AppointmentServiceEditingTests(TestCase):
    """Add / change / remove services on an existing appointment.

    Each operation keeps the calendar block length and the still-open
    invoice in sync. Once the invoice is paid the services lock.
    """

    def setUp(self):
        self.tenant, self.owner = _make_tenant('appt-svc-edit')
        self.provider = _make_provider(self.tenant)
        self.customer = _make_customer(self.tenant)
        self.category = ServiceCategory.objects.create(
            tenant=self.tenant, name='Treatments',
        )
        self.facial = self._service('Facial', 'FAC30', 30, 10000)
        self.botox = self._service('Botox', 'BTX20', 20, 20000)
        self.peel = self._service('Peel', 'PEEL45', 45, 15000)
        self.appt = _make_appointment(
            tenant=self.tenant, customer=self.customer,
            provider=self.provider, service=self.facial,
            start_utc=djtz.now() + dt.timedelta(days=1),
        )
        self.client = APIClient()
        self.client.force_login(self.owner)

    def _service(self, name, code, minutes, price):
        return Service.objects.create(
            tenant=self.tenant, category=self.category,
            name=name, code=code,
            duration_minutes=minutes, buffer_minutes=0,
            price_cents=price, service_type=Service.ServiceType.REGULAR,
        )

    def _invoice(self):
        from apps.invoices.models import Invoice
        return Invoice.objects.get(appointment=self.appt)

    def _add_url(self):
        return reverse('appointment-add-service', args=[self.appt.pk])

    def _change_url(self):
        return reverse('appointment-change-service', args=[self.appt.pk])

    def _remove_url(self, es_pk):
        return reverse(
            'appointment-remove-extra-service', args=[self.appt.pk, es_pk],
        )

    # ── Add ──────────────────────────────────────────────────────────

    def test_add_service_creates_extra_and_extends_block(self):
        old_end = self.appt.end_time
        resp = self.client.post(
            self._add_url(), {'service_id': self.botox.pk},
            format='json', HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.appt.refresh_from_db()
        self.assertEqual(self.appt.extra_services.count(), 1)
        extra = self.appt.extra_services.get()
        self.assertEqual(extra.service_id, self.botox.pk)
        self.assertEqual(extra.price_cents, 20000)
        self.assertEqual(extra.duration_minutes, 20)
        self.assertEqual(
            self.appt.end_time, old_end + dt.timedelta(minutes=20),
        )
        invoice = self._invoice()
        self.assertEqual(invoice.line_items.count(), 2)
        self.assertEqual(extra.invoice_line.service_id, self.botox.pk)

    def test_add_service_updates_total_price(self):
        self.client.post(
            self._add_url(), {'service_id': self.botox.pk},
            format='json', HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        resp = self.client.get(
            reverse('appointment-detail', args=[self.appt.pk]),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(resp.data['total_price_cents'], 30000)
        self.assertEqual(len(resp.data['extra_services']), 1)

    def test_add_unknown_service_rejected(self):
        resp = self.client.post(
            self._add_url(), {'service_id': 999999},
            format='json', HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(resp.status_code, 400)

    def test_add_inactive_service_rejected(self):
        self.botox.is_active = False
        self.botox.save()
        resp = self.client.post(
            self._add_url(), {'service_id': self.botox.pk},
            format='json', HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(resp.status_code, 400)

    def test_add_cross_tenant_service_rejected(self):
        other_tenant, _ = _make_tenant('appt-svc-other')
        other_cat = ServiceCategory.objects.create(
            tenant=other_tenant, name='X',
        )
        other_service = Service.objects.create(
            tenant=other_tenant, category=other_cat,
            name='Other', code='OTH30',
            duration_minutes=30, price_cents=5000,
            service_type=Service.ServiceType.REGULAR,
        )
        resp = self.client.post(
            self._add_url(), {'service_id': other_service.pk},
            format='json', HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(resp.status_code, 400)

    def test_add_service_audit_logged(self):
        self.client.post(
            self._add_url(), {'service_id': self.botox.pk},
            format='json', HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        log = (
            AuditLog.objects.filter(
                resource_type='appointment',
                resource_id=str(self.appt.pk),
                action=AuditLog.Action.UPDATE,
            )
            .order_by('-timestamp')
            .first()
        )
        self.assertIsNotNone(log)
        self.assertEqual(log.metadata.get('event'), 'service_added')
        self.assertEqual(log.metadata.get('service_id'), self.botox.pk)

    # ── Change ───────────────────────────────────────────────────────

    def test_change_service_swaps_primary_and_invoice(self):
        resp = self.client.post(
            self._change_url(), {'service_id': self.peel.pk},
            format='json', HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.appt.refresh_from_db()
        self.assertEqual(self.appt.service_id, self.peel.pk)
        self.assertEqual(self.appt.quoted_price_cents, 15000)
        line = self.appt.primary_invoice_line
        self.assertIsNotNone(line)
        line.refresh_from_db()
        self.assertEqual(line.service_id, self.peel.pk)
        self.assertEqual(line.unit_price_cents, 15000)

    def test_change_service_shifts_end_time_by_duration_delta(self):
        old_end = self.appt.end_time
        self.client.post(
            self._change_url(), {'service_id': self.peel.pk},
            format='json', HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.appt.refresh_from_db()
        # Peel 45m − Facial 30m = +15m.
        self.assertEqual(
            self.appt.end_time, old_end + dt.timedelta(minutes=15),
        )

    def test_change_to_same_service_is_noop(self):
        resp = self.client.post(
            self._change_url(), {'service_id': self.facial.pk},
            format='json', HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(resp.status_code, 200)
        self.appt.refresh_from_db()
        self.assertEqual(self.appt.service_id, self.facial.pk)

    # ── Remove ───────────────────────────────────────────────────────

    def test_remove_extra_service(self):
        add = self.client.post(
            self._add_url(), {'service_id': self.botox.pk},
            format='json', HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        extra_id = add.data['extra_services'][0]['id']
        self.appt.refresh_from_db()
        end_with_extra = self.appt.end_time
        resp = self.client.delete(
            self._remove_url(extra_id), HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.appt.refresh_from_db()
        self.assertEqual(self.appt.extra_services.count(), 0)
        self.assertEqual(
            self.appt.end_time, end_with_extra - dt.timedelta(minutes=20),
        )
        self.assertEqual(self._invoice().line_items.count(), 1)

    def test_remove_unknown_extra_service_404(self):
        resp = self.client.delete(
            self._remove_url(999999), HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(resp.status_code, 404)

    # ── Paid-invoice lock ────────────────────────────────────────────

    def test_services_locked_once_invoice_paid(self):
        self._invoice().close(by_user=self.owner, payment_method='cash')
        add = self.client.post(
            self._add_url(), {'service_id': self.botox.pk},
            format='json', HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(add.status_code, 409)
        change = self.client.post(
            self._change_url(), {'service_id': self.peel.pk},
            format='json', HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(change.status_code, 409)

    def test_services_editable_flag_reflects_invoice(self):
        resp = self.client.get(
            reverse('appointment-detail', args=[self.appt.pk]),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertTrue(resp.data['services_editable'])
        self._invoice().close(by_user=self.owner, payment_method='cash')
        resp2 = self.client.get(
            reverse('appointment-detail', args=[self.appt.pk]),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertFalse(resp2.data['services_editable'])


# ── Booking an appointment with multiple services at once ──────────


class AppointmentCreateWithExtraServicesTests(TestCase):
    """Multi-service bookings via `POST /api/appointments/`.

    The frontend supplies an `extras` array alongside the primary
    `service_id`. Each row carries `service_id` and an optional
    `provider_id` override (null = inherit the appointment's primary
    provider). The server snapshots each into an `AppointmentService`
    row and adds a matching invoice line in the same transaction, so
    one round-trip books a Facial + Botox + Peel visit cleanly.
    """

    def setUp(self):
        self.tenant, self.owner = _make_tenant('appt-create-extras')
        self.provider = _make_provider(self.tenant)
        # Second provider used for the per-service-provider override
        # tests below — also assigned to the default location.
        self.other_provider = _make_provider(self.tenant)
        self.customer = _make_customer(self.tenant)
        self.category = ServiceCategory.objects.create(
            tenant=self.tenant, name='Treatments',
        )
        self.facial = self._service('Facial', 'FAC30', 30, 10000)
        self.botox = self._service('Botox', 'BTX20', 20, 20000)
        self.peel = self._service('Peel', 'PEEL45', 45, 15000)
        self.client = APIClient()
        self.client.force_login(self.owner)
        self.url = reverse('appointment-list')

    def _service(self, name, code, minutes, price):
        return Service.objects.create(
            tenant=self.tenant, category=self.category,
            name=name, code=code,
            duration_minutes=minutes, buffer_minutes=0,
            price_cents=price, service_type=Service.ServiceType.REGULAR,
        )

    def _payload(self, *, total_minutes, extras=()):
        # Anchor at a fixed local hour tomorrow so the duration sums
        # never push the block across midnight in the test environment.
        start = (djtz.now() + dt.timedelta(days=1)).replace(
            hour=14, minute=0, second=0, microsecond=0,
        )
        end = start + dt.timedelta(minutes=total_minutes)
        # Normalize each extra to `{service_id, provider_id?}` dict
        # form (callers can pass either a bare service-id int or a
        # dict for compactness).
        normalized_extras = [
            {'service_id': e} if isinstance(e, int) else e
            for e in extras
        ]
        return {
            'customer_id': self.customer.pk,
            'service_id': self.facial.pk,
            'provider_id': self.provider.pk,
            'start_time': start.isoformat(),
            'end_time': end.isoformat(),
            'extras': normalized_extras,
        }

    def test_create_with_extras_creates_rows_and_lines(self):
        from apps.invoices.models import Invoice

        resp = self.client.post(
            self.url,
            self._payload(
                total_minutes=30 + 20 + 45,
                extras=[self.botox.pk, self.peel.pk],
            ),
            format='json', HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        appt = Appointment.objects.get(pk=resp.data['id'])
        self.assertEqual(appt.extra_services.count(), 2)
        botox_es = appt.extra_services.get(service=self.botox)
        # Snapshots taken at create time.
        self.assertEqual(botox_es.price_cents, 20000)
        self.assertEqual(botox_es.duration_minutes, 20)
        self.assertIsNotNone(botox_es.invoice_line_id)
        # No provider override → null (inherits primary).
        self.assertIsNone(botox_es.provider_id)
        invoice = Invoice.objects.get(appointment=appt)
        # Primary + two extras.
        self.assertEqual(invoice.line_items.count(), 3)
        self.assertEqual(
            resp.data['total_price_cents'], 10000 + 20000 + 15000,
        )

    def test_create_with_no_extras_unchanged(self):
        resp = self.client.post(
            self.url,
            self._payload(total_minutes=30),
            format='json', HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(resp.status_code, 201)
        appt = Appointment.objects.get(pk=resp.data['id'])
        self.assertEqual(appt.extra_services.count(), 0)

    def test_create_audit_records_extras(self):
        self.client.post(
            self.url,
            self._payload(total_minutes=30 + 20, extras=[self.botox.pk]),
            format='json', HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        log = (
            AuditLog.objects.filter(
                resource_type='appointment',
                action=AuditLog.Action.CREATE,
            )
            .order_by('-timestamp')
            .first()
        )
        self.assertIsNotNone(log)
        self.assertEqual(
            log.metadata.get('extras'),
            [{'service_id': self.botox.pk, 'provider_id': None}],
        )

    def test_create_with_unknown_extra_rejected(self):
        resp = self.client.post(
            self.url,
            self._payload(total_minutes=30, extras=[999999]),
            format='json', HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(resp.status_code, 400)

    def test_create_with_inactive_extra_rejected(self):
        self.botox.is_active = False
        self.botox.save()
        resp = self.client.post(
            self.url,
            self._payload(total_minutes=30, extras=[self.botox.pk]),
            format='json', HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(resp.status_code, 400)

    def test_create_with_cross_tenant_extra_rejected(self):
        other_tenant, _ = _make_tenant('appt-create-extras-other')
        other_cat = ServiceCategory.objects.create(
            tenant=other_tenant, name='X',
        )
        cross_service = Service.objects.create(
            tenant=other_tenant, category=other_cat,
            name='Other', code='OTH30',
            duration_minutes=30, price_cents=5000,
            service_type=Service.ServiceType.REGULAR,
        )
        resp = self.client.post(
            self.url,
            self._payload(total_minutes=30, extras=[cross_service.pk]),
            format='json', HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(resp.status_code, 400)

    def test_create_with_duplicate_extras_allowed(self):
        # Two areas of Botox in one visit is a legitimate booking.
        resp = self.client.post(
            self.url,
            self._payload(
                total_minutes=30 + 20 + 20,
                extras=[self.botox.pk, self.botox.pk],
            ),
            format='json', HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        appt = Appointment.objects.get(pk=resp.data['id'])
        self.assertEqual(
            appt.extra_services.filter(service=self.botox).count(), 2,
        )

    def test_extras_not_accepted_via_patch(self):
        appt = _make_appointment(
            tenant=self.tenant, customer=self.customer,
            provider=self.provider, service=self.facial,
            start_utc=djtz.now() + dt.timedelta(days=1),
        )
        resp = self.client.patch(
            reverse('appointment-detail', args=[appt.pk]),
            {'extras': [{'service_id': self.botox.pk}]},
            format='json', HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn('extras', resp.data)

    # ── Per-service provider overrides ───────────────────────────────

    def test_extra_with_provider_override_persists(self):
        resp = self.client.post(
            self.url,
            self._payload(
                total_minutes=30 + 20,
                extras=[{
                    'service_id': self.botox.pk,
                    'provider_id': self.other_provider.pk,
                }],
            ),
            format='json', HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        appt = Appointment.objects.get(pk=resp.data['id'])
        es = appt.extra_services.get(service=self.botox)
        self.assertEqual(es.provider_id, self.other_provider.pk)

    def test_extra_with_unknown_provider_rejected(self):
        resp = self.client.post(
            self.url,
            self._payload(
                total_minutes=30 + 20,
                extras=[{
                    'service_id': self.botox.pk,
                    'provider_id': 999999,
                }],
            ),
            format='json', HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn('extras', resp.data)

    def test_extra_with_cross_tenant_provider_rejected(self):
        other_tenant, _ = _make_tenant('appt-extras-prov-iso')
        cross_provider = _make_provider(other_tenant)
        resp = self.client.post(
            self.url,
            self._payload(
                total_minutes=30 + 20,
                extras=[{
                    'service_id': self.botox.pk,
                    'provider_id': cross_provider.pk,
                }],
            ),
            format='json', HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(resp.status_code, 400)

    def test_extra_with_provider_not_at_location_rejected(self):
        # Make a second location and assign no provider to it; the
        # default-location-scoped booking should reject a provider
        # who isn't a `MembershipLocation` at that site.
        from apps.tenants.models import Location
        Location.objects.create(
            tenant=self.tenant, name='Brooklyn', slug='brooklyn',
            timezone='America/New_York', is_active=True, is_default=False,
        )
        # other_provider IS assigned to the default location via the
        # _make_provider helper — so this test instead un-assigns them
        # to simulate "provider not at this site."
        from apps.tenants.models import MembershipLocation
        MembershipLocation.objects.filter(
            membership=self.other_provider,
        ).update(is_active=False)
        resp = self.client.post(
            self.url,
            self._payload(
                total_minutes=30 + 20,
                extras=[{
                    'service_id': self.botox.pk,
                    'provider_id': self.other_provider.pk,
                }],
            ),
            format='json', HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(resp.status_code, 400)

    def test_audit_records_provider_override(self):
        self.client.post(
            self.url,
            self._payload(
                total_minutes=30 + 20,
                extras=[{
                    'service_id': self.botox.pk,
                    'provider_id': self.other_provider.pk,
                }],
            ),
            format='json', HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        log = (
            AuditLog.objects.filter(
                resource_type='appointment',
                action=AuditLog.Action.CREATE,
            )
            .order_by('-timestamp')
            .first()
        )
        self.assertEqual(
            log.metadata.get('extras'),
            [{
                'service_id': self.botox.pk,
                'provider_id': self.other_provider.pk,
            }],
        )


# ── Schedule blocks (non-bookable time on a provider's calendar) ────


class TimeBlockTests(TestCase):
    """A block is a non-bookable period on a provider's day — lunch,
    personal time, training. CRUD + day-window filter + audit shape
    mirror the appointments API; no customer/service/invoice side
    because a block isn't a billable event.
    """

    def setUp(self):
        from apps.appointments.models import TimeBlock

        self.tenant, self.owner = _make_tenant('sched-block')
        self.provider = _make_provider(self.tenant)
        self.location = self.tenant.locations.get(is_default=True)
        self.TimeBlock = TimeBlock
        self.client = APIClient()
        self.client.force_login(self.owner)
        self.url = reverse('time-block-list')

    def _payload(self, *, minutes=60, reason='Lunch break', start=None):
        start = start or (djtz.now() + dt.timedelta(days=1)).replace(
            hour=12, minute=0, second=0, microsecond=0,
        )
        end = start + dt.timedelta(minutes=minutes)
        return {
            'provider_id': self.provider.pk,
            'start_time': start.isoformat(),
            'end_time': end.isoformat(),
            'reason': reason,
        }

    # ── Create ──────────────────────────────────────────────────────

    def test_create_block_persists_tenant_and_created_by(self):
        resp = self.client.post(
            self.url, self._payload(),
            format='json', HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        block = self.TimeBlock.objects.get(pk=resp.data['id'])
        self.assertEqual(block.tenant_id, self.tenant.id)
        self.assertEqual(block.created_by, self.owner)
        self.assertEqual(block.provider, self.provider)
        self.assertEqual(block.location, self.location)
        self.assertEqual(block.reason, 'Lunch break')

    def test_create_audit_records_reason_and_provider(self):
        self.client.post(
            self.url, self._payload(reason='Personal time'),
            format='json', HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        log = (
            AuditLog.objects.filter(
                resource_type='time_block',
                action=AuditLog.Action.CREATE,
            )
            .order_by('-timestamp')
            .first()
        )
        self.assertIsNotNone(log)
        self.assertEqual(log.metadata.get('reason'), 'Personal time')
        self.assertEqual(log.metadata.get('provider_id'), self.provider.pk)

    def test_create_blank_reason_rejected(self):
        resp = self.client.post(
            self.url, self._payload(reason='   '),
            format='json', HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn('reason', resp.data)

    def test_create_end_before_start_rejected(self):
        start = (djtz.now() + dt.timedelta(days=1)).replace(
            hour=12, minute=0, second=0, microsecond=0,
        )
        payload = self._payload(start=start)
        # Flip end behind start.
        payload['end_time'] = (start - dt.timedelta(minutes=30)).isoformat()
        resp = self.client.post(
            self.url, payload,
            format='json', HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn('end_time', resp.data)

    def test_create_provider_not_at_location_rejected(self):
        # Add a second location; the existing provider is only assigned
        # to the default site, so blocking them at the second site
        # should fail.
        from apps.tenants.models import Location
        other_loc = Location.objects.create(
            tenant=self.tenant, name='Brooklyn', slug='brooklyn',
            timezone='America/New_York', is_active=True, is_default=False,
        )
        resp = self.client.post(
            self.url,
            {**self._payload(), 'location_id': other_loc.pk},
            format='json', HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn('provider_id', resp.data)

    def test_create_cross_tenant_location_rejected(self):
        other_tenant, _ = _make_tenant('sched-block-other')
        cross_loc = other_tenant.locations.get(is_default=True)
        resp = self.client.post(
            self.url,
            {**self._payload(), 'location_id': cross_loc.pk},
            format='json', HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(resp.status_code, 400)

    # ── List ────────────────────────────────────────────────────────

    def test_list_filters_by_date(self):
        tomorrow = (djtz.now() + dt.timedelta(days=1)).replace(
            hour=12, minute=0, second=0, microsecond=0,
        )
        next_week = tomorrow + dt.timedelta(days=7)
        self.client.post(
            self.url, self._payload(start=tomorrow),
            format='json', HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.client.post(
            self.url, self._payload(start=next_week, reason='Personal'),
            format='json', HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        date_str = tomorrow.date().isoformat()
        resp = self.client.get(
            self.url + f'?date={date_str}',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data), 1)
        self.assertEqual(resp.data[0]['reason'], 'Lunch break')

    # ── Update / delete ─────────────────────────────────────────────

    def test_update_block_resize_audit_logged(self):
        create = self.client.post(
            self.url, self._payload(minutes=60),
            format='json', HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        block_id = create.data['id']
        block = self.TimeBlock.objects.get(pk=block_id)
        new_end = block.end_time + dt.timedelta(minutes=30)
        resp = self.client.patch(
            reverse('time-block-detail', args=[block_id]),
            {'end_time': new_end.isoformat()},
            format='json', HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        block.refresh_from_db()
        self.assertEqual(block.duration_minutes, 90)
        log = (
            AuditLog.objects.filter(
                resource_type='time_block',
                resource_id=str(block_id),
                action=AuditLog.Action.UPDATE,
            )
            .order_by('-timestamp')
            .first()
        )
        self.assertIsNotNone(log)
        self.assertTrue(log.metadata.get('resized'))

    def test_delete_block_audit_logged(self):
        create = self.client.post(
            self.url, self._payload(reason='Training'),
            format='json', HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        block_id = create.data['id']
        resp = self.client.delete(
            reverse('time-block-detail', args=[block_id]),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(
            self.TimeBlock.objects.filter(pk=block_id).exists(),
        )
        log = (
            AuditLog.objects.filter(
                resource_type='time_block',
                action=AuditLog.Action.DELETE,
            )
            .order_by('-timestamp')
            .first()
        )
        self.assertIsNotNone(log)
        self.assertEqual(log.metadata.get('reason'), 'Training')

    def test_cross_tenant_retrieve_404(self):
        other_tenant, other_owner = _make_tenant('sched-block-iso')
        other_provider = _make_provider(other_tenant)
        other_block = self.TimeBlock.objects.create(
            tenant=other_tenant,
            provider=other_provider,
            location=other_tenant.locations.get(is_default=True),
            start_time=djtz.now() + dt.timedelta(days=1),
            end_time=djtz.now() + dt.timedelta(days=1, hours=1),
            reason='Lunch',
        )
        resp = self.client.get(
            reverse('time-block-detail', args=[other_block.pk]),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(resp.status_code, 404)
