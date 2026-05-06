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

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.appointments.models import Appointment
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
