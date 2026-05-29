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
