"""Tests for the payments app (Stripe Connect onboarding chunk).

Stripe is mocked everywhere — no real network. Tests focus on:

  - MerchantAccount model behavior (is_ready_to_charge predicate)
  - Services: ensure_merchant_account idempotency,
    create_express_account creates Stripe account + persists IDs,
    sync_from_stripe_account mirrors flags + handles missing metadata
  - Webhook: signature verification, account.updated → sync,
    account.application.deauthorized → mark disabled,
    503 when secret missing, 400 on bad payload/signature
  - Views: permission gate (MANAGE_BILLING), summary always renders,
    onboarding-link 503 when Stripe not configured, happy path
"""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from apps.payments.models import MerchantAccount
from apps.payments.services import (
    StripeAPIError,
    StripeNotConfigured,
    ensure_merchant_account,
    sync_from_stripe_account,
)
from apps.tenants.models import Tenant, TenantMembership

User = get_user_model()


def _stripe_account(
    *, tenant_id: int, account_id: str = 'acct_test_123',
    charges: bool = True, payouts: bool = True, details: bool = True,
):
    """Build a SimpleNamespace shaped like a stripe.Account."""
    return SimpleNamespace(
        id=account_id,
        charges_enabled=charges,
        payouts_enabled=payouts,
        details_submitted=details,
        metadata={'lume_tenant_id': str(tenant_id)},
    )


# ── MerchantAccount model ────────────────────────────────────────


class MerchantAccountModelTests(TestCase):

    def setUp(self):
        self.tenant = Tenant.objects.create(
            name='Model Spa', slug='model-spa', plan='pro',
            status=Tenant.Status.ACTIVE,
        )

    def test_is_ready_to_charge_requires_all_flags(self):
        ma = MerchantAccount.objects.create(
            tenant=self.tenant,
            provider=MerchantAccount.Provider.STRIPE_CONNECT,
            stripe_account_id='acct_xyz',
            charges_enabled=True, payouts_enabled=True,
            details_submitted=True,
        )
        self.assertTrue(ma.is_ready_to_charge)

    def test_is_ready_to_charge_false_when_charges_disabled(self):
        ma = MerchantAccount.objects.create(
            tenant=self.tenant,
            provider=MerchantAccount.Provider.STRIPE_CONNECT,
            stripe_account_id='acct_xyz',
            charges_enabled=False,  # ← key flag missing
            payouts_enabled=True, details_submitted=True,
        )
        self.assertFalse(ma.is_ready_to_charge)

    def test_is_ready_to_charge_false_when_deauthorized(self):
        ma = MerchantAccount.objects.create(
            tenant=self.tenant,
            provider=MerchantAccount.Provider.STRIPE_CONNECT,
            stripe_account_id='acct_xyz',
            charges_enabled=True, payouts_enabled=True,
            details_submitted=True,
            disabled_at=dt.datetime.now(tz=dt.timezone.utc),
        )
        self.assertFalse(ma.is_ready_to_charge)

    def test_is_ready_to_charge_false_for_custom_provider(self):
        # Custom merchant has its own readiness signal — Stripe Connect
        # flags don't apply.
        ma = MerchantAccount.objects.create(
            tenant=self.tenant,
            provider=MerchantAccount.Provider.CUSTOM,
            stripe_account_id='acct_xyz',
            charges_enabled=True, payouts_enabled=True,
            details_submitted=True,
        )
        self.assertFalse(ma.is_ready_to_charge)


# ── Services ─────────────────────────────────────────────────────


class EnsureMerchantAccountTests(TestCase):

    def setUp(self):
        self.tenant = Tenant.objects.create(
            name='Ensure Spa', slug='ensure-spa', plan='pro',
            status=Tenant.Status.ACTIVE,
        )

    def test_creates_when_missing(self):
        self.assertFalse(
            MerchantAccount.objects.filter(tenant=self.tenant).exists(),
        )
        ma = ensure_merchant_account(self.tenant)
        self.assertEqual(ma.provider, MerchantAccount.Provider.STRIPE_CONNECT)
        self.assertEqual(ma.stripe_account_id, '')

    def test_idempotent_returns_existing(self):
        original = ensure_merchant_account(self.tenant)
        again = ensure_merchant_account(self.tenant)
        self.assertEqual(original.pk, again.pk)


class SyncFromStripeAccountTests(TestCase):

    def setUp(self):
        self.tenant = Tenant.objects.create(
            name='Sync Spa', slug='sync-spa-pay', plan='pro',
            status=Tenant.Status.ACTIVE,
        )
        self.account = MerchantAccount.objects.create(
            tenant=self.tenant,
            stripe_account_id='acct_test_999',
        )

    def test_mirrors_charges_payouts_details(self):
        synced = sync_from_stripe_account(
            _stripe_account(tenant_id=self.tenant.id, account_id='acct_test_999'),
        )
        self.assertIsNotNone(synced)
        self.assertTrue(synced.charges_enabled)
        self.assertTrue(synced.payouts_enabled)
        self.assertTrue(synced.details_submitted)

    def test_returns_none_when_metadata_missing(self):
        no_meta = SimpleNamespace(
            id='acct_test_999', charges_enabled=True,
            payouts_enabled=True, details_submitted=True,
            metadata={},
        )
        synced = sync_from_stripe_account(no_meta)
        self.assertIsNone(synced)

    def test_returns_none_when_tenant_not_known(self):
        bad = _stripe_account(tenant_id=99999999, account_id='acct_unknown')
        synced = sync_from_stripe_account(bad)
        self.assertIsNone(synced)


# ── Webhook ──────────────────────────────────────────────────────


class WebhookTests(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.url = reverse('payments-stripe-connect-webhook')
        self.tenant = Tenant.objects.create(
            name='WH Spa Pay', slug='wh-spa-pay', plan='pro',
            status=Tenant.Status.ACTIVE,
        )
        MerchantAccount.objects.create(
            tenant=self.tenant, stripe_account_id='acct_wh_1',
        )

    def _post(self, body=b'{}', sig='t=1,v1=abc'):
        return self.client.post(
            self.url, data=body, content_type='application/json',
            HTTP_STRIPE_SIGNATURE=sig,
        )

    @override_settings(STRIPE_CONNECT_WEBHOOK_SECRET='')
    def test_missing_secret_returns_503(self):
        resp = self._post()
        self.assertEqual(resp.status_code, 503)

    @override_settings(STRIPE_CONNECT_WEBHOOK_SECRET='whsec_test')
    @patch('stripe.Webhook.construct_event')
    def test_bad_signature_returns_400(self, construct):
        import stripe
        construct.side_effect = stripe.error.SignatureVerificationError(
            'bad sig', sig_header='t=...,v1=fake',
        )
        resp = self._post()
        self.assertEqual(resp.status_code, 400)

    @override_settings(STRIPE_CONNECT_WEBHOOK_SECRET='whsec_test')
    @patch('apps.payments.webhooks.sync_from_stripe_account')
    @patch('stripe.Webhook.construct_event')
    def test_account_updated_triggers_sync(self, construct, sync):
        construct.return_value = {
            'id': 'evt_acct_1',
            'type': 'account.updated',
            'data': {'object': {'id': 'acct_wh_1'}},
        }
        resp = self._post()
        self.assertEqual(resp.status_code, 200)
        sync.assert_called_once()

    @override_settings(STRIPE_CONNECT_WEBHOOK_SECRET='whsec_test')
    @patch('stripe.Webhook.construct_event')
    def test_deauthorization_marks_account_disabled(self, construct):
        construct.return_value = {
            'id': 'evt_deauth_1',
            'type': 'account.application.deauthorized',
            'data': {'object': SimpleNamespace(id='acct_wh_1')},
        }
        resp = self._post()
        self.assertEqual(resp.status_code, 200)
        account = MerchantAccount.objects.get(tenant=self.tenant)
        self.assertIsNotNone(account.disabled_at)
        self.assertFalse(account.charges_enabled)
        self.assertFalse(account.payouts_enabled)

    @override_settings(STRIPE_CONNECT_WEBHOOK_SECRET='whsec_test')
    @patch('stripe.Webhook.construct_event')
    def test_unknown_event_type_returns_200(self, construct):
        construct.return_value = {
            'id': 'evt_misc',
            'type': 'some.other.event',
            'data': {'object': {}},
        }
        resp = self._post()
        self.assertEqual(resp.status_code, 200)


# ── Views ────────────────────────────────────────────────────────


class PaymentsSummaryTests(TestCase):

    def setUp(self):
        self.tenant = Tenant.objects.create(
            name='Sum Spa Pay', slug='sum-spa-pay', plan='pro',
            status=Tenant.Status.ACTIVE,
        )
        self.owner = User.objects.create_user(
            email='sum-owner@pay.test', password='x',
        )
        TenantMembership.objects.create(
            user=self.owner, tenant=self.tenant,
            role=TenantMembership.Role.OWNER, is_active=True,
        )
        self.client = APIClient()
        self.url = reverse('payments-summary')

    def test_unauthenticated_403(self):
        resp = self.client.get(self.url, HTTP_X_TENANT_SLUG=self.tenant.slug)
        self.assertEqual(resp.status_code, 403)

    def test_front_desk_lacks_manage_billing(self):
        fd = User.objects.create_user(email='fd-pay@pay.test', password='x')
        TenantMembership.objects.create(
            user=fd, tenant=self.tenant,
            role=TenantMembership.Role.FRONT_DESK, is_active=True,
        )
        self.client.force_login(fd)
        resp = self.client.get(self.url, HTTP_X_TENANT_SLUG=self.tenant.slug)
        self.assertEqual(resp.status_code, 403)

    def test_owner_gets_summary_with_default_account(self):
        # Even with no MerchantAccount row yet, the endpoint returns
        # a useful "not connected" shape so the page renders cleanly.
        self.client.force_login(self.owner)
        resp = self.client.get(self.url, HTTP_X_TENANT_SLUG=self.tenant.slug)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['provider'], 'stripe_connect')
        self.assertEqual(resp.data['stripe_account_id'], '')
        self.assertFalse(resp.data['is_ready_to_charge'])
        self.assertIn('stripe_configured', resp.data)

    def test_summary_creates_default_account_on_first_read(self):
        self.client.force_login(self.owner)
        self.assertFalse(
            MerchantAccount.objects.filter(tenant=self.tenant).exists(),
        )
        self.client.get(self.url, HTTP_X_TENANT_SLUG=self.tenant.slug)
        self.assertTrue(
            MerchantAccount.objects.filter(tenant=self.tenant).exists(),
        )


class OnboardingLinkTests(TestCase):

    def setUp(self):
        self.tenant = Tenant.objects.create(
            name='Onboard Spa', slug='onboard-spa', plan='pro',
            status=Tenant.Status.ACTIVE,
        )
        self.owner = User.objects.create_user(
            email='onboard-owner@pay.test', password='x',
        )
        TenantMembership.objects.create(
            user=self.owner, tenant=self.tenant,
            role=TenantMembership.Role.OWNER, is_active=True,
        )
        self.client = APIClient()
        self.client.force_login(self.owner)
        self.url = reverse('payments-onboarding-link')

    @override_settings(STRIPE_SECRET_KEY='')
    def test_stripe_not_configured_returns_503(self):
        resp = self.client.post(
            self.url, {}, HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.data['code'], 'stripe_not_configured')

    @override_settings(STRIPE_SECRET_KEY='sk_test_fake')
    @patch('apps.payments.views.create_onboarding_link')
    def test_happy_path_returns_url(self, mock_create):
        mock_create.return_value = 'https://connect.stripe.com/onboarding/xyz'
        resp = self.client.post(
            self.url, {}, HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            resp.data['url'],
            'https://connect.stripe.com/onboarding/xyz',
        )

    @override_settings(STRIPE_SECRET_KEY='sk_test_fake')
    @patch('apps.payments.views.create_onboarding_link')
    def test_stripe_error_returns_502(self, mock_create):
        mock_create.side_effect = StripeAPIError('rate limited')
        resp = self.client.post(
            self.url, {}, HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(resp.status_code, 502)
        self.assertEqual(resp.data['code'], 'stripe_error')

    def test_front_desk_blocked(self):
        fd = User.objects.create_user(email='fd-on@pay.test', password='x')
        TenantMembership.objects.create(
            user=fd, tenant=self.tenant,
            role=TenantMembership.Role.FRONT_DESK, is_active=True,
        )
        self.client.logout()
        self.client.force_login(fd)
        resp = self.client.post(
            self.url, {}, HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(resp.status_code, 403)


# ── Charge card flow ─────────────────────────────────────────────


class ChargeInvoiceCardTests(TestCase):
    """POST /api/payments/invoices/<id>/charge-card/ creates a
    PaymentIntent on the spa's connected account + a local Charge
    row, returning the client_secret for Stripe Elements to confirm."""

    def setUp(self):
        from apps.appointments.models import Appointment
        from apps.customers.models import Customer
        from apps.invoices.models import Invoice
        from apps.services.models import Service, ServiceCategory

        self.tenant = Tenant.objects.create(
            name='Charge Spa', slug='charge-spa', plan='pro',
            status=Tenant.Status.ACTIVE,
        )
        self.owner = User.objects.create_user(
            email='ch-owner@pay.test', password='x',
        )
        TenantMembership.objects.create(
            user=self.owner, tenant=self.tenant,
            role=TenantMembership.Role.OWNER, is_active=True,
        )
        self.merchant = MerchantAccount.objects.create(
            tenant=self.tenant,
            stripe_account_id='acct_ch_test',
            charges_enabled=True, payouts_enabled=True,
            details_submitted=True,
        )
        # Minimal invoice fixture. The invoice serializer machinery
        # isn't exercised here — only the model + the action endpoint.
        self.customer = Customer.objects.create(
            tenant=self.tenant, first_name='Pat', last_name='Patient',
            email='pat@charge.test',
        )
        self.invoice = Invoice.objects.create(
            tenant=self.tenant, customer=self.customer,
            subtotal_cents=10_000, tax_cents=0, total_cents=10_000,
            status=Invoice.Status.OPEN,
        )
        self.client = APIClient()
        self.client.force_login(self.owner)
        self.url = reverse('payments-charge-invoice-card', args=[self.invoice.pk])

    def _post(self, body):
        return self.client.post(
            self.url, body, format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )

    def test_unauth_403(self):
        c = APIClient()
        resp = c.post(self.url, {'amount_cents': 10_000},
                      format='json', HTTP_X_TENANT_SLUG=self.tenant.slug)
        self.assertEqual(resp.status_code, 403)

    def test_invoice_not_open_returns_409(self):
        from apps.invoices.models import Invoice
        self.invoice.status = Invoice.Status.PAID
        # PAID requires closed_at (DB check constraint).
        self.invoice.closed_at = dt.datetime.now(tz=dt.timezone.utc)
        self.invoice.save()
        resp = self._post({'amount_cents': 10_000})
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.data['code'], 'invoice_not_open')

    def test_amount_not_int_400(self):
        resp = self._post({'amount_cents': 'oops'})
        self.assertEqual(resp.status_code, 400)

    @override_settings(STRIPE_SECRET_KEY='')
    def test_stripe_not_configured_503(self):
        resp = self._post({'amount_cents': 10_000})
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.data['code'], 'stripe_not_configured')

    @override_settings(STRIPE_SECRET_KEY='sk_test_fake')
    @patch('apps.payments.views.create_payment_intent_for_invoice')
    def test_happy_path_returns_client_secret(self, mock_create):
        from apps.payments.models import Charge
        # Build the (charge, client_secret) tuple the service returns.
        fake_charge = Charge.objects.create(
            tenant=self.tenant, invoice=self.invoice,
            merchant_account=self.merchant,
            amount_cents=10_000,
            stripe_payment_intent_id='pi_test_123',
            status=Charge.Status.PENDING,
        )
        mock_create.return_value = (fake_charge, 'pi_test_123_secret_abc')

        resp = self._post({'amount_cents': 10_000})
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(resp.data['client_secret'], 'pi_test_123_secret_abc')
        self.assertEqual(resp.data['charge_id'], fake_charge.pk)
        self.assertEqual(resp.data['stripe_account_id'], 'acct_ch_test')

    @override_settings(STRIPE_SECRET_KEY='sk_test_fake')
    @patch('apps.payments.views.create_payment_intent_for_invoice')
    def test_charge_refused_returns_409(self, mock_create):
        from apps.payments.services import ChargeRefusedError
        mock_create.side_effect = ChargeRefusedError(
            'Merchant account not ready to charge.',
        )
        resp = self._post({'amount_cents': 10_000})
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.data['code'], 'charge_refused')


# ── Refund flow ──────────────────────────────────────────────────


class RefundCardChargeTests(TestCase):
    """POST /api/payments/charges/<id>/refund/ issues a Stripe refund
    + appends a Refund row. Validates amount + reason before hitting
    Stripe."""

    def setUp(self):
        from apps.customers.models import Customer
        from apps.invoices.models import Invoice
        from apps.payments.models import Charge

        self.tenant = Tenant.objects.create(
            name='Refund Spa', slug='refund-spa', plan='pro',
            status=Tenant.Status.ACTIVE,
        )
        self.owner = User.objects.create_user(
            email='rf-owner@pay.test', password='x',
        )
        TenantMembership.objects.create(
            user=self.owner, tenant=self.tenant,
            role=TenantMembership.Role.OWNER, is_active=True,
        )
        self.merchant = MerchantAccount.objects.create(
            tenant=self.tenant,
            stripe_account_id='acct_rf_test',
            charges_enabled=True, payouts_enabled=True,
            details_submitted=True,
        )
        self.customer = Customer.objects.create(
            tenant=self.tenant, first_name='Pat', last_name='Refund',
            email='pat@refund.test',
        )
        self.invoice = Invoice.objects.create(
            tenant=self.tenant, customer=self.customer,
            subtotal_cents=10_000, tax_cents=0, total_cents=10_000,
            status=Invoice.Status.PAID,
            closed_at=dt.datetime.now(tz=dt.timezone.utc),
        )
        self.charge = Charge.objects.create(
            tenant=self.tenant, invoice=self.invoice,
            merchant_account=self.merchant,
            amount_cents=10_000,
            stripe_payment_intent_id='pi_rf_test',
            stripe_charge_id='ch_rf_test',
            status=Charge.Status.SUCCEEDED,
        )
        self.client = APIClient()
        self.client.force_login(self.owner)
        self.url = reverse('payments-refund-charge', args=[self.charge.pk])

    def _post(self, body):
        return self.client.post(
            self.url, body, format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )

    def test_unauth_403(self):
        c = APIClient()
        resp = c.post(self.url, {'amount_cents': 5_000, 'reason': 'test'},
                      format='json', HTTP_X_TENANT_SLUG=self.tenant.slug)
        self.assertEqual(resp.status_code, 403)

    def test_amount_not_int_400(self):
        resp = self._post({'amount_cents': 'oops', 'reason': 'r'})
        self.assertEqual(resp.status_code, 400)

    def test_missing_reason_400(self):
        resp = self._post({'amount_cents': 5_000})
        self.assertEqual(resp.status_code, 400)

    def test_blank_reason_400(self):
        resp = self._post({'amount_cents': 5_000, 'reason': '   '})
        self.assertEqual(resp.status_code, 400)

    def test_reason_too_long_400(self):
        resp = self._post({'amount_cents': 5_000, 'reason': 'x' * 256})
        self.assertEqual(resp.status_code, 400)

    @override_settings(STRIPE_SECRET_KEY='')
    def test_stripe_not_configured_503(self):
        resp = self._post({'amount_cents': 5_000, 'reason': 'customer requested'})
        self.assertEqual(resp.status_code, 503)

    @override_settings(STRIPE_SECRET_KEY='sk_test_fake')
    @patch('apps.payments.views.refund_charge')
    def test_happy_path(self, mock_refund):
        from apps.payments.models import Refund
        fake_refund = Refund.objects.create(
            tenant=self.tenant, charge=self.charge,
            amount_cents=5_000, reason='customer requested',
            stripe_refund_id='re_test_123',
            status=Refund.Status.PENDING,
        )
        # Mock side-effect: bump the charge rollup (real service does this)
        def _do_refund(*, charge, amount_cents, reason, operator):
            charge.refunded_cents = amount_cents
            charge.save(update_fields=['refunded_cents'])
            return fake_refund
        mock_refund.side_effect = _do_refund

        resp = self._post({'amount_cents': 5_000, 'reason': 'customer requested'})
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(resp.data['refund_id'], fake_refund.pk)
        self.assertEqual(resp.data['amount_cents'], 5_000)
        self.assertEqual(resp.data['charge_refunded_cents'], 5_000)

    @override_settings(STRIPE_SECRET_KEY='sk_test_fake')
    @patch('apps.payments.views.refund_charge')
    def test_refund_refused_returns_409(self, mock_refund):
        from apps.payments.services import RefundRefusedError
        mock_refund.side_effect = RefundRefusedError(
            'Amount exceeds refundable balance.',
        )
        resp = self._post({'amount_cents': 100_000, 'reason': 'whoops'})
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.data['code'], 'refund_refused')


# ── Charge / Refund model invariants ──────────────────────────────


class ChargeRefundModelInvariantTests(TestCase):
    """The CHECK constraints + computed properties protect the ledger
    from impossible states. Worth pinning so a future model edit
    doesn't silently relax them."""

    def setUp(self):
        from apps.customers.models import Customer
        from apps.invoices.models import Invoice

        self.tenant = Tenant.objects.create(
            name='Invariant Spa', slug='inv-spa', plan='pro',
            status=Tenant.Status.ACTIVE,
        )
        self.merchant = MerchantAccount.objects.create(
            tenant=self.tenant, stripe_account_id='acct_inv',
            charges_enabled=True, payouts_enabled=True,
            details_submitted=True,
        )
        self.customer = Customer.objects.create(
            tenant=self.tenant, first_name='I', last_name='V',
            email='iv@inv.test',
        )
        self.invoice = Invoice.objects.create(
            tenant=self.tenant, customer=self.customer,
            subtotal_cents=20_000, tax_cents=0, total_cents=20_000,
            status='paid',
            closed_at=dt.datetime.now(tz=dt.timezone.utc),
        )

    def test_charge_zero_amount_rejected(self):
        from django.db.utils import IntegrityError
        from apps.payments.models import Charge
        with self.assertRaises(IntegrityError):
            Charge.objects.create(
                tenant=self.tenant, invoice=self.invoice,
                merchant_account=self.merchant,
                amount_cents=0,
                stripe_payment_intent_id='pi_zero',
            )

    def test_refunded_cents_cannot_exceed_amount(self):
        from django.db.utils import IntegrityError
        from apps.payments.models import Charge
        c = Charge.objects.create(
            tenant=self.tenant, invoice=self.invoice,
            merchant_account=self.merchant,
            amount_cents=10_000,
            stripe_payment_intent_id='pi_over',
            status=Charge.Status.SUCCEEDED,
        )
        # Try to set refunded_cents above amount_cents — DB rejects.
        c.refunded_cents = 10_001
        with self.assertRaises(IntegrityError):
            c.save()

    def test_refundable_cents_is_amount_minus_refunded(self):
        from apps.payments.models import Charge
        c = Charge.objects.create(
            tenant=self.tenant, invoice=self.invoice,
            merchant_account=self.merchant,
            amount_cents=10_000, refunded_cents=3_000,
            stripe_payment_intent_id='pi_part',
            status=Charge.Status.SUCCEEDED,
        )
        self.assertEqual(c.refundable_cents, 7_000)
        self.assertFalse(c.is_fully_refunded)

    def test_refundable_is_zero_when_not_succeeded(self):
        from apps.payments.models import Charge
        c = Charge.objects.create(
            tenant=self.tenant, invoice=self.invoice,
            merchant_account=self.merchant,
            amount_cents=10_000,
            stripe_payment_intent_id='pi_pending',
            status=Charge.Status.PENDING,
        )
        self.assertEqual(c.refundable_cents, 0)

    def test_refund_zero_amount_rejected(self):
        from django.db.utils import IntegrityError
        from apps.payments.models import Charge, Refund
        c = Charge.objects.create(
            tenant=self.tenant, invoice=self.invoice,
            merchant_account=self.merchant,
            amount_cents=10_000,
            stripe_payment_intent_id='pi_for_zero_refund',
            status=Charge.Status.SUCCEEDED,
        )
        with self.assertRaises(IntegrityError):
            Refund.objects.create(
                tenant=self.tenant, charge=c,
                amount_cents=0, reason='nope',
                stripe_refund_id='re_zero',
            )
