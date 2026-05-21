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


# ── Social-guest visibility ─────────────────────────────────────────


class SocialGuestListFilterTests(TestCase):
    """Auto-created IG-DM Customer rows (is_social_guest=True) must NOT
    appear in the /api/customers/ list endpoint. Without this filter,
    every inbound DM from an unknown sender pollutes the operator's
    client list with "Instagram visitor 947238"-style placeholders
    that have no email/phone/legal-name and aren't real clients yet.

    Detail + custom actions still resolve social-guest rows so the
    social-merge flow keeps working.
    """

    @classmethod
    def setUpTestData(cls):
        cls.tenant, cls.owner = _make_tenant('soclist')
        cls.real_client = Customer.objects.create(
            tenant=cls.tenant,
            first_name='Maria', last_name='Real',
            email='maria@example.com',
            phone='555-1111',
        )
        cls.social_guest = Customer.objects.create(
            tenant=cls.tenant,
            first_name='Instagram visitor 123456',
            last_name='',
            is_social_guest=True,
            acquisition_source=Customer.AcquisitionSource.INSTAGRAM,
            external_source='instagram',
            external_id='ig-psid-123456',
        )

    def setUp(self):
        self.headers = {'HTTP_X_TENANT_SLUG': self.tenant.slug}
        self.url = reverse('customer-list')

    def test_list_hides_social_guests_by_default(self):
        response = _client(self.owner).get(self.url, **self.headers)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        rows = response.data.get('results', response.data) if isinstance(response.data, dict) else response.data
        ids = {row['id'] for row in rows}
        self.assertIn(self.real_client.id, ids)
        self.assertNotIn(
            self.social_guest.id, ids,
            'Social-guest rows must not appear in the operator client list',
        )

    def test_list_search_does_not_surface_social_guests(self):
        """Even when the query happens to match a social guest's
        placeholder name, they stay hidden."""
        response = _client(self.owner).get(
            self.url, {'q': 'Instagram'}, **self.headers,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        rows = response.data.get('results', response.data) if isinstance(response.data, dict) else response.data
        ids = {row['id'] for row in rows}
        self.assertNotIn(self.social_guest.id, ids)

    def test_list_can_opt_in_with_query_param(self):
        """Future operator tooling can request the unfiltered list."""
        response = _client(self.owner).get(
            self.url, {'include_social_guests': '1'}, **self.headers,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        rows = response.data.get('results', response.data) if isinstance(response.data, dict) else response.data
        ids = {row['id'] for row in rows}
        self.assertIn(self.social_guest.id, ids)

    def test_detail_endpoint_still_resolves_social_guest(self):
        """The merge banner on /clients/<social-guest-id> needs the
        detail view to keep working for social guests."""
        url = reverse('customer-detail', args=[self.social_guest.id])
        response = _client(self.owner).get(url, **self.headers)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['id'], self.social_guest.id)
        self.assertTrue(response.data['is_social_guest'])


class CustomerReferralTests(TestCase):
    """Phase 1A.2 — referral capture layer: the `referred_by` link, the
    `referred_by_code` intake input, the `referred_customers` reverse
    list, and the resolve-referral lookup endpoint."""

    @classmethod
    def setUpTestData(cls):
        cls.tenant, cls.owner = _make_tenant('ref-cap')
        cls.other_tenant, cls.other_owner = _make_tenant('ref-other')
        # An established client whose code new clients can use.
        cls.referrer = Customer.objects.create(
            tenant=cls.tenant, first_name='Rita', last_name='Referrer',
            email='rita@test.local',
        )
        cls.headers = {'HTTP_X_TENANT_SLUG': cls.tenant.slug}
        cls.list_url = reverse('customer-list')
        cls.resolve_url = reverse('customer-resolve-referral')

    def test_create_with_valid_code_links_referrer(self):
        resp = _client(self.owner).post(
            self.list_url,
            {'first_name': 'New', 'last_name': 'Client',
             'referred_by_code': self.referrer.referral_code},
            format='json', **self.headers,
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data['referred_by']['id'], self.referrer.id)
        created = Customer.objects.get(pk=resp.data['id'])
        self.assertEqual(created.referred_by_id, self.referrer.id)

    def test_create_with_lowercase_code_resolves(self):
        """Codes are stored uppercase; intake input is case-insensitive."""
        resp = _client(self.owner).post(
            self.list_url,
            {'first_name': 'Lower', 'last_name': 'Case',
             'referred_by_code': self.referrer.referral_code.lower()},
            format='json', **self.headers,
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data['referred_by']['id'], self.referrer.id)

    def test_unknown_code_is_rejected(self):
        resp = _client(self.owner).post(
            self.list_url,
            {'first_name': 'No', 'last_name': 'Match',
             'referred_by_code': 'ZZZZ9999'},
            format='json', **self.headers,
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('referred_by_code', resp.data)

    def test_blank_code_creates_without_referrer(self):
        resp = _client(self.owner).post(
            self.list_url,
            {'first_name': 'Solo', 'last_name': 'Client',
             'referred_by_code': ''},
            format='json', **self.headers,
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertIsNone(resp.data['referred_by'])

    def test_code_from_another_tenant_does_not_resolve(self):
        """Tenant isolation — a real code from another spa is 'not found'."""
        foreign = Customer.objects.create(
            tenant=self.other_tenant, first_name='Foreign', last_name='Client',
            email='foreign@test.local',
        )
        resp = _client(self.owner).post(
            self.list_url,
            {'first_name': 'Cross', 'last_name': 'Tenant',
             'referred_by_code': foreign.referral_code},
            format='json', **self.headers,
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_detail_includes_referred_customers(self):
        """A referred client appears in the referrer's reverse list."""
        Customer.objects.create(
            tenant=self.tenant, first_name='Brought', last_name='In',
            email='brought@test.local', referred_by=self.referrer,
        )
        resp = _client(self.owner).get(
            reverse('customer-detail', kwargs={'pk': self.referrer.pk}),
            **self.headers,
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        referred = resp.data['referred_customers']
        self.assertEqual(len(referred), 1)
        self.assertEqual(referred[0]['full_name'], 'Brought In')

    def test_self_referral_rejected_on_update(self):
        resp = _client(self.owner).patch(
            reverse('customer-detail', kwargs={'pk': self.referrer.pk}),
            {'referred_by_code': self.referrer.referral_code},
            format='json', **self.headers,
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_resolve_referral_endpoint_hit(self):
        resp = _client(self.owner).get(
            f'{self.resolve_url}?code={self.referrer.referral_code}',
            **self.headers,
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['id'], self.referrer.id)
        self.assertEqual(resp.data['full_name'], 'Rita Referrer')

    def test_resolve_referral_endpoint_miss(self):
        resp = _client(self.owner).get(
            f'{self.resolve_url}?code=ZZZZ9999', **self.headers,
        )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)


class CustomerSearchTests(TestCase):
    """The customer list `?q=` search must handle a full-name query.
    Each term is matched against any field; matching the whole string
    against each field finds nothing for a 'first last' search."""

    @classmethod
    def setUpTestData(cls):
        cls.tenant, cls.owner = _make_tenant('cust-search')
        cls.laura = Customer.objects.create(
            tenant=cls.tenant, first_name='Laura', last_name='Lou',
            email='laura@test.local',
        )
        # Decoy — shares the 'laura' term but not 'lou'.
        Customer.objects.create(
            tenant=cls.tenant, first_name='Laura', last_name='Smith',
            email='lauras@test.local',
        )
        cls.url = reverse('customer-list')
        cls.headers = {'HTTP_X_TENANT_SLUG': cls.tenant.slug}

    def _search(self, q: str) -> set[int]:
        resp = _client(self.owner).get(self.url, {'q': q}, **self.headers)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        rows = resp.data['results'] if isinstance(resp.data, dict) else resp.data
        return {row['id'] for row in rows}

    def test_full_name_search_finds_customer(self):
        self.assertIn(self.laura.id, self._search('laura lou'))

    def test_full_name_search_is_order_independent(self):
        self.assertIn(self.laura.id, self._search('lou laura'))

    def test_full_name_search_excludes_partial_match(self):
        # 'Laura Smith' shares 'laura' but not 'lou' — must not appear.
        self.assertEqual(self._search('laura lou'), {self.laura.id})

    def test_single_term_search_still_works(self):
        self.assertIn(self.laura.id, self._search('laura'))
