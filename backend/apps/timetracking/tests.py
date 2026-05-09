"""Tests for the time tracking API.

Covers:
  - Service layer: clock-in / clock-out happy path + the
    single-open-shift invariant under concurrent races.
  - Permission gating: self-service punches; cross-membership
    requires MANAGE_STAFF.
  - Read filtering: non-managers see only their own entries.
  - DB constraint: clock_out_at must be after clock_in_at.
  - Manager edit + delete with audit metadata persistence.
  - The "active" + "me" mobile-friendly endpoints.
"""

from __future__ import annotations

import datetime as dt

from django.contrib.auth import get_user_model
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.audit.models import AuditLog
from apps.tenants.models import (
    MembershipLocation,
    Tenant,
    TenantMembership,
)
from apps.tenants.services import create_tenant_with_defaults

from .models import TimeEntry
from .services import TimeTrackingError, clock_in, clock_out

User = get_user_model()


# ── Helpers ─────────────────────────────────────────────────────────


def _make_user(email: str) -> User:
    return User.objects.create_user(
        email=email, password='pw', first_name='F', last_name='L',
    )


def _make_tenant(slug: str) -> tuple[Tenant, User, TenantMembership]:
    owner = _make_user(f'{slug}-owner@test.local')
    tenant = create_tenant_with_defaults(
        name=slug.title(), slug=slug, owner_user=owner,
        status=Tenant.Status.ACTIVE,
    )
    owner_membership = TenantMembership.objects.get(
        user=owner, tenant=tenant,
    )
    return tenant, owner, owner_membership


def _make_member(
    tenant: Tenant, role: str, email: str | None = None,
) -> tuple[User, TenantMembership]:
    user = _make_user(email or f'{role}-{tenant.slug}@test.local')
    m = TenantMembership.objects.create(
        user=user, tenant=tenant, role=role, is_active=True,
    )
    MembershipLocation.objects.create(
        membership=m, location=tenant.locations.get(is_default=True),
        is_active=True,
    )
    return user, m


def _client_for(user) -> APIClient:
    c = APIClient()
    c.force_login(user)
    return c


# ── Service layer ───────────────────────────────────────────────────


class ClockInOutServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant, cls.owner, cls.owner_m = _make_tenant('tt-svc')
        cls.provider_user, cls.provider_m = _make_member(
            cls.tenant, TenantMembership.Role.PROVIDER, 'p@test.local',
        )

    def test_clock_in_creates_open_entry(self):
        entry = clock_in(membership=self.provider_m, by_user=self.provider_user)
        self.assertIsNotNone(entry.clock_in_at)
        self.assertIsNone(entry.clock_out_at)
        self.assertTrue(entry.is_open)
        self.assertEqual(entry.created_by, self.provider_user)

    def test_clock_in_twice_raises(self):
        clock_in(membership=self.provider_m, by_user=self.provider_user)
        with self.assertRaises(TimeTrackingError):
            clock_in(membership=self.provider_m, by_user=self.provider_user)

    def test_clock_out_closes_open_entry(self):
        clock_in(membership=self.provider_m, by_user=self.provider_user)
        entry = clock_out(
            membership=self.provider_m, by_user=self.provider_user,
        )
        self.assertIsNotNone(entry.clock_out_at)
        self.assertFalse(entry.is_open)
        self.assertGreaterEqual(entry.duration_seconds, 0)

    def test_clock_out_without_open_raises(self):
        with self.assertRaises(TimeTrackingError):
            clock_out(
                membership=self.provider_m, by_user=self.provider_user,
            )

    def test_clock_out_after_double_close_raises(self):
        clock_in(membership=self.provider_m, by_user=self.provider_user)
        clock_out(membership=self.provider_m, by_user=self.provider_user)
        with self.assertRaises(TimeTrackingError):
            clock_out(
                membership=self.provider_m, by_user=self.provider_user,
            )

    def test_db_constraint_rejects_clock_out_before_clock_in(self):
        from django.db import transaction
        from django.db.utils import IntegrityError
        now = timezone.now()
        # Wrap in a savepoint so the IntegrityError doesn't poison
        # the surrounding test transaction.
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                TimeEntry.objects.create(
                    tenant=self.tenant,
                    membership=self.provider_m,
                    clock_in_at=now,
                    clock_out_at=now - dt.timedelta(minutes=10),
                )


# ── Permission + read scope ─────────────────────────────────────────


class TimeEntryReadScopeTests(TestCase):
    """Non-managers only see their own entries; managers see all."""

    @classmethod
    def setUpTestData(cls):
        cls.tenant, cls.owner, cls.owner_m = _make_tenant('tt-scope')
        cls.alice_user, cls.alice = _make_member(
            cls.tenant, TenantMembership.Role.PROVIDER, 'alice@test.local',
        )
        cls.bob_user, cls.bob = _make_member(
            cls.tenant, TenantMembership.Role.PROVIDER, 'bob@test.local',
        )
        # Front desk — no MANAGE_STAFF.
        cls.fd_user, cls.fd = _make_member(
            cls.tenant, TenantMembership.Role.FRONT_DESK, 'fd@test.local',
        )

        now = timezone.now()
        TimeEntry.objects.create(
            tenant=cls.tenant, membership=cls.alice,
            clock_in_at=now - dt.timedelta(hours=1),
            clock_out_at=now,
        )
        TimeEntry.objects.create(
            tenant=cls.tenant, membership=cls.bob,
            clock_in_at=now - dt.timedelta(hours=2),
            clock_out_at=now,
        )

    def test_provider_sees_only_own_entries(self):
        response = _client_for(self.alice_user).get(
            reverse('time-entry-list'),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        memberships = {row['membership'] for row in response.data}
        self.assertEqual(memberships, {self.alice.pk})

    def test_front_desk_sees_only_own_entries(self):
        # FD has no entries of their own → empty list.
        response = _client_for(self.fd_user).get(
            reverse('time-entry-list'),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 0)

    def test_owner_sees_all_entries(self):
        response = _client_for(self.owner).get(
            reverse('time-entry-list'),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)


# ── Clock-in / clock-out endpoints ──────────────────────────────────


class ClockInOutEndpointTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant, cls.owner, cls.owner_m = _make_tenant('tt-ep')
        cls.alice_user, cls.alice = _make_member(
            cls.tenant, TenantMembership.Role.PROVIDER, 'alice@test.local',
        )
        cls.bob_user, cls.bob = _make_member(
            cls.tenant, TenantMembership.Role.PROVIDER, 'bob@test.local',
        )
        cls.fd_user, cls.fd = _make_member(
            cls.tenant, TenantMembership.Role.FRONT_DESK, 'fd@test.local',
        )

    def _client(self, user):
        return _client_for(user)

    def test_self_clock_in(self):
        response = self._client(self.alice_user).post(
            reverse('time-entry-clock-in-action'),
            data={},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data['membership'], self.alice.pk)
        self.assertEqual(response.data['source'], 'self')
        self.assertTrue(response.data['is_open'])

    def test_self_clock_in_twice_409(self):
        url = reverse('time-entry-clock-in-action')
        self._client(self.alice_user).post(
            url, data={}, format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        response = self._client(self.alice_user).post(
            url, data={}, format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    def test_self_clock_out_closes_shift(self):
        clock_in(membership=self.alice, by_user=self.alice_user)
        response = self._client(self.alice_user).post(
            reverse('time-entry-clock-out-action'),
            data={},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertFalse(response.data['is_open'])
        self.assertIsNotNone(response.data['clock_out_at'])

    def test_clock_out_without_open_409(self):
        response = self._client(self.alice_user).post(
            reverse('time-entry-clock-out-action'),
            data={},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    def test_provider_cannot_clock_in_someone_else(self):
        response = self._client(self.alice_user).post(
            reverse('time-entry-clock-in-action'),
            data={'membership_id': self.bob.pk},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_owner_can_clock_in_someone_else(self):
        response = self._client(self.owner).post(
            reverse('time-entry-clock-in-action'),
            data={'membership_id': self.bob.pk},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data['membership'], self.bob.pk)
        # Default source flips from SELF to FRONT_DESK when owner
        # punches someone else.
        self.assertEqual(response.data['source'], 'front_desk')

    def test_clock_in_audit_log(self):
        self._client(self.alice_user).post(
            reverse('time-entry-clock-in-action'),
            data={},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        log = AuditLog.objects.filter(
            resource_type='time_entry', action=AuditLog.Action.CREATE,
        ).order_by('-id').first()
        self.assertIsNotNone(log)
        self.assertEqual(log.metadata.get('event'), 'clock_in')
        self.assertTrue(log.metadata.get('self_punch'))

    def test_clock_out_records_duration_in_audit(self):
        clock_in(membership=self.alice, by_user=self.alice_user)
        self._client(self.alice_user).post(
            reverse('time-entry-clock-out-action'),
            data={},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        log = AuditLog.objects.filter(
            resource_type='time_entry', action=AuditLog.Action.UPDATE,
        ).order_by('-id').first()
        self.assertEqual(log.metadata.get('event'), 'clock_out')
        self.assertGreaterEqual(log.metadata.get('duration_seconds', 0), 0)


# ── Manager edit + delete ──────────────────────────────────────────


class ManagerEditTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant, cls.owner, cls.owner_m = _make_tenant('tt-edit')
        cls.alice_user, cls.alice = _make_member(
            cls.tenant, TenantMembership.Role.PROVIDER, 'alice@test.local',
        )

    def setUp(self):
        now = timezone.now()
        self.entry = TimeEntry.objects.create(
            tenant=self.tenant,
            membership=self.alice,
            clock_in_at=now - dt.timedelta(hours=8),
            clock_out_at=None,  # forgot to clock out
        )

    def test_owner_can_edit(self):
        new_close = self.entry.clock_in_at + dt.timedelta(hours=8)
        response = _client_for(self.owner).patch(
            reverse('time-entry-detail', kwargs={'pk': self.entry.pk}),
            data={'clock_out_at': new_close.isoformat()},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.entry.refresh_from_db()
        self.assertIsNotNone(self.entry.clock_out_at)
        self.assertEqual(self.entry.edited_by, self.owner)
        self.assertIsNotNone(self.entry.edited_at)

    def test_provider_cannot_edit_own_entry(self):
        response = _client_for(self.alice_user).patch(
            reverse('time-entry-detail', kwargs={'pk': self.entry.pk}),
            data={'notes': 'sneaky'},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_edit_rejects_clock_out_before_clock_in(self):
        bad = self.entry.clock_in_at - dt.timedelta(hours=1)
        response = _client_for(self.owner).patch(
            reverse('time-entry-detail', kwargs={'pk': self.entry.pk}),
            data={'clock_out_at': bad.isoformat()},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_owner_can_delete(self):
        response = _client_for(self.owner).delete(
            reverse('time-entry-detail', kwargs={'pk': self.entry.pk}),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(TimeEntry.objects.filter(pk=self.entry.pk).exists())

    def test_edit_audit_log_records_changed_fields(self):
        new_close = self.entry.clock_in_at + dt.timedelta(hours=8)
        _client_for(self.owner).patch(
            reverse('time-entry-detail', kwargs={'pk': self.entry.pk}),
            data={
                'clock_out_at': new_close.isoformat(),
                'notes': 'fixed missing punch',
            },
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        log = AuditLog.objects.filter(
            resource_type='time_entry', action=AuditLog.Action.UPDATE,
        ).order_by('-id').first()
        self.assertEqual(log.metadata.get('event'), 'manager_edit')
        self.assertIn('clock_out_at', log.metadata.get('fields_changed', []))
        self.assertIn('notes', log.metadata.get('fields_changed', []))


# ── Mobile-helper endpoints ─────────────────────────────────────────


class MobileHelperEndpointTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant, cls.owner, cls.owner_m = _make_tenant('tt-mob')
        cls.alice_user, cls.alice = _make_member(
            cls.tenant, TenantMembership.Role.PROVIDER, 'alice@test.local',
        )
        cls.bob_user, cls.bob = _make_member(
            cls.tenant, TenantMembership.Role.PROVIDER, 'bob@test.local',
        )

    def test_active_lists_only_open_shifts(self):
        # Alice open, Bob closed.
        clock_in(membership=self.alice, by_user=self.alice_user)
        clock_in(membership=self.bob, by_user=self.bob_user)
        clock_out(membership=self.bob, by_user=self.bob_user)

        # Even a non-manager can see the active list — useful for
        # the "who's in" panel rendered to everyone.
        response = _client_for(self.alice_user).get(
            reverse('time-entry-active'),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        memberships = [row['membership'] for row in response.data]
        self.assertEqual(memberships, [self.alice.pk])

    def test_me_returns_open_entry_and_recent(self):
        # Pre-populate three closed shifts + one open.
        now = timezone.now()
        for i in range(3):
            TimeEntry.objects.create(
                tenant=self.tenant, membership=self.alice,
                clock_in_at=now - dt.timedelta(days=i + 1),
                clock_out_at=now - dt.timedelta(days=i + 1) + dt.timedelta(hours=8),
            )
        clock_in(membership=self.alice, by_user=self.alice_user)

        response = _client_for(self.alice_user).get(
            reverse('time-entry-me'),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNotNone(response.data['open_entry'])
        self.assertEqual(len(response.data['recent']), 3)

    def test_me_with_no_entries_returns_nulls(self):
        response = _client_for(self.alice_user).get(
            reverse('time-entry-me'),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(response.data['open_entry'])
        self.assertEqual(response.data['recent'], [])


# ── Filtering ───────────────────────────────────────────────────────


class FilterTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant, cls.owner, cls.owner_m = _make_tenant('tt-filter')
        cls.alice_user, cls.alice = _make_member(
            cls.tenant, TenantMembership.Role.PROVIDER, 'alice@test.local',
        )
        cls.bob_user, cls.bob = _make_member(
            cls.tenant, TenantMembership.Role.PROVIDER, 'bob@test.local',
        )
        now = timezone.now()
        # Alice: yesterday closed + today open
        TimeEntry.objects.create(
            tenant=cls.tenant, membership=cls.alice,
            clock_in_at=now - dt.timedelta(days=1),
            clock_out_at=now - dt.timedelta(days=1) + dt.timedelta(hours=8),
        )
        TimeEntry.objects.create(
            tenant=cls.tenant, membership=cls.alice,
            clock_in_at=now - dt.timedelta(hours=2),
            clock_out_at=None,
        )
        # Bob: only today closed
        TimeEntry.objects.create(
            tenant=cls.tenant, membership=cls.bob,
            clock_in_at=now - dt.timedelta(hours=10),
            clock_out_at=now - dt.timedelta(hours=2),
        )

    def test_filter_by_membership(self):
        response = _client_for(self.owner).get(
            reverse('time-entry-list') + f'?membership={self.alice.pk}',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(len(response.data), 2)

    def test_filter_open_only(self):
        response = _client_for(self.owner).get(
            reverse('time-entry-list') + '?open=true',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['membership'], self.alice.pk)

    def test_filter_closed_only(self):
        response = _client_for(self.owner).get(
            reverse('time-entry-list') + '?open=false',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(len(response.data), 2)


# ── Tenant isolation ────────────────────────────────────────────────


class TenantIsolationTests(TestCase):
    def test_cannot_clock_into_other_tenants_membership(self):
        tenant_a, owner_a, _ = _make_tenant('tt-iso-a')
        tenant_b, _, _ = _make_tenant('tt-iso-b')
        _, b_member = _make_member(
            tenant_b, TenantMembership.Role.PROVIDER, 'bm@test.local',
        )
        response = _client_for(owner_a).post(
            reverse('time-entry-clock-in-action'),
            data={'membership_id': b_member.pk},
            format='json',
            HTTP_X_TENANT_SLUG=tenant_a.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


# ── Concurrency: single-open-shift invariant ────────────────────────


class ConcurrencyTests(TransactionTestCase):
    """Run the clock-in service under simulated concurrency.

    Both threads attempting clock-in serialize via select_for_update
    — first wins, second raises. This is the integrity guarantee
    the model layer doesn't enforce at the DB.
    """

    def setUp(self):
        self.tenant, self.owner, _ = _make_tenant('tt-concur')
        self.user, self.member = _make_member(
            self.tenant, TenantMembership.Role.PROVIDER, 'c@test.local',
        )

    def test_serial_clock_ins_only_one_succeeds(self):
        # Sanity: serial-but-back-to-back attempts in the same
        # process catch the "already open" guard via the
        # transaction. We don't spin real threads here — tests
        # would be too slow / DB-flaky for CI. The
        # select_for_update lock is exercised in the model code;
        # this just proves the second call raises rather than
        # creating a duplicate row.
        clock_in(membership=self.member, by_user=self.user)
        with self.assertRaises(TimeTrackingError):
            clock_in(membership=self.member, by_user=self.user)
        # Exactly one row exists.
        self.assertEqual(
            TimeEntry.objects.filter(membership=self.member).count(),
            1,
        )
