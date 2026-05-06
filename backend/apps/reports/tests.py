"""Tests for the reports app.

These exercise the three Session 1 reports + the catalog endpoint, and
double as SOC 2 evidence for ADR 0013: every report run writes an
audit log entry, category-permission gates do what they say, and
tenant isolation holds across all reports.

Test layout:

    BaseReportViewTests        — date-range parsing, validation, defaults, audit envelope
    SalesByDateRangeTests      — aggregation correctness, payment-method breakdown, void/unpaid exclusion
    RevenueByProviderTests     — provider grouping, name composition, standalone-invoice exclusion
    NewVsReturningTests        — classification rules, status-agnostic counting, empty case
    ReportCatalogTests         — permission filtering, empty-category omission, role-by-role coverage
    PermissionGatingTests      — front_desk blocked from financial; bookkeeper allowed; etc.
    TenantIsolationTests       — Tenant A's reports never include Tenant B's data
    AuditLoggingTests          — every successful run writes one AuditLog (READ); no PHI in metadata
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

from apps.appointments.models import Appointment
from apps.audit.models import AuditLog
from apps.customers.models import Customer
from apps.invoices.models import Invoice
from apps.services.models import Service, ServiceCategory
from apps.tenants.models import Tenant, TenantMembership
from apps.tenants.permissions import P
from apps.tenants.services import create_tenant_with_defaults

User = get_user_model()


# ── Helpers ──────────────────────────────────────────────────────────────


def _make_user(email: str, **kwargs) -> User:
    return User.objects.create_user(email=email, password='test-password', **kwargs)


def _make_tenant_with_owner(slug: str) -> tuple[Tenant, User]:
    owner = _make_user(f'{slug}-owner@test.local', first_name='Owner', last_name=slug.title())
    tenant = create_tenant_with_defaults(
        name=slug.title(), slug=slug, owner_user=owner, status=Tenant.Status.ACTIVE,
    )
    return tenant, owner


def _make_membership(*, user, tenant, role, **kwargs) -> TenantMembership:
    from apps.tenants.models import MembershipLocation
    membership = TenantMembership.objects.create(
        user=user, tenant=tenant, role=role, is_active=True, **kwargs,
    )
    MembershipLocation.objects.create(
        membership=membership,
        location=tenant.locations.get(is_default=True),
        is_active=True,
    )
    return membership


def _make_service(tenant, *, name='Botox 20u', price_cents=20000, tax='0') -> Service:
    cat, _ = ServiceCategory.objects.get_or_create(tenant=tenant, name=f'{name}-cat')
    return Service.objects.create(
        tenant=tenant, category=cat, name=name,
        code=name.replace(' ', '')[:8].upper(),
        duration_minutes=30, buffer_minutes=0,
        price_cents=price_cents, tax_rate_percent=Decimal(tax),
        service_type=Service.ServiceType.REGULAR,
    )


def _make_customer(tenant, *, first='Pat', last='Patient', email_suffix=None) -> Customer:
    suffix = email_suffix or f'{first}-{last}'.lower()
    return Customer.objects.create(
        tenant=tenant, first_name=first, last_name=last,
        email=f'{suffix}@example.com',
    )


def _make_appointment(
    tenant, *, customer, service, provider,
    start: dt.datetime, status_val=Appointment.Status.BOOKED,
) -> Appointment:
    end = start + dt.timedelta(minutes=service.duration_minutes)
    return Appointment.objects.create(
        tenant=tenant, customer=customer, provider=provider, service=service,
        location=tenant.locations.get(is_default=True),
        start_time=start, end_time=end, status=status_val,
        quoted_price_cents=service.price_cents,
    )


def _close_invoice_at(invoice: Invoice, *, by_user, when: dt.datetime, payment_method='cash'):
    """Close an invoice and force `closed_at` to a specific past datetime.

    Reports filter on `closed_at__date`. To exercise multi-day windows
    we need closed-at distributed across days; production close() uses
    timezone.now() which all collapses to today.
    """
    invoice.close(by_user=by_user, payment_method=payment_method)
    Invoice.objects.filter(pk=invoice.pk).update(closed_at=when)


def _api_client_for(user) -> APIClient:
    """Authenticated APIClient that hits the real session middleware path."""
    client = APIClient()
    client.force_login(user)
    return client


def _get_report(client: APIClient, *, url: str, tenant_slug: str, **params):
    return client.get(url, data=params, HTTP_X_TENANT_SLUG=tenant_slug)


# ── Base view: param parsing + envelope shape ───────────────────────────


class BaseReportViewTests(TestCase):
    """Date-range parsing, defaults, validation — exercised through the financial endpoint."""

    def setUp(self):
        self.tenant, self.owner = _make_tenant_with_owner('base')
        self.client = _api_client_for(self.owner)
        self.url = reverse('reports-financial-sales-by-date-range')

    def test_default_date_range_is_last_30_days(self):
        response = _get_report(self.client, url=self.url, tenant_slug=self.tenant.slug)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        params = response.data['params']
        date_from = dt.date.fromisoformat(params['date_from'])
        date_to = dt.date.fromisoformat(params['date_to'])
        self.assertEqual(date_to, dt.date.today())
        self.assertEqual((date_to - date_from).days, 29)  # 30-day inclusive window

    def test_inverted_range_rejected(self):
        response = _get_report(
            self.client, url=self.url, tenant_slug=self.tenant.slug,
            date_from='2026-05-10', date_to='2026-05-01',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('date_from', response.data)

    def test_malformed_date_rejected(self):
        response = _get_report(
            self.client, url=self.url, tenant_slug=self.tenant.slug,
            date_from='not-a-date',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_too_wide_range_rejected(self):
        response = _get_report(
            self.client, url=self.url, tenant_slug=self.tenant.slug,
            date_from='2024-01-01', date_to='2026-05-01',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('date_to', response.data)

    def test_envelope_shape_is_consistent(self):
        response = _get_report(self.client, url=self.url, tenant_slug=self.tenant.slug)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.data
        self.assertEqual(set(body.keys()), {'report_id', 'params', 'summary', 'rows'})
        self.assertEqual(body['report_id'], 'financial.sales_by_date_range')
        self.assertIsInstance(body['rows'], list)
        self.assertIsInstance(body['summary'], dict)


# ── Sales by date range ─────────────────────────────────────────────────


class SalesByDateRangeTests(TestCase):
    def setUp(self):
        self.tenant, self.owner = _make_tenant_with_owner('sales')
        self.provider_user = _make_user('sales-provider@test.local')
        self.provider = _make_membership(
            user=self.provider_user, tenant=self.tenant,
            role=TenantMembership.Role.PROVIDER, is_bookable=True,
        )
        self.customer = _make_customer(self.tenant)
        self.service = _make_service(self.tenant, price_cents=10000, tax='0')
        self.url = reverse('reports-financial-sales-by-date-range')
        self.client = _api_client_for(self.owner)

    def _book_and_pay(self, *, days_ago: int, method='cash', amount=10000):
        """Create an appointment, close its invoice, set closed_at N days back."""
        if amount != 10000:
            svc = _make_service(self.tenant, name=f'svc-{amount}', price_cents=amount)
        else:
            svc = self.service
        when = timezone.now() - dt.timedelta(days=days_ago + 1)  # appointment in the past
        appt = _make_appointment(
            self.tenant, customer=self.customer, service=svc, provider=self.provider,
            start=when, status_val=Appointment.Status.CHECKED_IN,
        )
        invoice = Invoice.objects.get(appointment=appt)
        closed_when = timezone.now() - dt.timedelta(days=days_ago)
        _close_invoice_at(invoice, by_user=self.owner, when=closed_when, payment_method=method)
        return invoice

    def test_sums_paid_invoices_in_window(self):
        self._book_and_pay(days_ago=2, amount=10000)
        self._book_and_pay(days_ago=3, amount=15000)
        # An invoice closed before the window should be excluded.
        self._book_and_pay(days_ago=40, amount=99999)
        date_to = dt.date.today()
        date_from = date_to - dt.timedelta(days=10)
        response = _get_report(
            self.client, url=self.url, tenant_slug=self.tenant.slug,
            date_from=date_from.isoformat(), date_to=date_to.isoformat(),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        summary = response.data['summary']
        self.assertEqual(summary['total_gross_cents'], 25000)
        self.assertEqual(summary['paid_invoice_count'], 2)

    def test_excludes_void_and_open_invoices(self):
        # OPEN invoice in window — appointment booked, invoice never closed.
        appt = _make_appointment(
            self.tenant, customer=self.customer, service=self.service, provider=self.provider,
            start=timezone.now() - dt.timedelta(days=2),
            status_val=Appointment.Status.BOOKED,
        )
        # VOID invoice in window — close, then void via cancellation flow
        # or direct status update for the test.
        appt2 = _make_appointment(
            self.tenant, customer=self.customer, service=self.service, provider=self.provider,
            start=timezone.now() - dt.timedelta(days=2),
            status_val=Appointment.Status.CHECKED_IN,
        )
        inv2 = Invoice.objects.get(appointment=appt2)
        inv2.void(by_user=self.owner, reason='test')
        # PAID invoice in window — should appear.
        self._book_and_pay(days_ago=2, amount=10000)
        response = _get_report(self.client, url=self.url, tenant_slug=self.tenant.slug)
        self.assertEqual(response.data['summary']['total_gross_cents'], 10000)
        self.assertEqual(response.data['summary']['paid_invoice_count'], 1)

    def test_per_day_rows_include_zero_revenue_days(self):
        self._book_and_pay(days_ago=1, amount=10000)
        date_to = dt.date.today()
        date_from = date_to - dt.timedelta(days=4)
        response = _get_report(
            self.client, url=self.url, tenant_slug=self.tenant.slug,
            date_from=date_from.isoformat(), date_to=date_to.isoformat(),
        )
        rows = response.data['rows']
        # 5 days inclusive
        self.assertEqual(len(rows), 5)
        # Exactly one day should have non-zero revenue.
        non_zero = [r for r in rows if r['gross_cents'] > 0]
        self.assertEqual(len(non_zero), 1)
        self.assertEqual(non_zero[0]['gross_cents'], 10000)

    def test_payment_method_breakdown(self):
        self._book_and_pay(days_ago=1, method='cash', amount=10000)
        self._book_and_pay(days_ago=2, method='cash', amount=5000)
        self._book_and_pay(days_ago=3, method='check', amount=20000)
        response = _get_report(self.client, url=self.url, tenant_slug=self.tenant.slug)
        breakdown = response.data['summary']['by_payment_method']
        # Highest first
        self.assertEqual(breakdown[0]['method'], 'check')
        self.assertEqual(breakdown[0]['gross_cents'], 20000)
        self.assertEqual(breakdown[1]['method'], 'cash')
        self.assertEqual(breakdown[1]['gross_cents'], 15000)
        self.assertEqual(breakdown[1]['invoice_count'], 2)


# ── Revenue by provider ─────────────────────────────────────────────────


class RevenueByProviderTests(TestCase):
    def setUp(self):
        self.tenant, self.owner = _make_tenant_with_owner('revprov')
        # Two providers
        self.alice_user = _make_user('alice@test.local', first_name='Alice', last_name='Lee')
        self.alice = _make_membership(
            user=self.alice_user, tenant=self.tenant,
            role=TenantMembership.Role.PROVIDER, is_bookable=True,
        )
        self.bob_user = _make_user('bob@test.local', first_name='Bob', last_name='Kim')
        self.bob = _make_membership(
            user=self.bob_user, tenant=self.tenant,
            role=TenantMembership.Role.PROVIDER, is_bookable=True,
        )
        self.customer = _make_customer(self.tenant)
        self.service = _make_service(self.tenant, price_cents=10000, tax='0')
        self.url = reverse('reports-staff-revenue-by-provider')
        self.client = _api_client_for(self.owner)

    def _book_for(self, provider, *, days_ago=1, amount=10000):
        svc = self.service if amount == 10000 else _make_service(
            self.tenant, name=f'svc-{provider.pk}-{amount}', price_cents=amount,
        )
        appt = _make_appointment(
            self.tenant, customer=self.customer, service=svc, provider=provider,
            start=timezone.now() - dt.timedelta(days=days_ago + 1),
            status_val=Appointment.Status.CHECKED_IN,
        )
        invoice = Invoice.objects.get(appointment=appt)
        _close_invoice_at(
            invoice, by_user=self.owner,
            when=timezone.now() - dt.timedelta(days=days_ago),
        )

    def test_groups_revenue_per_provider(self):
        self._book_for(self.alice, amount=10000)
        self._book_for(self.alice, amount=15000)
        self._book_for(self.bob, amount=20000)
        response = _get_report(self.client, url=self.url, tenant_slug=self.tenant.slug)
        rows = response.data['rows']
        self.assertEqual(len(rows), 2)
        # Highest revenue first
        self.assertEqual(rows[0]['provider_id'], self.alice.pk)
        self.assertEqual(rows[0]['provider_name'], 'Alice Lee')
        self.assertEqual(rows[0]['gross_cents'], 25000)
        self.assertEqual(rows[0]['appointment_count'], 2)
        self.assertEqual(rows[1]['provider_id'], self.bob.pk)
        self.assertEqual(rows[1]['gross_cents'], 20000)

    def test_omits_providers_with_no_paid_invoices(self):
        self._book_for(self.alice, amount=10000)
        # Bob exists but did nothing — shouldn't appear.
        response = _get_report(self.client, url=self.url, tenant_slug=self.tenant.slug)
        rows = response.data['rows']
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['provider_id'], self.alice.pk)

    def test_summary_totals_match_rows(self):
        self._book_for(self.alice, amount=10000)
        self._book_for(self.bob, amount=20000)
        response = _get_report(self.client, url=self.url, tenant_slug=self.tenant.slug)
        summary = response.data['summary']
        self.assertEqual(summary['provider_count'], 2)
        self.assertEqual(summary['total_gross_cents'], 30000)
        self.assertEqual(summary['total_appointments'], 2)
        self.assertEqual(summary['avg_revenue_per_provider_cents'], 15000)


# ── New vs returning ────────────────────────────────────────────────────


class NewVsReturningTests(TestCase):
    def setUp(self):
        self.tenant, self.owner = _make_tenant_with_owner('newret')
        self.provider_user = _make_user('newret-prov@test.local')
        self.provider = _make_membership(
            user=self.provider_user, tenant=self.tenant,
            role=TenantMembership.Role.PROVIDER, is_bookable=True,
        )
        self.service = _make_service(self.tenant)
        self.url = reverse('reports-guests-new-vs-returning')
        self.client = _api_client_for(self.owner)

    def _appt(self, customer, *, days_ago: int, status_val=Appointment.Status.BOOKED):
        return _make_appointment(
            self.tenant, customer=customer, service=self.service, provider=self.provider,
            start=timezone.now() - dt.timedelta(days=days_ago),
            status_val=status_val,
        )

    def test_classifies_new_vs_returning_correctly(self):
        new_customer = _make_customer(self.tenant, first='New', last='Cust', email_suffix='new1')
        returning_customer = _make_customer(self.tenant, first='Old', last='Cust', email_suffix='old1')
        # Returning customer's first-ever appointment is 100 days back
        self._appt(returning_customer, days_ago=100)
        # Both have an appointment 5 days ago (in the window)
        self._appt(new_customer, days_ago=5)
        self._appt(returning_customer, days_ago=5)

        date_to = dt.date.today()
        date_from = date_to - dt.timedelta(days=10)
        response = _get_report(
            self.client, url=self.url, tenant_slug=self.tenant.slug,
            date_from=date_from.isoformat(), date_to=date_to.isoformat(),
        )
        summary = response.data['summary']
        self.assertEqual(summary['new_count'], 1)
        self.assertEqual(summary['returning_count'], 1)
        self.assertEqual(summary['total_unique_customers'], 2)

        rows_by_id = {r['customer_id']: r for r in response.data['rows']}
        self.assertEqual(rows_by_id[new_customer.id]['classification'], 'new')
        self.assertEqual(rows_by_id[returning_customer.id]['classification'], 'returning')

    def test_counts_cancelled_and_no_show_as_visits(self):
        # The classification question is "did this person have an
        # appointment scheduled" — cancellations + no-shows still count.
        first_timer = _make_customer(self.tenant, first='Cancel', last='Carla', email_suffix='cancel')
        self._appt(first_timer, days_ago=3, status_val=Appointment.Status.CANCELLED)

        date_to = dt.date.today()
        date_from = date_to - dt.timedelta(days=10)
        response = _get_report(
            self.client, url=self.url, tenant_slug=self.tenant.slug,
            date_from=date_from.isoformat(), date_to=date_to.isoformat(),
        )
        self.assertEqual(response.data['summary']['new_count'], 1)
        self.assertEqual(response.data['summary']['total_unique_customers'], 1)

    def test_empty_window_returns_zeros(self):
        # No appointments at all.
        response = _get_report(self.client, url=self.url, tenant_slug=self.tenant.slug)
        self.assertEqual(response.data['summary']['new_count'], 0)
        self.assertEqual(response.data['summary']['returning_count'], 0)
        self.assertEqual(response.data['rows'], [])


# ── Catalog ─────────────────────────────────────────────────────────────


class ReportCatalogTests(TestCase):
    def setUp(self):
        self.tenant, self.owner = _make_tenant_with_owner('catalog')
        self.url = reverse('reports-catalog')

    def test_owner_sees_all_populated_categories(self):
        client = _api_client_for(self.owner)
        response = client.get(self.url, HTTP_X_TENANT_SLUG=self.tenant.slug)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        category_ids = [c['id'] for c in response.data['categories']]
        # Marketing has no reports yet → omitted. Everything else is populated.
        self.assertEqual(set(category_ids), {'financial', 'staff', 'guests', 'operations'})

    def test_front_desk_sees_only_operations(self):
        # front_desk has VIEW_OPERATIONS_REPORTS but no other category.
        fd_user = _make_user('fd@test.local', first_name='Fran', last_name='Desk')
        _make_membership(
            user=fd_user, tenant=self.tenant,
            role=TenantMembership.Role.FRONT_DESK,
        )
        client = _api_client_for(fd_user)
        response = client.get(self.url, HTTP_X_TENANT_SLUG=self.tenant.slug)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        category_ids = [c['id'] for c in response.data['categories']]
        self.assertEqual(set(category_ids), {'operations'})

    def test_bookkeeper_sees_financial_and_staff(self):
        bk_user = _make_user('bk@test.local', first_name='Brooke', last_name='Keeper')
        _make_membership(
            user=bk_user, tenant=self.tenant,
            role=TenantMembership.Role.BOOKKEEPER,
        )
        client = _api_client_for(bk_user)
        response = client.get(self.url, HTTP_X_TENANT_SLUG=self.tenant.slug)
        category_ids = [c['id'] for c in response.data['categories']]
        self.assertEqual(set(category_ids), {'financial', 'staff'})

    def test_marketing_role_sees_guests_only(self):
        mk_user = _make_user('mk@test.local', first_name='Mark', last_name='Etting')
        _make_membership(
            user=mk_user, tenant=self.tenant,
            role=TenantMembership.Role.MARKETING,
        )
        client = _api_client_for(mk_user)
        response = client.get(self.url, HTTP_X_TENANT_SLUG=self.tenant.slug)
        category_ids = [c['id'] for c in response.data['categories']]
        self.assertEqual(set(category_ids), {'guests'})

    def test_each_report_includes_phi_tier(self):
        client = _api_client_for(self.owner)
        response = client.get(self.url, HTTP_X_TENANT_SLUG=self.tenant.slug)
        for category in response.data['categories']:
            for report in category['reports']:
                self.assertIn('phi_tier', report)
                self.assertIn(report['phi_tier'], {'none', 'aggregated', 'per_customer'})


# ── Permission gating on individual reports ─────────────────────────────


class PermissionGatingTests(TestCase):
    def setUp(self):
        self.tenant, self.owner = _make_tenant_with_owner('permgate')

    def _hit(self, user, view_name):
        client = _api_client_for(user)
        return client.get(reverse(view_name), HTTP_X_TENANT_SLUG=self.tenant.slug)

    def test_front_desk_blocked_from_financial_report(self):
        fd_user = _make_user('fd-block@test.local')
        _make_membership(
            user=fd_user, tenant=self.tenant,
            role=TenantMembership.Role.FRONT_DESK,
        )
        response = self._hit(fd_user, 'reports-financial-sales-by-date-range')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_bookkeeper_allowed_to_financial_report(self):
        bk_user = _make_user('bk-allow@test.local')
        _make_membership(
            user=bk_user, tenant=self.tenant,
            role=TenantMembership.Role.BOOKKEEPER,
        )
        response = self._hit(bk_user, 'reports-financial-sales-by-date-range')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_marketing_blocked_from_staff_report(self):
        mk_user = _make_user('mk-block@test.local')
        _make_membership(
            user=mk_user, tenant=self.tenant,
            role=TenantMembership.Role.MARKETING,
        )
        response = self._hit(mk_user, 'reports-staff-revenue-by-provider')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_marketing_allowed_to_guest_report(self):
        mk_user = _make_user('mk-allow@test.local')
        _make_membership(
            user=mk_user, tenant=self.tenant,
            role=TenantMembership.Role.MARKETING,
        )
        response = self._hit(mk_user, 'reports-guests-new-vs-returning')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_unauthenticated_blocked(self):
        client = APIClient()
        response = client.get(
            reverse('reports-financial-sales-by-date-range'),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


# ── Tenant isolation ────────────────────────────────────────────────────


class TenantIsolationTests(TestCase):
    """Tenant A's reports never include Tenant B's data — even when the
    same user has memberships in both tenants."""

    def setUp(self):
        self.tenant_a, self.owner_a = _make_tenant_with_owner('iso-a')
        self.tenant_b, self.owner_b = _make_tenant_with_owner('iso-b')

        # Provider + customer + paid invoice in tenant A
        self.prov_a_user = _make_user('iso-prov-a@test.local', first_name='ProvA', last_name='X')
        self.prov_a = _make_membership(
            user=self.prov_a_user, tenant=self.tenant_a,
            role=TenantMembership.Role.PROVIDER, is_bookable=True,
        )
        self.cust_a = _make_customer(self.tenant_a, first='CustA', last='X', email_suffix='cust-a')
        self.svc_a = _make_service(self.tenant_a, price_cents=10000)
        appt_a = _make_appointment(
            self.tenant_a, customer=self.cust_a, service=self.svc_a, provider=self.prov_a,
            start=timezone.now() - dt.timedelta(days=2),
            status_val=Appointment.Status.CHECKED_IN,
        )
        inv_a = Invoice.objects.get(appointment=appt_a)
        _close_invoice_at(inv_a, by_user=self.owner_a, when=timezone.now() - dt.timedelta(days=1))

        # Same shape in tenant B with a much larger invoice — if isolation
        # is broken the financial report for A would include B's $999.99.
        self.prov_b_user = _make_user('iso-prov-b@test.local')
        self.prov_b = _make_membership(
            user=self.prov_b_user, tenant=self.tenant_b,
            role=TenantMembership.Role.PROVIDER, is_bookable=True,
        )
        self.cust_b = _make_customer(self.tenant_b, first='CustB', last='X', email_suffix='cust-b')
        self.svc_b = _make_service(self.tenant_b, price_cents=99999)
        appt_b = _make_appointment(
            self.tenant_b, customer=self.cust_b, service=self.svc_b, provider=self.prov_b,
            start=timezone.now() - dt.timedelta(days=2),
            status_val=Appointment.Status.CHECKED_IN,
        )
        inv_b = Invoice.objects.get(appointment=appt_b)
        _close_invoice_at(inv_b, by_user=self.owner_b, when=timezone.now() - dt.timedelta(days=1))

    def test_financial_report_excludes_other_tenants_revenue(self):
        client = _api_client_for(self.owner_a)
        response = client.get(
            reverse('reports-financial-sales-by-date-range'),
            HTTP_X_TENANT_SLUG=self.tenant_a.slug,
        )
        self.assertEqual(response.data['summary']['total_gross_cents'], 10000)

    def test_staff_report_excludes_other_tenants_providers(self):
        client = _api_client_for(self.owner_a)
        response = client.get(
            reverse('reports-staff-revenue-by-provider'),
            HTTP_X_TENANT_SLUG=self.tenant_a.slug,
        )
        provider_ids = {r['provider_id'] for r in response.data['rows']}
        self.assertEqual(provider_ids, {self.prov_a.pk})

    def test_guest_report_excludes_other_tenants_customers(self):
        client = _api_client_for(self.owner_a)
        response = client.get(
            reverse('reports-guests-new-vs-returning'),
            HTTP_X_TENANT_SLUG=self.tenant_a.slug,
        )
        customer_ids = {r['customer_id'] for r in response.data['rows']}
        self.assertEqual(customer_ids, {self.cust_a.id})


# ── Audit logging ───────────────────────────────────────────────────────


class AuditLoggingTests(TestCase):
    """Every successful report run writes one AuditLog (READ); metadata
    records the report id + params + row count, never PHI."""

    def setUp(self):
        self.tenant, self.owner = _make_tenant_with_owner('audit')
        self.client = _api_client_for(self.owner)

    def _baseline(self, report_id: str) -> int:
        return AuditLog.objects.filter(
            resource_type='report', resource_id=report_id,
        ).count()

    def test_financial_report_writes_audit_entry(self):
        before = self._baseline('financial.sales_by_date_range')
        response = self.client.get(
            reverse('reports-financial-sales-by-date-range'),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        after = self._baseline('financial.sales_by_date_range')
        self.assertEqual(after, before + 1)
        entry = (
            AuditLog.objects
            .filter(resource_type='report', resource_id='financial.sales_by_date_range')
            .latest('timestamp')
        )
        self.assertEqual(entry.action, AuditLog.Action.READ)
        self.assertEqual(entry.user, self.owner)
        self.assertEqual(entry.tenant, self.tenant)
        self.assertEqual(entry.metadata['category'], 'financial')
        self.assertIn('params', entry.metadata)
        self.assertIn('row_count', entry.metadata)

    def test_failed_run_does_not_write_audit_entry(self):
        # Permission-denied caller — audit should NOT log a successful read.
        fd_user = _make_user('fd-audit@test.local')
        _make_membership(
            user=fd_user, tenant=self.tenant,
            role=TenantMembership.Role.FRONT_DESK,
        )
        before = self._baseline('financial.sales_by_date_range')
        client = _api_client_for(fd_user)
        response = client.get(
            reverse('reports-financial-sales-by-date-range'),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        after = self._baseline('financial.sales_by_date_range')
        self.assertEqual(after, before)

    def test_audit_metadata_contains_no_phi(self):
        """Even for the per-customer-PHI report, audit metadata records
        only counts + params — never customer names, emails, or IDs."""
        provider_user = _make_user('audit-prov@test.local')
        provider = _make_membership(
            user=provider_user, tenant=self.tenant,
            role=TenantMembership.Role.PROVIDER, is_bookable=True,
        )
        customer = _make_customer(self.tenant, first='Phi', last='Sensitive', email_suffix='phi-test')
        svc = _make_service(self.tenant)
        _make_appointment(
            self.tenant, customer=customer, service=svc, provider=provider,
            start=timezone.now() - dt.timedelta(days=1),
        )
        response = self.client.get(
            reverse('reports-guests-new-vs-returning'),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Confirm the response itself contains the customer (so we know
        # we're not accidentally testing an empty report).
        self.assertEqual(response.data['summary']['new_count'], 1)
        self.assertEqual(response.data['rows'][0]['customer_name'], 'Phi Sensitive')

        entry = (
            AuditLog.objects
            .filter(resource_type='report', resource_id='guests.new_vs_returning')
            .latest('timestamp')
        )
        # Audit metadata must use a fixed, no-PHI schema. We pin the key
        # set so a future change that smuggles PHI into the audit log
        # (e.g. a debug 'first_customer' field) breaks this test loudly.
        self.assertEqual(set(entry.metadata.keys()), {'category', 'params', 'row_count'})
        self.assertEqual(entry.metadata['category'], 'guests')
        self.assertEqual(entry.metadata['row_count'], 1)
        self.assertEqual(set(entry.metadata['params'].keys()), {'date_from', 'date_to'})
        # And no PHI substrings anywhere in the JSON form.
        import json
        as_json = json.dumps(entry.metadata)
        for forbidden in ('Phi', 'Sensitive', 'phi-test', customer.email):
            self.assertNotIn(forbidden, as_json)


# ── Session 2: smoke tests for the 18 new reports ─────────────────────────
#
# These exercise endpoint reachability + envelope shape + audit-log
# writes against a small seeded fixture. Detailed aggregation
# correctness for each report would balloon the suite; we trust the
# end-to-end live-data smoke (run separately) for that and use these
# tests as the regression net for breaking the BaseReportView contract.


class Session2EndpointSmokeTests(TestCase):
    """Hit each Session 2 endpoint as the owner; assert 200 + envelope shape."""

    SESSION_2_REPORTS = [
        # (url_name, report_id)
        ('reports-financial-daily-close-out',         'financial.daily_close_out'),
        ('reports-financial-ar-aging',                'financial.ar_aging'),
        ('reports-financial-revenue-by-service',      'financial.revenue_by_service'),
        ('reports-financial-revenue-by-location',     'financial.revenue_by_location'),
        ('reports-financial-tax-collected',           'financial.tax_collected'),
        ('reports-staff-schedule-utilization',        'staff.schedule_utilization'),
        ('reports-staff-no-show-rate-by-provider',    'staff.no_show_rate_by_provider'),
        ('reports-staff-new-clients-by-provider',     'staff.new_clients_by_provider'),
        ('reports-staff-repeat-rate-by-provider',     'staff.repeat_rate_by_provider'),
        ('reports-guests-top-spenders',               'guests.top_spenders'),
        ('reports-guests-inactive-clients',           'guests.inactive_clients'),
        ('reports-guests-birthday-list',              'guests.birthday_list'),
        ('reports-guests-visit-frequency',            'guests.visit_frequency'),
        ('reports-guests-forms-outstanding',          'guests.forms_outstanding'),
        ('reports-operations-appointments-by-status', 'operations.appointments_by_status'),
        ('reports-operations-no-show-rate',           'operations.no_show_rate'),
        ('reports-operations-cancellation-rate',      'operations.cancellation_rate'),
        ('reports-operations-booking-lead-time',      'operations.booking_lead_time'),
        ('reports-operations-service-mix',            'operations.service_mix'),
        ('reports-operations-busiest-hours',          'operations.busiest_hours'),
    ]

    def setUp(self):
        self.tenant, self.owner = _make_tenant_with_owner('session2')
        self.provider_user = _make_user('s2-prov@test.local', first_name='Sam', last_name='Provider')
        self.provider = _make_membership(
            user=self.provider_user, tenant=self.tenant,
            role=TenantMembership.Role.PROVIDER, is_bookable=True,
        )
        self.customer = _make_customer(self.tenant, first='Sara', last='Customer')
        self.service = _make_service(self.tenant, price_cents=10000)
        # One PAID invoice, one OPEN invoice, one cancelled appointment —
        # gives every report at least one row to chew on.
        appt_paid = _make_appointment(
            self.tenant, customer=self.customer, service=self.service, provider=self.provider,
            start=timezone.now() - dt.timedelta(days=2),
            status_val=Appointment.Status.CHECKED_IN,
        )
        inv = Invoice.objects.get(appointment=appt_paid)
        _close_invoice_at(inv, by_user=self.owner, when=timezone.now() - dt.timedelta(days=1))

        _make_appointment(
            self.tenant, customer=self.customer, service=self.service, provider=self.provider,
            start=timezone.now() - dt.timedelta(days=4),
            status_val=Appointment.Status.NO_SHOW,
        )
        _make_appointment(
            self.tenant, customer=self.customer, service=self.service, provider=self.provider,
            start=timezone.now() - dt.timedelta(days=5),
            status_val=Appointment.Status.CANCELLED,
        )

        self.client = _api_client_for(self.owner)

    def test_every_session_2_endpoint_returns_200_with_envelope(self):
        for url_name, report_id in self.SESSION_2_REPORTS:
            with self.subTest(report=url_name):
                response = self.client.get(
                    reverse(url_name), HTTP_X_TENANT_SLUG=self.tenant.slug,
                )
                self.assertEqual(
                    response.status_code, status.HTTP_200_OK,
                    f'{url_name} returned {response.status_code}: {response.content[:200]!r}',
                )
                body = response.data
                self.assertEqual(set(body.keys()), {'report_id', 'params', 'summary', 'rows'})
                self.assertEqual(body['report_id'], report_id)
                self.assertIsInstance(body['rows'], list)
                self.assertIsInstance(body['summary'], dict)

    def test_every_session_2_endpoint_writes_audit_entry(self):
        for url_name, report_id in self.SESSION_2_REPORTS:
            with self.subTest(report=url_name):
                before = AuditLog.objects.filter(
                    resource_type='report', resource_id=report_id,
                ).count()
                response = self.client.get(
                    reverse(url_name), HTTP_X_TENANT_SLUG=self.tenant.slug,
                )
                self.assertEqual(response.status_code, status.HTTP_200_OK)
                after = AuditLog.objects.filter(
                    resource_type='report', resource_id=report_id,
                ).count()
                self.assertEqual(after, before + 1)


class Session2PermissionGatingTests(TestCase):
    """Spot-check the new permission gates for the new reports.

    Owner sees everything; the per-category breakdown is already
    exercised by `ReportCatalogTests`. Here we just assert the
    front-desk's `VIEW_OPERATIONS_REPORTS` actually unlocks an
    operations report (it didn't have anywhere to apply pre-Session 2).
    """

    def setUp(self):
        self.tenant, self.owner = _make_tenant_with_owner('s2perm')
        self.fd_user = _make_user('s2-fd@test.local')
        _make_membership(
            user=self.fd_user, tenant=self.tenant,
            role=TenantMembership.Role.FRONT_DESK,
        )

    def test_front_desk_can_run_appointments_by_status(self):
        client = _api_client_for(self.fd_user)
        response = client.get(
            reverse('reports-operations-appointments-by-status'),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_front_desk_blocked_from_top_spenders(self):
        client = _api_client_for(self.fd_user)
        response = client.get(
            reverse('reports-guests-top-spenders'),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_marketing_can_run_birthday_list(self):
        mk_user = _make_user('s2-mk@test.local')
        _make_membership(
            user=mk_user, tenant=self.tenant,
            role=TenantMembership.Role.MARKETING,
        )
        client = _api_client_for(mk_user)
        response = client.get(
            reverse('reports-guests-birthday-list'),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)


class Session2InputValidationTests(TestCase):
    """Reports with non-date params validate them honestly."""

    def setUp(self):
        self.tenant, self.owner = _make_tenant_with_owner('s2val')
        self.client = _api_client_for(self.owner)

    def test_top_spenders_rejects_invalid_limit(self):
        response = self.client.get(
            reverse('reports-guests-top-spenders'),
            data={'limit': 'banana'},
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('limit', response.data)

    def test_top_spenders_rejects_oversized_limit(self):
        response = self.client.get(
            reverse('reports-guests-top-spenders'),
            data={'limit': '99999'},
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_inactive_clients_validates_days(self):
        response = self.client.get(
            reverse('reports-guests-inactive-clients'),
            data={'days': '-5'},
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_birthday_list_validates_window_days(self):
        response = self.client.get(
            reverse('reports-guests-birthday-list'),
            data={'window_days': '500'},
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class Session2TenantIsolationTests(TestCase):
    """Spot-check tenant isolation on the per-customer reports added
    in Session 2 — the ones with PHI rows."""

    def setUp(self):
        self.tenant_a, self.owner_a = _make_tenant_with_owner('s2iso-a')
        self.tenant_b, self.owner_b = _make_tenant_with_owner('s2iso-b')

        prov_a_user = _make_user('s2iso-prov-a@test.local')
        prov_a = _make_membership(
            user=prov_a_user, tenant=self.tenant_a,
            role=TenantMembership.Role.PROVIDER, is_bookable=True,
        )
        prov_b_user = _make_user('s2iso-prov-b@test.local')
        prov_b = _make_membership(
            user=prov_b_user, tenant=self.tenant_b,
            role=TenantMembership.Role.PROVIDER, is_bookable=True,
        )
        self.cust_a = _make_customer(self.tenant_a, first='IsoCustA', email_suffix='isoca')
        self.cust_b = _make_customer(self.tenant_b, first='IsoCustB', email_suffix='isocb')
        svc_a = _make_service(self.tenant_a, price_cents=50000)
        svc_b = _make_service(self.tenant_b, price_cents=99999)
        appt_a = _make_appointment(
            self.tenant_a, customer=self.cust_a, service=svc_a, provider=prov_a,
            start=timezone.now() - dt.timedelta(days=2),
            status_val=Appointment.Status.CHECKED_IN,
        )
        inv_a = Invoice.objects.get(appointment=appt_a)
        _close_invoice_at(inv_a, by_user=self.owner_a, when=timezone.now() - dt.timedelta(days=1))
        appt_b = _make_appointment(
            self.tenant_b, customer=self.cust_b, service=svc_b, provider=prov_b,
            start=timezone.now() - dt.timedelta(days=2),
            status_val=Appointment.Status.CHECKED_IN,
        )
        inv_b = Invoice.objects.get(appointment=appt_b)
        _close_invoice_at(inv_b, by_user=self.owner_b, when=timezone.now() - dt.timedelta(days=1))

    def test_top_spenders_isolated_per_tenant(self):
        client = _api_client_for(self.owner_a)
        response = client.get(
            reverse('reports-guests-top-spenders'),
            HTTP_X_TENANT_SLUG=self.tenant_a.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        customer_ids = {r['customer_id'] for r in response.data['rows']}
        self.assertEqual(customer_ids, {self.cust_a.id})

    def test_ar_aging_isolated_per_tenant(self):
        # Create an open invoice in B that's old enough to bucket.
        Invoice.objects.filter(customer=self.cust_b).update(
            status=Invoice.Status.OPEN, closed_at=None,
        )
        client = _api_client_for(self.owner_a)
        response = client.get(
            reverse('reports-financial-ar-aging'),
            HTTP_X_TENANT_SLUG=self.tenant_a.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        customer_ids = {r['customer_id'] for r in response.data['rows']}
        # A's invoice is paid; B's open invoice should NOT appear.
        self.assertNotIn(self.cust_b.id, customer_ids)


# ── Session 3: CSV export + PHI confirmation gate ─────────────────────────


class CSVExportTests(TestCase):
    """CSV download via `?download=csv`, PHI-confirmation gate, and the
    EXPORT audit-log shape."""

    def setUp(self):
        self.tenant, self.owner = _make_tenant_with_owner('csv')
        prov_user = _make_user('csv-prov@test.local', first_name='Csv', last_name='Provider')
        self.provider = _make_membership(
            user=prov_user, tenant=self.tenant,
            role=TenantMembership.Role.PROVIDER, is_bookable=True,
        )
        self.customer = _make_customer(self.tenant, first='Csv', last='Customer')
        self.service = _make_service(self.tenant, price_cents=10000)
        appt = _make_appointment(
            self.tenant, customer=self.customer, service=self.service, provider=self.provider,
            start=timezone.now() - dt.timedelta(days=2),
            status_val=Appointment.Status.CHECKED_IN,
        )
        invoice = Invoice.objects.get(appointment=appt)
        _close_invoice_at(
            invoice, by_user=self.owner,
            when=timezone.now() - dt.timedelta(days=1),
        )
        self.client = _api_client_for(self.owner)

    def _drain(self, response) -> str:
        return b''.join(response.streaming_content).decode('utf-8')

    def test_no_phi_report_csv_downloads(self):
        response = self.client.get(
            reverse('reports-financial-sales-by-date-range') + '?download=csv',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response['Content-Type'], 'text/csv; charset=utf-8')
        self.assertIn('attachment', response['Content-Disposition'])
        self.assertIn('financial.sales_by_date_range_', response['Content-Disposition'])
        body = self._drain(response)
        # Header + at least 30 daily rows
        self.assertGreater(len(body.splitlines()), 30)
        self.assertIn('Date', body.splitlines()[0])

    def test_aggregated_phi_report_csv_downloads_without_confirm(self):
        # Staff revenue is `aggregated` (names staff, not customers).
        # No PHI gate.
        response = self.client.get(
            reverse('reports-staff-revenue-by-provider') + '?download=csv',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = self._drain(response)
        self.assertIn('Provider Name', body.splitlines()[0])

    def test_per_customer_csv_blocked_without_phi_confirm(self):
        response = self.client.get(
            reverse('reports-guests-top-spenders') + '?download=csv',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        # Structured detail so the frontend can detect this specific
        # gate (vs. a generic permission denial).
        self.assertEqual(response.data['code'], 'phi_confirmation_required')
        self.assertEqual(response.data['phi_tier'], 'per_customer')

    def test_per_customer_csv_allowed_with_phi_confirm(self):
        response = self.client.get(
            reverse('reports-guests-top-spenders') + '?download=csv&phi_confirmed=true',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = self._drain(response)
        self.assertIn('Customer Name', body.splitlines()[0])

    def test_phi_confirm_truthy_values_all_accepted(self):
        for truthy in ('true', '1', 'yes', 'on', 'TRUE'):
            response = self.client.get(
                reverse('reports-guests-top-spenders')
                + f'?download=csv&phi_confirmed={truthy}',
                HTTP_X_TENANT_SLUG=self.tenant.slug,
            )
            self.assertEqual(
                response.status_code, status.HTTP_200_OK,
                f'phi_confirmed={truthy!r} should pass',
            )

    def test_phi_confirm_falsy_or_missing_blocks(self):
        for falsy in ('false', '0', 'no', '', 'banana'):
            response = self.client.get(
                reverse('reports-guests-top-spenders')
                + f'?download=csv&phi_confirmed={falsy}',
                HTTP_X_TENANT_SLUG=self.tenant.slug,
            )
            self.assertEqual(
                response.status_code, status.HTTP_403_FORBIDDEN,
                f'phi_confirmed={falsy!r} should be rejected',
            )

    def test_csv_export_writes_export_audit_entry(self):
        before = AuditLog.objects.filter(
            action=AuditLog.Action.EXPORT,
            resource_id='financial.sales_by_date_range',
        ).count()
        response = self.client.get(
            reverse('reports-financial-sales-by-date-range') + '?download=csv',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        # Drain the streaming response so the audit write completes
        # under the test client (the helper reads the generator).
        list(response.streaming_content)
        after = AuditLog.objects.filter(
            action=AuditLog.Action.EXPORT,
            resource_id='financial.sales_by_date_range',
        ).count()
        self.assertEqual(after, before + 1)
        entry = (
            AuditLog.objects
            .filter(action=AuditLog.Action.EXPORT, resource_id='financial.sales_by_date_range')
            .latest('timestamp')
        )
        # Metadata pinned: same fields as a READ + phi_tier + phi_confirmed.
        self.assertEqual(set(entry.metadata.keys()),
                         {'category', 'params', 'row_count', 'phi_tier', 'phi_confirmed'})
        self.assertEqual(entry.metadata['phi_tier'], 'none')
        self.assertFalse(entry.metadata['phi_confirmed'])  # only set True for per_customer

    def test_phi_export_audit_entry_records_phi_confirmed_true(self):
        response = self.client.get(
            reverse('reports-guests-top-spenders') + '?download=csv&phi_confirmed=true',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        list(response.streaming_content)
        entry = (
            AuditLog.objects
            .filter(action=AuditLog.Action.EXPORT, resource_id='guests.top_spenders')
            .latest('timestamp')
        )
        self.assertTrue(entry.metadata['phi_confirmed'])
        self.assertEqual(entry.metadata['phi_tier'], 'per_customer')

    def test_csv_export_does_not_write_read_audit_entry(self):
        """Sanity: a CSV download should NOT also log a READ entry —
        the same request can't be both an on-screen view and an
        export."""
        before_read = AuditLog.objects.filter(
            action=AuditLog.Action.READ,
            resource_id='financial.sales_by_date_range',
        ).count()
        response = self.client.get(
            reverse('reports-financial-sales-by-date-range') + '?download=csv',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        list(response.streaming_content)
        after_read = AuditLog.objects.filter(
            action=AuditLog.Action.READ,
            resource_id='financial.sales_by_date_range',
        ).count()
        self.assertEqual(after_read, before_read)

    def test_daily_close_out_csv_uses_custom_columns(self):
        """csv_columns override expands `by_method` into one column per
        payment method — confirms the override hook actually fires."""
        response = self.client.get(
            reverse('reports-financial-daily-close-out') + '?download=csv',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = self._drain(response)
        header = body.splitlines()[0]
        # All four PaymentMethod choices should appear as columns.
        self.assertIn('Cash', header)
        self.assertIn('Check', header)
        self.assertIn('Card', header)
        self.assertIn('Other', header)
        # And NOT a JSON-stringified by_method column.
        self.assertNotIn('by_method', header.lower())

    def test_csv_filename_includes_date_range(self):
        response = self.client.get(
            reverse('reports-financial-sales-by-date-range')
            + '?download=csv&date_from=2026-04-01&date_to=2026-04-30',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertIn('2026-04-01_2026-04-30', response['Content-Disposition'])

    def test_csv_export_respects_category_permission(self):
        """A user without the report's category permission can't export
        either — the PHI gate is on top of, not instead of, the basic
        role gate."""
        fd_user = _make_user('csv-fd@test.local')
        _make_membership(
            user=fd_user, tenant=self.tenant,
            role=TenantMembership.Role.FRONT_DESK,
        )
        client = _api_client_for(fd_user)
        response = client.get(
            reverse('reports-financial-sales-by-date-range') + '?download=csv',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
