"""Tests for the customers API.

Focused on the Phase 1A.1 hardening: PHI redaction. A user with
`VIEW_CLIENT_LIST` (e.g. front desk) can retrieve a customer record
but must NOT see PHI fields — DOB, address, emergency contact,
medical history, allergies, medications, Fitzpatrick, free-text
notes. Only `VIEW_CLIENT_PHI` (provider / manager / owner) lifts the
redaction. The write path enforces the same gate so a front-desk
user can't blind-write a medical field they can't read.

See [ADR 0017 — PHI field redaction](docs/decisions/0017-phi-redaction.md).
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.customers.models import Customer
from apps.customers.serializers import PHI_FIELDS
from apps.tenants.models import (
    JobTitle,
    MembershipLocation,
    Tenant,
    TenantMembership,
)
from apps.tenants.services import create_tenant_with_defaults

User = get_user_model()


# ── Fixtures ─────────────────────────────────────────────────────────


def _make_user(email: str, **kwargs):
    return User.objects.create_user(email=email, password='test-pw', **kwargs)


def _make_tenant(slug: str) -> tuple[Tenant, User]:
    owner = _make_user(f'{slug}-owner@test.local')
    tenant = create_tenant_with_defaults(
        name=slug.title(), slug=slug, owner_user=owner,
        status=Tenant.Status.ACTIVE,
    )
    return tenant, owner


def _membership(tenant: Tenant, role: str, slug_suffix: str) -> tuple[User, TenantMembership]:
    user = _make_user(f'{slug_suffix}-{tenant.slug}@test.local')
    job_title = None
    if role == TenantMembership.Role.PROVIDER:
        job_title, _ = JobTitle.objects.get_or_create(
            tenant=tenant, name='Nurse Practitioner',
            defaults={'is_clinical': True},
        )
    membership = TenantMembership.objects.create(
        user=user, tenant=tenant, role=role,
        job_title=job_title, is_active=True,
    )
    MembershipLocation.objects.create(
        membership=membership,
        location=tenant.locations.get(is_default=True),
        is_active=True,
    )
    return user, membership


def _make_customer(tenant: Tenant) -> Customer:
    return Customer.objects.create(
        tenant=tenant,
        first_name='Pat', last_name='Patient',
        email=f'pat-{tenant.slug}@test.local',
        phone='555-0101',
        date_of_birth='1990-04-15',
        address_line1='123 Main St',
        city='Austin', state='TX', zip_code='78701',
        emergency_name='Sam Spouse', emergency_phone='555-0102',
        medical_history='Hypertension, controlled.',
        allergies='Penicillin',
        medications='Lisinopril 10mg daily',
        skin_type_fitzpatrick=3,
        notes='Prefers morning appointments.',
    )


def _client(user) -> APIClient:
    c = APIClient()
    c.force_login(user)
    return c


# ── Tests ────────────────────────────────────────────────────────────


class CustomerPHIRedactionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant, cls.owner = _make_tenant('phi-red')
        cls.provider_user, _ = _membership(cls.tenant, TenantMembership.Role.PROVIDER, 'prov')
        cls.fd_user, _ = _membership(cls.tenant, TenantMembership.Role.FRONT_DESK, 'fd')
        cls.mkt_user, _ = _membership(cls.tenant, TenantMembership.Role.MARKETING, 'mkt')
        cls.customer = _make_customer(cls.tenant)
        cls.url = reverse('customer-detail', kwargs={'pk': cls.customer.pk})
        cls.headers = {'HTTP_X_TENANT_SLUG': cls.tenant.slug}

    # ── Read path ────────────────────────────────────────────────

    def test_owner_sees_all_phi(self):
        response = _client(self.owner).get(self.url, **self.headers)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        for f in PHI_FIELDS:
            self.assertIn(f, response.data, f'Owner should see {f}')

    def test_provider_sees_all_phi(self):
        response = _client(self.provider_user).get(self.url, **self.headers)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        for f in PHI_FIELDS:
            self.assertIn(f, response.data, f'Provider should see {f}')

    def test_front_desk_phi_redacted(self):
        response = _client(self.fd_user).get(self.url, **self.headers)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        for f in PHI_FIELDS:
            self.assertNotIn(f, response.data, f'Front desk should NOT see {f}')
        # Non-PHI contact + identity fields stay visible — front desk
        # still needs to call/email customers about their bookings.
        self.assertEqual(response.data['first_name'], 'Pat')
        self.assertEqual(response.data['email'], f'pat-{self.tenant.slug}@test.local')
        self.assertEqual(response.data['phone'], '555-0101')

    def test_marketing_phi_redacted(self):
        # Marketing role has VIEW_CLIENT_LIST but not VIEW_CLIENT_PHI.
        response = _client(self.mkt_user).get(self.url, **self.headers)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        for f in PHI_FIELDS:
            self.assertNotIn(f, response.data)

    # ── Write path (defense in depth) ────────────────────────────

    def test_front_desk_can_edit_non_phi(self):
        response = _client(self.fd_user).patch(
            self.url, data={'phone': '555-9999'}, format='json', **self.headers,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.phone, '555-9999')

    def test_front_desk_cannot_write_phi_fields(self):
        original = self.customer.medical_history
        response = _client(self.fd_user).patch(
            self.url,
            data={'medical_history': 'Tampering attempt.'},
            format='json', **self.headers,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('medical_history', response.data)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.medical_history, original)

    def test_front_desk_mixed_patch_rejects_atomically(self):
        # If even one PHI field is in the payload, the whole request is
        # rejected — no partial writes. Atomic rejection is the only way
        # to keep the read/write gate from leaking across patch shapes.
        original_phone = self.customer.phone
        response = _client(self.fd_user).patch(
            self.url,
            data={'phone': '555-7777', 'allergies': 'Should not write'},
            format='json', **self.headers,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('allergies', response.data)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.phone, original_phone)

    def test_owner_can_write_phi_fields(self):
        response = _client(self.owner).patch(
            self.url,
            data={'medical_history': 'Updated by owner.'},
            format='json', **self.headers,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.medical_history, 'Updated by owner.')
