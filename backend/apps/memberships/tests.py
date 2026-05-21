"""Tests for the memberships catalog API.

Step 1 covers the catalog (`MembershipPlan` + `MembershipPlanItem`)
plus the read-only Subscription endpoints + the cancel action.
Sale + redemption (PENDING→ACTIVE flip on close, redeem-from-
membership action) live in step 2's tests inside the invoices
test module.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.audit.models import AuditLog
from apps.appointments.models import Appointment
from apps.customers.models import Customer
from apps.invoices.models import Invoice
from apps.services.models import Service, ServiceCategory
from apps.tenants.models import (
    MembershipLocation,
    Tenant,
    TenantMembership,
)
from apps.tenants.services import create_tenant_with_defaults

from .models import MembershipPlan, MembershipPlanItem, Subscription

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


def _make_provider(tenant: Tenant) -> TenantMembership:
    user = _make_user(f'prov-{tenant.slug}@test.local')
    m = TenantMembership.objects.create(
        user=user, tenant=tenant,
        role=TenantMembership.Role.PROVIDER,
        is_bookable=True, is_active=True,
    )
    MembershipLocation.objects.create(
        membership=m, location=tenant.locations.get(is_default=True),
        is_active=True,
    )
    return m


def _make_service(
    tenant: Tenant, *, name: str = 'Facial', price_cents: int = 10000,
) -> Service:
    cat, _ = ServiceCategory.objects.get_or_create(
        tenant=tenant, name='Default',
    )
    return Service.objects.create(
        tenant=tenant, category=cat, name=name,
        duration_minutes=30, price_cents=price_cents,
        service_type=Service.ServiceType.REGULAR,
        tax_rate_percent=Decimal('0'),
    )


def _make_customer(tenant: Tenant, email: str | None = None) -> Customer:
    return Customer.objects.create(
        tenant=tenant,
        first_name='Pat', last_name='Patient',
        email=email or 'pat@x.com',
    )


def _client_for(user) -> APIClient:
    c = APIClient()
    c.force_login(user)
    return c


# ── Model layer ─────────────────────────────────────────────────────


class MembershipPlanModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant, cls.owner = _make_tenant('mbr-model')
        cls.facial = _make_service(cls.tenant, name='Facial', price_cents=10000)

    def test_sku_auto_generated(self):
        plan = MembershipPlan.objects.create(
            tenant=self.tenant, name='Glow Club', price_cents=9900,
        )
        self.assertEqual(plan.sku, 'GC')

    def test_sku_collision_retries(self):
        MembershipPlan.objects.create(
            tenant=self.tenant, name='Glow Club', sku='GC', price_cents=9900,
        )
        p2 = MembershipPlan.objects.create(
            tenant=self.tenant, name='Glow Club', price_cents=9900,
        )
        self.assertEqual(p2.sku, 'GC-2')

    def test_billing_interval_defaults_to_monthly(self):
        plan = MembershipPlan.objects.create(
            tenant=self.tenant, name='Default', price_cents=5000,
        )
        self.assertEqual(plan.billing_interval, MembershipPlan.BillingInterval.MONTHLY)
        self.assertEqual(plan.cycle_days, 30)

    def test_annual_cycle_days(self):
        plan = MembershipPlan.objects.create(
            tenant=self.tenant, name='Yearly',
            price_cents=99000,
            billing_interval=MembershipPlan.BillingInterval.ANNUAL,
        )
        self.assertEqual(plan.cycle_days, 365)

    def test_plan_item_quantity_positive_constraint(self):
        from django.db.utils import IntegrityError
        plan = MembershipPlan.objects.create(
            tenant=self.tenant, name='X', price_cents=100,
        )
        with self.assertRaises(IntegrityError):
            MembershipPlanItem.objects.create(
                plan=plan, service=self.facial, quantity_per_cycle=0,
            )

    def test_plan_item_unique_per_service(self):
        from django.db.utils import IntegrityError
        plan = MembershipPlan.objects.create(
            tenant=self.tenant, name='X', price_cents=100,
        )
        MembershipPlanItem.objects.create(
            plan=plan, service=self.facial, quantity_per_cycle=2,
        )
        with self.assertRaises(IntegrityError):
            MembershipPlanItem.objects.create(
                plan=plan, service=self.facial, quantity_per_cycle=3,
            )

    def test_plan_item_unique_per_category(self):
        from django.db.utils import IntegrityError
        plan = MembershipPlan.objects.create(
            tenant=self.tenant, name='Cat', price_cents=100,
        )
        MembershipPlanItem.objects.create(
            plan=plan, category=self.facial.category, quantity_per_cycle=1,
        )
        with self.assertRaises(IntegrityError):
            MembershipPlanItem.objects.create(
                plan=plan, category=self.facial.category, quantity_per_cycle=2,
            )

    def test_plan_item_neither_service_nor_category_rejected(self):
        from django.db.utils import IntegrityError
        plan = MembershipPlan.objects.create(
            tenant=self.tenant, name='Neither', price_cents=100,
        )
        with self.assertRaises(IntegrityError):
            MembershipPlanItem.objects.create(plan=plan, quantity_per_cycle=1)

    def test_plan_item_both_service_and_category_rejected(self):
        from django.db.utils import IntegrityError
        plan = MembershipPlan.objects.create(
            tenant=self.tenant, name='Both', price_cents=100,
        )
        with self.assertRaises(IntegrityError):
            MembershipPlanItem.objects.create(
                plan=plan, service=self.facial,
                category=self.facial.category, quantity_per_cycle=1,
            )


# ── Permissions ─────────────────────────────────────────────────────


class MembershipPlanPermissionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant, cls.owner = _make_tenant('mbr-perm')
        cls.fd_user, _ = _make_front_desk(cls.tenant)
        cls.facial = _make_service(cls.tenant)

    def test_anonymous_blocked(self):
        response = APIClient().get(
            reverse('membership-plan-list'),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_front_desk_can_read(self):
        # Catalog must be visible at POS even though front-desk
        # can't author plans.
        response = _client_for(self.fd_user).get(
            reverse('membership-plan-list'),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_front_desk_cannot_create(self):
        response = _client_for(self.fd_user).post(
            reverse('membership-plan-list'),
            data={
                'name': 'Test',
                'price_cents': 1000,
                'items_input': [
                    {'service_id': self.facial.pk, 'quantity_per_cycle': 1},
                ],
            },
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_owner_can_create(self):
        response = _client_for(self.owner).post(
            reverse('membership-plan-list'),
            data={
                'name': 'Glow Club',
                'price_cents': 9900,
                'billing_interval': 'monthly',
                'items_input': [
                    {'service_id': self.facial.pk, 'quantity_per_cycle': 1},
                ],
            },
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(
            response.status_code, status.HTTP_201_CREATED, response.data,
        )
        self.assertEqual(response.data['name'], 'Glow Club')
        self.assertEqual(len(response.data['items']), 1)


# ── CRUD with nested items ──────────────────────────────────────────


class MembershipPlanCRUDTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant, cls.owner = _make_tenant('mbr-crud')
        cls.facial = _make_service(cls.tenant, name='Facial', price_cents=10000)
        cls.peel = _make_service(cls.tenant, name='Peel', price_cents=15000)

    def setUp(self):
        self.client = _client_for(self.owner)

    def test_create_with_multiple_items(self):
        response = self.client.post(
            reverse('membership-plan-list'),
            data={
                'name': 'VIP Club',
                'price_cents': 18000,
                'member_discount_percent': '10',
                'items_input': [
                    {'service_id': self.facial.pk, 'quantity_per_cycle': 1},
                    {'service_id': self.peel.pk, 'quantity_per_cycle': 1},
                ],
            },
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(
            response.status_code, status.HTTP_201_CREATED, response.data,
        )
        self.assertEqual(response.data['a_la_carte_total_cents'], 25000)
        self.assertEqual(response.data['implicit_discount_cents'], 7000)

    def test_create_without_items_rejected(self):
        response = self.client.post(
            reverse('membership-plan-list'),
            data={'name': 'Empty', 'price_cents': 1000},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_with_duplicate_service_rejected(self):
        response = self.client.post(
            reverse('membership-plan-list'),
            data={
                'name': 'Dup',
                'price_cents': 1000,
                'items_input': [
                    {'service_id': self.facial.pk, 'quantity_per_cycle': 1},
                    {'service_id': self.facial.pk, 'quantity_per_cycle': 2},
                ],
            },
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_with_cross_tenant_service_rejected(self):
        other_tenant, _ = _make_tenant('mbr-crud-other')
        cross_service = _make_service(other_tenant, name='Other')
        response = self.client.post(
            reverse('membership-plan-list'),
            data={
                'name': 'Cross-tenant',
                'price_cents': 1000,
                'items_input': [
                    {'service_id': cross_service.pk, 'quantity_per_cycle': 1},
                ],
            },
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_update_replaces_items_wholesale(self):
        create = self.client.post(
            reverse('membership-plan-list'),
            data={
                'name': 'OneFacial',
                'price_cents': 10000,
                'items_input': [
                    {'service_id': self.facial.pk, 'quantity_per_cycle': 1},
                ],
            },
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        plan_id = create.data['id']

        response = self.client.patch(
            reverse('membership-plan-detail', kwargs={'pk': plan_id}),
            data={
                'items_input': [
                    {'service_id': self.peel.pk, 'quantity_per_cycle': 2},
                ],
            },
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        items = response.data['items']
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['service_name'], 'Peel')
        self.assertEqual(items[0]['quantity_per_cycle'], 2)

    def test_update_without_items_keeps_existing(self):
        create = self.client.post(
            reverse('membership-plan-list'),
            data={
                'name': 'Stable',
                'price_cents': 10000,
                'items_input': [
                    {'service_id': self.facial.pk, 'quantity_per_cycle': 1},
                ],
            },
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        plan_id = create.data['id']

        response = self.client.patch(
            reverse('membership-plan-detail', kwargs={'pk': plan_id}),
            data={'price_cents': 12000},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['items']), 1)

    def test_destroy_with_no_subscriptions(self):
        plan = MembershipPlan.objects.create(
            tenant=self.tenant, name='X', price_cents=100,
        )
        MembershipPlanItem.objects.create(
            plan=plan, service=self.facial, quantity_per_cycle=1,
        )
        response = self.client.delete(
            reverse('membership-plan-detail', kwargs={'pk': plan.pk}),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_destroy_with_subscriptions_rejected(self):
        # Set up: create a plan + a customer + appointment so we can
        # create a Subscription via direct ORM (sale flow lives in
        # step 2, but for this test we just need to prove delete is
        # blocked).
        plan = MembershipPlan.objects.create(
            tenant=self.tenant, name='Has Subs', price_cents=100,
        )
        MembershipPlanItem.objects.create(
            plan=plan, service=self.facial, quantity_per_cycle=1,
        )
        provider = _make_provider(self.tenant)
        customer = _make_customer(self.tenant)
        appt = Appointment.objects.create(
            tenant=self.tenant,
            customer=customer,
            provider=provider,
            service=self.facial,
            location=self.tenant.locations.get(is_default=True),
            start_time=timezone.now() + dt.timedelta(hours=1),
            end_time=timezone.now() + dt.timedelta(hours=2),
            status=Appointment.Status.CHECKED_IN,
            quoted_price_cents=self.facial.price_cents,
            created_by=self.owner,
        )
        invoice = Invoice.objects.get(appointment=appt)
        line = invoice.line_items.first()
        Subscription.objects.create(
            tenant=self.tenant,
            customer=customer,
            plan=plan,
            source_invoice_line=line,
            name='Has Subs',
            price_cents=100,
            billing_interval=MembershipPlan.BillingInterval.MONTHLY,
        )
        response = self.client.delete(
            reverse('membership-plan-detail', kwargs={'pk': plan.pk}),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('detail', response.data)

    def test_cross_tenant_404(self):
        other_tenant, _ = _make_tenant('mbr-crud-other-2')
        plan = MembershipPlan.objects.create(
            tenant=other_tenant, name='Other', price_cents=100,
        )
        response = self.client.get(
            reverse('membership-plan-detail', kwargs={'pk': plan.pk}),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


# ── Category lines ("any service in this category") ─────────────────


class MembershipPlanCategoryTests(TestCase):
    """A plan line can include a whole `ServiceCategory` — any service
    in it is redeemable. Covers create/validate + a-la-carte valuation
    (the average price of the category's active services)."""

    @classmethod
    def setUpTestData(cls):
        cls.tenant, cls.owner = _make_tenant('mbr-cat')
        cls.facials = ServiceCategory.objects.create(
            tenant=cls.tenant, name='Facials',
        )

        def _svc(name, price):
            return Service.objects.create(
                tenant=cls.tenant, category=cls.facials, name=name,
                duration_minutes=30, price_cents=price,
                service_type=Service.ServiceType.REGULAR,
                tax_rate_percent=Decimal('0'),
            )

        cls.basic = _svc('Basic Facial', 8000)
        cls.deluxe = _svc('Deluxe Facial', 12000)
        cls.peel = _make_service(cls.tenant, name='Peel', price_cents=15000)

    def setUp(self):
        self.client = _client_for(self.owner)

    def test_create_plan_with_category_line(self):
        response = self.client.post(
            reverse('membership-plan-list'),
            data={
                'name': 'Facial Club',
                'price_cents': 9000,
                'items_input': [
                    {'category_id': self.facials.pk, 'quantity_per_cycle': 2},
                ],
            },
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(
            response.status_code, status.HTTP_201_CREATED, response.data,
        )
        items = response.data['items']
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['item_type'], 'category')
        self.assertEqual(items[0]['category_id'], self.facials.pk)
        self.assertEqual(items[0]['category_name'], 'Facials')
        # avg(8000, 12000) = 10000, × 2 credits = 20000.
        self.assertEqual(response.data['a_la_carte_total_cents'], 20000)

    def test_mixed_service_and_category_lines(self):
        response = self.client.post(
            reverse('membership-plan-list'),
            data={
                'name': 'Combo Club',
                'price_cents': 20000,
                'items_input': [
                    {'service_id': self.peel.pk, 'quantity_per_cycle': 1},
                    {'category_id': self.facials.pk, 'quantity_per_cycle': 1},
                ],
            },
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(
            response.status_code, status.HTTP_201_CREATED, response.data,
        )
        kinds = sorted(i['item_type'] for i in response.data['items'])
        self.assertEqual(kinds, ['category', 'service'])
        # Peel 15000 + avg facial 10000 = 25000.
        self.assertEqual(response.data['a_la_carte_total_cents'], 25000)

    def test_line_with_both_service_and_category_rejected(self):
        response = self.client.post(
            reverse('membership-plan-list'),
            data={
                'name': 'Bad',
                'price_cents': 1000,
                'items_input': [
                    {
                        'service_id': self.basic.pk,
                        'category_id': self.facials.pk,
                        'quantity_per_cycle': 1,
                    },
                ],
            },
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_line_with_neither_service_nor_category_rejected(self):
        response = self.client.post(
            reverse('membership-plan-list'),
            data={
                'name': 'Bad',
                'price_cents': 1000,
                'items_input': [{'quantity_per_cycle': 1}],
            },
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_duplicate_category_rejected(self):
        response = self.client.post(
            reverse('membership-plan-list'),
            data={
                'name': 'Dup',
                'price_cents': 1000,
                'items_input': [
                    {'category_id': self.facials.pk, 'quantity_per_cycle': 1},
                    {'category_id': self.facials.pk, 'quantity_per_cycle': 2},
                ],
            },
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cross_tenant_category_rejected(self):
        other_tenant, _ = _make_tenant('mbr-cat-other')
        cross_cat = ServiceCategory.objects.create(
            tenant=other_tenant, name='Other Cat',
        )
        response = self.client.post(
            reverse('membership-plan-list'),
            data={
                'name': 'Cross',
                'price_cents': 1000,
                'items_input': [
                    {'category_id': cross_cat.pk, 'quantity_per_cycle': 1},
                ],
            },
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


# ── Filtering ───────────────────────────────────────────────────────


class MembershipPlanFilterTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant, cls.owner = _make_tenant('mbr-filter')
        cls.facial = _make_service(cls.tenant)
        cls.active = MembershipPlan.objects.create(
            tenant=cls.tenant, name='Active Plan', sku='AP',
            price_cents=9900, is_active=True,
        )
        MembershipPlanItem.objects.create(
            plan=cls.active, service=cls.facial, quantity_per_cycle=1,
        )
        cls.inactive = MembershipPlan.objects.create(
            tenant=cls.tenant, name='Old Plan', sku='OP',
            price_cents=4900, is_active=False,
        )
        MembershipPlanItem.objects.create(
            plan=cls.inactive, service=cls.facial, quantity_per_cycle=1,
        )

    def setUp(self):
        self.client = _client_for(self.owner)

    def test_filter_active_true(self):
        response = self.client.get(
            reverse('membership-plan-list') + '?active=true',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        names = sorted(r['name'] for r in response.data)
        self.assertEqual(names, ['Active Plan'])

    def test_filter_active_false(self):
        response = self.client.get(
            reverse('membership-plan-list') + '?active=false',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        names = sorted(r['name'] for r in response.data)
        self.assertEqual(names, ['Old Plan'])

    def test_search_q_matches_name_or_sku(self):
        response = self.client.get(
            reverse('membership-plan-list') + '?q=AP',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        names = [r['name'] for r in response.data]
        self.assertEqual(names, ['Active Plan'])


# ── Audit log shape ─────────────────────────────────────────────────


class MembershipPlanAuditTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant, cls.owner = _make_tenant('mbr-audit')
        cls.facial = _make_service(cls.tenant)

    def setUp(self):
        self.client = _client_for(self.owner)

    def test_create_audit_records_billing_interval_and_count(self):
        self.client.post(
            reverse('membership-plan-list'),
            data={
                'name': 'Yearly',
                'price_cents': 99000,
                'billing_interval': 'annual',
                'items_input': [
                    {'service_id': self.facial.pk, 'quantity_per_cycle': 12},
                ],
            },
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        log = AuditLog.objects.filter(
            resource_type='membership_plan', action=AuditLog.Action.CREATE,
        ).order_by('-id').first()
        self.assertIsNotNone(log)
        self.assertEqual(log.metadata.get('billing_interval'), 'annual')
        self.assertEqual(log.metadata.get('item_count'), 1)


# ── Subscription read endpoints + cancel action ─────────────────────


class SubscriptionEndpointTests(TestCase):
    """Sale flow lives in step 2; here we just construct a
    subscription via the ORM and verify the read + cancel surfaces
    work."""

    @classmethod
    def setUpTestData(cls):
        cls.tenant, cls.owner = _make_tenant('mbr-sub')
        cls.facial = _make_service(cls.tenant)
        cls.provider = _make_provider(cls.tenant)
        cls.customer = _make_customer(cls.tenant)
        cls.plan = MembershipPlan.objects.create(
            tenant=cls.tenant, name='Glow Club', sku='GC',
            price_cents=9900,
        )
        MembershipPlanItem.objects.create(
            plan=cls.plan, service=cls.facial, quantity_per_cycle=1,
        )
        appt = Appointment.objects.create(
            tenant=cls.tenant,
            customer=cls.customer,
            provider=cls.provider,
            service=cls.facial,
            location=cls.tenant.locations.get(is_default=True),
            start_time=timezone.now() + dt.timedelta(hours=1),
            end_time=timezone.now() + dt.timedelta(hours=2),
            status=Appointment.Status.CHECKED_IN,
            quoted_price_cents=cls.facial.price_cents,
            created_by=cls.owner,
        )
        invoice = Invoice.objects.get(appointment=appt)
        cls.line = invoice.line_items.first()
        cls.subscription = Subscription.objects.create(
            tenant=cls.tenant,
            customer=cls.customer,
            plan=cls.plan,
            source_invoice_line=cls.line,
            name='Glow Club',
            price_cents=9900,
            billing_interval=MembershipPlan.BillingInterval.MONTHLY,
            status=Subscription.Status.ACTIVE,
            started_at=timezone.now(),
            current_period_starts_at=timezone.now(),
            current_period_ends_at=timezone.now() + dt.timedelta(days=30),
        )

    def setUp(self):
        self.client = _client_for(self.owner)

    def test_list_filtered_by_customer(self):
        response = self.client.get(
            reverse('subscription-list')
            + f'?customer={self.customer.pk}',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['name'], 'Glow Club')

    def test_list_filtered_by_status(self):
        response = self.client.get(
            reverse('subscription-list')
            + '?status=active',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(len(response.data), 1)

        response = self.client.get(
            reverse('subscription-list')
            + '?status=cancelled',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(len(response.data), 0)

    def test_cancel_requires_reason(self):
        response = self.client.post(
            reverse('subscription-cancel', kwargs={'pk': self.subscription.pk}),
            data={},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cancel_active_subscription(self):
        response = self.client.post(
            reverse('subscription-cancel', kwargs={'pk': self.subscription.pk}),
            data={'reason': 'Customer requested cancellation'},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.status, Subscription.Status.CANCELLED)
        self.assertEqual(
            self.subscription.cancel_reason,
            'Customer requested cancellation',
        )
        self.assertEqual(self.subscription.cancelled_by, self.owner)

    def test_cancel_already_cancelled_409(self):
        self.subscription.status = Subscription.Status.CANCELLED
        self.subscription.save()
        response = self.client.post(
            reverse('subscription-cancel', kwargs={'pk': self.subscription.pk}),
            data={'reason': 'duplicate cancel'},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    def test_front_desk_cannot_cancel(self):
        fd_user, _ = _make_front_desk(self.tenant)
        response = _client_for(fd_user).post(
            reverse('subscription-cancel', kwargs={'pk': self.subscription.pk}),
            data={'reason': 'sneaky'},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_cancel_writes_audit_log(self):
        self.client.post(
            reverse('subscription-cancel', kwargs={'pk': self.subscription.pk}),
            data={'reason': 'moved out of state'},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        log = AuditLog.objects.filter(
            resource_type='subscription',
            action=AuditLog.Action.UPDATE,
        ).order_by('-id').first()
        self.assertIsNotNone(log)
        self.assertEqual(log.metadata.get('event'), 'cancelled')
        self.assertEqual(log.metadata.get('from_status'), 'active')
        self.assertEqual(log.metadata.get('reason'), 'moved out of state')
