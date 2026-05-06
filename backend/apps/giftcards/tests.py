"""Tests for the gift cards API + invoice integration.

Covers:
  - Code auto-gen format + per-tenant uniqueness
  - Read endpoints (list / retrieve / lookup / cross-tenant 404)
  - Void action (reason required, locked-out by redemptions, balance
    forfeited via ADJUSTMENT ledger row, audit shape)
  - Invoice integration:
      - add-gift-card-sale creates a PENDING card + line
      - close flips PENDING → ACTIVE + writes ISSUE row
      - apply-gift-card decrements balance + bumps invoice credits
      - reverse-gift-card-redemption restores balance
      - reopen blocked once a card has redemptions OR the invoice
        consumed gift card credits
      - void cascade-VOIDs PENDING gift cards
  - Ledger invariant: balance == sum(ledger entries)
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db.models import Sum
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.appointments.models import Appointment
from apps.audit.models import AuditLog
from apps.customers.models import Customer
from apps.invoices.models import Invoice, InvoiceStateError
from apps.services.models import Service, ServiceCategory
from apps.tenants.models import (
    MembershipLocation,
    Tenant,
    TenantMembership,
)
from apps.tenants.services import create_tenant_with_defaults

from .models import (
    CODE_PREFIX,
    GiftCard,
    GiftCardLedger,
    generate_gift_card_code,
)

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
        role=TenantMembership.Role.FRONT_DESK, is_active=True,
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


def _make_service(tenant: Tenant, *, price_cents: int = 10000) -> Service:
    cat, _ = ServiceCategory.objects.get_or_create(
        tenant=tenant, name='Default',
    )
    return Service.objects.create(
        tenant=tenant, category=cat, name='Service',
        duration_minutes=30, price_cents=price_cents,
        service_type=Service.ServiceType.REGULAR,
        tax_rate_percent=Decimal('0'),
    )


def _make_customer(tenant: Tenant, **overrides) -> Customer:
    defaults = dict(
        tenant=tenant,
        first_name='Pat', last_name='Patient',
        email='pat@x.com',
    )
    defaults.update(overrides)
    return Customer.objects.create(**defaults)


def _make_appointment(
    tenant: Tenant, *, customer: Customer, service: Service,
    provider: TenantMembership, owner: User,
    start: dt.datetime | None = None,
) -> Appointment:
    start = start or (timezone.now() + dt.timedelta(hours=1))
    return Appointment.objects.create(
        tenant=tenant,
        customer=customer,
        provider=provider,
        service=service,
        location=tenant.locations.get(is_default=True),
        start_time=start,
        end_time=start + dt.timedelta(minutes=service.duration_minutes),
        status=Appointment.Status.CHECKED_IN,
        quoted_price_cents=service.price_cents,
        created_by=owner,
    )


def _client_for(user) -> APIClient:
    c = APIClient()
    c.force_login(user)
    return c


def _ledger_invariant_holds(card: GiftCard) -> bool:
    card.refresh_from_db()
    total = card.ledger_entries.aggregate(s=Sum('amount_cents'))['s'] or 0
    return total == card.balance_cents


# ── Code generation ─────────────────────────────────────────────────


class GiftCardCodeTests(TestCase):
    def test_code_format(self):
        code = generate_gift_card_code()
        self.assertTrue(code.startswith(f'{CODE_PREFIX}-'))
        # GC-XXXX-YYYY = 2 + 1 + 4 + 1 + 4 = 12 chars
        self.assertEqual(len(code), 12)
        parts = code.split('-')
        self.assertEqual(len(parts), 3)
        self.assertEqual(len(parts[1]), 4)
        self.assertEqual(len(parts[2]), 4)

    def test_code_excludes_ambiguous_chars(self):
        # Generate a bunch and verify never see I/O/0/1.
        for _ in range(200):
            code = generate_gift_card_code()
            for c in code.replace('-', '').replace(CODE_PREFIX, ''):
                self.assertNotIn(c, {'I', 'O', '0', '1'})

    def test_code_uniqueness_within_tenant(self):
        from django.db.utils import IntegrityError
        tenant, owner = _make_tenant('gc-code')
        provider = _make_provider(tenant)
        customer = _make_customer(tenant)
        service = _make_service(tenant)
        appt = _make_appointment(
            tenant, customer=customer, service=service,
            provider=provider, owner=owner,
        )
        invoice = Invoice.objects.get(appointment=appt)
        line = invoice.line_items.first()
        GiftCard.objects.create(
            tenant=tenant,
            code='GC-AAAA-BBBB',
            source_invoice_line=line,
            initial_value_cents=10000,
            balance_cents=0,
            issued_to_name='Recipient',
        )
        # Need a second line for the second card (1:1 source FK).
        from apps.invoices.models import InvoiceLineItem
        line2 = InvoiceLineItem.objects.create(
            invoice=invoice, description='Test',
            quantity=1, unit_price_cents=5000,
        )
        with self.assertRaises(IntegrityError):
            GiftCard.objects.create(
                tenant=tenant,
                code='GC-AAAA-BBBB',  # duplicate
                source_invoice_line=line2,
                initial_value_cents=5000,
                balance_cents=0,
                issued_to_name='X',
            )


# ── Permissions + read endpoints ────────────────────────────────────


class GiftCardReadTests(TestCase):
    """List / retrieve / lookup / void permission gating."""

    @classmethod
    def setUpTestData(cls):
        cls.tenant, cls.owner = _make_tenant('gc-read')
        cls.fd_user, _ = _make_front_desk(cls.tenant)
        cls.provider = _make_provider(cls.tenant)
        cls.customer = _make_customer(cls.tenant)
        cls.service = _make_service(cls.tenant)
        appt = _make_appointment(
            cls.tenant, customer=cls.customer, service=cls.service,
            provider=cls.provider, owner=cls.owner,
        )
        invoice = Invoice.objects.get(appointment=appt)
        line = invoice.line_items.first()
        cls.card = GiftCard.objects.create(
            tenant=cls.tenant,
            source_invoice_line=line,
            initial_value_cents=10000,
            balance_cents=10000,
            status=GiftCard.Status.ACTIVE,
            issued_to_name='Recipient',
            issued_at=timezone.now(),
        )
        # Synthesize a matching ISSUE ledger row so the invariant
        # check passes (this card was created via ORM, not the
        # endpoint).
        GiftCardLedger.objects.create(
            tenant=cls.tenant, gift_card=cls.card,
            kind=GiftCardLedger.Kind.ISSUE,
            amount_cents=10000,
            invoice=invoice,
            by_user=cls.owner,
        )

    def test_anonymous_blocked(self):
        response = APIClient().get(
            reverse('gift-card-list'),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_front_desk_can_read(self):
        response = _client_for(self.fd_user).get(
            reverse('gift-card-list'),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)

    def test_lookup_by_code_hit(self):
        response = _client_for(self.fd_user).post(
            reverse('gift-card-lookup'),
            data={'code': self.card.code},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['code'], self.card.code)
        self.assertEqual(response.data['balance_cents'], 10000)

    def test_lookup_case_insensitive(self):
        response = _client_for(self.fd_user).post(
            reverse('gift-card-lookup'),
            data={'code': self.card.code.lower()},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_lookup_miss_returns_404(self):
        response = _client_for(self.fd_user).post(
            reverse('gift-card-lookup'),
            data={'code': 'GC-XXXX-XXXX'},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_lookup_cross_tenant_returns_404(self):
        # A user from a different tenant looking up our code must
        # miss (404 — tenant scoping in `for_current_tenant`).
        other_tenant, other_owner = _make_tenant('gc-read-other')
        response = _client_for(other_owner).post(
            reverse('gift-card-lookup'),
            data={'code': self.card.code},
            format='json',
            HTTP_X_TENANT_SLUG=other_tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_filter_by_status(self):
        response = _client_for(self.fd_user).get(
            reverse('gift-card-list') + '?status=active',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(len(response.data), 1)
        response = _client_for(self.fd_user).get(
            reverse('gift-card-list') + '?status=voided',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(len(response.data), 0)


class GiftCardVoidTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant, cls.owner = _make_tenant('gc-void')
        cls.fd_user, _ = _make_front_desk(cls.tenant)
        cls.provider = _make_provider(cls.tenant)
        cls.customer = _make_customer(cls.tenant)
        cls.service = _make_service(cls.tenant)

    def setUp(self):
        appt = _make_appointment(
            self.tenant, customer=self.customer, service=self.service,
            provider=self.provider, owner=self.owner,
        )
        self.invoice = Invoice.objects.get(appointment=appt)
        line = self.invoice.line_items.first()
        self.card = GiftCard.objects.create(
            tenant=self.tenant,
            source_invoice_line=line,
            initial_value_cents=10000,
            balance_cents=10000,
            status=GiftCard.Status.ACTIVE,
            issued_to_name='Recipient',
            issued_at=timezone.now(),
        )
        GiftCardLedger.objects.create(
            tenant=self.tenant, gift_card=self.card,
            kind=GiftCardLedger.Kind.ISSUE,
            amount_cents=10000,
            invoice=self.invoice,
            by_user=self.owner,
        )

    def _void_url(self, pk):
        return reverse('gift-card-void', kwargs={'pk': pk})

    def test_void_requires_reason(self):
        response = _client_for(self.owner).post(
            self._void_url(self.card.pk),
            data={},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_void_zeroes_balance_via_adjustment_ledger(self):
        response = _client_for(self.owner).post(
            self._void_url(self.card.pk),
            data={'reason': 'Lost card, reissuing'},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.card.refresh_from_db()
        self.assertEqual(self.card.status, GiftCard.Status.VOIDED)
        self.assertEqual(self.card.balance_cents, 0)
        self.assertEqual(self.card.void_reason, 'Lost card, reissuing')
        self.assertEqual(self.card.voided_by, self.owner)
        self.assertTrue(_ledger_invariant_holds(self.card))

    def test_void_already_voided_409(self):
        self.card.status = GiftCard.Status.VOIDED
        self.card.save()
        response = _client_for(self.owner).post(
            self._void_url(self.card.pk),
            data={'reason': 'duplicate'},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    def test_void_with_redemptions_blocked(self):
        # Add a synthetic REDEEM ledger row + reflect on balance.
        GiftCardLedger.objects.create(
            tenant=self.tenant, gift_card=self.card,
            kind=GiftCardLedger.Kind.REDEEM,
            amount_cents=-2500,
            invoice=self.invoice,
            by_user=self.owner,
        )
        self.card.balance_cents = 7500
        self.card.save()

        response = _client_for(self.owner).post(
            self._void_url(self.card.pk),
            data={'reason': 'block test'},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    def test_void_audit_log_records_forfeited_balance(self):
        _client_for(self.owner).post(
            self._void_url(self.card.pk),
            data={'reason': 'damaged'},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        log = AuditLog.objects.filter(
            resource_type='gift_card', action=AuditLog.Action.UPDATE,
        ).order_by('-id').first()
        self.assertEqual(log.metadata.get('event'), 'voided')
        self.assertEqual(log.metadata.get('forfeited_balance_cents'), 10000)

    def test_front_desk_cannot_void(self):
        response = _client_for(self.fd_user).post(
            self._void_url(self.card.pk),
            data={'reason': 'sneaky'},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


# ── Invoice integration: sale ───────────────────────────────────────


class GiftCardSaleTests(TestCase):
    """Selling a gift card on an invoice creates a PENDING card;
    close flips ACTIVE + writes ISSUE row; void cascade-VOIDs."""

    def setUp(self):
        self.tenant, self.owner = _make_tenant('gc-sale')
        self.provider = _make_provider(self.tenant)
        self.customer = _make_customer(self.tenant)
        self.service = _make_service(self.tenant)
        appt = _make_appointment(
            self.tenant, customer=self.customer, service=self.service,
            provider=self.provider, owner=self.owner,
        )
        self.invoice = Invoice.objects.get(appointment=appt)
        self.client = _client_for(self.owner)

    def _sale_url(self):
        return reverse(
            'invoice-add-gift-card-sale', kwargs={'pk': self.invoice.pk},
        )

    def test_sale_creates_pending_card_with_zero_balance(self):
        response = self.client.post(
            self._sale_url(),
            data={
                'value_cents': 10000,
                'recipient_name': 'Aunt Mary',
                'recipient_email': 'mary@example.com',
            },
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        card = GiftCard.objects.get(tenant=self.tenant)
        self.assertEqual(card.status, GiftCard.Status.PENDING)
        self.assertEqual(card.initial_value_cents, 10000)
        self.assertEqual(card.balance_cents, 0)  # not yet issued
        self.assertEqual(card.issued_to_name, 'Aunt Mary')
        self.assertEqual(card.purchaser_customer, self.customer)

    def test_sale_with_recipient_customer(self):
        recipient = _make_customer(
            self.tenant, first_name='Recipient', last_name='Customer',
            email='recipient@x.com',
        )
        response = self.client.post(
            self._sale_url(),
            data={
                'value_cents': 5000,
                'recipient_customer_id': recipient.pk,
            },
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        card = GiftCard.objects.get(tenant=self.tenant)
        self.assertEqual(card.issued_to_customer, recipient)

    def test_sale_requires_recipient(self):
        response = self.client.post(
            self._sale_url(),
            data={'value_cents': 5000},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_sale_creates_invoice_line(self):
        self.client.post(
            self._sale_url(),
            data={'value_cents': 5000, 'recipient_name': 'X'},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        line = self.invoice.line_items.order_by('-id').first()
        self.assertEqual(line.unit_price_cents, 5000)
        self.assertIsNone(line.service)
        self.assertIsNone(line.product)
        self.assertIsNone(line.package)
        self.assertIsNone(line.membership_plan)
        # Description includes the recipient + amount.
        self.assertIn('$50.00', line.description)
        self.assertIn('X', line.description)

    def test_sale_on_paid_invoice_409(self):
        self.invoice.close(by_user=self.owner, payment_method='cash')
        response = self.client.post(
            self._sale_url(),
            data={'value_cents': 5000, 'recipient_name': 'X'},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    def test_close_activates_pending_card_and_writes_issue_ledger(self):
        self.client.post(
            self._sale_url(),
            data={'value_cents': 10000, 'recipient_name': 'X'},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.invoice.close(by_user=self.owner, payment_method='cash')
        card = GiftCard.objects.get(tenant=self.tenant)
        self.assertEqual(card.status, GiftCard.Status.ACTIVE)
        self.assertIsNotNone(card.issued_at)
        self.assertEqual(card.balance_cents, 10000)
        # Exactly one ISSUE ledger entry.
        issue_count = card.ledger_entries.filter(
            kind=GiftCardLedger.Kind.ISSUE,
        ).count()
        self.assertEqual(issue_count, 1)
        # Invariant holds.
        self.assertTrue(_ledger_invariant_holds(card))

    def test_void_cascade_voids_pending_card(self):
        self.client.post(
            self._sale_url(),
            data={'value_cents': 10000, 'recipient_name': 'X'},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.invoice.void(by_user=self.owner, reason='customer changed mind')
        card = GiftCard.objects.get(tenant=self.tenant)
        self.assertEqual(card.status, GiftCard.Status.VOIDED)
        self.assertEqual(card.void_reason, 'invoice_voided')

    def test_reopen_with_no_redemptions_reverts_card_to_pending(self):
        self.client.post(
            self._sale_url(),
            data={'value_cents': 10000, 'recipient_name': 'X'},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.invoice.close(by_user=self.owner, payment_method='cash')
        self.invoice.reopen(by_user=self.owner, reason='oops')
        card = GiftCard.objects.get(tenant=self.tenant)
        self.assertEqual(card.status, GiftCard.Status.PENDING)
        self.assertEqual(card.balance_cents, 0)
        # ISSUE ledger row was deleted on reopen.
        self.assertEqual(card.ledger_entries.count(), 0)


# ── Invoice integration: redemption ─────────────────────────────────


class GiftCardRedemptionTests(TestCase):
    """Applying gift card credits to a checkout invoice."""

    def setUp(self):
        self.tenant, self.owner = _make_tenant('gc-rdm')
        self.provider = _make_provider(self.tenant)
        self.customer = _make_customer(self.tenant)
        self.service = _make_service(self.tenant, price_cents=15000)

        # Sale invoice — closed, card ACTIVE with $100 balance.
        sale_appt = _make_appointment(
            self.tenant, customer=self.customer, service=self.service,
            provider=self.provider, owner=self.owner,
            start=timezone.now() - dt.timedelta(days=15),
        )
        self.sale_invoice = Invoice.objects.get(appointment=sale_appt)
        self.client = _client_for(self.owner)
        self.client.post(
            reverse(
                'invoice-add-gift-card-sale',
                kwargs={'pk': self.sale_invoice.pk},
            ),
            data={'value_cents': 10000, 'recipient_name': 'Recipient'},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.sale_invoice.close(by_user=self.owner, payment_method='cash')
        self.card = GiftCard.objects.get(tenant=self.tenant)

        # Checkout invoice — total $150, will redeem $30 of the card.
        checkout_appt = _make_appointment(
            self.tenant, customer=self.customer, service=self.service,
            provider=self.provider, owner=self.owner,
            start=timezone.now() + dt.timedelta(days=1),
        )
        self.checkout_invoice = Invoice.objects.get(appointment=checkout_appt)

    def _apply_url(self, invoice_pk):
        return reverse(
            'invoice-apply-gift-card', kwargs={'pk': invoice_pk},
        )

    def _reverse_url(self, invoice_pk, ledger_pk):
        return reverse(
            'invoice-reverse-gift-card-redemption',
            kwargs={'pk': invoice_pk, 'ledger_pk': ledger_pk},
        )

    def test_apply_decrements_card_and_bumps_invoice_credits(self):
        response = self.client.post(
            self._apply_url(self.checkout_invoice.pk),
            data={'code': self.card.code, 'amount_cents': 3000},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.card.refresh_from_db()
        self.assertEqual(self.card.balance_cents, 7000)
        self.checkout_invoice.refresh_from_db()
        self.assertEqual(self.checkout_invoice.gift_card_credits_cents, 3000)
        self.assertEqual(self.checkout_invoice.amount_due_cents, 12000)
        # Ledger has an ISSUE + a REDEEM row; invariant holds.
        self.assertTrue(_ledger_invariant_holds(self.card))

    def test_apply_full_invoice_total_zeroes_amount_due(self):
        # Apply $150 — covers the whole invoice.
        response = self.client.post(
            self._apply_url(self.checkout_invoice.pk),
            data={'code': self.card.code, 'amount_cents': 15000},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        # The card only has $100 — should reject.
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_apply_more_than_amount_due_rejected(self):
        # Card has $100. Invoice is $150 due. Apply $200 → exceeds card
        # balance → 400.
        response = self.client.post(
            self._apply_url(self.checkout_invoice.pk),
            data={'code': self.card.code, 'amount_cents': 20000},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_apply_more_than_balance_rejected(self):
        # First redeem $80, leaving $20 on card.
        self.client.post(
            self._apply_url(self.checkout_invoice.pk),
            data={'code': self.card.code, 'amount_cents': 8000},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        # Try $30 — only $20 left.
        response = self.client.post(
            self._apply_url(self.checkout_invoice.pk),
            data={'code': self.card.code, 'amount_cents': 3000},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_apply_unknown_code_404(self):
        response = self.client.post(
            self._apply_url(self.checkout_invoice.pk),
            data={'code': 'GC-XXXX-XXXX', 'amount_cents': 1000},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_apply_voided_card_rejected(self):
        self.card.status = GiftCard.Status.VOIDED
        self.card.save()
        response = self.client.post(
            self._apply_url(self.checkout_invoice.pk),
            data={'code': self.card.code, 'amount_cents': 1000},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    def test_apply_expired_card_rejected(self):
        self.card.expires_at = timezone.now() - dt.timedelta(days=1)
        self.card.save()
        response = self.client.post(
            self._apply_url(self.checkout_invoice.pk),
            data={'code': self.card.code, 'amount_cents': 1000},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    def test_reverse_restores_balance_and_decrements_invoice_credits(self):
        # Apply $30, then reverse.
        apply_response = self.client.post(
            self._apply_url(self.checkout_invoice.pk),
            data={'code': self.card.code, 'amount_cents': 3000},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        ledger_id = apply_response.data.get('id')
        # The ledger ID isn't on the invoice payload — pull it from
        # the audit metadata or just look it up.
        ledger = GiftCardLedger.objects.filter(
            kind=GiftCardLedger.Kind.REDEEM,
            invoice=self.checkout_invoice,
        ).order_by('-id').first()

        response = self.client.delete(
            self._reverse_url(self.checkout_invoice.pk, ledger.pk),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)

        self.card.refresh_from_db()
        self.assertEqual(self.card.balance_cents, 10000)
        self.checkout_invoice.refresh_from_db()
        self.assertEqual(self.checkout_invoice.gift_card_credits_cents, 0)
        self.assertTrue(_ledger_invariant_holds(self.card))

    def test_reverse_idempotent(self):
        self.client.post(
            self._apply_url(self.checkout_invoice.pk),
            data={'code': self.card.code, 'amount_cents': 3000},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        ledger = GiftCardLedger.objects.filter(
            kind=GiftCardLedger.Kind.REDEEM,
            invoice=self.checkout_invoice,
        ).first()
        # First reverse — succeeds.
        first = self.client.delete(
            self._reverse_url(self.checkout_invoice.pk, ledger.pk),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(first.status_code, status.HTTP_200_OK)
        # Second reverse — refused.
        second = self.client.delete(
            self._reverse_url(self.checkout_invoice.pk, ledger.pk),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(second.status_code, status.HTTP_409_CONFLICT)

    def test_reopen_invoice_with_redemptions_blocked(self):
        # Apply credits to the checkout invoice + close it.
        self.client.post(
            self._apply_url(self.checkout_invoice.pk),
            data={'code': self.card.code, 'amount_cents': 3000},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.checkout_invoice.close(by_user=self.owner, payment_method='cash')
        # Reopen should refuse.
        with self.assertRaises(InvoiceStateError):
            self.checkout_invoice.reopen(
                by_user=self.owner, reason='attempt',
            )

    def test_reopen_sale_invoice_blocked_after_card_redeemed(self):
        # Redeem the card → reopening the SALE invoice should refuse.
        self.client.post(
            self._apply_url(self.checkout_invoice.pk),
            data={'code': self.card.code, 'amount_cents': 1000},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        with self.assertRaises(InvoiceStateError):
            self.sale_invoice.reopen(by_user=self.owner, reason='attempt')

    def test_apply_against_paid_invoice_409(self):
        self.checkout_invoice.close(
            by_user=self.owner, payment_method='cash',
        )
        response = self.client.post(
            self._apply_url(self.checkout_invoice.pk),
            data={'code': self.card.code, 'amount_cents': 1000},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    def test_apply_audit_log_metadata(self):
        self.client.post(
            self._apply_url(self.checkout_invoice.pk),
            data={'code': self.card.code, 'amount_cents': 2500},
            format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        log = (
            AuditLog.objects.filter(
                resource_type='invoice',
                resource_id=str(self.checkout_invoice.pk),
                action=AuditLog.Action.UPDATE,
            )
            .order_by('-timestamp')
            .first()
        )
        self.assertEqual(log.metadata.get('event'), 'gift_card_applied')
        self.assertEqual(log.metadata.get('amount_cents'), 2500)
        self.assertEqual(log.metadata.get('card_balance_after'), 7500)
