"""Tests for the waitlist API.

Covers four invariants:

  1. Tenant scoping — public submit + internal list both respect
     the tenant slug; cross-tenant references are rejected.
  2. Dedupe — re-submitting an identical waiting entry returns the
     existing one instead of creating a duplicate.
  3. Status transitions — operator PATCH stamps the corresponding
     timestamp (contacted_at, declined_at, booked_at) automatically.
  4. Audit logging — public submit + status updates record entries
     with `user=None` (public) or `user=<operator>` (internal),
     `tenant=<resolved>`, and PHI-free metadata.
"""

from __future__ import annotations

import datetime as dt

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.audit.models import AuditLog
from apps.customers.models import Customer
from apps.services.models import Service, ServiceCategory
from apps.tenants.models import (
    MembershipLocation,
    Tenant,
    TenantMembership,
)
from apps.tenants.services import create_tenant_with_defaults

from .models import WaitlistEntry

User = get_user_model()


# ── Fixtures ─────────────────────────────────────────────────────────


def _make_user(email: str, **kwargs):
    return User.objects.create_user(email=email, password='test-pw', **kwargs)


def _make_tenant(slug: str) -> tuple[Tenant, User]:
    owner = _make_user(f'{slug}-owner@test.local')
    tenant = create_tenant_with_defaults(
        name=slug.title(), slug=slug, owner_user=owner,
        status=Tenant.Status.ACTIVE,
        timezone='America/New_York',
    )
    return tenant, owner


def _make_provider(tenant, *, location=None) -> TenantMembership:
    user = _make_user(
        f'p-{tenant.slug}-{TenantMembership.objects.filter(tenant=tenant).count()}@test.local',
        first_name='Sam', last_name='Provider',
    )
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


def _make_service(tenant) -> Service:
    cat = ServiceCategory.objects.create(tenant=tenant, name='Cat')
    return Service.objects.create(
        tenant=tenant, category=cat,
        name='Service', duration_minutes=30,
        price_cents=10000, service_type=Service.ServiceType.REGULAR,
        is_active=True, is_bookable_online=True,
    )


# ── Public submit ────────────────────────────────────────────────────


class PublicWaitlistSubmitTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant, cls.owner = _make_tenant('wl-pub')
        cls.location = cls.tenant.locations.get(is_default=True)
        cls.service = _make_service(cls.tenant)
        cls.provider = _make_provider(cls.tenant, location=cls.location)

    def _url(self):
        return reverse('public-waitlist-join', kwargs={'tenant_slug': self.tenant.slug})

    def _payload(self, **overrides):
        base = {
            'service_id': self.service.pk,
            'location_id': self.location.pk,
            'provider_id': self.provider.pk,
            'preferred_date': (dt.date.today() + dt.timedelta(days=7)).isoformat(),
            'customer_first_name': 'Jane',
            'customer_last_name': 'Doe',
            'customer_email': 'jane@test.local',
            'customer_phone': '555-0100',
        }
        base.update(overrides)
        return base

    def test_happy_path_creates_entry(self):
        response = APIClient().post(self._url(), data=self._payload(), format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data['status'], 'waiting')
        self.assertIn('service_name', response.data)

        entry = WaitlistEntry.objects.get(pk=response.data['id'])
        self.assertEqual(entry.tenant, self.tenant)
        self.assertEqual(entry.source, 'online')
        self.assertEqual(entry.customer.email, 'jane@test.local')

    def test_dedupe_returns_existing_on_resubmit(self):
        client = APIClient()
        first = client.post(self._url(), data=self._payload(), format='json')
        self.assertEqual(first.status_code, status.HTTP_201_CREATED, first.data)
        second = client.post(self._url(), data=self._payload(), format='json')
        # Dedupe path: 200 (not 201) and same id.
        self.assertEqual(second.status_code, status.HTTP_200_OK, second.data)
        self.assertEqual(second.data['id'], first.data['id'])
        self.assertEqual(WaitlistEntry.objects.count(), 1)

    def test_provider_optional(self):
        response = APIClient().post(
            self._url(),
            data=self._payload(provider_id=None),
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        entry = WaitlistEntry.objects.get(pk=response.data['id'])
        self.assertIsNone(entry.provider_id)

    def test_cross_tenant_service_rejected(self):
        other_tenant, _ = _make_tenant('wl-other')
        other_service = _make_service(other_tenant)
        response = APIClient().post(
            self._url(),
            data=self._payload(service_id=other_service.pk),
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(WaitlistEntry.objects.count(), 0)

    def test_disabled_tenant_404(self):
        self.tenant.online_booking_enabled = False
        self.tenant.save()
        response = APIClient().post(self._url(), data=self._payload(), format='json')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_audit_log_on_create(self):
        APIClient().post(self._url(), data=self._payload(), format='json')
        log = AuditLog.objects.filter(
            tenant=self.tenant,
            resource_type='waitlist_entry',
            action=AuditLog.Action.CREATE,
        ).first()
        self.assertIsNotNone(log)
        self.assertIsNone(log.user)  # public flow
        self.assertEqual(log.metadata.get('event'), 'public_waitlist_join')
        # Email + phone must NOT appear in audit metadata.
        meta_str = str(log.metadata)
        self.assertNotIn('jane@test.local', meta_str)
        self.assertNotIn('555-0100', meta_str)

    def test_dedupe_does_not_double_audit(self):
        client = APIClient()
        client.post(self._url(), data=self._payload(), format='json')
        client.post(self._url(), data=self._payload(), format='json')
        creates = AuditLog.objects.filter(
            tenant=self.tenant,
            resource_type='waitlist_entry',
            action=AuditLog.Action.CREATE,
        ).count()
        self.assertEqual(creates, 1)


# ── Operator-side list + status transitions ─────────────────────────


class WaitlistInternalTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant, cls.owner = _make_tenant('wl-int')
        cls.location = cls.tenant.locations.get(is_default=True)
        cls.service = _make_service(cls.tenant)
        cls.provider = _make_provider(cls.tenant, location=cls.location)
        cls.customer = Customer.objects.create(
            tenant=cls.tenant, first_name='Pat', last_name='Customer',
            email='pat@test.local', phone='555-1111',
        )

    def setUp(self):
        self.entry = WaitlistEntry.objects.create(
            tenant=self.tenant, customer=self.customer,
            service=self.service, location=self.location,
            preferred_date=dt.date.today() + dt.timedelta(days=7),
            source='online',
        )
        self.client = APIClient()
        self.client.force_login(self.owner)

    def _detail_url(self):
        return reverse('waitlist-entry-detail', kwargs={'pk': self.entry.pk})

    def test_list_returns_tenant_scoped_entries(self):
        # Spin up a second tenant + entry; the list must NOT include it.
        other_tenant, _ = _make_tenant('wl-other-int')
        WaitlistEntry.objects.create(
            tenant=other_tenant,
            customer=Customer.objects.create(
                tenant=other_tenant, first_name='X', last_name='Y',
                email='x@y.local',
            ),
            service=_make_service(other_tenant),
            location=other_tenant.locations.get(is_default=True),
            preferred_date=dt.date.today(),
        )
        response = self.client.get(
            reverse('waitlist-entry-list'),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = [e['id'] for e in response.data]
        self.assertEqual(ids, [self.entry.pk])

    def test_status_filter(self):
        # Add a contacted entry; ?status=waiting should exclude it.
        WaitlistEntry.objects.create(
            tenant=self.tenant, customer=self.customer,
            service=self.service, location=self.location,
            preferred_date=dt.date.today() + dt.timedelta(days=14),
            status=WaitlistEntry.Status.CONTACTED,
            source='online',
        )
        response = self.client.get(
            reverse('waitlist-entry-list') + '?status=waiting',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        statuses = {e['status'] for e in response.data}
        self.assertEqual(statuses, {'waiting'})

    def test_patch_status_to_contacted_stamps_timestamp(self):
        response = self.client.patch(
            self._detail_url(),
            data={'status': 'contacted'},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.status, 'contacted')
        self.assertIsNotNone(self.entry.contacted_at)

    def test_patch_status_to_booked_stamps_timestamp(self):
        response = self.client.patch(
            self._detail_url(),
            data={'status': 'booked'},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.entry.refresh_from_db()
        self.assertIsNotNone(self.entry.booked_at)

    def test_patch_invalid_field_rejected(self):
        # Trying to mutate WHAT the customer asked for is rejected.
        response = self.client.patch(
            self._detail_url(),
            data={'service_id': 99999},  # not editable
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_patch_invalid_status_rejected(self):
        response = self.client.patch(
            self._detail_url(),
            data={'status': 'not-a-real-status'},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_audit_log_on_status_change(self):
        self.client.patch(
            self._detail_url(),
            data={'status': 'declined'},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        log = AuditLog.objects.filter(
            tenant=self.tenant,
            resource_type='waitlist_entry',
            action=AuditLog.Action.UPDATE,
            resource_id=str(self.entry.pk),
        ).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.user, self.owner)
        self.assertEqual(log.metadata.get('from_status'), 'waiting')
        self.assertEqual(log.metadata.get('to_status'), 'declined')

    def test_anonymous_blocked_from_internal_list(self):
        client = APIClient()  # no force_login
        response = client.get(
            reverse('waitlist-entry-list'),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


# ── Staff-side create (manual add) ──────────────────────────────────


class WaitlistStaffCreateTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant, cls.owner = _make_tenant('wl-staff')
        cls.location = cls.tenant.locations.get(is_default=True)
        cls.service = _make_service(cls.tenant)
        cls.provider = _make_provider(cls.tenant, location=cls.location)
        cls.customer = Customer.objects.create(
            tenant=cls.tenant, first_name='Pat', last_name='Customer',
            email='pat@test.local', phone='555-1111',
        )

    def setUp(self):
        self.client = APIClient()
        self.client.force_login(self.owner)

    def _payload(self, **overrides):
        base = {
            'customer_id': self.customer.pk,
            'service_id': self.service.pk,
            'location_id': self.location.pk,
            'provider_id': self.provider.pk,
            'preferred_date': (dt.date.today() + dt.timedelta(days=7)).isoformat(),
            'notes': 'Called in, prefers afternoons.',
        }
        base.update(overrides)
        return base

    def test_staff_can_add_existing_customer(self):
        response = self.client.post(
            reverse('waitlist-entry-list'),
            data=self._payload(),
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        # Response is the full WaitlistEntry shape (not the public confirmation).
        self.assertIn('customer_phone', response.data)
        self.assertIn('customer_email', response.data)

        entry = WaitlistEntry.objects.get(pk=response.data['id'])
        self.assertEqual(entry.tenant, self.tenant)
        self.assertEqual(entry.source, 'staff')  # the discriminator
        self.assertEqual(entry.customer, self.customer)
        self.assertEqual(entry.notes, 'Called in, prefers afternoons.')

    def test_provider_optional_for_staff_add(self):
        response = self.client.post(
            reverse('waitlist-entry-list'),
            data=self._payload(provider_id=None),
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        entry = WaitlistEntry.objects.get(pk=response.data['id'])
        self.assertIsNone(entry.provider_id)

    def test_cross_tenant_customer_rejected(self):
        other_tenant, _ = _make_tenant('wl-staff-other')
        other_customer = Customer.objects.create(
            tenant=other_tenant, first_name='X', last_name='Y', email='x@y.local',
        )
        response = self.client.post(
            reverse('waitlist-entry-list'),
            data=self._payload(customer_id=other_customer.pk),
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(WaitlistEntry.objects.count(), 0)

    def test_cross_tenant_service_rejected(self):
        other_tenant, _ = _make_tenant('wl-staff-svc')
        other_service = _make_service(other_tenant)
        response = self.client.post(
            reverse('waitlist-entry-list'),
            data=self._payload(service_id=other_service.pk),
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(WaitlistEntry.objects.count(), 0)

    def test_anonymous_blocked_from_create(self):
        client = APIClient()
        response = client.post(
            reverse('waitlist-entry-list'),
            data=self._payload(),
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_audit_log_on_staff_create(self):
        self.client.post(
            reverse('waitlist-entry-list'),
            data=self._payload(),
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        log = AuditLog.objects.filter(
            tenant=self.tenant,
            resource_type='waitlist_entry',
            action=AuditLog.Action.CREATE,
        ).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.user, self.owner)  # operator, not anonymous
        self.assertEqual(log.metadata.get('event'), 'staff_waitlist_add')

    def test_staff_can_add_new_customer_inline(self):
        # No customer_id; raw name/email/phone fields create the
        # Customer record on the way through.
        existing_count = Customer.objects.filter(tenant=self.tenant).count()
        response = self.client.post(
            reverse('waitlist-entry-list'),
            data={
                'service_id': self.service.pk,
                'location_id': self.location.pk,
                'preferred_date': (dt.date.today() + dt.timedelta(days=7)).isoformat(),
                'customer_first_name': 'Brand',
                'customer_last_name': 'New',
                'customer_email': 'brand-new@test.local',
                'customer_phone': '555-7000',
            },
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(
            Customer.objects.filter(tenant=self.tenant).count(),
            existing_count + 1,
        )
        entry = WaitlistEntry.objects.get(pk=response.data['id'])
        self.assertEqual(entry.source, 'staff')
        self.assertEqual(entry.customer.email, 'brand-new@test.local')

    def test_staff_new_customer_path_matches_existing_by_email(self):
        # Existing customer with this email/phone — the new-customer
        # path should re-attach (not create a duplicate).
        existing_count = Customer.objects.filter(tenant=self.tenant).count()
        response = self.client.post(
            reverse('waitlist-entry-list'),
            data={
                'service_id': self.service.pk,
                'location_id': self.location.pk,
                'preferred_date': (dt.date.today() + dt.timedelta(days=7)).isoformat(),
                'customer_first_name': 'Pat',
                'customer_last_name': 'Customer',
                'customer_email': self.customer.email,
                'customer_phone': self.customer.phone,
            },
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        # No new customer row created — the existing one was matched.
        self.assertEqual(
            Customer.objects.filter(tenant=self.tenant).count(),
            existing_count,
        )
        entry = WaitlistEntry.objects.get(pk=response.data['id'])
        self.assertEqual(entry.customer_id, self.customer.pk)

    def test_missing_customer_fields_rejected(self):
        # No customer_id AND no name/email/phone → 400 with which
        # fields are required.
        response = self.client.post(
            reverse('waitlist-entry-list'),
            data={
                'service_id': self.service.pk,
                'location_id': self.location.pk,
                'preferred_date': (dt.date.today() + dt.timedelta(days=7)).isoformat(),
            },
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        body = response.data
        self.assertIn('customer_first_name', body)
        self.assertIn('customer_email', body)
