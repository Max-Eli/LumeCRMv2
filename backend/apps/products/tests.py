"""Tests for the products API.

Covers: model defaults + SKU auto-gen + collision retry,
permission gating (read open / write requires MANAGE_SERVICES),
tenant isolation, search + filter (q, category, active, low_stock),
audit log shape, stock-adjustment action (delta + note required +
locking + audit), inactive products excluded from active=true.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.audit.models import AuditLog
from apps.tenants.models import (
    MembershipLocation,
    Tenant,
    TenantMembership,
)
from apps.tenants.services import create_tenant_with_defaults

from .models import Product, ProductCategory

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


def _client_for(user) -> APIClient:
    c = APIClient()
    c.force_login(user)
    return c


# ── Model layer ─────────────────────────────────────────────────────


class ProductModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant, cls.owner = _make_tenant('prod-model')

    def test_sku_auto_generated_from_name(self):
        p = Product.objects.create(
            tenant=self.tenant, name='Vitamin C Serum 30ml', price_cents=4500,
        )
        self.assertEqual(p.sku, 'VCS30')

    def test_sku_collision_retries_with_suffix(self):
        Product.objects.create(
            tenant=self.tenant, name='Sunscreen Pro', sku='SP', price_cents=3000,
        )
        p2 = Product.objects.create(
            tenant=self.tenant, name='Sunscreen Pro', price_cents=3000,
        )
        # Auto-gen would be 'SP'; collision → 'SP-2'.
        self.assertEqual(p2.sku, 'SP-2')

    def test_sku_uniqueness_per_tenant_only(self):
        # Same SKU is fine across tenants.
        other_tenant, _ = _make_tenant('prod-model-other')
        Product.objects.create(
            tenant=self.tenant, name='Cream', sku='CR1', price_cents=1000,
        )
        Product.objects.create(
            tenant=other_tenant, name='Cream', sku='CR1', price_cents=1000,
        )
        # No IntegrityError → pass

    def test_is_low_stock_respects_track_inventory_off(self):
        p = Product.objects.create(
            tenant=self.tenant, name='Gift card', price_cents=5000,
            track_inventory=False, low_stock_threshold=5, stock_quantity=0,
        )
        self.assertFalse(p.is_low_stock)

    def test_is_low_stock_threshold_zero_disables_warning(self):
        p = Product.objects.create(
            tenant=self.tenant, name='Toner', price_cents=2000,
            stock_quantity=0, low_stock_threshold=0,
        )
        self.assertFalse(p.is_low_stock)

    def test_is_low_stock_at_or_below_threshold(self):
        p = Product.objects.create(
            tenant=self.tenant, name='Wipes', price_cents=500,
            stock_quantity=3, low_stock_threshold=5,
        )
        self.assertTrue(p.is_low_stock)
        p.stock_quantity = 5
        p.save()
        self.assertTrue(p.is_low_stock)
        p.stock_quantity = 6
        p.save()
        self.assertFalse(p.is_low_stock)

    def test_price_dollars_formatting(self):
        p = Product.objects.create(
            tenant=self.tenant, name='X', price_cents=4599,
        )
        self.assertEqual(p.price_dollars, '$45.99')


# ── Permission gating ───────────────────────────────────────────────


class ProductPermissionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant, cls.owner = _make_tenant('prod-perm')
        cls.fd_user, cls.fd_membership = _make_front_desk(cls.tenant)

    def test_anonymous_blocked(self):
        response = APIClient().get(
            reverse('product-list'),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_authenticated_member_can_read(self):
        response = _client_for(self.fd_user).get(
            reverse('product-list'),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_front_desk_cannot_create(self):
        response = _client_for(self.fd_user).post(
            reverse('product-list'),
            data={'name': 'Test', 'price_cents': 1000},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_owner_can_create(self):
        response = _client_for(self.owner).post(
            reverse('product-list'),
            data={'name': 'Vitamin C Serum', 'price_cents': 4500},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data['sku'], 'VCS')


# ── CRUD + tenant isolation ─────────────────────────────────────────


class ProductCRUDTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant, cls.owner = _make_tenant('prod-crud')

    def setUp(self):
        self.client = _client_for(self.owner)

    def test_create_with_category(self):
        cat = ProductCategory.objects.create(tenant=self.tenant, name='Skincare')
        response = self.client.post(
            reverse('product-list'),
            data={
                'name': 'Cream',
                'price_cents': 5000,
                'category_id': cat.pk,
                'stock_quantity': 12,
                'low_stock_threshold': 3,
            },
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data['category']['name'], 'Skincare')
        self.assertEqual(response.data['stock_quantity'], 12)
        self.assertFalse(response.data['is_low_stock'])

    def test_update_partial(self):
        p = Product.objects.create(
            tenant=self.tenant, name='X', price_cents=1000, stock_quantity=5,
        )
        response = self.client.patch(
            reverse('product-detail', kwargs={'pk': p.pk}),
            data={'price_cents': 1500},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        p.refresh_from_db()
        self.assertEqual(p.price_cents, 1500)
        self.assertEqual(p.stock_quantity, 5)  # unchanged

    def test_destroy(self):
        p = Product.objects.create(
            tenant=self.tenant, name='X', price_cents=1000,
        )
        response = self.client.delete(
            reverse('product-detail', kwargs={'pk': p.pk}),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Product.objects.filter(pk=p.pk).exists())

    def test_cross_tenant_404(self):
        other_tenant, _ = _make_tenant('prod-crud-other')
        p = Product.objects.create(
            tenant=other_tenant, name='Other', price_cents=1000,
        )
        response = self.client.get(
            reverse('product-detail', kwargs={'pk': p.pk}),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


# ── Filtering ───────────────────────────────────────────────────────


class ProductFilterTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant, cls.owner = _make_tenant('prod-filter')
        cls.cat_skin = ProductCategory.objects.create(
            tenant=cls.tenant, name='Skincare',
        )
        cls.cat_supp = ProductCategory.objects.create(
            tenant=cls.tenant, name='Supplements',
        )
        Product.objects.create(
            tenant=cls.tenant, name='Vitamin C Serum',
            sku='VCS', category=cls.cat_skin,
            price_cents=4500, stock_quantity=2, low_stock_threshold=5,
        )
        Product.objects.create(
            tenant=cls.tenant, name='Collagen powder',
            sku='COL', category=cls.cat_supp,
            price_cents=3500, stock_quantity=20, low_stock_threshold=5,
        )
        Product.objects.create(
            tenant=cls.tenant, name='Discontinued cream',
            sku='DC', category=cls.cat_skin,
            price_cents=1000, is_active=False,
        )

    def setUp(self):
        self.client = _client_for(self.owner)

    def test_search_q_matches_name_or_sku(self):
        response = self.client.get(
            reverse('product-list') + '?q=vitamin',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        names = [r['name'] for r in response.data]
        self.assertEqual(names, ['Vitamin C Serum'])

        response = self.client.get(
            reverse('product-list') + '?q=COL',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        names = [r['name'] for r in response.data]
        self.assertEqual(names, ['Collagen powder'])

    def test_filter_by_category(self):
        response = self.client.get(
            reverse('product-list') + f'?category={self.cat_supp.pk}',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        names = sorted(r['name'] for r in response.data)
        self.assertEqual(names, ['Collagen powder'])

    def test_filter_active(self):
        response = self.client.get(
            reverse('product-list') + '?active=true',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        names = sorted(r['name'] for r in response.data)
        self.assertEqual(names, ['Collagen powder', 'Vitamin C Serum'])

        response = self.client.get(
            reverse('product-list') + '?active=false',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        names = sorted(r['name'] for r in response.data)
        self.assertEqual(names, ['Discontinued cream'])

    def test_filter_low_stock(self):
        # Vitamin C: stock 2, threshold 5 → low; Collagen: 20/5 → not.
        response = self.client.get(
            reverse('product-list') + '?low_stock=true',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        names = [r['name'] for r in response.data]
        self.assertEqual(names, ['Vitamin C Serum'])


# ── Stock adjustment + audit ────────────────────────────────────────


class StockAdjustmentTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant, cls.owner = _make_tenant('prod-adj')

    def setUp(self):
        self.client = _client_for(self.owner)
        self.product = Product.objects.create(
            tenant=self.tenant, name='Toner', price_cents=2000,
            stock_quantity=10,
        )

    def _adjust_url(self, pk):
        return reverse('product-adjust-stock', kwargs={'pk': pk})

    def test_positive_delta(self):
        response = self.client.post(
            self._adjust_url(self.product.pk),
            data={'delta': 5, 'note': 'Received shipment'},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['stock_quantity'], 15)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 15)

    def test_negative_delta_can_go_below_zero(self):
        response = self.client.post(
            self._adjust_url(self.product.pk),
            data={'delta': -15, 'note': 'Damaged box write-off'},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # IntegerField (signed) lets us see backorder reality.
        self.assertEqual(response.data['stock_quantity'], -5)

    def test_zero_delta_rejected(self):
        response = self.client.post(
            self._adjust_url(self.product.pk),
            data={'delta': 0, 'note': 'noop'},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_note_required(self):
        response = self.client.post(
            self._adjust_url(self.product.pk),
            data={'delta': 3},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_audit_log_records_delta_and_note(self):
        self.client.post(
            self._adjust_url(self.product.pk),
            data={'delta': 7, 'note': 'Recount correction'},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        log = AuditLog.objects.filter(
            resource_type='product',
            resource_id=self.product.pk,
            action=AuditLog.Action.UPDATE,
        ).order_by('-id').first()
        self.assertIsNotNone(log)
        self.assertEqual(log.metadata.get('event'), 'stock_adjusted')
        self.assertEqual(log.metadata.get('delta'), 7)
        self.assertEqual(log.metadata.get('before'), 10)
        self.assertEqual(log.metadata.get('after'), 17)
        self.assertEqual(log.metadata.get('note'), 'Recount correction')

    def test_front_desk_cannot_adjust(self):
        fd_user, _ = _make_front_desk(self.tenant)
        response = _client_for(fd_user).post(
            self._adjust_url(self.product.pk),
            data={'delta': 1, 'note': 'sneaky'},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


# ── Audit log shape on standard CRUD ────────────────────────────────


class ProductAuditTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant, cls.owner = _make_tenant('prod-audit')

    def setUp(self):
        self.client = _client_for(self.owner)

    def test_create_writes_audit(self):
        self.client.post(
            reverse('product-list'),
            data={'name': 'X', 'price_cents': 100},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        log = AuditLog.objects.filter(
            resource_type='product', action=AuditLog.Action.CREATE,
        ).first()
        self.assertIsNotNone(log)

    def test_list_writes_aggregate_audit(self):
        Product.objects.create(tenant=self.tenant, name='A', price_cents=100)
        Product.objects.create(tenant=self.tenant, name='B', price_cents=100)
        self.client.get(
            reverse('product-list'),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        log = AuditLog.objects.filter(
            resource_type='product_list', action=AuditLog.Action.READ,
        ).order_by('-id').first()
        self.assertIsNotNone(log)
        self.assertEqual(log.metadata.get('count'), 2)


# ── Categories CRUD ─────────────────────────────────────────────────


class ProductCategoryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant, cls.owner = _make_tenant('prod-cat')

    def setUp(self):
        self.client = _client_for(self.owner)

    def test_create_and_list(self):
        response = self.client.post(
            reverse('product-category-list'),
            data={'name': 'Skincare', 'color': '#ffaa00'},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data['name'], 'Skincare')

        list_response = self.client.get(
            reverse('product-category-list'),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(len(list_response.data), 1)

    def test_unique_name_per_tenant(self):
        self.client.post(
            reverse('product-category-list'),
            data={'name': 'Skincare'},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        # Same name same tenant → 400.
        response = self.client.post(
            reverse('product-category-list'),
            data={'name': 'Skincare'},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
