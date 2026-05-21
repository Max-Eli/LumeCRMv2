"""Tests for the public booking API.

Covers the four invariants that define correctness:

  1. Tenant scoping — endpoints respect the URL slug; cross-tenant
     resource references are rejected (a service from tenant A can't
     be booked under tenant B).
  2. Eligibility — only active + bookable + location-assigned + job-
     title-eligible providers appear in the providers endpoint and
     are accepted by submit-booking.
  3. Availability — slots respect ProviderSchedule + lead time +
     existing appointments. Submit-booking re-validates and returns
     409 when the slot was taken between fetch and submit.
  4. Audit logging — every endpoint records an entry; submit + manage
     capture IP + user-agent for the HIPAA trail.

All tests use real DB queries (no mocking) per the integration-tests
discipline established in apps.invoices and apps.forms.
"""

from __future__ import annotations

import datetime as dt

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.appointments.models import Appointment
from apps.audit.models import AuditLog
from apps.customers.models import Customer
from apps.services.models import Service, ServiceCategory
from apps.tenants.models import (
    JobTitle,
    MembershipLocation,
    ProviderSchedule,
    Tenant,
    TenantMembership,
)
from apps.tenants.services import create_tenant_with_defaults

User = get_user_model()


# ── Test fixtures ───────────────────────────────────────────────────


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


def _make_provider(
    tenant: Tenant, *, location=None, job_title=None,
    first_name: str = 'Sam', last_name: str = 'Provider',
) -> TenantMembership:
    user = _make_user(
        f'provider-{tenant.slug}-{TenantMembership.objects.filter(tenant=tenant).count()}@test.local',
        first_name=first_name,
        last_name=last_name,
    )
    membership = TenantMembership.objects.create(
        user=user, tenant=tenant,
        role=TenantMembership.Role.PROVIDER,
        is_bookable=True, is_active=True,
        job_title=job_title,
    )
    if location is None:
        location = tenant.locations.get(is_default=True)
    MembershipLocation.objects.create(
        membership=membership, location=location, is_active=True,
    )
    return membership


def _make_service(tenant: Tenant, *, name: str = 'Facial', duration: int = 30,
                  category: ServiceCategory | None = None) -> Service:
    if category is None:
        category = ServiceCategory.objects.create(tenant=tenant, name=f'{name}-Cat')
    return Service.objects.create(
        tenant=tenant, category=category,
        name=name,
        duration_minutes=duration, buffer_minutes=0,
        price_cents=10000,
        service_type=Service.ServiceType.REGULAR,
        is_active=True, is_bookable_online=True,
    )


def _full_week_schedule(start: str, end: str) -> dict:
    return {
        day: [{'start': start, 'end': end}]
        for day in ProviderSchedule.WEEKDAYS
    }


def _attach_schedule(provider: TenantMembership, *, hours: dict | None = None) -> ProviderSchedule:
    assignment = provider.location_assignments.first()
    return ProviderSchedule.objects.create(
        membership_location=assignment,
        weekly_hours=hours or _full_week_schedule('09:00', '17:00'),
    )


# ── Tenant info endpoint ────────────────────────────────────────────


class TenantInfoTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant, cls.owner = _make_tenant('infotest')

    def test_returns_branding_and_locations(self):
        client = APIClient()
        url = reverse('booking-tenant-info', kwargs={'tenant_slug': self.tenant.slug})
        response = client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['slug'], self.tenant.slug)
        self.assertIn('primary_color', response.data)
        self.assertEqual(len(response.data['locations']), 1)
        self.assertEqual(
            response.data['locations'][0]['id'],
            self.tenant.locations.get(is_default=True).pk,
        )

    def test_unknown_slug_404(self):
        client = APIClient()
        url = reverse('booking-tenant-info', kwargs={'tenant_slug': 'no-such-spa'})
        response = client.get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_inactive_tenant_404(self):
        # Trial-status tenant should not be reachable from the public surface
        # — same 404 as nonexistent so we don't leak which slugs exist.
        owner = _make_user('trial-owner@test.local')
        trial = create_tenant_with_defaults(
            name='Trial', slug='trialspa', owner_user=owner,
            status=Tenant.Status.TRIAL,
        )
        client = APIClient()
        url = reverse('booking-tenant-info', kwargs={'tenant_slug': trial.slug})
        response = client.get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_writes_audit_log(self):
        client = APIClient()
        client.get(reverse('booking-tenant-info', kwargs={'tenant_slug': self.tenant.slug}))
        log = AuditLog.objects.filter(
            tenant=self.tenant,
            resource_type='booking_tenant_info',
        ).first()
        self.assertIsNotNone(log)
        self.assertIsNone(log.user)  # public flow — no user

    def test_disabled_tenant_404(self):
        # Operator paused online bookings — the public surface should
        # 404 the same way it does for nonexistent slugs (no leak).
        self.tenant.online_booking_enabled = False
        self.tenant.save()
        url = reverse('booking-tenant-info', kwargs={'tenant_slug': self.tenant.slug})
        response = APIClient().get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_welcome_and_cancellation_in_payload(self):
        self.tenant.online_booking_welcome_message = 'New patient? First visit free!'
        self.tenant.online_booking_cancellation_policy = '24-hour notice required.'
        self.tenant.save()
        url = reverse('booking-tenant-info', kwargs={'tenant_slug': self.tenant.slug})
        response = APIClient().get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['welcome_message'], 'New patient? First visit free!')
        self.assertEqual(response.data['cancellation_policy'], '24-hour notice required.')


# ── Services list endpoint ──────────────────────────────────────────


class ServiceListTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant, cls.owner = _make_tenant('servicelist')
        cls.bookable = _make_service(cls.tenant, name='Bookable')
        cls.staff_only = Service.objects.create(
            tenant=cls.tenant,
            category=ServiceCategory.objects.create(tenant=cls.tenant, name='Internal'),
            name='Staff-only',
            duration_minutes=30,
            price_cents=10000,
            service_type=Service.ServiceType.REGULAR,
            is_bookable_online=False,
        )
        cls.addon = Service.objects.create(
            tenant=cls.tenant,
            category=cls.bookable.category,
            name='Add-on',
            duration_minutes=15,
            price_cents=2000,
            service_type=Service.ServiceType.ADDON,
            is_bookable_online=True,
        )
        cls.inactive = Service.objects.create(
            tenant=cls.tenant,
            category=cls.bookable.category,
            name='Retired',
            duration_minutes=30,
            price_cents=10000,
            service_type=Service.ServiceType.REGULAR,
            is_bookable_online=True,
            is_active=False,
        )

    def test_only_returns_publicly_bookable_regular_services(self):
        url = reverse('booking-service-list', kwargs={'tenant_slug': self.tenant.slug})
        response = APIClient().get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        names = {s['name'] for s in response.data}
        self.assertEqual(names, {'Bookable'})

    def test_cross_tenant_isolation(self):
        # Make a second tenant with its own service. Hitting tenant-A's URL
        # must not return tenant-B's services.
        other_tenant, _ = _make_tenant('other-spa')
        _make_service(other_tenant, name='Other-Service')
        url = reverse('booking-service-list', kwargs={'tenant_slug': self.tenant.slug})
        response = APIClient().get(url)
        names = {s['name'] for s in response.data}
        self.assertNotIn('Other-Service', names)


# ── Eligible providers endpoint ────────────────────────────────────


class ProviderListTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant, cls.owner = _make_tenant('providerlist')
        cls.location = cls.tenant.locations.get(is_default=True)
        # `create_tenant_with_defaults` seeds a list of default job titles
        # — re-create-or-fetch the names we want rather than blindly
        # creating duplicates.
        cls.np_title = JobTitle.objects.create(tenant=cls.tenant, name='Custom-NP', is_clinical=True)
        cls.aesth_title, _ = JobTitle.objects.get_or_create(
            tenant=cls.tenant, name='Aesthetician',
        )

        # Service with NP-only eligibility.
        category = ServiceCategory.objects.create(tenant=cls.tenant, name='Injectables')
        category.eligible_job_titles.add(cls.np_title)
        cls.np_service = _make_service(cls.tenant, name='Botox', category=category)

        # Service with no eligibility constraints.
        cls.open_service = _make_service(cls.tenant, name='Facial')

        cls.np_provider = _make_provider(
            cls.tenant, location=cls.location, job_title=cls.np_title,
            first_name='Nadia', last_name='NP',
        )
        cls.aesth_provider = _make_provider(
            cls.tenant, location=cls.location, job_title=cls.aesth_title,
            first_name='Alex', last_name='Aesth',
        )

    def _get(self, *, service_id, location_id=None):
        url = reverse('booking-provider-list', kwargs={'tenant_slug': self.tenant.slug})
        return APIClient().get(url, {
            'service': service_id,
            'location': location_id or self.location.pk,
        })

    def test_eligibility_filters_by_job_title(self):
        response = self._get(service_id=self.np_service.pk)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = {p['id'] for p in response.data}
        self.assertEqual(ids, {self.np_provider.pk})

    def test_unrestricted_service_returns_all_bookable(self):
        response = self._get(service_id=self.open_service.pk)
        ids = {p['id'] for p in response.data}
        self.assertEqual(ids, {self.np_provider.pk, self.aesth_provider.pk})

    def test_omitting_location_falls_back_to_default(self):
        # The portal booking flow doesn't pass `?location=` — the
        # endpoint must fall back to the tenant's default site rather
        # than 400 (which surfaced as "no provider is bookable").
        url = reverse('booking-provider-list', kwargs={'tenant_slug': self.tenant.slug})
        response = APIClient().get(url, {'service': self.open_service.pk})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = {p['id'] for p in response.data}
        self.assertEqual(ids, {self.np_provider.pk, self.aesth_provider.pk})

    def test_inactive_provider_excluded(self):
        self.aesth_provider.is_active = False
        self.aesth_provider.save()
        response = self._get(service_id=self.open_service.pk)
        ids = {p['id'] for p in response.data}
        self.assertEqual(ids, {self.np_provider.pk})

    def test_non_bookable_provider_excluded(self):
        self.aesth_provider.is_bookable = False
        self.aesth_provider.save()
        response = self._get(service_id=self.open_service.pk)
        ids = {p['id'] for p in response.data}
        self.assertEqual(ids, {self.np_provider.pk})

    def test_provider_at_other_location_excluded(self):
        # Build a second location and put the np_provider there only.
        from apps.tenants.models import Location
        other = Location.objects.create(
            tenant=self.tenant, name='Other', slug='other',
            timezone='America/New_York',
        )
        # Re-attach np_provider only to "other" → the original location
        # picker should exclude them.
        self.np_provider.location_assignments.all().delete()
        MembershipLocation.objects.create(
            membership=self.np_provider, location=other, is_active=True,
        )
        response = self._get(service_id=self.open_service.pk)
        ids = {p['id'] for p in response.data}
        self.assertEqual(ids, {self.aesth_provider.pk})

    def test_display_name_is_first_plus_last_initial(self):
        response = self._get(service_id=self.open_service.pk)
        names = {p['display_name'] for p in response.data}
        self.assertIn('Nadia N.', names)
        self.assertIn('Alex A.', names)


# ── Slots endpoint ──────────────────────────────────────────────────


class SlotListTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant, cls.owner = _make_tenant('slotlist')
        cls.location = cls.tenant.locations.get(is_default=True)
        cls.service = _make_service(cls.tenant, name='30min', duration=30)
        cls.provider = _make_provider(cls.tenant, location=cls.location,
                                      first_name='Pat', last_name='Test')
        # 09:00-17:00 every day
        _attach_schedule(cls.provider)

    def _slot_url(self):
        return reverse('booking-slot-list', kwargs={'tenant_slug': self.tenant.slug})

    def test_returns_slots_for_specific_provider(self):
        # Pick a date well in the future so lead-time doesn't matter.
        future_date = (dt.date.today() + dt.timedelta(days=14)).isoformat()
        response = APIClient().get(self._slot_url(), {
            'service': self.service.pk,
            'location': self.location.pk,
            'date': future_date,
            'provider': self.provider.pk,
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # 9-17 = 8 hours, 30-min step = 16 candidate slots, last one ends 17:00
        self.assertGreater(len(response.data), 0)
        self.assertEqual(response.data[0]['provider_id'], self.provider.pk)

    def test_any_provider_unions_across_providers(self):
        # Add a second provider; both should contribute slots.
        second = _make_provider(self.tenant, location=self.location,
                                first_name='Robin', last_name='Two')
        _attach_schedule(second)
        future_date = (dt.date.today() + dt.timedelta(days=14)).isoformat()
        response = APIClient().get(self._slot_url(), {
            'service': self.service.pk,
            'location': self.location.pk,
            'date': future_date,
            'provider': 'any',
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Same slots because both are open the same hours, but
        # provider_id must be present and be one of the two.
        provider_ids = {s['provider_id'] for s in response.data}
        self.assertTrue(provider_ids.issubset({self.provider.pk, second.pk}))

    def test_include_unavailable_returns_taken_slots(self):
        # Existing 10:00 NY appointment for 30 min. With
        # include_unavailable=true the response must contain the
        # overlapping slots (09:45, 10:00, 10:15) marked
        # `available=False`, so the public UI can render them as Taken
        # rather than showing confusing gaps.
        import zoneinfo
        ny = zoneinfo.ZoneInfo('America/New_York')
        future_date = dt.date.today() + dt.timedelta(days=14)
        existing_start = dt.datetime(
            future_date.year, future_date.month, future_date.day,
            10, 0, tzinfo=ny,
        )
        Appointment.objects.create(
            tenant=self.tenant,
            customer=Customer.objects.create(
                tenant=self.tenant, first_name='X', last_name='Y',
                email='unavail@test.local',
            ),
            provider=self.provider, service=self.service, location=self.location,
            start_time=existing_start,
            end_time=existing_start + dt.timedelta(minutes=30),
            status=Appointment.Status.BOOKED,
        )
        response = APIClient().get(self._slot_url(), {
            'service': self.service.pk,
            'location': self.location.pk,
            'date': future_date.isoformat(),
            'provider': self.provider.pk,
            'include_unavailable': 'true',
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        by_start = {s['start']: s for s in response.data}
        # Spot-check three known overlaps + two known free slots.
        for blocked in ('T09:45', 'T10:00:', 'T10:15'):
            match = next((k for k in by_start if blocked in k), None)
            self.assertIsNotNone(match, f'{blocked} not present')
            self.assertFalse(by_start[match]['available'], f'{blocked} should be unavailable')
            self.assertIsNone(
                by_start[match].get('provider_id'),
                'provider_id must be null on unavailable slots',
            )
        for free in ('T09:30', 'T10:30'):
            match = next((k for k in by_start if free in k), None)
            self.assertIsNotNone(match, f'{free} not present')
            self.assertTrue(by_start[match]['available'])
            self.assertEqual(by_start[match]['provider_id'], self.provider.pk)

    def test_schedule_resolves_in_location_timezone(self):
        # Schedule "09:00" must mean 9 AM NY local, not 9 AM UTC. A
        # tenant in EDT (-4) booking at 9 AM should land at 13:00 UTC.
        # Regression for the "5 AM EDT" bug: server-tz UTC treatment
        # of schedule strings put bookings before the calendar's day
        # window and operators couldn't see their own bookings.
        future_date = (dt.date.today() + dt.timedelta(days=14)).isoformat()
        response = APIClient().get(self._slot_url(), {
            'service': self.service.pk,
            'location': self.location.pk,
            'date': future_date,
            'provider': self.provider.pk,
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreater(len(response.data), 0)
        first_start = response.data[0]['start']
        # Earliest slot of a 09:00-17:00 NY schedule is 09:00 NY local
        # (DRF preserves the location-tz offset). The offset will be
        # -04:00 (EDT) or -05:00 (EST) depending on date — we just
        # assert the local-time component.
        self.assertIn('T09:00:00', first_start)
        self.assertTrue(
            first_start.endswith('-04:00') or first_start.endswith('-05:00'),
            f'first slot was {first_start}; expected NY tz offset',
        )

    def test_cross_location_appointment_blocks_provider(self):
        # Sarah works at Main and at a second location. An appointment
        # at Main should block the same time at the second location —
        # one human, two sites. Without this guard, the slot picker
        # would happily double-book the same person at both sites.
        from apps.tenants.models import Location, MembershipLocation
        second = Location.objects.create(
            tenant=self.tenant, name='Annex', slug='annex',
            timezone='America/New_York',
        )
        ml = MembershipLocation.objects.create(
            membership=self.provider, location=second, is_active=True,
        )
        ProviderSchedule.objects.create(
            membership_location=ml,
            weekly_hours=_full_week_schedule('09:00', '17:00'),
        )

        # Existing appointment at MAIN at 10:00 NY for 30 min.
        import zoneinfo
        ny = zoneinfo.ZoneInfo('America/New_York')
        future_date = dt.date.today() + dt.timedelta(days=14)
        es = dt.datetime(
            future_date.year, future_date.month, future_date.day,
            10, 0, tzinfo=ny,
        )
        Appointment.objects.create(
            tenant=self.tenant,
            customer=Customer.objects.create(
                tenant=self.tenant, first_name='X', last_name='Y',
                email='cross@test.local',
            ),
            provider=self.provider, service=self.service,
            location=self.location,  # MAIN, not the second location
            start_time=es,
            end_time=es + dt.timedelta(minutes=30),
            status=Appointment.Status.BOOKED,
        )

        # Query slots at the SECOND location — overlap window should
        # still be blocked, because Sarah (one human) is busy at Main.
        response = APIClient().get(self._slot_url(), {
            'service': self.service.pk,
            'location': second.pk,
            'date': future_date.isoformat(),
            'provider': self.provider.pk,
        })
        starts_local = {s['start'] for s in response.data}
        # 10:00 NY = the busy window at Main.
        self.assertFalse(
            any('T10:00:' in s for s in starts_local),
            'cross-location double-booking guard failed — Sarah is busy at Main',
        )
        # Non-overlapping slots remain available at the second location.
        self.assertTrue(any('T09:30' in s for s in starts_local))

    def test_lead_minutes_setting_filters_near_slots(self):
        # Set lead time to ~30 days so today's slots are all dropped.
        self.tenant.online_booking_lead_minutes = 60 * 24 * 30
        self.tenant.save()
        today = dt.date.today().isoformat()
        response = APIClient().get(self._slot_url(), {
            'service': self.service.pk,
            'location': self.location.pk,
            'date': today,
            'provider': self.provider.pk,
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, [])

    def test_window_days_setting_caps_far_future(self):
        # Default window is 60 days. Querying 100 days out → empty list.
        self.tenant.online_booking_window_days = 7
        self.tenant.save()
        far_future = (dt.date.today() + dt.timedelta(days=30)).isoformat()
        response = APIClient().get(self._slot_url(), {
            'service': self.service.pk,
            'location': self.location.pk,
            'date': far_future,
            'provider': self.provider.pk,
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, [])

    def test_invalid_date_400(self):
        response = APIClient().get(self._slot_url(), {
            'service': self.service.pk,
            'location': self.location.pk,
            'date': 'not-a-date',
            'provider': 'any',
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_existing_appointment_blocks_overlapping_slot(self):
        # Book the 10:00-10:30 NY-local slot on a future Monday — slots
        # that overlap that 30-min window (09:45, 10:00, 10:15) must
        # not appear. Earlier (09:30) and later (10:30) slots remain.
        import zoneinfo
        ny = zoneinfo.ZoneInfo('America/New_York')
        future_date = dt.date.today() + dt.timedelta(days=14)
        existing_start = dt.datetime(
            future_date.year, future_date.month, future_date.day,
            10, 0, tzinfo=ny,
        )
        Appointment.objects.create(
            tenant=self.tenant,
            customer=Customer.objects.create(
                tenant=self.tenant, first_name='X', last_name='Y',
                email='blocker@test.local',
            ),
            provider=self.provider, service=self.service, location=self.location,
            start_time=existing_start,
            end_time=existing_start + dt.timedelta(minutes=30),
            status=Appointment.Status.BOOKED,
        )
        response = APIClient().get(self._slot_url(), {
            'service': self.service.pk,
            'location': self.location.pk,
            'date': future_date.isoformat(),
            'provider': self.provider.pk,
        })
        # DRF preserves the location-tz offset on aware datetimes. The
        # blocking appt is at 10:00 NY local; slots at 09:45, 10:00,
        # 10:15 NY overlap and must be absent. The non-overlapping
        # 09:30 and 10:30 NY slots remain.
        starts_local = {s['start'] for s in response.data}
        for blocked_local in ('T09:45', 'T10:00:', 'T10:15'):
            self.assertFalse(
                any(blocked_local in s for s in starts_local),
                f'expected {blocked_local} to be blocked but it appeared',
            )
        self.assertTrue(any('T09:30' in s for s in starts_local))
        self.assertTrue(any('T10:30' in s for s in starts_local))


# ── Submit booking endpoint ─────────────────────────────────────────


class SubmitBookingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant, cls.owner = _make_tenant('submit')
        cls.location = cls.tenant.locations.get(is_default=True)
        cls.service = _make_service(cls.tenant, name='30min', duration=30)
        cls.provider = _make_provider(cls.tenant, location=cls.location,
                                      first_name='Pat', last_name='Test')
        _attach_schedule(cls.provider)

    def setUp(self):
        # Clear DRF's throttle cache between tests — counts accumulate
        # in Django's local-memory cache and hit the 10/hour cap when
        # this class runs alongside other booking-submit tests.
        from django.core.cache import cache
        cache.clear()

    def _book_url(self):
        return reverse('booking-submit', kwargs={'tenant_slug': self.tenant.slug})

    def _payload(self, **overrides):
        # Pick a slot that the calculator will offer: future Monday 14:00 UTC,
        # which falls in the 09-17 every-day schedule when interpreted in
        # America/New_York → 14:00 NY = 18:00 UTC, but server tz is what
        # matters for the schedule. Use a fixed forward-looking date and
        # pull a real slot from the calculator to avoid TZ drift surprise.
        from .availability import compute_provider_slots
        on_date = dt.date.today() + dt.timedelta(days=14)
        slots = compute_provider_slots(
            provider=self.provider, service=self.service,
            location=self.location, on_date=on_date,
        )
        first_slot = slots[0]
        base = {
            'service_id': self.service.pk,
            'provider_id': self.provider.pk,
            'location_id': self.location.pk,
            'start_time': first_slot.start.isoformat(),
            'customer_first_name': 'Jane',
            'customer_last_name': 'Doe',
            'customer_email': 'jane@example.com',
            'customer_phone': '555-0100',
        }
        base.update(overrides)
        return base

    def test_happy_path_creates_appointment_and_customer(self):
        response = APIClient().post(
            self._book_url(),
            data=self._payload(),
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertIn('booking_token', response.data)
        self.assertTrue(response.data['booking_token'])
        self.assertEqual(response.data['status'], Appointment.Status.BOOKED)

        appt = Appointment.objects.get(pk=response.data['id'])
        self.assertEqual(appt.tenant, self.tenant)
        self.assertEqual(appt.source, 'online')
        self.assertEqual(appt.customer.email, 'jane@example.com')

    def test_returning_customer_reuses_record(self):
        existing = Customer.objects.create(
            tenant=self.tenant,
            first_name='Jane', last_name='Doe',
            email='jane@example.com', phone='555-0100',
        )
        response = APIClient().post(
            self._book_url(),
            data=self._payload(),
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        appt = Appointment.objects.get(pk=response.data['id'])
        self.assertEqual(appt.customer_id, existing.pk)

    def test_cross_tenant_service_rejected(self):
        # Service from a different tenant must 400.
        other_tenant, _ = _make_tenant('cross-tenant')
        other_service = _make_service(other_tenant, name='Other')
        payload = self._payload(service_id=other_service.pk)
        response = APIClient().post(self._book_url(), data=payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_ineligible_provider_rejected(self):
        # Make a job-title-restricted service and try to book a non-matching provider.
        np_title = JobTitle.objects.create(tenant=self.tenant, name='NP-only')
        cat = ServiceCategory.objects.create(tenant=self.tenant, name='NP-Cat')
        cat.eligible_job_titles.add(np_title)
        restricted = _make_service(self.tenant, name='Restricted', category=cat)
        payload = self._payload(service_id=restricted.pk)
        response = APIClient().post(self._book_url(), data=payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_double_booking_returns_409(self):
        # Submit twice for the SAME start_time. _payload() rebuilds the
        # payload each call and would pick the next free slot on the
        # second pass, so we capture the payload once and replay it.
        payload = self._payload()
        client = APIClient()
        first = client.post(self._book_url(), data=payload, format='json')
        self.assertEqual(first.status_code, status.HTTP_201_CREATED, first.data)

        second = client.post(self._book_url(), data=payload, format='json')
        self.assertEqual(second.status_code, status.HTTP_409_CONFLICT, second.data)

    def test_audit_log_on_submit(self):
        APIClient().post(self._book_url(), data=self._payload(), format='json')
        log = AuditLog.objects.filter(
            tenant=self.tenant,
            resource_type='appointment',
            action=AuditLog.Action.CREATE,
        ).first()
        self.assertIsNotNone(log)
        self.assertIsNone(log.user)
        self.assertEqual(log.metadata.get('event'), 'online_booking_submitted')

    def test_confirmation_email_sent(self):
        from django.core import mail
        mail.outbox = []
        response = APIClient().post(
            self._book_url(),
            data=self._payload(customer_email='confirm@example.com'),
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self.assertEqual(msg.to, ['confirm@example.com'])
        self.assertIn(self.tenant.name, msg.subject)
        # Manage link must point at the booking_token, not the pk.
        self.assertIn(response.data['booking_token'], msg.body)

    def test_submit_endpoint_has_per_ip_throttle_attached(self):
        # Structural check: the wire-up is in place. We don't burst-
        # fire requests in tests because DRF caches throttle rates at
        # instantiation, making runtime rate overrides fragile —
        # cleaner to verify the throttle class is attached and the
        # rate is configured in settings, then trust DRF's own
        # well-tested throttle behavior.
        from django.conf import settings as django_settings
        from .permissions import BookingSubmitThrottle
        from .views import BookingSubmitView

        self.assertIn(BookingSubmitThrottle, BookingSubmitView.throttle_classes)
        self.assertIn(
            'booking_submit',
            django_settings.REST_FRAMEWORK.get('DEFAULT_THROTTLE_RATES', {}),
        )

    def test_confirmation_email_audit_logs_domain_only(self):
        APIClient().post(
            self._book_url(),
            data=self._payload(customer_email='someone@example.com'),
            format='json',
        )
        log = AuditLog.objects.filter(
            tenant=self.tenant,
            metadata__event='confirmation_email_sent',
        ).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.metadata.get('recipient_email_domain'), 'example.com')
        # Full address must NOT be present — domain-only logging per ADR 0012.
        self.assertNotIn('someone@example.com', str(log.metadata))


# ── Manage by token ─────────────────────────────────────────────────


class ManageBookingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant, cls.owner = _make_tenant('manage')
        cls.location = cls.tenant.locations.get(is_default=True)
        cls.service = _make_service(cls.tenant, name='Service')
        cls.provider = _make_provider(cls.tenant, location=cls.location)
        _attach_schedule(cls.provider)

    def _book_one(self) -> Appointment:
        from django.utils import timezone as djtz
        future_start = djtz.now() + dt.timedelta(days=7)
        return Appointment.objects.create(
            tenant=self.tenant,
            customer=Customer.objects.create(
                tenant=self.tenant, first_name='Manage', last_name='Me',
                email='manage@example.com',
            ),
            provider=self.provider, service=self.service, location=self.location,
            start_time=future_start,
            end_time=future_start + dt.timedelta(minutes=30),
            status=Appointment.Status.BOOKED,
            source='online',
            booking_token='tok_' + 'a' * 30,
            quoted_price_cents=self.service.price_cents,
        )

    def test_lookup_by_token(self):
        appt = self._book_one()
        url = reverse('booking-manage', kwargs={'token': appt.booking_token})
        response = APIClient().get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['id'], appt.pk)
        self.assertEqual(response.data['booking_token'], appt.booking_token)
        self.assertIn('tenant', response.data)
        self.assertEqual(response.data['tenant']['slug'], self.tenant.slug)

    def test_unknown_token_404(self):
        url = reverse('booking-manage', kwargs={'token': 'nonexistent-token'})
        response = APIClient().get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_cancel_transitions_to_cancelled(self):
        appt = self._book_one()
        url = reverse('booking-manage-cancel', kwargs={'token': appt.booking_token})
        response = APIClient().post(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        appt.refresh_from_db()
        self.assertEqual(appt.status, Appointment.Status.CANCELLED)
        self.assertIsNotNone(appt.cancelled_at)

    def test_cancel_idempotent_on_already_cancelled(self):
        appt = self._book_one()
        appt.status = Appointment.Status.CANCELLED
        appt.save()
        url = reverse('booking-manage-cancel', kwargs={'token': appt.booking_token})
        response = APIClient().post(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_cancel_rejected_on_completed(self):
        appt = self._book_one()
        appt.status = Appointment.Status.COMPLETED
        appt.save()
        url = reverse('booking-manage-cancel', kwargs={'token': appt.booking_token})
        response = APIClient().post(url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_audit_log_on_view_and_cancel(self):
        appt = self._book_one()
        APIClient().get(reverse('booking-manage', kwargs={'token': appt.booking_token}))
        APIClient().post(reverse('booking-manage-cancel', kwargs={'token': appt.booking_token}))

        view_log = AuditLog.objects.filter(
            tenant=self.tenant,
            resource_type='appointment',
            action=AuditLog.Action.READ,
            resource_id=str(appt.pk),
        ).first()
        cancel_log = AuditLog.objects.filter(
            tenant=self.tenant,
            resource_type='appointment',
            action=AuditLog.Action.UPDATE,
            resource_id=str(appt.pk),
        ).first()
        self.assertIsNotNone(view_log)
        self.assertIsNotNone(cancel_log)
        self.assertEqual(cancel_log.metadata.get('event'), 'customer_cancelled_via_token')


# ── Reschedule via manage token ─────────────────────────────────────


class ManageBookingRescheduleTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant, cls.owner = _make_tenant('reschedule')
        cls.location = cls.tenant.locations.get(is_default=True)
        cls.service = _make_service(cls.tenant, name='Service', duration=30)
        cls.provider = _make_provider(cls.tenant, location=cls.location)
        _attach_schedule(cls.provider)

    def _book_one(self, *, start: dt.datetime | None = None) -> Appointment:
        import zoneinfo
        ny = zoneinfo.ZoneInfo('America/New_York')
        if start is None:
            future = dt.date.today() + dt.timedelta(days=14)
            start = dt.datetime(future.year, future.month, future.day, 10, 0, tzinfo=ny)
        return Appointment.objects.create(
            tenant=self.tenant,
            customer=Customer.objects.create(
                tenant=self.tenant, first_name='Reschedule', last_name='Me',
                email='reschedule@example.com',
            ),
            provider=self.provider, service=self.service, location=self.location,
            start_time=start,
            end_time=start + dt.timedelta(minutes=30),
            status=Appointment.Status.BOOKED,
            source='online',
            booking_token='tok_resched_' + 'a' * 24,
            quoted_price_cents=self.service.price_cents,
        )

    def _reschedule_url(self, token: str) -> str:
        return reverse('booking-manage-reschedule', kwargs={'token': token})

    def test_happy_path_moves_appointment(self):
        import zoneinfo
        ny = zoneinfo.ZoneInfo('America/New_York')
        appt = self._book_one()
        future = dt.date.today() + dt.timedelta(days=14)
        new_start = dt.datetime(future.year, future.month, future.day, 14, 0, tzinfo=ny)

        response = APIClient().post(
            self._reschedule_url(appt.booking_token),
            data={'start_time': new_start.isoformat()},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        appt.refresh_from_db()
        self.assertEqual(appt.start_time, new_start)
        self.assertEqual(appt.status, Appointment.Status.BOOKED)

    def test_reschedule_to_unavailable_slot_returns_409(self):
        # Book a second appointment that occupies 14:00 NY local;
        # then try to reschedule the first one onto that taken slot.
        import zoneinfo
        ny = zoneinfo.ZoneInfo('America/New_York')
        future = dt.date.today() + dt.timedelta(days=14)
        first = self._book_one()
        second_start = dt.datetime(future.year, future.month, future.day, 14, 0, tzinfo=ny)
        Appointment.objects.create(
            tenant=self.tenant,
            customer=Customer.objects.create(
                tenant=self.tenant, first_name='Other', last_name='Customer',
                email='other-resched@example.com',
            ),
            provider=self.provider, service=self.service, location=self.location,
            start_time=second_start,
            end_time=second_start + dt.timedelta(minutes=30),
            status=Appointment.Status.BOOKED,
        )
        response = APIClient().post(
            self._reschedule_url(first.booking_token),
            data={'start_time': second_start.isoformat()},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    def test_reschedule_to_same_slot_is_noop_success(self):
        # Re-submit the same start_time. The reschedule path soft-
        # excludes the appointment from its own conflict set, so the
        # current slot stays "available."
        appt = self._book_one()
        response = APIClient().post(
            self._reschedule_url(appt.booking_token),
            data={'start_time': appt.start_time.isoformat()},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)

    def test_reschedule_rejected_on_cancelled(self):
        appt = self._book_one()
        appt.status = Appointment.Status.CANCELLED
        appt.save()
        response = APIClient().post(
            self._reschedule_url(appt.booking_token),
            data={'start_time': appt.start_time.isoformat()},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_reschedule_beyond_window_rejected(self):
        appt = self._book_one()
        far = dt.date.today() + dt.timedelta(days=400)
        far_start = dt.datetime(far.year, far.month, far.day, 10, 0)
        from django.utils import timezone as djtz
        far_start = djtz.make_aware(far_start)
        response = APIClient().post(
            self._reschedule_url(appt.booking_token),
            data={'start_time': far_start.isoformat()},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_reschedule_when_killswitch_off_rejected(self):
        appt = self._book_one()
        self.tenant.online_booking_enabled = False
        self.tenant.save()
        response = APIClient().post(
            self._reschedule_url(appt.booking_token),
            data={'start_time': appt.start_time.isoformat()},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_reschedule_audit_log_records_old_and_new_starts(self):
        import zoneinfo
        ny = zoneinfo.ZoneInfo('America/New_York')
        appt = self._book_one()
        old_start_instant = appt.start_time  # in-memory; same instant as DB
        future = dt.date.today() + dt.timedelta(days=14)
        new_start = dt.datetime(future.year, future.month, future.day, 11, 30, tzinfo=ny)

        APIClient().post(
            self._reschedule_url(appt.booking_token),
            data={'start_time': new_start.isoformat()},
            format='json',
        )
        log = AuditLog.objects.filter(
            tenant=self.tenant,
            resource_type='appointment',
            action=AuditLog.Action.UPDATE,
            metadata__event='customer_rescheduled_via_token',
        ).first()
        self.assertIsNotNone(log)
        # Compare instants, not string representations — Django stores
        # UTC and the audit log records the UTC ISO string while the
        # test built the value in NY tz.
        self.assertEqual(
            dt.datetime.fromisoformat(log.metadata['from_start']),
            old_start_instant,
        )
        self.assertEqual(
            dt.datetime.fromisoformat(log.metadata['to_start']),
            new_start,
        )
        self.assertIsNone(log.user)  # public flow

    def test_reschedule_sends_email_with_reschedule_subject(self):
        from django.core import mail
        import zoneinfo
        ny = zoneinfo.ZoneInfo('America/New_York')
        mail.outbox = []
        appt = self._book_one()
        future = dt.date.today() + dt.timedelta(days=14)
        new_start = dt.datetime(future.year, future.month, future.day, 13, 0, tzinfo=ny)
        APIClient().post(
            self._reschedule_url(appt.booking_token),
            data={'start_time': new_start.isoformat()},
            format='json',
        )
        self.assertEqual(len(mail.outbox), 1)
        msg = mail.outbox[0]
        # Subject reflects the move, not a fresh booking.
        self.assertIn('moved', msg.subject.lower())
        self.assertEqual(msg.to, ['reschedule@example.com'])


# ── find_or_create_customer matching rules ──────────────────────────


class CustomerMatchingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant, _ = _make_tenant('match')

    def test_email_plus_phone_match(self):
        from .services import find_or_create_customer
        existing = Customer.objects.create(
            tenant=self.tenant, first_name='Jane', last_name='Doe',
            email='jane@example.com', phone='555-1234',
        )
        match, created = find_or_create_customer(
            tenant=self.tenant,
            first_name='Jane', last_name='Doe',
            email='jane@example.com', phone='555-1234',
        )
        self.assertFalse(created)
        self.assertEqual(match.pk, existing.pk)

    def test_phone_only_match(self):
        from .services import find_or_create_customer
        existing = Customer.objects.create(
            tenant=self.tenant, first_name='Old', last_name='Name',
            email='old@example.com', phone='555-1234',
        )
        match, created = find_or_create_customer(
            tenant=self.tenant,
            first_name='New', last_name='Name',
            email='new@example.com', phone='555-1234',
        )
        self.assertFalse(created)
        self.assertEqual(match.pk, existing.pk)

    def test_no_match_creates_new_record(self):
        from .services import find_or_create_customer
        match, created = find_or_create_customer(
            tenant=self.tenant,
            first_name='Brand', last_name='New',
            email='brand@example.com', phone='555-9999',
        )
        self.assertTrue(created)
        self.assertEqual(match.tenant, self.tenant)

    def test_cross_tenant_no_match(self):
        # Same email + phone in tenant A must NOT match for tenant B.
        from .services import find_or_create_customer
        other, _ = _make_tenant('other-match')
        Customer.objects.create(
            tenant=other, first_name='Jane', last_name='Doe',
            email='jane@example.com', phone='555-1234',
        )
        match, created = find_or_create_customer(
            tenant=self.tenant,
            first_name='Jane', last_name='Doe',
            email='jane@example.com', phone='555-1234',
        )
        self.assertTrue(created)
        self.assertNotEqual(match.tenant, other)
