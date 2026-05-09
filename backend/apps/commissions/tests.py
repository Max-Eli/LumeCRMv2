"""Tests for commissions.

Covers:
  - Money math: `compute_commission_cents` rounding edges
  - Rule resolution: per-category override beats base rate
  - Accrual on invoice close (provider with rule, w/o rule, inactive
    rule, no provider, product line skipped)
  - Idempotency: re-accruing on the same invoice doesn't double up
  - Reversal on invoice reopen
  - Re-close after reopen creates fresh accruals (net = double, but
    one accrual + one reversal + one accrual)
  - Permission gating: rules require MANAGE_STAFF; entries scoped
    to own membership unless VIEW_STAFF_REPORTS
  - Tenant isolation
  - Snapshots: rate + line subtotal frozen on the entry
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
from apps.tenants.models import (
    MembershipLocation,
    Tenant,
    TenantMembership,
)
from apps.tenants.services import create_tenant_with_defaults

from .models import (
    CommissionEntry,
    CommissionRule,
    CommissionRuleOverride,
    compute_commission_cents,
)
from .services import accrue_for_invoice, reverse_for_invoice

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


def _make_member(
    tenant: Tenant, role: str, email: str,
    is_bookable: bool = False,
) -> tuple[User, TenantMembership]:
    user = _make_user(email)
    m = TenantMembership.objects.create(
        user=user, tenant=tenant, role=role, is_active=True,
        is_bookable=is_bookable,
    )
    MembershipLocation.objects.create(
        membership=m, location=tenant.locations.get(is_default=True),
        is_active=True,
    )
    return user, m


def _make_category(tenant: Tenant, name: str) -> ServiceCategory:
    return ServiceCategory.objects.create(tenant=tenant, name=name)


def _make_service(
    tenant: Tenant, *, category: ServiceCategory | None = None,
    name: str = 'Service', price_cents: int = 10000,
) -> Service:
    if category is None:
        category = _make_category(tenant, 'Default')
    return Service.objects.create(
        tenant=tenant, category=category, name=name,
        duration_minutes=30, price_cents=price_cents,
        service_type=Service.ServiceType.REGULAR,
        tax_rate_percent=Decimal('0'),
    )


def _make_customer(tenant: Tenant) -> Customer:
    return Customer.objects.create(
        tenant=tenant, first_name='Pat', last_name='Patient',
        email='pat@x.com',
    )


def _make_appointment_invoice(
    *,
    tenant: Tenant,
    customer: Customer,
    service: Service,
    provider: TenantMembership,
    owner: User,
    start: dt.datetime | None = None,
) -> tuple[Appointment, Invoice]:
    start = start or (timezone.now() + dt.timedelta(hours=1))
    appt = Appointment.objects.create(
        tenant=tenant, customer=customer, provider=provider,
        service=service,
        location=tenant.locations.get(is_default=True),
        start_time=start,
        end_time=start + dt.timedelta(minutes=service.duration_minutes),
        status=Appointment.Status.CHECKED_IN,
        quoted_price_cents=service.price_cents,
        created_by=owner,
    )
    return appt, Invoice.objects.get(appointment=appt)


def _client_for(user) -> APIClient:
    c = APIClient()
    c.force_login(user)
    return c


# ── Money math ──────────────────────────────────────────────────────


class CommissionMathTests(TestCase):
    def test_zero_rate_returns_zero(self):
        self.assertEqual(
            compute_commission_cents(line_subtotal_cents=10000, rate_percent=0),
            0,
        )

    def test_basic_calculation(self):
        # 20% of $100 = $20
        self.assertEqual(
            compute_commission_cents(
                line_subtotal_cents=10000, rate_percent=Decimal('20'),
            ),
            2000,
        )

    def test_rounds_half_up(self):
        # 12.5% of $1.01 = 12.625¢ → rounds to 13¢
        self.assertEqual(
            compute_commission_cents(
                line_subtotal_cents=101, rate_percent=Decimal('12.5'),
            ),
            13,
        )

    def test_zero_subtotal_returns_zero(self):
        self.assertEqual(
            compute_commission_cents(
                line_subtotal_cents=0, rate_percent=Decimal('20'),
            ),
            0,
        )


# ── Rule resolution ─────────────────────────────────────────────────


class RuleResolutionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant, cls.owner = _make_tenant('comm-rule')
        cls.user, cls.member = _make_member(
            cls.tenant, TenantMembership.Role.PROVIDER, 'p@test.local',
            is_bookable=True,
        )
        cls.cat_a = _make_category(cls.tenant, 'Botox')
        cls.cat_b = _make_category(cls.tenant, 'Facials')
        cls.rule = CommissionRule.objects.create(
            tenant=cls.tenant, membership=cls.member,
            base_rate_percent=Decimal('10'),
        )
        CommissionRuleOverride.objects.create(
            rule=cls.rule, category=cls.cat_a,
            rate_percent=Decimal('25'),
        )

    def test_override_applies(self):
        self.assertEqual(
            self.rule.rate_for_category(self.cat_a.pk), Decimal('25'),
        )

    def test_no_override_falls_back_to_base(self):
        self.assertEqual(
            self.rule.rate_for_category(self.cat_b.pk), Decimal('10'),
        )

    def test_null_category_falls_back_to_base(self):
        self.assertEqual(
            self.rule.rate_for_category(None), Decimal('10'),
        )


# ── Accrual on invoice close ────────────────────────────────────────


class AccrualTests(TestCase):
    """Walk the close path with various provider + rule states."""

    @classmethod
    def setUpTestData(cls):
        cls.tenant, cls.owner = _make_tenant('comm-accr')
        cls.cat = _make_category(cls.tenant, 'Default')
        cls.service = _make_service(
            cls.tenant, category=cls.cat, price_cents=20000,
        )

    def setUp(self):
        self.provider_user, self.provider = _make_member(
            self.tenant, TenantMembership.Role.PROVIDER,
            f'p-{self.id()}@test.local', is_bookable=True,
        )
        self.customer = _make_customer(self.tenant)

    def test_close_creates_accrual_for_provider_with_rule(self):
        CommissionRule.objects.create(
            tenant=self.tenant, membership=self.provider,
            base_rate_percent=Decimal('15'),
        )
        appt, invoice = _make_appointment_invoice(
            tenant=self.tenant, customer=self.customer,
            service=self.service, provider=self.provider,
            owner=self.owner,
        )
        invoice.close(by_user=self.owner, payment_method='cash')

        entries = CommissionEntry.objects.filter(invoice=invoice).order_by('id')
        self.assertEqual(entries.count(), 1)
        e = entries.first()
        self.assertEqual(e.kind, CommissionEntry.Kind.ACCRUAL)
        self.assertEqual(e.membership, self.provider)
        # 15% of $200 = $30
        self.assertEqual(e.amount_cents, 3000)
        # Rate snapshotted on the row.
        self.assertEqual(e.rate_percent, Decimal('15.00'))
        self.assertEqual(e.line_subtotal_cents, 20000)

    def test_no_rule_means_no_accrual(self):
        appt, invoice = _make_appointment_invoice(
            tenant=self.tenant, customer=self.customer,
            service=self.service, provider=self.provider,
            owner=self.owner,
        )
        invoice.close(by_user=self.owner, payment_method='cash')
        self.assertEqual(
            CommissionEntry.objects.filter(invoice=invoice).count(), 0,
        )

    def test_inactive_rule_means_no_accrual(self):
        CommissionRule.objects.create(
            tenant=self.tenant, membership=self.provider,
            base_rate_percent=Decimal('15'), is_active=False,
        )
        appt, invoice = _make_appointment_invoice(
            tenant=self.tenant, customer=self.customer,
            service=self.service, provider=self.provider,
            owner=self.owner,
        )
        invoice.close(by_user=self.owner, payment_method='cash')
        self.assertEqual(
            CommissionEntry.objects.filter(invoice=invoice).count(), 0,
        )

    def test_zero_rate_means_no_accrual(self):
        CommissionRule.objects.create(
            tenant=self.tenant, membership=self.provider,
            base_rate_percent=Decimal('0'),
        )
        appt, invoice = _make_appointment_invoice(
            tenant=self.tenant, customer=self.customer,
            service=self.service, provider=self.provider,
            owner=self.owner,
        )
        invoice.close(by_user=self.owner, payment_method='cash')
        self.assertEqual(
            CommissionEntry.objects.filter(invoice=invoice).count(), 0,
        )

    def test_per_category_override_applied(self):
        rule = CommissionRule.objects.create(
            tenant=self.tenant, membership=self.provider,
            base_rate_percent=Decimal('10'),
        )
        CommissionRuleOverride.objects.create(
            rule=rule, category=self.cat,
            rate_percent=Decimal('25'),
        )
        appt, invoice = _make_appointment_invoice(
            tenant=self.tenant, customer=self.customer,
            service=self.service, provider=self.provider,
            owner=self.owner,
        )
        invoice.close(by_user=self.owner, payment_method='cash')

        e = CommissionEntry.objects.get(invoice=invoice)
        # 25% of $200 = $50, NOT 10% of $200 = $20
        self.assertEqual(e.amount_cents, 5000)
        self.assertEqual(e.rate_percent, Decimal('25.00'))

    def test_idempotent_reaccrue(self):
        """Calling accrue_for_invoice twice on the same invoice
        doesn't create duplicate entries."""
        CommissionRule.objects.create(
            tenant=self.tenant, membership=self.provider,
            base_rate_percent=Decimal('15'),
        )
        appt, invoice = _make_appointment_invoice(
            tenant=self.tenant, customer=self.customer,
            service=self.service, provider=self.provider,
            owner=self.owner,
        )
        invoice.close(by_user=self.owner, payment_method='cash')
        # Manually call accrue again (simulating a buggy hook
        # firing twice).
        accrue_for_invoice(invoice=invoice, by_user=self.owner)
        self.assertEqual(
            CommissionEntry.objects.filter(
                invoice=invoice,
                kind=CommissionEntry.Kind.ACCRUAL,
            ).count(),
            1,
        )

    def test_audit_log_includes_commissions_accrued(self):
        CommissionRule.objects.create(
            tenant=self.tenant, membership=self.provider,
            base_rate_percent=Decimal('10'),
        )
        appt, invoice = _make_appointment_invoice(
            tenant=self.tenant, customer=self.customer,
            service=self.service, provider=self.provider,
            owner=self.owner,
        )
        invoice.close(by_user=self.owner, payment_method='cash')
        log = (
            AuditLog.objects.filter(
                resource_type='invoice',
                resource_id=str(invoice.pk),
                action=AuditLog.Action.UPDATE,
            )
            .order_by('-timestamp')
            .first()
        )
        snapshot = log.metadata.get('commissions_accrued') or []
        self.assertEqual(len(snapshot), 1)
        self.assertEqual(snapshot[0]['membership_id'], self.provider.pk)


# ── Reversal on reopen ──────────────────────────────────────────────


class ReversalTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant, cls.owner = _make_tenant('comm-rev')
        cls.cat = _make_category(cls.tenant, 'Default')
        cls.service = _make_service(
            cls.tenant, category=cls.cat, price_cents=10000,
        )

    def setUp(self):
        self.provider_user, self.provider = _make_member(
            self.tenant, TenantMembership.Role.PROVIDER,
            f'p-{self.id()}@test.local', is_bookable=True,
        )
        CommissionRule.objects.create(
            tenant=self.tenant, membership=self.provider,
            base_rate_percent=Decimal('20'),
        )
        self.customer = _make_customer(self.tenant)
        self.appt, self.invoice = _make_appointment_invoice(
            tenant=self.tenant, customer=self.customer,
            service=self.service, provider=self.provider,
            owner=self.owner,
        )

    def test_reopen_creates_reversal(self):
        self.invoice.close(by_user=self.owner, payment_method='cash')
        self.invoice.reopen(by_user=self.owner, reason='oops')

        entries = CommissionEntry.objects.filter(
            invoice=self.invoice,
        ).order_by('id')
        self.assertEqual(entries.count(), 2)

        accrual, reversal = entries[0], entries[1]
        self.assertEqual(accrual.kind, CommissionEntry.Kind.ACCRUAL)
        self.assertEqual(reversal.kind, CommissionEntry.Kind.REVERSAL)
        self.assertEqual(reversal.amount_cents, -accrual.amount_cents)
        self.assertEqual(reversal.reverses, accrual)
        self.assertEqual(reversal.line_subtotal_cents, accrual.line_subtotal_cents)
        self.assertEqual(reversal.rate_percent, accrual.rate_percent)

    def test_reopen_reverse_is_idempotent(self):
        self.invoice.close(by_user=self.owner, payment_method='cash')
        self.invoice.reopen(by_user=self.owner, reason='oops')
        # Manually call reverse_for_invoice — should be a no-op.
        snaps = reverse_for_invoice(invoice=self.invoice, by_user=self.owner)
        self.assertEqual(snaps, [])

    def test_reopen_then_close_creates_fresh_accrual(self):
        """Net behavior: 1 accrual + 1 reversal + 1 accrual.
        Customer paid once, refunded, paid again — net commission =
        what one accrual would be."""
        self.invoice.close(by_user=self.owner, payment_method='cash')
        self.invoice.reopen(by_user=self.owner, reason='oops')
        self.invoice.close(by_user=self.owner, payment_method='cash')

        entries = CommissionEntry.objects.filter(
            invoice=self.invoice,
        ).order_by('id')
        self.assertEqual(entries.count(), 3)
        kinds = [e.kind for e in entries]
        self.assertEqual(
            kinds,
            [
                CommissionEntry.Kind.ACCRUAL,
                CommissionEntry.Kind.REVERSAL,
                CommissionEntry.Kind.ACCRUAL,
            ],
        )

        # Net commission for the membership = first accrual reversed
        # + new accrual = 2000c (the new accrual). Net is correct.
        from django.db.models import Sum
        net = (
            CommissionEntry.objects
            .filter(membership=self.provider)
            .aggregate(s=Sum('amount_cents'))['s']
        )
        self.assertEqual(net, 2000)

    def test_audit_log_includes_commissions_reversed(self):
        self.invoice.close(by_user=self.owner, payment_method='cash')
        self.invoice.reopen(by_user=self.owner, reason='oops')

        log = (
            AuditLog.objects.filter(
                resource_type='invoice',
                resource_id=str(self.invoice.pk),
                action=AuditLog.Action.UPDATE,
            )
            .order_by('-timestamp')
            .first()
        )
        snap = log.metadata.get('commissions_reversed') or []
        self.assertEqual(len(snap), 1)


# ── Permission gating ───────────────────────────────────────────────


class RulePermissionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant, cls.owner = _make_tenant('comm-perm')
        cls.fd_user, cls.fd = _make_member(
            cls.tenant, TenantMembership.Role.FRONT_DESK, 'fd@test.local',
        )
        cls.provider_user, cls.provider = _make_member(
            cls.tenant, TenantMembership.Role.PROVIDER, 'p@test.local',
            is_bookable=True,
        )

    def test_anonymous_blocked(self):
        response = APIClient().get(
            reverse('commission-rule-list'),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_front_desk_can_read(self):
        response = _client_for(self.fd_user).get(
            reverse('commission-rule-list'),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_front_desk_cannot_create(self):
        response = _client_for(self.fd_user).post(
            reverse('commission-rule-list'),
            data={
                'membership': self.provider.pk,
                'base_rate_percent': '15',
            },
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_owner_can_create_with_overrides(self):
        cat = _make_category(self.tenant, 'Botox')
        response = _client_for(self.owner).post(
            reverse('commission-rule-list'),
            data={
                'membership': self.provider.pk,
                'base_rate_percent': '10',
                'overrides_input': [
                    {'category_id': cat.pk, 'rate_percent': '25'},
                ],
            },
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(len(response.data['overrides']), 1)
        self.assertEqual(response.data['overrides'][0]['rate_percent'], '25.00')


class EntryReadScopeTests(TestCase):
    """Non-managers see only their own entries; bookkeeper /
    manager / owner see everyone's."""

    @classmethod
    def setUpTestData(cls):
        cls.tenant, cls.owner = _make_tenant('comm-read')
        cls.alice_user, cls.alice = _make_member(
            cls.tenant, TenantMembership.Role.PROVIDER, 'alice@test.local',
            is_bookable=True,
        )
        cls.bob_user, cls.bob = _make_member(
            cls.tenant, TenantMembership.Role.PROVIDER, 'bob@test.local',
            is_bookable=True,
        )
        cls.bookkeeper_user, cls.bookkeeper = _make_member(
            cls.tenant, TenantMembership.Role.BOOKKEEPER, 'bk@test.local',
        )
        cls.fd_user, cls.fd = _make_member(
            cls.tenant, TenantMembership.Role.FRONT_DESK, 'fd@test.local',
        )

        # Set up rules + close one invoice per provider so each
        # has an accrual.
        cat = _make_category(cls.tenant, 'Default')
        service = _make_service(cls.tenant, category=cat, price_cents=10000)
        for member, member_user in [
            (cls.alice, cls.alice_user), (cls.bob, cls.bob_user),
        ]:
            CommissionRule.objects.create(
                tenant=cls.tenant, membership=member,
                base_rate_percent=Decimal('20'),
            )
            customer = Customer.objects.create(
                tenant=cls.tenant, first_name='X', last_name='Y',
                email=f'{member_user.email}-cust',
            )
            _, invoice = _make_appointment_invoice(
                tenant=cls.tenant, customer=customer,
                service=service, provider=member, owner=cls.owner,
            )
            invoice.close(by_user=cls.owner, payment_method='cash')

    def test_provider_sees_only_own_entries(self):
        response = _client_for(self.alice_user).get(
            reverse('commission-entry-list'),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        memberships = {row['membership'] for row in response.data}
        self.assertEqual(memberships, {self.alice.pk})

    def test_front_desk_sees_only_own_entries(self):
        response = _client_for(self.fd_user).get(
            reverse('commission-entry-list'),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # FD has no entries of their own.
        self.assertEqual(len(response.data), 0)

    def test_bookkeeper_sees_all_entries(self):
        response = _client_for(self.bookkeeper_user).get(
            reverse('commission-entry-list'),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)

    def test_owner_sees_all_entries(self):
        response = _client_for(self.owner).get(
            reverse('commission-entry-list'),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(len(response.data), 2)


class TotalsEndpointTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant, cls.owner = _make_tenant('comm-tot')
        cls.alice_user, cls.alice = _make_member(
            cls.tenant, TenantMembership.Role.PROVIDER, 'a@test.local',
            is_bookable=True,
        )
        cls.bob_user, cls.bob = _make_member(
            cls.tenant, TenantMembership.Role.PROVIDER, 'b@test.local',
            is_bookable=True,
        )
        cat = _make_category(cls.tenant, 'D')
        service = _make_service(cls.tenant, category=cat, price_cents=10000)

        for member, user in [
            (cls.alice, cls.alice_user), (cls.bob, cls.bob_user),
        ]:
            CommissionRule.objects.create(
                tenant=cls.tenant, membership=member,
                base_rate_percent=Decimal('20'),
            )
            customer = Customer.objects.create(
                tenant=cls.tenant, first_name='X', last_name='Y',
                email=f'{user.email}-cust',
            )
            _, invoice = _make_appointment_invoice(
                tenant=cls.tenant, customer=customer,
                service=service, provider=member, owner=cls.owner,
            )
            invoice.close(by_user=cls.owner, payment_method='cash')

    def test_totals_aggregates_per_membership(self):
        response = _client_for(self.owner).get(
            reverse('commission-entry-totals'),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)
        net_by_member = {row['membership_id']: row['net_cents'] for row in response.data}
        self.assertEqual(net_by_member[self.alice.pk], 2000)
        self.assertEqual(net_by_member[self.bob.pk], 2000)

    def test_totals_filterable_by_membership(self):
        response = _client_for(self.owner).get(
            reverse('commission-entry-totals')
            + f'?membership={self.alice.pk}',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['membership_id'], self.alice.pk)


# ── Tenant isolation ────────────────────────────────────────────────


class TenantIsolationTests(TestCase):
    def test_cannot_create_rule_for_another_tenants_membership(self):
        tenant_a, owner_a = _make_tenant('comm-iso-a')
        tenant_b, _ = _make_tenant('comm-iso-b')
        _, b_member = _make_member(
            tenant_b, TenantMembership.Role.PROVIDER, 'bm@test.local',
            is_bookable=True,
        )
        response = _client_for(owner_a).post(
            reverse('commission-rule-list'),
            data={
                'membership': b_member.pk,
                'base_rate_percent': '20',
            },
            format='json',
            HTTP_X_TENANT_SLUG=tenant_a.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
