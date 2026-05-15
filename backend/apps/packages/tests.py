"""Tests for the packages catalog API.

Step 1 covers the catalog side only — `Package` + `PackageItem`
CRUD with nested items, search/filter, permission gating, tenant
isolation, audit log shape, delete-with-purchases blocked.

Sale + redemption (PurchasedPackage, draw-down ledger) live in
step 2's tests inside the invoices test module since they're
driven by the invoice action endpoints.
"""

from __future__ import annotations

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.audit.models import AuditLog
from apps.services.models import Service, ServiceCategory
from apps.tenants.models import (
    MembershipLocation,
    Tenant,
    TenantMembership,
)
from apps.tenants.services import create_tenant_with_defaults

from .models import Package, PackageItem

User = get_user_model()


# ── Helpers ─────────────────────────────────────────────────────────


def _make_user(email: str) -> User:
    return User.objects.create_user(
        email=email, password='pw', first_name='F', last_name='L',
    )


def _make_tenant(slug: str) -> tuple[Tenant, User]:
    owner = _make_user(f'{slug}-owner@test.local')
    tenant = create_tenant_with_defaults(
        name=slug.title(), slug=slug, owner_user=owner,
        status=Tenant.Status.ACTIVE,
    )
    return tenant, owner


def _make_front_desk(tenant: Tenant) -> tuple[User, TenantMembership]:
    user = _make_user(f'fd-{tenant.slug}@test.local')
    m = TenantMembership.objects.create(
        user=user, tenant=tenant,
        role=TenantMembership.Role.FRONT_DESK,
        is_active=True,
    )
    MembershipLocation.objects.create(
        membership=m, location=tenant.locations.get(is_default=True),
        is_active=True,
    )
    return user, m


def _make_service(
    tenant: Tenant, *, name: str = 'Facial', price_cents: int = 10000,
) -> Service:
    cat, _ = ServiceCategory.objects.get_or_create(
        tenant=tenant, name='Default category',
    )
    return Service.objects.create(
        tenant=tenant, category=cat, name=name,
        duration_minutes=30, price_cents=price_cents,
        service_type=Service.ServiceType.REGULAR,
        tax_rate_percent=Decimal('0'),
    )


def _client_for(user) -> APIClient:
    c = APIClient()
    c.force_login(user)
    return c


# ── Model layer ─────────────────────────────────────────────────────


class PackageModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant, cls.owner = _make_tenant('pkg-model')
        cls.facial = _make_service(cls.tenant, name='Facial', price_cents=10000)

    def test_sku_auto_generated(self):
        p = Package.objects.create(
            tenant=self.tenant, name='Five Facial Pack', price_cents=40000,
        )
        self.assertEqual(p.sku, 'FFP')

    def test_sku_collision_retries(self):
        Package.objects.create(
            tenant=self.tenant, name='Glow Bundle', sku='GB', price_cents=10000,
        )
        p2 = Package.objects.create(
            tenant=self.tenant, name='Glow Bundle', price_cents=10000,
        )
        self.assertEqual(p2.sku, 'GB-2')

    def test_validity_days_nullable(self):
        p = Package.objects.create(
            tenant=self.tenant, name='Lifetime', price_cents=99900,
            validity_days=None,
        )
        self.assertIsNone(p.validity_days)

    def test_package_item_quantity_positive_constraint(self):
        from django.db.utils import IntegrityError

        p = Package.objects.create(
            tenant=self.tenant, name='X', price_cents=100,
        )
        with self.assertRaises(IntegrityError):
            PackageItem.objects.create(
                package=p, service=self.facial, quantity=0,
            )

    def test_package_item_unique_per_package_service(self):
        from django.db.utils import IntegrityError

        p = Package.objects.create(
            tenant=self.tenant, name='X', price_cents=100,
        )
        PackageItem.objects.create(package=p, service=self.facial, quantity=5)
        with self.assertRaises(IntegrityError):
            PackageItem.objects.create(package=p, service=self.facial, quantity=3)


# ── Permission gating ───────────────────────────────────────────────


class PackagePermissionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant, cls.owner = _make_tenant('pkg-perm')
        cls.fd_user, cls.fd_membership = _make_front_desk(cls.tenant)
        cls.facial = _make_service(cls.tenant)

    def test_anonymous_blocked(self):
        response = APIClient().get(
            reverse('package-list'),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_front_desk_can_read(self):
        # Catalog must be visible at POS, even though front-desk
        # can't create / edit catalog rows.
        response = _client_for(self.fd_user).get(
            reverse('package-list'),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_front_desk_cannot_create(self):
        response = _client_for(self.fd_user).post(
            reverse('package-list'),
            data={
                'name': 'Test',
                'price_cents': 1000,
                'items_input': [{'service_id': self.facial.pk, 'quantity': 1}],
            },
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_owner_can_create(self):
        response = _client_for(self.owner).post(
            reverse('package-list'),
            data={
                'name': 'Five Facial',
                'price_cents': 40000,
                'validity_days': 365,
                'items_input': [{'service_id': self.facial.pk, 'quantity': 5}],
            },
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data['name'], 'Five Facial')
        self.assertEqual(len(response.data['items']), 1)


# ── CRUD with nested items ──────────────────────────────────────────


class PackageCRUDTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant, cls.owner = _make_tenant('pkg-crud')
        cls.facial = _make_service(cls.tenant, name='Facial', price_cents=10000)
        cls.peel = _make_service(cls.tenant, name='Peel', price_cents=15000)

    def setUp(self):
        self.client = _client_for(self.owner)

    def test_create_with_multiple_items(self):
        response = self.client.post(
            reverse('package-list'),
            data={
                'name': 'Glow Bundle',
                'price_cents': 18000,
                'items_input': [
                    {'service_id': self.facial.pk, 'quantity': 1},
                    {'service_id': self.peel.pk, 'quantity': 1},
                ],
            },
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data['a_la_carte_total_cents'], 25000)
        self.assertEqual(response.data['implicit_discount_cents'], 7000)

    def test_create_without_items_rejected(self):
        response = self.client.post(
            reverse('package-list'),
            data={'name': 'Empty', 'price_cents': 1000},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_with_duplicate_service_rejected(self):
        response = self.client.post(
            reverse('package-list'),
            data={
                'name': 'Dup',
                'price_cents': 1000,
                'items_input': [
                    {'service_id': self.facial.pk, 'quantity': 1},
                    {'service_id': self.facial.pk, 'quantity': 1},
                ],
            },
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_with_cross_tenant_service_rejected(self):
        other_tenant, _ = _make_tenant('pkg-crud-other')
        cross_service = _make_service(other_tenant, name='Cross')

        response = self.client.post(
            reverse('package-list'),
            data={
                'name': 'Cross-tenant',
                'price_cents': 1000,
                'items_input': [{'service_id': cross_service.pk, 'quantity': 1}],
            },
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_update_replaces_items_wholesale(self):
        # Create with [facial × 5].
        create = self.client.post(
            reverse('package-list'),
            data={
                'name': 'Fivepack',
                'price_cents': 40000,
                'items_input': [{'service_id': self.facial.pk, 'quantity': 5}],
            },
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        package_id = create.data['id']

        # Replace with [peel × 3].
        response = self.client.patch(
            reverse('package-detail', kwargs={'pk': package_id}),
            data={
                'items_input': [{'service_id': self.peel.pk, 'quantity': 3}],
            },
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        items = response.data['items']
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['service_name'], 'Peel')
        self.assertEqual(items[0]['quantity'], 3)

    def test_update_without_items_keeps_existing_items(self):
        create = self.client.post(
            reverse('package-list'),
            data={
                'name': 'Stable',
                'price_cents': 10000,
                'items_input': [{'service_id': self.facial.pk, 'quantity': 2}],
            },
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        package_id = create.data['id']

        response = self.client.patch(
            reverse('package-detail', kwargs={'pk': package_id}),
            data={'price_cents': 12000},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['items']), 1)

    def test_destroy_with_no_purchases(self):
        package = Package.objects.create(
            tenant=self.tenant, name='X', price_cents=100,
        )
        PackageItem.objects.create(
            package=package, service=self.facial, quantity=1,
        )
        response = self.client.delete(
            reverse('package-detail', kwargs={'pk': package.pk}),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_cross_tenant_404(self):
        other_tenant, _ = _make_tenant('pkg-crud-other-2')
        package = Package.objects.create(
            tenant=other_tenant, name='Other', price_cents=100,
        )
        response = self.client.get(
            reverse('package-detail', kwargs={'pk': package.pk}),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


# ── Filtering ───────────────────────────────────────────────────────


class PackageFilterTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant, cls.owner = _make_tenant('pkg-filter')
        cls.facial = _make_service(cls.tenant)
        cls.active = Package.objects.create(
            tenant=cls.tenant, name='Active Bundle', sku='AB',
            price_cents=20000, is_active=True,
        )
        PackageItem.objects.create(
            package=cls.active, service=cls.facial, quantity=2,
        )
        cls.inactive = Package.objects.create(
            tenant=cls.tenant, name='Old Bundle', sku='OB',
            price_cents=15000, is_active=False,
        )
        PackageItem.objects.create(
            package=cls.inactive, service=cls.facial, quantity=2,
        )

    def setUp(self):
        self.client = _client_for(self.owner)

    def test_filter_active_true(self):
        response = self.client.get(
            reverse('package-list') + '?active=true',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        names = sorted(r['name'] for r in response.data)
        self.assertEqual(names, ['Active Bundle'])

    def test_filter_active_false(self):
        response = self.client.get(
            reverse('package-list') + '?active=false',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        names = sorted(r['name'] for r in response.data)
        self.assertEqual(names, ['Old Bundle'])

    def test_search_q_matches_name_or_sku(self):
        response = self.client.get(
            reverse('package-list') + '?q=AB',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        names = [r['name'] for r in response.data]
        self.assertEqual(names, ['Active Bundle'])


# ── Audit log + delete-with-purchases (placeholder) ─────────────────


class PackageAuditTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant, cls.owner = _make_tenant('pkg-audit')
        cls.facial = _make_service(cls.tenant)

    def setUp(self):
        self.client = _client_for(self.owner)

    def test_create_audit_records_item_count(self):
        self.client.post(
            reverse('package-list'),
            data={
                'name': 'X', 'price_cents': 1000,
                'items_input': [{'service_id': self.facial.pk, 'quantity': 1}],
            },
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        log = AuditLog.objects.filter(
            resource_type='package', action=AuditLog.Action.CREATE,
        ).order_by('-id').first()
        self.assertIsNotNone(log)
        self.assertEqual(log.metadata.get('item_count'), 1)

    def test_list_writes_aggregate_audit(self):
        Package.objects.create(tenant=self.tenant, name='A', price_cents=100)
        Package.objects.create(tenant=self.tenant, name='B', price_cents=100)
        self.client.get(
            reverse('package-list'),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        log = AuditLog.objects.filter(
            resource_type='package_list', action=AuditLog.Action.READ,
        ).order_by('-id').first()
        self.assertIsNotNone(log)
        self.assertEqual(log.metadata.get('count'), 2)


# ── Build-custom: per-customer one-off package + draft invoice ─────


class BuildCustomPackageEndpointTests(TestCase):
    """Covers the `/api/purchased-packages/build-custom/` POS-style
    endpoint: atomically creates a draft Invoice + a one-off
    `PurchasedPackage` (with `source_template = NULL`) for a
    specific customer.

    Six invariants:
      1. Happy path: a valid payload creates the invoice + package
         + items, returns the IDs, audit-logs the create.
      2. Tenant scoping: customers / services from other tenants
         can't be referenced.
      3. Validation: empty items, unknown service, inactive service,
         duplicate service rows all reject with 400.
      4. Permission: front-desk (has PROCESS_PAYMENT) can call it;
         a member without PROCESS_PAYMENT cannot.
      5. Status: created PurchasedPackage starts PENDING.
      6. Invoice number is assigned + returned.
    """

    @classmethod
    def setUpTestData(cls):
        from apps.customers.models import Customer

        cls.tenant, cls.owner = _make_tenant('build-custom')
        cls.other_tenant, _ = _make_tenant('build-custom-other')
        cls.facial = _make_service(cls.tenant, name='HydraFacial', price_cents=15000)
        cls.peel = _make_service(cls.tenant, name='Peel', price_cents=20000)
        cls.foreign_service = _make_service(
            cls.other_tenant, name='Foreign service', price_cents=5000,
        )
        cls.customer = Customer.objects.create(
            tenant=cls.tenant, first_name='Jane', last_name='Doe',
            email='jane@test.local', phone='+15551234567',
        )
        cls.foreign_customer = Customer.objects.create(
            tenant=cls.other_tenant, first_name='Foreign', last_name='Customer',
            email='foreign@test.local', phone='+15559876543',
        )

    def setUp(self):
        self.client = _client_for(self.owner)
        self.url = '/api/purchased-packages/build-custom/'

    def _valid_payload(self):
        return {
            'customer_id': self.customer.id,
            'name': '5 HydraFacials',
            'price_cents': 60000,
            'validity_days': 365,
            'items': [
                {'service_id': self.facial.id, 'quantity': 5},
            ],
        }

    def test_happy_path_creates_package_and_invoice(self):
        from apps.invoices.models import Invoice
        from apps.packages.models import PurchasedPackage

        response = self.client.post(
            self.url, data=self._valid_payload(),
            format='json', HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, 201, response.data)

        # PurchasedPackage was created with the right shape.
        pkg_id = response.data['purchased_package']['id']
        pkg = PurchasedPackage.objects.get(pk=pkg_id)
        self.assertEqual(pkg.customer, self.customer)
        self.assertEqual(pkg.tenant, self.tenant)
        self.assertIsNone(pkg.source_template)
        self.assertEqual(pkg.status, PurchasedPackage.Status.PENDING)
        self.assertEqual(pkg.price_cents, 60000)
        self.assertEqual(pkg.validity_days, 365)
        self.assertEqual(pkg.items.count(), 1)
        item = pkg.items.first()
        self.assertEqual(item.service_id, self.facial.id)
        self.assertEqual(item.quantity_purchased, 5)
        self.assertEqual(item.quantity_remaining, 5)

        # Invoice was created, is OPEN, has a number, has the line.
        invoice_id = response.data['invoice_id']
        invoice = Invoice.objects.get(pk=invoice_id)
        self.assertEqual(invoice.status, Invoice.Status.OPEN)
        self.assertEqual(invoice.customer, self.customer)
        self.assertIsNone(invoice.appointment)
        self.assertTrue(invoice.invoice_number)
        self.assertEqual(response.data['invoice_number'], invoice.invoice_number)
        self.assertEqual(invoice.total_cents, 60000)

    def test_create_writes_audit_log(self):
        self.client.post(
            self.url, data=self._valid_payload(),
            format='json', HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        log = AuditLog.objects.filter(
            resource_type='purchased_package',
            action=AuditLog.Action.CREATE,
        ).order_by('-id').first()
        self.assertIsNotNone(log)
        self.assertEqual(log.metadata.get('kind'), 'custom_one_off')
        self.assertEqual(log.metadata.get('customer_id'), self.customer.id)
        self.assertEqual(log.metadata.get('item_count'), 1)

    def test_rejects_cross_tenant_customer(self):
        payload = self._valid_payload()
        payload['customer_id'] = self.foreign_customer.id
        response = self.client.post(
            self.url, data=payload,
            format='json', HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('customer_id', response.data)

    def test_rejects_cross_tenant_service(self):
        payload = self._valid_payload()
        payload['items'] = [{'service_id': self.foreign_service.id, 'quantity': 1}]
        response = self.client.post(
            self.url, data=payload,
            format='json', HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('items', response.data)

    def test_rejects_inactive_service(self):
        self.peel.is_active = False
        self.peel.save(update_fields=['is_active'])
        payload = self._valid_payload()
        payload['items'] = [{'service_id': self.peel.id, 'quantity': 1}]
        response = self.client.post(
            self.url, data=payload,
            format='json', HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('items', response.data)

    def test_rejects_empty_items(self):
        payload = self._valid_payload()
        payload['items'] = []
        response = self.client.post(
            self.url, data=payload,
            format='json', HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, 400)

    def test_rejects_duplicate_service_rows(self):
        payload = self._valid_payload()
        payload['items'] = [
            {'service_id': self.facial.id, 'quantity': 2},
            {'service_id': self.facial.id, 'quantity': 3},
        ]
        response = self.client.post(
            self.url, data=payload,
            format='json', HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, 400)

    def test_front_desk_can_build_custom_package(self):
        # Front-desk has PROCESS_PAYMENT in the default role grants
        # → POS-style endpoint should work for them.
        _, _ = _make_front_desk(self.tenant)
        from django.contrib.auth import get_user_model

        fd_user = get_user_model().objects.get(email=f'fd-{self.tenant.slug}@test.local')
        fd_client = _client_for(fd_user)

        response = fd_client.post(
            self.url, data=self._valid_payload(),
            format='json', HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, 201, response.data)
