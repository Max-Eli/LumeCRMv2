"""Tests for tenant settings + writable membership endpoints.

Phase 1H session 1 surface — `GET/PATCH /api/tenant/` for the current
tenant's business profile + branding, and `PATCH /api/memberships/{id}/`
for staff role / activation / job-title / bookable changes.

The audit trail and the last-owner guardrail are both load-bearing for
SOC 2 (separation of duties + change traceability), so they get
explicit coverage here, not just integration smoke.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.audit.models import AuditLog
from apps.tenants.models import JobTitle, Tenant, TenantMembership
from apps.tenants.services import create_tenant_with_defaults

User = get_user_model()


def _make_user(email: str, **kwargs) -> User:
    return User.objects.create_user(email=email, password='test-password', **kwargs)


def _make_tenant(slug: str) -> tuple[Tenant, User]:
    owner = _make_user(f'{slug}-owner@test.local', first_name='Owner')
    tenant = create_tenant_with_defaults(
        name=slug.title(),
        slug=slug,
        owner_user=owner,
        status=Tenant.Status.ACTIVE,
    )
    return tenant, owner


def _make_membership(*, user: User, tenant: Tenant, role: str, location=None, **kwargs) -> TenantMembership:
    """Create a tenant membership AND auto-assign it to a location.

    Mirrors the runtime Add-Employee flow where every membership has at
    least one MembershipLocation entry. Without that, the location-
    scoped queries return nothing for the test fixture and cascading
    test failures result. Defaults to the tenant's default location;
    pass `location=` to override.
    """
    from apps.tenants.models import MembershipLocation

    membership = TenantMembership.objects.create(
        user=user, tenant=tenant, role=role, is_active=True, **kwargs,
    )
    if location is None:
        location = tenant.locations.get(is_default=True)
    MembershipLocation.objects.create(
        membership=membership, location=location, is_active=True,
    )
    return membership


# ── Tenant settings GET / PATCH ────────────────────────────────────────


class TenantSettingsReadTests(TestCase):
    def setUp(self):
        self.tenant, self.owner = _make_tenant('read-tenant')
        self.client = APIClient()
        self.client.force_login(self.owner)

    def test_owner_can_read_tenant_settings(self):
        url = reverse('tenant-settings')
        response = self.client.get(url, HTTP_X_TENANT_SLUG=self.tenant.slug)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['slug'], 'read-tenant')
        self.assertEqual(response.data['name'], 'Read-Tenant')
        self.assertIn('primary_color', response.data)
        self.assertIn('logo_url', response.data)
        # Per-site fields (timezone, address, hours, phone, email) live
        # on Location now — they should NOT be on the tenant payload.
        for stale in ('timezone', 'phone', 'email', 'address_line1', 'business_open_time'):
            self.assertNotIn(stale, response.data)

    def test_read_writes_audit_entry(self):
        url = reverse('tenant-settings')
        self.client.get(url, HTTP_X_TENANT_SLUG=self.tenant.slug)
        log = AuditLog.objects.filter(
            resource_type='tenant',
            resource_id=str(self.tenant.id),
            action=AuditLog.Action.READ,
        ).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.user, self.owner)


class TenantSettingsUpdateTests(TestCase):
    def setUp(self):
        self.tenant, self.owner = _make_tenant('update-tenant')
        self.url = reverse('tenant-settings')

    def test_owner_can_update_branding(self):
        # Tenant carries branding only after the Phase 4E cleanup.
        # Per-site fields (address, hours, etc.) are tested in
        # `LocationsUpdateTests`; this guards the remaining surface.
        client = APIClient()
        client.force_login(self.owner)
        response = client.patch(
            self.url,
            data={
                'primary_color': '#95122C',
                'logo_url': 'https://example.com/logo.png',
            },
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.primary_color, '#95122C')
        self.assertEqual(self.tenant.logo_url, 'https://example.com/logo.png')

    def test_update_writes_audit_entry_with_fields_changed(self):
        client = APIClient()
        client.force_login(self.owner)
        client.patch(
            self.url,
            data={'primary_color': '#FF0000', 'logo_url': 'https://example.com/x.png'},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        log = (
            AuditLog.objects
            .filter(
                resource_type='tenant',
                resource_id=str(self.tenant.id),
                action=AuditLog.Action.UPDATE,
            )
            .order_by('-timestamp')
            .first()
        )
        self.assertIsNotNone(log)
        self.assertEqual(
            sorted(log.metadata.get('fields_changed', [])),
            ['logo_url', 'primary_color'],
        )

    def test_name_is_read_only(self):
        # Locked after onboarding — appears on invoices/receipts/emails;
        # casual rename would silently break consistency. Renames go
        # through Django admin instead.
        client = APIClient()
        client.force_login(self.owner)
        response = client.patch(
            self.url,
            data={'name': 'Attempted Rename'},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.name, 'Update-Tenant')

    def test_slug_is_read_only(self):
        client = APIClient()
        client.force_login(self.owner)
        response = client.patch(
            self.url,
            data={'slug': 'attempted-rename'},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.slug, 'update-tenant')

    def test_per_location_fields_are_silently_ignored(self):
        # Stale clients posting old field names (timezone / phone / etc.)
        # shouldn't 500 — DRF's ModelSerializer ignores unknown fields
        # by default. Verify the request still succeeds and the
        # branding fields update normally.
        client = APIClient()
        client.force_login(self.owner)
        response = client.patch(
            self.url,
            data={
                'primary_color': '#123456',
                # These are no longer on Tenant; should be ignored.
                'timezone': 'America/Los_Angeles',
                'phone': '555-9999',
                'business_open_time': '06:00:00',
            },
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.primary_color, '#123456')

    def test_front_desk_cannot_update(self):
        fd_user = _make_user('fd@test.local')
        _make_membership(
            user=fd_user, tenant=self.tenant, role=TenantMembership.Role.FRONT_DESK,
        )
        client = APIClient()
        client.force_login(fd_user)
        response = client.patch(
            self.url,
            data={'primary_color': '#000000'},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.tenant.refresh_from_db()
        # The original default seeded by onboarding stays put.
        self.assertEqual(self.tenant.primary_color, '#1f2937')


# ── Membership PATCH ──────────────────────────────────────────────────


class MembershipUpdateTests(TestCase):
    def setUp(self):
        self.tenant, self.owner = _make_tenant('staff-tenant')
        self.fd_user = _make_user('fd@test.local', first_name='Fred')
        self.fd_membership = _make_membership(
            user=self.fd_user, tenant=self.tenant, role=TenantMembership.Role.FRONT_DESK,
        )
        self.np_title = JobTitle.objects.filter(
            tenant=self.tenant, name='Nurse Practitioner',
        ).first()

    def _url(self, mid: int) -> str:
        return reverse('membership-detail', args=[mid])

    def test_owner_can_change_role(self):
        client = APIClient()
        client.force_login(self.owner)
        response = client.patch(
            self._url(self.fd_membership.id),
            data={'role': 'manager'},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.fd_membership.refresh_from_db()
        self.assertEqual(self.fd_membership.role, 'manager')

    def test_owner_can_deactivate_member(self):
        client = APIClient()
        client.force_login(self.owner)
        response = client.patch(
            self._url(self.fd_membership.id),
            data={'is_active': False},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.fd_membership.refresh_from_db()
        self.assertFalse(self.fd_membership.is_active)

    def test_owner_can_set_job_title_and_bookable(self):
        client = APIClient()
        client.force_login(self.owner)
        response = client.patch(
            self._url(self.fd_membership.id),
            data={'job_title_id': self.np_title.id, 'is_bookable': True},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.fd_membership.refresh_from_db()
        self.assertEqual(self.fd_membership.job_title_id, self.np_title.id)
        self.assertTrue(self.fd_membership.is_bookable)

    def test_front_desk_cannot_edit_membership(self):
        client = APIClient()
        client.force_login(self.fd_user)
        response = client.patch(
            self._url(self.fd_membership.id),
            data={'role': 'manager'},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_last_active_owner_cannot_be_demoted(self):
        owner_membership = TenantMembership.objects.get(
            user=self.owner, tenant=self.tenant, role='owner',
        )
        client = APIClient()
        client.force_login(self.owner)
        response = client.patch(
            self._url(owner_membership.id),
            data={'role': 'manager'},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn('owner', str(response.data).lower())
        owner_membership.refresh_from_db()
        self.assertEqual(owner_membership.role, 'owner')

    def test_last_active_owner_cannot_be_deactivated(self):
        owner_membership = TenantMembership.objects.get(
            user=self.owner, tenant=self.tenant, role='owner',
        )
        client = APIClient()
        client.force_login(self.owner)
        response = client.patch(
            self._url(owner_membership.id),
            data={'is_active': False},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        owner_membership.refresh_from_db()
        self.assertTrue(owner_membership.is_active)

    def test_owner_can_be_demoted_when_another_owner_exists(self):
        second_owner_user = _make_user('owner2@test.local', first_name='Olive')
        _make_membership(
            user=second_owner_user, tenant=self.tenant, role=TenantMembership.Role.OWNER,
        )
        original = TenantMembership.objects.get(
            user=self.owner, tenant=self.tenant, role='owner',
        )
        client = APIClient()
        client.force_login(self.owner)
        response = client.patch(
            self._url(original.id),
            data={'role': 'manager'},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        original.refresh_from_db()
        self.assertEqual(original.role, 'manager')

    def test_role_change_writes_audit_with_before_after(self):
        client = APIClient()
        client.force_login(self.owner)
        client.patch(
            self._url(self.fd_membership.id),
            data={'role': 'manager'},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        log = (
            AuditLog.objects
            .filter(
                resource_type='membership',
                resource_id=str(self.fd_membership.id),
                action=AuditLog.Action.UPDATE,
            )
            .order_by('-timestamp')
            .first()
        )
        self.assertIsNotNone(log)
        self.assertEqual(log.metadata.get('from_role'), 'front_desk')
        self.assertEqual(log.metadata.get('to_role'), 'manager')

    def test_destroy_is_disallowed(self):
        client = APIClient()
        client.force_login(self.owner)
        response = client.delete(
            self._url(self.fd_membership.id),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)


# ── Add employee (POST /api/memberships/) ────────────────────────────


class AddEmployeeTests(TestCase):
    def setUp(self):
        self.tenant, self.owner = _make_tenant('add-emp-tenant')
        self.fd_user = _make_user('addfd@test.local')
        self.fd_membership = _make_membership(
            user=self.fd_user, tenant=self.tenant,
            role=TenantMembership.Role.FRONT_DESK,
        )
        self.url = reverse('membership-list')

    def _post(self, client, payload):
        return client.post(
            self.url, data=payload, format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )

    def test_owner_can_add_brand_new_employee_returns_temp_password(self):
        client = APIClient()
        client.force_login(self.owner)
        response = self._post(client, {
            'email': 'new-hire@test.local',
            'first_name': 'New',
            'last_name': 'Hire',
            'role': 'provider',
            'is_bookable': True,
        })
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        # Detail shape returned, plus a one-time temp_password.
        self.assertIn('temp_password', response.data)
        self.assertGreater(len(response.data['temp_password']), 8)
        self.assertEqual(response.data['user_email'], 'new-hire@test.local')
        self.assertEqual(response.data['role'], 'provider')
        self.assertTrue(response.data['is_bookable'])
        # User actually created with the temp password set.
        u = User.objects.get(email='new-hire@test.local')
        self.assertTrue(u.check_password(response.data['temp_password']))

    def test_attaching_existing_user_does_not_return_temp_password(self):
        # Pre-existing user with a known password.
        existing = _make_user('existing@test.local', first_name='Ex', last_name='Isting')
        client = APIClient()
        client.force_login(self.owner)
        response = self._post(client, {
            'email': 'existing@test.local',
            'first_name': 'Ex',
            'last_name': 'Isting',
            'role': 'manager',
        })
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertNotIn('temp_password', response.data)
        # The membership is for this user.
        self.assertEqual(response.data['user_email'], 'existing@test.local')
        # Existing user still has their original password (not reset).
        existing.refresh_from_db()
        self.assertTrue(existing.check_password('test-password'))

    def test_email_lookup_is_case_insensitive(self):
        _make_user('mixedcase@test.local')
        client = APIClient()
        client.force_login(self.owner)
        response = self._post(client, {
            'email': 'MixedCase@TEST.local',  # different case, same email
            'first_name': 'X', 'last_name': 'Y',
            'role': 'front_desk',
        })
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        # Should NOT have created a duplicate user.
        self.assertEqual(User.objects.filter(email__iexact='mixedcase@test.local').count(), 1)
        self.assertNotIn('temp_password', response.data)

    def test_duplicate_membership_in_same_tenant_rejected(self):
        # fd_user is already a member of self.tenant.
        client = APIClient()
        client.force_login(self.owner)
        response = self._post(client, {
            'email': self.fd_user.email,
            'first_name': 'Already', 'last_name': 'There',
            'role': 'manager',
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('already', str(response.data).lower())

    def test_front_desk_cannot_add_employee(self):
        client = APIClient()
        client.force_login(self.fd_user)
        response = self._post(client, {
            'email': 'sneaky@test.local',
            'first_name': 'X', 'last_name': 'Y',
            'role': 'manager',
        })
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(User.objects.filter(email='sneaky@test.local').exists())

    def test_create_writes_audit_entry(self):
        client = APIClient()
        client.force_login(self.owner)
        response = self._post(client, {
            'email': 'auditme@test.local',
            'first_name': 'Audit', 'last_name': 'Me',
            'role': 'provider',
        })
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        log = AuditLog.objects.filter(
            resource_type='membership',
            resource_id=str(response.data['id']),
            action=AuditLog.Action.CREATE,
        ).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.metadata.get('role'), 'provider')
        self.assertEqual(log.metadata.get('attached_existing_user'), False)

    def test_new_employee_auto_assigned_to_active_location(self):
        # No `location_ids` in payload + no cookie → falls back to the
        # tenant's default location. The new membership gets one
        # MembershipLocation row pointing at it. This makes the
        # "Add employee" flow Just Work for the most common case
        # (operator on the calendar / staff page at a specific site).
        client = APIClient()
        client.force_login(self.owner)
        response = self._post(client, {
            'email': 'auto-assigned@test.local',
            'first_name': 'A', 'last_name': 'A',
            'role': 'provider',
        })
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        new_membership = TenantMembership.objects.get(id=response.data['id'])
        assignments = list(new_membership.location_assignments.all())
        self.assertEqual(len(assignments), 1)
        default_location = self.tenant.locations.get(is_default=True)
        self.assertEqual(assignments[0].location_id, default_location.id)
        self.assertTrue(assignments[0].is_active)

    def test_new_employee_cookie_pinned_location_assigned(self):
        # Cookie pointing at a non-default location → the new membership
        # is assigned there, not to the tenant default.
        extra_location = Location.objects.create(
            tenant=self.tenant, name='Brooklyn', slug='brooklyn',
            is_default=False, is_active=True,
        )
        client = APIClient()
        client.force_login(self.owner)
        client.cookies[ACTIVE_LOCATION_COOKIE] = 'brooklyn'
        response = self._post(client, {
            'email': 'brooklyn-hire@test.local',
            'first_name': 'B', 'last_name': 'B',
            'role': 'provider',
        })
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        new_membership = TenantMembership.objects.get(id=response.data['id'])
        assignments = list(new_membership.location_assignments.all())
        self.assertEqual(len(assignments), 1)
        self.assertEqual(assignments[0].location_id, extra_location.id)

    def test_explicit_location_ids_overrides_active_location(self):
        # Owner adds a multi-site employee in one shot — assign to both
        # sites at create time. Active-location auto-assign is bypassed.
        loc_b = Location.objects.create(
            tenant=self.tenant, name='Brooklyn', slug='brooklyn',
            is_default=False, is_active=True,
        )
        loc_q = Location.objects.create(
            tenant=self.tenant, name='Queens', slug='queens',
            is_default=False, is_active=True,
        )
        client = APIClient()
        client.force_login(self.owner)
        response = self._post(client, {
            'email': 'multi-site@test.local',
            'first_name': 'M', 'last_name': 'M',
            'role': 'provider',
            'location_ids': [loc_b.id, loc_q.id],
        })
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        new_membership = TenantMembership.objects.get(id=response.data['id'])
        assigned_ids = set(new_membership.location_assignments.values_list('location_id', flat=True))
        self.assertEqual(assigned_ids, {loc_b.id, loc_q.id})
        # Default location is NOT auto-included when explicit list is provided.
        default_location = self.tenant.locations.get(is_default=True)
        self.assertNotIn(default_location.id, assigned_ids)

    def test_explicit_empty_location_ids_creates_no_assignments(self):
        # `location_ids: []` is the explicit "no auto-assignment" opt-out.
        # The employee is created but invisible to location-scoped queries
        # until they're assigned later.
        client = APIClient()
        client.force_login=self.owner
        client = APIClient()
        client.force_login(self.owner)
        response = self._post(client, {
            'email': 'unassigned@test.local',
            'first_name': 'U', 'last_name': 'U',
            'role': 'provider',
            'location_ids': [],
        })
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        new_membership = TenantMembership.objects.get(id=response.data['id'])
        self.assertFalse(new_membership.location_assignments.exists())

    def test_cross_tenant_location_id_rejected_on_create(self):
        # Other tenant's location → 400, no membership created.
        other_tenant, _ = _make_tenant('other-create')
        other_location = other_tenant.locations.get(is_default=True)
        client = APIClient()
        client.force_login(self.owner)
        response = self._post(client, {
            'email': 'cross-tenant@test.local',
            'first_name': 'C', 'last_name': 'T',
            'role': 'provider',
            'location_ids': [other_location.id],
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('location_ids', response.data)
        self.assertFalse(User.objects.filter(email='cross-tenant@test.local').exists())


# ── Employee detail (GET /api/memberships/{id}/ + PATCH for nested user) ──


class EmployeeDetailTests(TestCase):
    def setUp(self):
        self.tenant, self.owner = _make_tenant('detail-tenant')
        self.fd_user = _make_user('emp@test.local', first_name='Em', last_name='Ployee')
        self.fd_membership = _make_membership(
            user=self.fd_user, tenant=self.tenant,
            role=TenantMembership.Role.FRONT_DESK,
        )

    def _url(self, mid: int) -> str:
        return reverse('membership-detail', args=[mid])

    def test_detail_includes_employment_payroll_and_user_contact(self):
        client = APIClient()
        client.force_login(self.owner)
        response = client.get(
            self._url(self.fd_membership.id),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Personal contact (user-side, nested through membership)
        self.assertIn('user_phone', response.data)
        self.assertIn('user_address_line1', response.data)
        # Employment + payroll (membership-side)
        self.assertIn('employment_type', response.data)
        self.assertIn('pay_type', response.data)
        self.assertIn('pay_rate_cents', response.data)
        self.assertIn('hire_date', response.data)
        # Multi-center summary
        self.assertIn('other_memberships', response.data)
        self.assertEqual(response.data['other_memberships'], [])

    def test_other_memberships_lists_other_tenants_for_same_user(self):
        # Make a second tenant + membership for the same user.
        other_tenant, _other_owner = _make_tenant('other-spa')
        _make_membership(
            user=self.fd_user, tenant=other_tenant,
            role=TenantMembership.Role.PROVIDER,
        )
        client = APIClient()
        client.force_login(self.owner)
        response = client.get(
            self._url(self.fd_membership.id),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        others = response.data['other_memberships']
        self.assertEqual(len(others), 1)
        self.assertEqual(others[0]['tenant_name'], 'Other-Spa')
        self.assertEqual(others[0]['role'], 'provider')

    def test_owner_can_update_user_contact_and_payroll_in_one_patch(self):
        client = APIClient()
        client.force_login(self.owner)
        response = client.patch(
            self._url(self.fd_membership.id),
            data={
                'user_phone': '555-1234',
                'user_address_line1': '1 Main St',
                'user_city': 'NYC',
                'employment_type': 'full_time',
                'pay_type': 'hourly',
                'pay_rate_cents': 3500,  # $35/hour
                'hire_date': '2024-01-15',
            },
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # User-side fields landed.
        self.fd_user.refresh_from_db()
        self.assertEqual(self.fd_user.phone, '555-1234')
        self.assertEqual(self.fd_user.address_line1, '1 Main St')
        self.assertEqual(self.fd_user.city, 'NYC')
        # Membership-side fields landed.
        self.fd_membership.refresh_from_db()
        self.assertEqual(self.fd_membership.employment_type, 'full_time')
        self.assertEqual(self.fd_membership.pay_type, 'hourly')
        self.assertEqual(self.fd_membership.pay_rate_cents, 3500)
        self.assertEqual(self.fd_membership.hire_date.isoformat(), '2024-01-15')

    def test_user_email_is_read_only_on_patch(self):
        client = APIClient()
        client.force_login(self.owner)
        client.patch(
            self._url(self.fd_membership.id),
            data={'user_email': 'attempted-rename@test.local'},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.fd_user.refresh_from_db()
        self.assertEqual(self.fd_user.email, 'emp@test.local')

    def test_detail_includes_active_location_ids(self):
        # The membership was created via `_make_membership` which auto-
        # assigns to the tenant's default location.
        from apps.tenants.models import Location, MembershipLocation
        loc_b = Location.objects.create(
            tenant=self.tenant, name='Brooklyn', slug='brooklyn',
            is_default=False, is_active=True,
        )
        MembershipLocation.objects.create(
            membership=self.fd_membership, location=loc_b, is_active=True,
        )
        client = APIClient()
        client.force_login(self.owner)
        response = client.get(
            self._url(self.fd_membership.id),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        default = self.tenant.locations.get(is_default=True)
        self.assertEqual(
            sorted(response.data['location_ids']),
            sorted([default.id, loc_b.id]),
        )

    def test_set_location_ids_replaces_assignments_with_soft_delete(self):
        # Start: assigned to default ('main') from _make_membership setup.
        # Goal: replace with [brooklyn] only — main becomes deactivated,
        # brooklyn becomes active (created or reactivated).
        from apps.tenants.models import Location, MembershipLocation
        loc_b = Location.objects.create(
            tenant=self.tenant, name='Brooklyn', slug='brooklyn',
            is_default=False, is_active=True,
        )
        default = self.tenant.locations.get(is_default=True)
        client = APIClient()
        client.force_login(self.owner)
        response = client.patch(
            self._url(self.fd_membership.id),
            data={'set_location_ids': [loc_b.id]},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Read shape returns active assignments only.
        self.assertEqual(response.data['location_ids'], [loc_b.id])
        # DB shape: original main row is preserved with is_active=False
        # (audit trail), new brooklyn row is is_active=True.
        main_assignment = MembershipLocation.objects.get(
            membership=self.fd_membership, location=default,
        )
        self.assertFalse(main_assignment.is_active)
        brooklyn_assignment = MembershipLocation.objects.get(
            membership=self.fd_membership, location=loc_b,
        )
        self.assertTrue(brooklyn_assignment.is_active)

    def test_set_location_ids_reactivates_existing_soft_deleted_row(self):
        # If the membership previously was at a location and got
        # deactivated, re-adding that location flips the same row back
        # rather than creating a duplicate (which would violate the
        # (membership, location) unique constraint).
        from apps.tenants.models import MembershipLocation
        default = self.tenant.locations.get(is_default=True)
        # Pre-deactivate the default assignment.
        MembershipLocation.objects.filter(
            membership=self.fd_membership, location=default,
        ).update(is_active=False)
        client = APIClient()
        client.force_login(self.owner)
        response = client.patch(
            self._url(self.fd_membership.id),
            data={'set_location_ids': [default.id]},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # The same row is reactivated — no duplicate.
        rows = MembershipLocation.objects.filter(
            membership=self.fd_membership, location=default,
        )
        self.assertEqual(rows.count(), 1)
        self.assertTrue(rows.first().is_active)

    def test_cross_tenant_location_id_rejected_on_set(self):
        other_tenant, _ = _make_tenant('other-set')
        other_location = other_tenant.locations.get(is_default=True)
        client = APIClient()
        client.force_login(self.owner)
        response = client.patch(
            self._url(self.fd_membership.id),
            data={'set_location_ids': [other_location.id]},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('set_location_ids', response.data)

    def test_set_location_ids_writes_audit_metadata(self):
        from apps.tenants.models import Location
        loc_b = Location.objects.create(
            tenant=self.tenant, name='Brooklyn', slug='brooklyn',
            is_default=False, is_active=True,
        )
        client = APIClient()
        client.force_login(self.owner)
        client.patch(
            self._url(self.fd_membership.id),
            data={'set_location_ids': [loc_b.id]},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        log = AuditLog.objects.filter(
            resource_type='membership',
            resource_id=str(self.fd_membership.id),
            action=AuditLog.Action.UPDATE,
        ).order_by('-id').first()
        self.assertIsNotNone(log)
        changes = log.metadata.get('location_assignments') or {}
        default = self.tenant.locations.get(is_default=True)
        self.assertEqual(changes.get('created_location_ids'), [loc_b.id])
        self.assertEqual(changes.get('deactivated_location_ids'), [default.id])

    def test_patch_without_set_location_ids_leaves_assignments_alone(self):
        # Owner edits the employee's payroll without touching locations
        # — the assignments must NOT be reconciled to "empty" (which
        # would deactivate everything).
        client = APIClient()
        client.force_login(self.owner)
        response = client.patch(
            self._url(self.fd_membership.id),
            data={'pay_rate_cents': 5000},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        default = self.tenant.locations.get(is_default=True)
        self.assertEqual(response.data['location_ids'], [default.id])


# ── Location + MembershipLocation (Phase 1H multi-location, session 1) ──
#
# Session 1 ships the data model + active-location resolution. There's no
# REST surface yet — the locations management UI lands in session 2.
# These tests cover what's in Session 1's contract:
#
#   - Onboarding seeds a default Location and links the owner to it.
#   - The data backfill migration produced one default Location per
#     pre-existing tenant + a MembershipLocation per existing membership.
#     (Tested indirectly: every tenant created via the service has the
#     same shape the backfill would produce.)
#   - The `unique_default_per_tenant` constraint actually fires.
#   - The `LocationMiddleware` resolves: cookie → tenant default → None,
#     and ignores cookies that point at a different tenant's location.

from apps.tenants.context import get_current_location
from apps.tenants.middleware import ACTIVE_LOCATION_COOKIE
from apps.tenants.models import Location, MembershipLocation


class LocationOnboardingTests(TestCase):
    """`create_tenant_with_defaults` should seed a default Location and
    link the owner's membership to it in the same transaction."""

    def test_default_location_seeded_for_new_tenant(self):
        owner = _make_user('default-loc@test.local')
        tenant = create_tenant_with_defaults(
            name='Default-Loc Spa',
            slug='default-loc',
            owner_user=owner,
            timezone='America/Los_Angeles',
            phone='415-555-0100',
            address_line1='1 Market St',
            city='San Francisco',
            state='CA',
            zip_code='94105',
            business_open_time='09:00',
            business_close_time='19:00',
        )

        locations = list(tenant.locations.all())
        self.assertEqual(len(locations), 1)
        location = locations[0]
        self.assertEqual(location.name, 'Main')
        self.assertEqual(location.slug, 'main')
        self.assertTrue(location.is_default)
        self.assertTrue(location.is_active)
        # Per-site fields copied from the tenant onboarding kwargs.
        self.assertEqual(location.timezone, 'America/Los_Angeles')
        self.assertEqual(location.city, 'San Francisco')
        self.assertEqual(location.state, 'CA')
        self.assertEqual(str(location.business_open_time), '09:00:00')

    def test_owner_membership_assigned_to_default_location(self):
        owner = _make_user('owner-loc@test.local')
        tenant = create_tenant_with_defaults(
            name='Owner-Loc Spa',
            slug='owner-loc',
            owner_user=owner,
        )
        owner_membership = tenant.memberships.get(user=owner)
        assignments = list(owner_membership.location_assignments.all())
        self.assertEqual(len(assignments), 1)
        self.assertEqual(assignments[0].location.slug, 'main')
        self.assertTrue(assignments[0].is_active)


class LocationConstraintTests(TestCase):
    """The DB-level constraints are load-bearing: a tenant with two
    `is_default=True` locations would corrupt active-location fallback."""

    def test_only_one_default_location_per_tenant(self):
        from django.db import IntegrityError, transaction

        tenant, _owner = _make_tenant('one-default')
        # The default already exists from onboarding; trying to add a
        # second one with is_default=True must fail at the DB layer.
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Location.objects.create(
                    tenant=tenant,
                    name='Second Default',
                    slug='second',
                    is_default=True,
                )

    def test_two_tenants_can_each_have_their_own_default(self):
        # The partial unique index is *per-tenant* — two different
        # tenants both having a default is fine.
        t1, _ = _make_tenant('multi-a')
        t2, _ = _make_tenant('multi-b')
        self.assertTrue(t1.locations.filter(is_default=True).exists())
        self.assertTrue(t2.locations.filter(is_default=True).exists())

    def test_location_slug_unique_per_tenant(self):
        from django.db import IntegrityError, transaction

        tenant, _ = _make_tenant('slug-unique')
        # Default 'main' was seeded; a second 'main' must fail.
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Location.objects.create(
                    tenant=tenant,
                    name='Duplicate Main',
                    slug='main',
                )

    def test_same_slug_allowed_across_different_tenants(self):
        # Two tenants can both have a 'main' location — slug is namespaced
        # to tenant. Onboarding seeds 'main' for each; no conflict.
        _, _ = _make_tenant('slug-x')
        _, _ = _make_tenant('slug-y')
        self.assertEqual(Location.objects.filter(slug='main').count(), 2)


class LocationMiddlewareTests(TestCase):
    """`LocationMiddleware` resolves the active location from the
    `lume_active_location` cookie, falling back to the tenant's default.
    A cookie that doesn't match an active location of the request's
    tenant must be ignored — never resolve to another tenant's site."""

    def setUp(self):
        # Two tenants. Tenant A has two locations (default 'main' +
        # extra 'manhattan'); tenant B has just its default.
        self.tenant_a, self.owner_a = _make_tenant('mw-a')
        self.tenant_b, self.owner_b = _make_tenant('mw-b')
        self.location_a_extra = Location.objects.create(
            tenant=self.tenant_a,
            name='Manhattan',
            slug='manhattan',
            is_default=False,
            is_active=True,
        )
        self.client = APIClient()
        self.client.force_login(self.owner_a)

    def _hit_endpoint_with_cookie(self, *, tenant_slug, cookie_value=None):
        """Hit any endpoint that runs the middleware stack, then read
        `request.location` from the test response wrapper. We use the
        existing `/api/tenant/` endpoint (already covered by other
        tests) and instead assert on the side effect we care about:
        the contextvar value seen by the request."""
        # The simplest way to observe the resolved location is to peek
        # at the contextvar from inside a custom assertion view, but
        # that's heavyweight. Instead, drive the middleware directly.
        from django.test import RequestFactory

        from apps.tenants.middleware import LocationMiddleware, TenantMiddleware

        rf = RequestFactory()
        request = rf.get('/api/tenant/', HTTP_X_TENANT_SLUG=tenant_slug)
        if cookie_value is not None:
            request.COOKIES[ACTIVE_LOCATION_COOKIE] = cookie_value
        # Attach a user so the rest of the stack is happy (not strictly
        # needed for location resolution).
        request.user = self.owner_a

        captured = {}

        def fake_view(req):
            captured['location'] = get_current_location()
            captured['request_location'] = req.location
            from django.http import HttpResponse
            return HttpResponse('ok')

        # Compose the stack: TenantMiddleware then LocationMiddleware.
        stack = TenantMiddleware(LocationMiddleware(fake_view))
        stack(request)
        return captured

    def test_falls_back_to_tenant_default_when_no_cookie(self):
        result = self._hit_endpoint_with_cookie(tenant_slug='mw-a')
        self.assertIsNotNone(result['request_location'])
        self.assertEqual(result['request_location'].slug, 'main')
        self.assertTrue(result['request_location'].is_default)

    def test_uses_cookie_when_it_matches_an_active_location(self):
        result = self._hit_endpoint_with_cookie(
            tenant_slug='mw-a', cookie_value='manhattan',
        )
        self.assertEqual(result['request_location'].slug, 'manhattan')

    def test_ignores_cookie_pointing_at_other_tenants_location(self):
        # Tenant A asks for tenant B's slug — must not cross tenants;
        # falls back to A's default.
        result = self._hit_endpoint_with_cookie(
            tenant_slug='mw-a', cookie_value='main',
        )
        # 'main' exists in both tenants but the lookup is scoped to
        # tenant_a — and that 'main' IS A's default, so this still
        # resolves to A's main. To test cross-tenant guard we need a
        # slug that exists ONLY in tenant B. Add one.
        Location.objects.create(
            tenant=self.tenant_b, name='Brooklyn', slug='brooklyn', is_default=False,
        )
        result = self._hit_endpoint_with_cookie(
            tenant_slug='mw-a', cookie_value='brooklyn',
        )
        # Tenant A doesn't have 'brooklyn' — middleware falls back to A's default.
        self.assertEqual(result['request_location'].slug, 'main')
        self.assertEqual(result['request_location'].tenant_id, self.tenant_a.id)

    def test_ignores_cookie_pointing_at_inactive_location(self):
        self.location_a_extra.is_active = False
        self.location_a_extra.save()
        result = self._hit_endpoint_with_cookie(
            tenant_slug='mw-a', cookie_value='manhattan',
        )
        # Inactive location is ignored; falls back to default.
        self.assertEqual(result['request_location'].slug, 'main')

    def test_resolves_to_none_when_no_tenant_on_request(self):
        # No tenant slug header → no tenant → no location. Should not raise.
        result = self._hit_endpoint_with_cookie(tenant_slug='nonexistent-tenant')
        self.assertIsNone(result['request_location'])


class LocationDataMigrationShapeTests(TestCase):
    """Sanity-check the shape produced by the data migration is what
    code downstream of it will assume.

    The actual 0006 RunPython ran against the test DB during setup;
    we reassert the invariants here so a future regression that
    silently breaks the seeded data is caught.
    """

    def test_every_tenant_has_exactly_one_default_active_location(self):
        # Seed three tenants the canonical way.
        for slug in ('shape-a', 'shape-b', 'shape-c'):
            _make_tenant(slug)
        for tenant in Tenant.objects.all():
            defaults = tenant.locations.filter(is_default=True, is_active=True)
            self.assertEqual(
                defaults.count(), 1,
                f'tenant {tenant.slug} should have exactly 1 default active location',
            )

    def test_every_membership_has_a_location_assignment(self):
        # Both the onboarding service AND the test helpers auto-create
        # a MembershipLocation row at the tenant's default location.
        # This test guards the invariant that consumers downstream of
        # the membership table can rely on: every membership has at
        # least one assignment. (The runtime Add-Employee flow also
        # auto-assigns to the active location — see
        # `AddEmployeeTests.test_new_employee_auto_assigned_to_active_location`.)
        tenant, owner = _make_tenant('assignment-shape')
        worker = _make_user('worker-shape@test.local')
        membership = _make_membership(
            user=worker, tenant=tenant, role=TenantMembership.Role.PROVIDER,
        )
        owner_m = tenant.memberships.get(user=owner)
        self.assertTrue(owner_m.location_assignments.exists())
        self.assertTrue(membership.location_assignments.exists())


# ── Locations REST API (Phase 4E session 2) ──────────────────────────
#
# `/api/locations/` covers list / create / retrieve / update for the
# current tenant. Read is open to anyone in the tenant (front-desk needs
# to know which sites exist for the location switcher); write is gated
# by `MANAGE_TENANT_SETTINGS` (owners by default). Three invariants are
# enforced application-side so the UI gets a friendly 400 instead of a
# 500 from the partial-unique DB constraint:
#
#   1. Cannot deactivate the only active location.
#   2. Cannot deactivate the current default.
#   3. Cannot un-set is_default on the current default. To "switch
#      defaults", PATCH another location with is_default=true — viewset
#      atomically demotes the previous default in the same transaction.


class LocationsListReadTests(TestCase):
    """Anyone authenticated in the tenant can list locations."""

    def setUp(self):
        self.tenant, self.owner = _make_tenant('list-tenant')
        self.fd_user = _make_user('fd@list.local')
        _make_membership(user=self.fd_user, tenant=self.tenant, role=TenantMembership.Role.FRONT_DESK)
        self.url = reverse('location-list')

    def test_owner_can_list_locations(self):
        client = APIClient()
        client.force_login(self.owner)
        response = client.get(self.url, HTTP_X_TENANT_SLUG=self.tenant.slug)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # The default 'Main' location was seeded by onboarding.
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['slug'], 'main')
        self.assertTrue(response.data[0]['is_default'])

    def test_front_desk_can_list_locations(self):
        # Read is open to everyone in the tenant — they need this for
        # the location switcher, and it's not sensitive PHI.
        client = APIClient()
        client.force_login(self.fd_user)
        response = client.get(self.url, HTTP_X_TENANT_SLUG=self.tenant.slug)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)

    def test_list_only_returns_current_tenants_locations(self):
        # Create a second tenant with its own 'main' — must not leak.
        other_tenant, _ = _make_tenant('other-list')
        Location.objects.create(
            tenant=other_tenant, name='Other Site', slug='other', is_default=False,
        )
        client = APIClient()
        client.force_login(self.owner)
        response = client.get(self.url, HTTP_X_TENANT_SLUG=self.tenant.slug)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['slug'], 'main')


class LocationsCreateTests(TestCase):
    def setUp(self):
        self.tenant, self.owner = _make_tenant('create-tenant')
        self.fd_user = _make_user('fd@create.local')
        _make_membership(user=self.fd_user, tenant=self.tenant, role=TenantMembership.Role.FRONT_DESK)
        self.url = reverse('location-list')

    def _post(self, *, user, data):
        client = APIClient()
        client.force_login(user)
        return client.post(
            self.url, data=data, format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )

    def test_owner_can_create_location_with_explicit_slug(self):
        response = self._post(user=self.owner, data={
            'name': 'Manhattan',
            'slug': 'manhattan',
            'timezone': 'America/New_York',
            'address_line1': '50 W 23rd St',
            'city': 'New York',
            'state': 'NY',
            'zip_code': '10010',
        })
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['slug'], 'manhattan')
        self.assertEqual(response.data['state'], 'NY')
        self.assertFalse(response.data['is_default'])  # Default flag unchanged
        self.assertTrue(response.data['is_active'])

    def test_slug_auto_derived_from_name_when_omitted(self):
        response = self._post(user=self.owner, data={
            'name': 'Brooklyn Studio',
        })
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['slug'], 'brooklyn-studio')

    def test_slug_must_be_unique_per_tenant(self):
        # 'main' already exists from onboarding.
        response = self._post(user=self.owner, data={'name': 'Main', 'slug': 'main'})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('slug', response.data)

    def test_setting_is_default_atomically_demotes_previous(self):
        # Create a second location and ask for it to be the new default
        # in the same request. The old default ('main') must flip to False.
        response = self._post(user=self.owner, data={
            'name': 'Hudson Yards', 'slug': 'hy', 'is_default': True,
        })
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.data['is_default'])
        old_default = Location.objects.get(tenant=self.tenant, slug='main')
        self.assertFalse(old_default.is_default)
        # And the DB constraint is still satisfied: exactly one default.
        defaults = Location.objects.filter(tenant=self.tenant, is_default=True)
        self.assertEqual(defaults.count(), 1)

    def test_front_desk_cannot_create_location(self):
        response = self._post(user=self.fd_user, data={'name': 'Brooklyn'})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_create_writes_audit_log(self):
        self._post(user=self.owner, data={'name': 'Audit Site'})
        log = AuditLog.objects.filter(
            resource_type='location', action=AuditLog.Action.CREATE,
        ).order_by('-id').first()
        self.assertIsNotNone(log)
        self.assertEqual(log.user, self.owner)
        self.assertEqual(log.metadata.get('slug'), 'audit-site')


class LocationsUpdateTests(TestCase):
    def setUp(self):
        self.tenant, self.owner = _make_tenant('update-tenant')
        # Pre-create a second location so we have something to deactivate /
        # promote without tripping the "only active" guardrail.
        self.extra = Location.objects.create(
            tenant=self.tenant, name='Brooklyn', slug='brooklyn',
            is_default=False, is_active=True,
        )
        self.default = self.tenant.locations.get(is_default=True)

    def _patch(self, location_id, data, user=None):
        client = APIClient()
        client.force_login(user or self.owner)
        return client.patch(
            reverse('location-detail', args=[location_id]),
            data=data, format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )

    def test_owner_can_rename_location(self):
        response = self._patch(self.extra.id, {'name': 'Brooklyn Heights'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.extra.refresh_from_db()
        self.assertEqual(self.extra.name, 'Brooklyn Heights')

    def test_state_normalized_to_uppercase(self):
        response = self._patch(self.extra.id, {'state': 'ny'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.extra.refresh_from_db()
        self.assertEqual(self.extra.state, 'NY')

    def test_close_must_come_after_open(self):
        response = self._patch(self.extra.id, {
            'business_open_time': '18:00',
            'business_close_time': '09:00',
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('business_close_time', response.data)

    def test_promoting_to_default_demotes_previous(self):
        response = self._patch(self.extra.id, {'is_default': True})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.extra.refresh_from_db()
        self.default.refresh_from_db()
        self.assertTrue(self.extra.is_default)
        self.assertFalse(self.default.is_default)
        self.assertEqual(
            self.tenant.locations.filter(is_default=True).count(), 1,
        )

    def test_cannot_unset_is_default_on_current_default(self):
        response = self._patch(self.default.id, {'is_default': False})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('is_default', response.data)
        self.default.refresh_from_db()
        self.assertTrue(self.default.is_default)

    def test_cannot_deactivate_default_location(self):
        response = self._patch(self.default.id, {'is_active': False})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('is_active', response.data)
        self.default.refresh_from_db()
        self.assertTrue(self.default.is_active)

    def test_cannot_deactivate_only_active_location(self):
        # Make 'extra' the default + active; deactivate 'main'; then
        # try to deactivate 'extra' too. Must fail.
        self._patch(self.extra.id, {'is_default': True})
        self.extra.refresh_from_db()
        self.default.refresh_from_db()
        # default has been demoted to is_default=False but still active.
        # Deactivate it.
        r1 = self._patch(self.default.id, {'is_active': False})
        self.assertEqual(r1.status_code, status.HTTP_200_OK)
        # Now try to deactivate the new default 'extra' — only active left.
        r2 = self._patch(self.extra.id, {'is_active': False})
        self.assertEqual(r2.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('is_active', r2.data)

    def test_can_deactivate_non_default_when_others_remain_active(self):
        # 'main' is default + active; 'extra' is non-default + active.
        # Deactivating 'extra' is fine.
        response = self._patch(self.extra.id, {'is_active': False})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.extra.refresh_from_db()
        self.assertFalse(self.extra.is_active)

    def test_slug_edit_must_remain_unique_per_tenant(self):
        # Try to rename brooklyn → main (collision with default).
        response = self._patch(self.extra.id, {'slug': 'main'})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('slug', response.data)

    def test_front_desk_cannot_update_location(self):
        fd = _make_user('fd-update@test.local')
        _make_membership(user=fd, tenant=self.tenant, role=TenantMembership.Role.FRONT_DESK)
        response = self._patch(self.extra.id, {'name': 'Hijacked'}, user=fd)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_cross_tenant_update_returns_404(self):
        other_tenant, other_owner = _make_tenant('cross-tenant-update')
        other_location = Location.objects.create(
            tenant=other_tenant, name='Other', slug='other', is_default=False,
        )
        # Authenticated as our tenant's owner, with our tenant's slug,
        # try to PATCH a location owned by a different tenant.
        response = self._patch(other_location.id, {'name': 'Hijacked'})
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        # And nothing changed on the other tenant's row.
        other_location.refresh_from_db()
        self.assertEqual(other_location.name, 'Other')

    def test_update_writes_audit_log_with_default_swap_metadata(self):
        self._patch(self.extra.id, {'is_default': True})
        log = AuditLog.objects.filter(
            resource_type='location',
            action=AuditLog.Action.UPDATE,
            resource_id=str(self.extra.id),
        ).order_by('-id').first()
        self.assertIsNotNone(log)
        self.assertEqual(log.metadata.get('to_is_default'), True)
        self.assertEqual(log.metadata.get('from_is_default'), False)


class LocationsRetrieveTests(TestCase):
    def test_retrieve_writes_audit_read_entry(self):
        tenant, owner = _make_tenant('retrieve-tenant')
        default_loc = tenant.locations.get(is_default=True)
        client = APIClient()
        client.force_login(owner)
        response = client.get(
            reverse('location-detail', args=[default_loc.id]),
            HTTP_X_TENANT_SLUG=tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['slug'], 'main')
        log = AuditLog.objects.filter(
            resource_type='location',
            action=AuditLog.Action.READ,
            resource_id=str(default_loc.id),
        ).first()
        self.assertIsNotNone(log)

    def test_cross_tenant_retrieve_returns_404(self):
        tenant_a, owner_a = _make_tenant('xt-a')
        tenant_b, _ = _make_tenant('xt-b')
        b_default = tenant_b.locations.get(is_default=True)
        client = APIClient()
        client.force_login(owner_a)
        response = client.get(
            reverse('location-detail', args=[b_default.id]),
            HTTP_X_TENANT_SLUG=tenant_a.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class LocationsDeleteTests(TestCase):
    def test_destroy_is_disallowed(self):
        tenant, owner = _make_tenant('no-delete')
        loc = tenant.locations.first()
        client = APIClient()
        client.force_login(owner)
        response = client.delete(
            reverse('location-detail', args=[loc.id]),
            HTTP_X_TENANT_SLUG=tenant.slug,
        )
        # ModelViewSet.http_method_names omits DELETE, so DRF returns 405.
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)


# ── ProviderSchedule API (Phase 1C session 4) ───────────────────────


from apps.tenants.models import MembershipLocation, ProviderSchedule


def _make_schedule_payload(monday_blocks=None, **per_day):
    """Build a valid weekly_hours payload — every weekday key with
    the supplied blocks, defaulting to empty arrays for unset days."""
    payload = {day: [] for day in ProviderSchedule.WEEKDAYS}
    if monday_blocks is not None:
        payload['monday'] = monday_blocks
    payload.update(per_day)
    return payload


class ScheduleReadTests(TestCase):
    """`GET /api/schedules/{membership_location_id}/` returns the
    canonical empty shape when no schedule has been set, and the
    persisted weekly_hours when one exists. Cross-tenant ids 404."""

    def setUp(self):
        self.tenant, self.owner = _make_tenant('sched-read')
        self.fd_user = _make_user('fd-sched@test.local')
        self.membership = _make_membership(
            user=self.fd_user, tenant=self.tenant, role=TenantMembership.Role.PROVIDER,
            is_bookable=True,
        )
        self.assignment = self.membership.location_assignments.first()
        self.client = APIClient()
        self.client.force_login(self.owner)

    def _get(self, ml_id):
        return self.client.get(
            reverse('provider-schedule', args=[ml_id]),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )

    def test_returns_empty_shape_when_no_schedule(self):
        response = self._get(self.assignment.id)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        weekly = response.data['weekly_hours']
        self.assertEqual(set(weekly.keys()), set(ProviderSchedule.WEEKDAYS))
        for day in ProviderSchedule.WEEKDAYS:
            self.assertEqual(weekly[day], [])

    def test_returns_persisted_weekly_hours(self):
        ProviderSchedule.objects.create(
            membership_location=self.assignment,
            weekly_hours=_make_schedule_payload(
                monday_blocks=[{'start': '09:00', 'end': '17:00'}],
            ),
        )
        response = self._get(self.assignment.id)
        self.assertEqual(response.data['weekly_hours']['monday'],
                         [{'start': '09:00', 'end': '17:00'}])

    def test_cross_tenant_404(self):
        other_tenant, _ = _make_tenant('sched-other')
        other_user = _make_user('other-sched@test.local')
        other_membership = _make_membership(
            user=other_user, tenant=other_tenant, role=TenantMembership.Role.PROVIDER,
        )
        other_ml = other_membership.location_assignments.first()
        response = self._get(other_ml.id)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class SchedulePutTests(TestCase):
    """`PUT /api/schedules/{ml_id}/` validates + persists the weekly
    template. Owner+manager only; full-replace; audit-logged."""

    def setUp(self):
        self.tenant, self.owner = _make_tenant('sched-put')
        self.provider_user = _make_user('prov-put@test.local')
        self.membership = _make_membership(
            user=self.provider_user, tenant=self.tenant,
            role=TenantMembership.Role.PROVIDER, is_bookable=True,
        )
        self.assignment = self.membership.location_assignments.first()
        self.client = APIClient()
        self.client.force_login(self.owner)

    def _put(self, body):
        return self.client.put(
            reverse('provider-schedule', args=[self.assignment.id]),
            data=body, format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )

    def test_creates_schedule_on_first_put(self):
        body = {'weekly_hours': _make_schedule_payload(
            monday_blocks=[{'start': '09:00', 'end': '17:00'}],
            tuesday=[{'start': '09:00', 'end': '17:00'}],
        )}
        response = self._put(body)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(
            ProviderSchedule.objects.filter(membership_location=self.assignment).exists(),
        )
        schedule = ProviderSchedule.objects.get(membership_location=self.assignment)
        self.assertEqual(schedule.weekly_hours['monday'],
                         [{'start': '09:00', 'end': '17:00'}])

    def test_overwrites_existing_schedule(self):
        ProviderSchedule.objects.create(
            membership_location=self.assignment,
            weekly_hours=_make_schedule_payload(
                monday_blocks=[{'start': '09:00', 'end': '17:00'}],
            ),
        )
        new_body = {'weekly_hours': _make_schedule_payload(
            monday_blocks=[],  # Mon now off
            wednesday=[{'start': '12:00', 'end': '20:00'}],
        )}
        response = self._put(new_body)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        schedule = ProviderSchedule.objects.get(membership_location=self.assignment)
        self.assertEqual(schedule.weekly_hours['monday'], [])
        self.assertEqual(schedule.weekly_hours['wednesday'],
                         [{'start': '12:00', 'end': '20:00'}])

    def test_supports_split_shifts(self):
        body = {'weekly_hours': _make_schedule_payload(
            monday_blocks=[
                {'start': '09:00', 'end': '13:00'},
                {'start': '14:00', 'end': '18:00'},
            ],
        )}
        response = self._put(body)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data['weekly_hours']['monday'],
            [
                {'start': '09:00', 'end': '13:00'},
                {'start': '14:00', 'end': '18:00'},
            ],
        )

    def test_rejects_overlapping_blocks(self):
        body = {'weekly_hours': _make_schedule_payload(
            monday_blocks=[
                {'start': '09:00', 'end': '12:00'},
                {'start': '11:00', 'end': '14:00'},  # overlap
            ],
        )}
        response = self._put(body)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('monday', str(response.data).lower())

    def test_rejects_end_before_start(self):
        body = {'weekly_hours': _make_schedule_payload(
            monday_blocks=[{'start': '17:00', 'end': '09:00'}],
        )}
        response = self._put(body)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('monday', str(response.data).lower())

    def test_rejects_unknown_weekday_key(self):
        body = {'weekly_hours': {**ProviderSchedule.empty_weekly_hours(), 'tueday': []}}
        response = self._put(body)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('tueday', str(response.data).lower())

    def test_rejects_invalid_hhmm(self):
        body = {'weekly_hours': _make_schedule_payload(
            monday_blocks=[{'start': '9am', 'end': '5pm'}],
        )}
        response = self._put(body)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_front_desk_cannot_edit_schedule(self):
        fd_user = _make_user('fd-cant@test.local')
        _make_membership(
            user=fd_user, tenant=self.tenant, role=TenantMembership.Role.FRONT_DESK,
        )
        client = APIClient()
        client.force_login(fd_user)
        response = client.put(
            reverse('provider-schedule', args=[self.assignment.id]),
            data={'weekly_hours': ProviderSchedule.empty_weekly_hours()},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_put_writes_audit_entry(self):
        body = {'weekly_hours': _make_schedule_payload(
            monday_blocks=[{'start': '09:00', 'end': '17:00'}],
        )}
        self._put(body)
        log = AuditLog.objects.filter(
            resource_type='schedule', resource_id=str(self.assignment.id),
        ).order_by('-id').first()
        self.assertIsNotNone(log)
        self.assertEqual(log.metadata.get('days_with_hours'), ['monday'])


class BookableMembershipScheduleEmbedTests(TestCase):
    """When `?location=current` is set, the bookable-memberships
    response embeds `membership_location_id` and `schedule_for_location`
    so the calendar can render the dimmed overlay in one round-trip."""

    def setUp(self):
        self.tenant, self.owner = _make_tenant('bm-embed')
        self.assignment = self.owner.memberships.get(tenant=self.tenant).location_assignments.first()
        self.provider_user = _make_user('provider-embed@test.local')
        self.provider = _make_membership(
            user=self.provider_user, tenant=self.tenant,
            role=TenantMembership.Role.PROVIDER, is_bookable=True,
        )
        self.provider_assignment = self.provider.location_assignments.first()
        self.client = APIClient()
        self.client.force_login(self.owner)

    def _list_with_location(self, location_param='current'):
        return self.client.get(
            f"{reverse('membership-list')}?bookable=true&active=true&location={location_param}",
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )

    def test_embeds_membership_location_id(self):
        response = self._list_with_location()
        provider_row = next(r for r in response.data if r['id'] == self.provider.id)
        self.assertEqual(provider_row['membership_location_id'], self.provider_assignment.id)

    def test_schedule_is_null_when_no_schedule_set(self):
        response = self._list_with_location()
        provider_row = next(r for r in response.data if r['id'] == self.provider.id)
        self.assertIsNone(provider_row['schedule_for_location'])

    def test_schedule_returns_weekly_hours_when_set(self):
        ProviderSchedule.objects.create(
            membership_location=self.provider_assignment,
            weekly_hours=_make_schedule_payload(
                monday_blocks=[{'start': '09:00', 'end': '17:00'}],
            ),
        )
        response = self._list_with_location()
        provider_row = next(r for r in response.data if r['id'] == self.provider.id)
        self.assertIsNotNone(provider_row['schedule_for_location'])
        self.assertEqual(
            provider_row['schedule_for_location']['monday'],
            [{'start': '09:00', 'end': '17:00'}],
        )

    def test_org_wide_request_omits_location_scoped_fields(self):
        # Without `?location=`, the response has no schedule fields —
        # the staff list shouldn't pay for that data.
        response = self.client.get(
            reverse('membership-list'),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        for row in response.data:
            self.assertIsNone(row.get('membership_location_id'))
            self.assertIsNone(row.get('schedule_for_location'))


# ── Invitation flow ──────────────────────────────────────────────────


class StaffInvitationTests(TestCase):
    """Covers ADR 0019 — email invite-and-accept flow that replaces
    the temp-password reveal."""

    def setUp(self):
        from django.core import mail
        mail.outbox = []

        self.tenant, self.owner = _make_tenant('invite-tenant')
        self.manager_user = _make_user('mgr@test.local', first_name='Mac', last_name='Manager')
        self.manager_membership = TenantMembership.objects.create(
            user=self.manager_user, tenant=self.tenant,
            role=TenantMembership.Role.MANAGER, is_active=True,
        )
        self.fd_user = _make_user('fd@test.local', first_name='Front', last_name='Desk')
        self.fd_membership = TenantMembership.objects.create(
            user=self.fd_user, tenant=self.tenant,
            role=TenantMembership.Role.FRONT_DESK, is_active=True,
        )

        self.client = APIClient()
        self.client.force_login(self.owner)

    def _invite_url(self) -> str:
        return reverse('membership-invite')

    def test_owner_can_invite(self):
        from django.core import mail
        response = self.client.post(
            self._invite_url(),
            data={
                'email': 'new-hire@example.test',
                'role': 'provider',
                'is_bookable': True,
            },
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data['email'], 'new-hire@example.test')
        self.assertEqual(response.data['role'], 'provider')
        self.assertTrue(response.data['is_pending'])
        self.assertEqual(len(mail.outbox), 1)
        sent = mail.outbox[0]
        self.assertEqual(sent.to, ['new-hire@example.test'])
        self.assertIn(self.tenant.name, sent.subject)
        from apps.tenants.models import Invitation
        invitation = Invitation.objects.get(email='new-hire@example.test')
        self.assertIn(invitation.token, sent.body)

    def test_invite_link_targets_tenant_crm_subdomain(self):
        """The accept link must resolve to the tenant's CRM subdomain,
        not the bare apex — the apex serves the marketing site and
        404s on /accept-invitation (the bug reported from the field)."""
        from django.core import mail
        from apps.tenants.models import Invitation

        with self.settings(PUBLIC_BASE_URL='https://lumecrm.test'):
            mail.outbox = []
            response = self.client.post(
                self._invite_url(),
                data={'email': 'subdomain-hire@example.test', 'role': 'provider'},
                format='json',
                HTTP_X_TENANT_SLUG=self.tenant.slug,
            )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        invitation = Invitation.objects.get(email='subdomain-hire@example.test')
        sent = mail.outbox[0]
        expected = (
            f'https://{self.tenant.slug}.lumecrm.test'
            f'/accept-invitation/{invitation.token}'
        )
        self.assertIn(expected, sent.body)
        # Must NOT be the bare apex — that lands on the marketing 404.
        self.assertNotIn('https://lumecrm.test/accept-invitation/', sent.body)

    def test_manager_can_invite(self):
        c = APIClient()
        c.force_login(self.manager_user)
        response = c.post(
            self._invite_url(),
            data={'email': 'mgr-hire@example.test', 'role': 'front_desk'},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)

    def test_front_desk_cannot_invite(self):
        c = APIClient()
        c.force_login(self.fd_user)
        response = c.post(
            self._invite_url(),
            data={'email': 'sneak@example.test', 'role': 'front_desk'},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_cannot_invite_existing_member(self):
        response = self.client.post(
            self._invite_url(),
            data={'email': self.manager_user.email, 'role': 'provider'},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('already a member', response.data['detail'])

    def test_duplicate_pending_invitation_rejected(self):
        from django.core import mail
        first = self.client.post(
            self._invite_url(),
            data={'email': 'dup@example.test', 'role': 'provider'},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        mail.outbox = []
        second = self.client.post(
            self._invite_url(),
            data={'email': 'dup@example.test', 'role': 'provider'},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(second.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('pending invitation', second.data['detail'])
        self.assertEqual(len(mail.outbox), 0)

    def test_lookup_returns_tenant_and_role(self):
        from apps.tenants.models import Invitation
        self.client.post(
            self._invite_url(),
            data={'email': 'lookup@example.test', 'role': 'provider', 'is_bookable': True},
            format='json', HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        invitation = Invitation.objects.get(email='lookup@example.test')
        anon = APIClient()
        response = anon.get(
            reverse('auth-invitation-lookup', kwargs={'token': invitation.token}),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['tenant_name'], self.tenant.name)
        self.assertEqual(response.data['role'], 'provider')
        self.assertTrue(response.data['is_pending'])
        # Recipient email is intentionally NOT exposed in the lookup.
        self.assertNotIn('email', response.data)

    def test_lookup_unknown_token_returns_404(self):
        anon = APIClient()
        response = anon.get(
            reverse('auth-invitation-lookup', kwargs={'token': 'not-a-real-token'}),
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_accept_creates_user_and_membership(self):
        from apps.tenants.models import Invitation
        self.client.post(
            self._invite_url(),
            data={'email': 'accept@example.test', 'role': 'provider', 'is_bookable': True},
            format='json', HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        invitation = Invitation.objects.get(email='accept@example.test')
        anon = APIClient()
        response = anon.post(
            reverse('auth-invitation-accept'),
            data={
                'token': invitation.token,
                'password': 'a-strong-password-123',
                'first_name': 'New',
                'last_name': 'Hire',
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['tenant_slug'], self.tenant.slug)
        self.assertEqual(response.data['redirect'], '/dashboard')
        new_user = User.objects.get(email='accept@example.test')
        self.assertEqual(new_user.first_name, 'New')
        self.assertEqual(new_user.last_name, 'Hire')
        self.assertTrue(new_user.check_password('a-strong-password-123'))
        membership = TenantMembership.objects.get(user=new_user, tenant=self.tenant)
        self.assertEqual(membership.role, 'provider')
        self.assertTrue(membership.is_bookable)
        self.assertTrue(membership.is_active)
        invitation.refresh_from_db()
        self.assertIsNotNone(invitation.accepted_at)
        self.assertEqual(invitation.accepted_by_user_id, new_user.id)

    def test_accept_rejects_short_password(self):
        from apps.tenants.models import Invitation
        self.client.post(
            self._invite_url(),
            data={'email': 'shortpw@example.test', 'role': 'provider'},
            format='json', HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        invitation = Invitation.objects.get(email='shortpw@example.test')
        anon = APIClient()
        response = anon.post(
            reverse('auth-invitation-accept'),
            data={
                'token': invitation.token,
                'password': 'short',
                'first_name': 'Short', 'last_name': 'PW',
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_accept_rejects_existing_email(self):
        User.objects.create_user(
            email='already-here@example.test',
            password='their-real-password',
            first_name='Existing', last_name='User',
        )
        from apps.tenants.models import Invitation
        self.client.post(
            self._invite_url(),
            data={'email': 'already-here@example.test', 'role': 'provider'},
            format='json', HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        invitation = Invitation.objects.get(email='already-here@example.test')
        anon = APIClient()
        response = anon.post(
            reverse('auth-invitation-accept'),
            data={
                'token': invitation.token,
                'password': 'new-attempted-password-xyz',
                'first_name': 'Hacker', 'last_name': 'Attempt',
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('already exists', response.data['detail'].lower())
        existing = User.objects.get(email='already-here@example.test')
        self.assertTrue(existing.check_password('their-real-password'))

    def test_accept_idempotent_rejects_replay(self):
        from apps.tenants.models import Invitation
        self.client.post(
            self._invite_url(),
            data={'email': 'replay@example.test', 'role': 'provider'},
            format='json', HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        invitation = Invitation.objects.get(email='replay@example.test')
        anon = APIClient()
        first = anon.post(
            reverse('auth-invitation-accept'),
            data={
                'token': invitation.token,
                'password': 'a-strong-password-123',
                'first_name': 'R', 'last_name': 'P',
            },
            format='json',
        )
        self.assertEqual(first.status_code, status.HTTP_200_OK)
        replay = anon.post(
            reverse('auth-invitation-accept'),
            data={
                'token': invitation.token,
                'password': 'second-strong-password-456',
                'first_name': 'R2', 'last_name': 'P2',
            },
            format='json',
        )
        self.assertEqual(replay.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('already been accepted', replay.data['detail'])

    def test_accept_rejects_expired_token(self):
        from datetime import timedelta
        from django.utils import timezone as djtz

        from apps.tenants.models import Invitation
        self.client.post(
            self._invite_url(),
            data={'email': 'expired@example.test', 'role': 'provider'},
            format='json', HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        invitation = Invitation.objects.get(email='expired@example.test')
        invitation.expires_at = djtz.now() - timedelta(seconds=1)
        invitation.save(update_fields=['expires_at'])
        anon = APIClient()
        response = anon.post(
            reverse('auth-invitation-accept'),
            data={
                'token': invitation.token,
                'password': 'a-strong-password-123',
                'first_name': 'X', 'last_name': 'P',
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('expired', response.data['detail'].lower())


# ── TenantMiddleware Origin/Referer fallback ────────────────────────


from django.test import override_settings as _override_settings


@_override_settings(ALLOWED_HOSTS=['*'])
class TenantMiddlewareOriginFallbackTests(TestCase):
    """The middleware resolves tenant from `request.get_host()` first,
    then `X-Tenant-Slug` header, then `Origin` / `Referer` headers.

    The Origin/Referer paths exist because the customer-portal
    frontend lives at `<tenant>.<domain>` but its API calls hit
    `api.<domain>` where neither the subdomain (it's `api`) nor a
    cookie-driven `X-Tenant-Slug` is available for anonymous users.
    The browser always sets `Origin` on a cross-origin fetch, so we
    use it as a routing signal — authorization is enforced elsewhere
    (magic-link token / session cookie binds to a specific tenant).
    """

    @classmethod
    def setUpTestData(cls):
        owner = get_user_model().objects.create_user(
            email='origin-owner@test.local', password='pw',
        )
        cls.tenant = create_tenant_with_defaults(
            name='Origin Spa', slug='origin-spa',
            owner_user=owner, status=Tenant.Status.ACTIVE,
        )

    def _drive_middleware(self, **request_kwargs):
        from django.test import RequestFactory
        from apps.tenants.middleware import TenantMiddleware

        rf = RequestFactory()
        request = rf.get('/api/portal/me/', **request_kwargs)
        # Anonymous user — portal request before login.
        from django.contrib.auth.models import AnonymousUser
        request.user = AnonymousUser()

        captured: dict = {}

        def fake_view(req):
            captured['tenant'] = req.tenant
            from django.http import HttpResponse
            return HttpResponse('ok')

        TenantMiddleware(fake_view)(request)
        return captured

    def test_origin_header_resolves_to_tenant_from_subdomain(self):
        # No tenant in the request host (it's `api.lume.test` in this
        # call); Origin carries `https://origin-spa.lume.test`.
        result = self._drive_middleware(
            HTTP_HOST='api.lume.test',
            HTTP_ORIGIN='https://origin-spa.lume.test',
        )
        self.assertEqual(result['tenant'], self.tenant)

    def test_referer_falls_through_when_origin_missing(self):
        result = self._drive_middleware(
            HTTP_HOST='api.lume.test',
            HTTP_REFERER='https://origin-spa.lume.test/portal/login',
        )
        self.assertEqual(result['tenant'], self.tenant)

    def test_origin_with_unknown_subdomain_returns_none(self):
        result = self._drive_middleware(
            HTTP_HOST='api.lume.test',
            HTTP_ORIGIN='https://no-such-spa.lume.test',
        )
        self.assertIsNone(result['tenant'])

    def test_origin_with_reserved_subdomain_returns_none(self):
        # `api.lume.test` as the Origin shouldn't resolve to a tenant.
        result = self._drive_middleware(
            HTTP_HOST='api.lume.test',
            HTTP_ORIGIN='https://api.lume.test',
        )
        self.assertIsNone(result['tenant'])

    def test_request_host_subdomain_still_wins_over_origin(self):
        # When the request itself arrives on a tenant subdomain, that
        # wins. Origin is only consulted as a fallback.
        other_owner = get_user_model().objects.create_user(
            email='origin-other-owner@test.local', password='pw',
        )
        other_tenant = create_tenant_with_defaults(
            name='Other', slug='origin-other',
            owner_user=other_owner, status=Tenant.Status.ACTIVE,
        )
        result = self._drive_middleware(
            HTTP_HOST='origin-spa.lume.test',
            HTTP_ORIGIN='https://origin-other.lume.test',
        )
        # Host subdomain (origin-spa) wins, not Origin (origin-other).
        self.assertEqual(result['tenant'], self.tenant)
        self.assertNotEqual(result['tenant'], other_tenant)

    def test_x_tenant_slug_header_still_wins_over_origin(self):
        # Header explicit-override takes precedence over Origin sniffing.
        other_owner = get_user_model().objects.create_user(
            email='origin-hdr-owner@test.local', password='pw',
        )
        other_tenant = create_tenant_with_defaults(
            name='Header-Override', slug='origin-hdr',
            owner_user=other_owner, status=Tenant.Status.ACTIVE,
        )
        result = self._drive_middleware(
            HTTP_HOST='api.lume.test',
            HTTP_X_TENANT_SLUG='origin-hdr',
            HTTP_ORIGIN='https://origin-spa.lume.test',
        )
        self.assertEqual(result['tenant'], other_tenant)

    def test_malformed_origin_falls_through_safely(self):
        result = self._drive_middleware(
            HTTP_HOST='api.lume.test',
            HTTP_ORIGIN='not-a-real-url',
        )
        self.assertIsNone(result['tenant'])


# ── Cross-tenant isolation enforcement (security regression) ───────


@_override_settings(ALLOWED_HOSTS=['*'])
class CrossTenantSessionTerminationTests(TestCase):
    """Bug discovered 2026-05-16: a staff user signed into tenant A
    could navigate to tenant B's subdomain and silently carry their
    session over (the session cookie is scoped to `.<domain>` so it
    rides every subdomain). `TenantMiddleware` now force-logs-out
    staff sessions that land on a tenant the user has no active
    membership for. Platform admins are intentionally exempt — they
    need cross-tenant reach for support.
    """

    @classmethod
    def setUpTestData(cls):
        cls.tenant_a, cls.owner_a = _make_tenant_pair('iso-a')
        cls.tenant_b, cls.owner_b = _make_tenant_pair('iso-b')

    def _drive(self, *, user, host):
        from django.test import RequestFactory
        from apps.tenants.middleware import TenantMiddleware

        rf = RequestFactory()
        request = rf.get('/api/auth/me/', HTTP_HOST=host)
        request.user = user

        # Stand-in for a real session so logout() has something to flush.
        # SessionMiddleware would populate this in a real request; we
        # fake it minimally so django.contrib.auth.logout doesn't crash.
        from django.contrib.sessions.backends.db import SessionStore
        request.session = SessionStore()

        captured: dict = {}

        def fake_view(req):
            captured['user_is_authenticated'] = req.user.is_authenticated
            captured['membership'] = req.tenant_membership
            captured['tenant'] = req.tenant
            from django.http import HttpResponse
            return HttpResponse('ok')

        TenantMiddleware(fake_view)(request)
        return captured

    def test_staff_on_their_own_tenant_passes_through(self):
        result = self._drive(user=self.owner_a, host='iso-a.lume.test')
        self.assertTrue(result['user_is_authenticated'])
        self.assertIsNotNone(result['membership'])
        self.assertEqual(result['tenant'], self.tenant_a)

    def test_staff_on_foreign_tenant_session_force_terminated(self):
        # Owner of A hits tenant B's subdomain. Middleware MUST nuke
        # the session so downstream views see an anonymous user.
        result = self._drive(user=self.owner_a, host='iso-b.lume.test')
        self.assertFalse(result['user_is_authenticated'])
        self.assertIsNone(result['membership'])
        self.assertEqual(result['tenant'], self.tenant_b)

    def test_platform_admin_can_cross_tenants(self):
        # Platform admins keep their session — used for support hops.
        admin = get_user_model().objects.create_user(
            email='iso-admin@test.local', password='pw',
            is_platform_admin=True,
        )
        result = self._drive(user=admin, host='iso-b.lume.test')
        self.assertTrue(result['user_is_authenticated'])
        # No membership for admin on B — but the session stays alive.
        self.assertIsNone(result['membership'])

    def test_superuser_can_cross_tenants(self):
        admin = get_user_model().objects.create_user(
            email='iso-su@test.local', password='pw',
            is_superuser=True, is_staff=True,
        )
        result = self._drive(user=admin, host='iso-b.lume.test')
        self.assertTrue(result['user_is_authenticated'])

    def test_anonymous_request_on_foreign_tenant_unaffected(self):
        # Anonymous requests don't trigger the kill-step — there's no
        # session to revoke. The middleware just sets tenant/membership.
        from django.contrib.auth.models import AnonymousUser
        result = self._drive(user=AnonymousUser(), host='iso-b.lume.test')
        self.assertFalse(result['user_is_authenticated'])
        self.assertEqual(result['tenant'], self.tenant_b)

    def test_no_tenant_resolved_does_not_logout(self):
        # On a bare/unknown host where tenant is None there's no
        # tenant boundary to enforce — leave the session alone.
        result = self._drive(user=self.owner_a, host='unknown.lume.test')
        self.assertTrue(result['user_is_authenticated'])
        self.assertIsNone(result['tenant'])


def _make_tenant_pair(slug):
    owner = get_user_model().objects.create_user(
        email=f'{slug}-owner@test.local', password='pw',
    )
    tenant = create_tenant_with_defaults(
        name=slug, slug=slug, owner_user=owner,
        status=Tenant.Status.ACTIVE,
    )
    return tenant, owner


class ContractorSelfScheduleTests(TestCase):
    """Contractors can edit their OWN ProviderSchedule; everyone else's
    schedule editing stays manager-gated. `GET /api/schedules/mine/` is
    self-scoped so a contractor can load their own availability."""

    def setUp(self):
        self.tenant, self.owner = _make_tenant('contractor-sched')
        self.contractor_user = _make_user('contractor@test.local')
        self.contractor = _make_membership(
            user=self.contractor_user, tenant=self.tenant,
            role=TenantMembership.Role.PROVIDER, is_bookable=True,
            employment_type=TenantMembership.EmploymentType.CONTRACTOR,
        )
        self.contractor_ml = self.contractor.location_assignments.first()

        self.staff_user = _make_user('fulltime@test.local')
        self.staff = _make_membership(
            user=self.staff_user, tenant=self.tenant,
            role=TenantMembership.Role.PROVIDER, is_bookable=True,
            employment_type=TenantMembership.EmploymentType.FULL_TIME,
        )
        self.staff_ml = self.staff.location_assignments.first()

    def _put(self, user, ml_id, weekly):
        client = APIClient()
        client.force_login(user)
        return client.put(
            reverse('provider-schedule', args=[ml_id]),
            data={'weekly_hours': weekly}, format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )

    def test_contractor_can_edit_own_schedule(self):
        resp = self._put(
            self.contractor_user, self.contractor_ml.id,
            _make_schedule_payload(monday_blocks=[{'start': '10:00', 'end': '15:00'}]),
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        self.assertEqual(
            resp.data['weekly_hours']['monday'],
            [{'start': '10:00', 'end': '15:00'}],
        )

    def test_contractor_cannot_edit_another_persons_schedule(self):
        resp = self._put(
            self.contractor_user, self.staff_ml.id,
            _make_schedule_payload(monday_blocks=[{'start': '10:00', 'end': '15:00'}]),
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_full_time_staff_cannot_self_edit_schedule(self):
        # A non-contractor's schedule stays manager-managed.
        resp = self._put(self.staff_user, self.staff_ml.id, _make_schedule_payload())
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_owner_can_still_edit_anyones_schedule(self):
        resp = self._put(
            self.owner, self.contractor_ml.id,
            _make_schedule_payload(monday_blocks=[{'start': '09:00', 'end': '12:00'}]),
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)

    def test_mine_endpoint_lists_own_schedule_for_contractor(self):
        client = APIClient()
        client.force_login(self.contractor_user)
        resp = client.get(
            reverse('my-schedules'), HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(resp.data['can_edit'])
        ml_ids = {loc['membership_location_id'] for loc in resp.data['locations']}
        self.assertIn(self.contractor_ml.id, ml_ids)

    def test_mine_endpoint_can_edit_false_for_non_contractor(self):
        client = APIClient()
        client.force_login(self.staff_user)
        resp = client.get(
            reverse('my-schedules'), HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertFalse(resp.data['can_edit'])
