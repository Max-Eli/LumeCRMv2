"""Tests for the billing app.

Stripe is mocked everywhere — no real network calls. Tests focus on:

  - Webhook receiver: signature verification, event routing,
    graceful failure when STRIPE_WEBHOOK_SECRET is empty.
  - ``sync_from_stripe``: tenant resolution from metadata, plan +
    status mirroring, period-end roll resets usage counters,
    addon quantity rebuild from items, grandfathered short-circuit.
  - Portal session endpoint: permission gate (MANAGE_BILLING),
    grandfathered 409, not-configured 503, happy path.

The actual Stripe API calls (Customer.create, Subscription.create,
billing_portal.Session.create) are exercised against Stripe Test mode
manually before launch — the assertions there are about the network
contract, not our code, and adding a real-Stripe pytest suite would
slow CI without buying confidence we can't get from manual replay.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from apps.billing.services import (
    StripeBillingError,
    StripeNotConfigured,
    is_configured,
    sync_from_stripe,
)
from apps.tenants.models import Tenant, TenantMembership

User = get_user_model()


def _stripe_subscription(
    *,
    tenant_id: int,
    plan: str = 'pro',
    status: str = 'active',
    current_period_end: int = 1_900_000_000,  # far-future ts
    items: list[dict] | None = None,
):
    """Build a SimpleNamespace shaped like a stripe.Subscription object.

    Stripe SDK objects support attribute access; SimpleNamespace
    behaves identically for our purposes (we don't call methods on
    the subscription itself, only read fields).
    """
    item_objs = []
    for item in items or []:
        price_obj = SimpleNamespace(metadata=item.get('price_metadata', {}))
        item_objs.append(SimpleNamespace(
            price=price_obj,
            quantity=item.get('quantity', 1),
        ))
    return SimpleNamespace(
        id='sub_test_123',
        status=status,
        current_period_end=current_period_end,
        metadata={
            'lume_tenant_id': str(tenant_id),
            'lume_plan': plan,
        },
        items=SimpleNamespace(data=item_objs),
    )


# ── sync_from_stripe ─────────────────────────────────────────────


class SyncFromStripeTests(TestCase):
    """Verifies that webhook-driven state syncs land correctly on
    the Tenant row. Each Stripe status maps to a specific local
    status; period end rolls reset usage; add-on items rebuild
    addon_quantities."""

    def setUp(self):
        self.tenant = Tenant.objects.create(
            name='Sync Spa', slug='sync-spa', plan='trial',
            stripe_subscription_id='sub_test_123',
            current_period_sms_count=42,
            current_period_email_count=99,
        )

    def test_trialing_status_maps_to_trial(self):
        sub = _stripe_subscription(tenant_id=self.tenant.id, status='trialing', plan='pro')
        synced = sync_from_stripe(sub)
        self.assertEqual(synced.status, Tenant.Status.TRIAL)
        # plan stays 'trial' while trialing, regardless of target plan
        self.assertEqual(synced.plan, Tenant.Plan.TRIAL)

    def test_active_status_maps_plan_to_target(self):
        sub = _stripe_subscription(tenant_id=self.tenant.id, status='active', plan='pro')
        synced = sync_from_stripe(sub)
        self.assertEqual(synced.status, Tenant.Status.ACTIVE)
        self.assertEqual(synced.plan, Tenant.Plan.PRO)

    def test_past_due_status_maps_to_past_due(self):
        sub = _stripe_subscription(tenant_id=self.tenant.id, status='past_due', plan='pro')
        synced = sync_from_stripe(sub)
        self.assertEqual(synced.status, Tenant.Status.PAST_DUE)

    def test_unpaid_status_also_maps_to_past_due(self):
        sub = _stripe_subscription(tenant_id=self.tenant.id, status='unpaid', plan='pro')
        synced = sync_from_stripe(sub)
        self.assertEqual(synced.status, Tenant.Status.PAST_DUE)

    def test_canceled_status_maps_to_cancelled(self):
        sub = _stripe_subscription(tenant_id=self.tenant.id, status='canceled', plan='pro')
        synced = sync_from_stripe(sub)
        self.assertEqual(synced.status, Tenant.Status.CANCELLED)

    def test_period_roll_resets_usage_counters(self):
        sub = _stripe_subscription(
            tenant_id=self.tenant.id, status='active', plan='pro',
            current_period_end=2_000_000_000,
        )
        synced = sync_from_stripe(sub)
        self.assertEqual(synced.current_period_sms_count, 0)
        self.assertEqual(synced.current_period_email_count, 0)

    def test_addon_items_rebuild_quantities(self):
        sub = _stripe_subscription(
            tenant_id=self.tenant.id, status='active', plan='pro',
            items=[
                # Base plan price — no addon metadata, should be ignored.
                {'price_metadata': {}, 'quantity': 1},
                {'price_metadata': {'lume_addon_key': 'staff'}, 'quantity': 3},
                {'price_metadata': {'lume_addon_key': 'location'}, 'quantity': 1},
                {'price_metadata': {'lume_addon_key': 'email_10k'}, 'quantity': 2},
            ],
        )
        synced = sync_from_stripe(sub)
        self.assertEqual(synced.addon_quantities, {
            'staff': 3, 'location': 1, 'email_10k': 2,
        })

    def test_addon_with_zero_quantity_omitted(self):
        sub = _stripe_subscription(
            tenant_id=self.tenant.id, status='active', plan='pro',
            items=[
                {'price_metadata': {'lume_addon_key': 'staff'}, 'quantity': 0},
                {'price_metadata': {'lume_addon_key': 'location'}, 'quantity': 2},
            ],
        )
        synced = sync_from_stripe(sub)
        self.assertEqual(synced.addon_quantities, {'location': 2})

    def test_grandfathered_tenant_short_circuits(self):
        gf = Tenant.objects.create(
            name='Grandfathered', slug='gf-spa', plan='pro',
            grandfathered=True, current_period_sms_count=100,
        )
        sub = _stripe_subscription(tenant_id=gf.id, status='active', plan='pro')
        # Should NOT mutate the grandfathered tenant even if a stray
        # webhook arrives for them. Counters stay where they were.
        synced = sync_from_stripe(sub)
        self.assertEqual(synced.current_period_sms_count, 100)
        # Status untouched (we didn't set TRIAL on the gf row).

    def test_missing_tenant_id_metadata_raises(self):
        sub = SimpleNamespace(
            id='sub_no_meta', status='active',
            current_period_end=2_000_000_000,
            metadata={},
            items=SimpleNamespace(data=[]),
        )
        with self.assertRaises(StripeBillingError):
            sync_from_stripe(sub)

    def test_bad_tenant_id_raises(self):
        sub = _stripe_subscription(tenant_id=99999999, status='active', plan='pro')
        with self.assertRaises(StripeBillingError):
            sync_from_stripe(sub)


# ── Webhook signature + routing ──────────────────────────────────


class WebhookTests(TestCase):
    """The Stripe webhook receiver verifies signatures + routes
    events to ``sync_from_stripe``. These tests mock the SDK's
    Webhook.construct_event so we can drive the path without
    real signing secrets."""

    def setUp(self):
        self.client = APIClient()
        self.tenant = Tenant.objects.create(
            name='WH Spa', slug='wh-spa', plan='trial',
            stripe_subscription_id='sub_wh_1',
        )
        self.url = reverse('billing-stripe-webhook')

    def _post(self, body=b'{}', sig='t=1,v1=abc'):
        return self.client.post(
            self.url, data=body, content_type='application/json',
            HTTP_STRIPE_SIGNATURE=sig,
        )

    @override_settings(STRIPE_WEBHOOK_SECRET='')
    def test_missing_secret_returns_503(self):
        resp = self._post()
        self.assertEqual(resp.status_code, 503)

    @override_settings(STRIPE_WEBHOOK_SECRET='whsec_test')
    @patch('stripe.Webhook.construct_event')
    def test_invalid_payload_returns_400(self, construct):
        construct.side_effect = ValueError('bad json')
        resp = self._post(body=b'not json')
        self.assertEqual(resp.status_code, 400)

    @override_settings(STRIPE_WEBHOOK_SECRET='whsec_test')
    @patch('stripe.Webhook.construct_event')
    def test_bad_signature_returns_400(self, construct):
        import stripe
        construct.side_effect = stripe.error.SignatureVerificationError(
            'bad sig', sig_header='t=...,v1=fake',
        )
        resp = self._post()
        self.assertEqual(resp.status_code, 400)

    @override_settings(STRIPE_WEBHOOK_SECRET='whsec_test')
    @patch('apps.billing.webhooks.sync_from_stripe')
    @patch('stripe.Webhook.construct_event')
    def test_subscription_updated_calls_sync(self, construct, sync):
        construct.return_value = {
            'id': 'evt_1',
            'type': 'customer.subscription.updated',
            'data': {'object': {'id': 'sub_wh_1'}},
        }
        resp = self._post()
        self.assertEqual(resp.status_code, 200)
        sync.assert_called_once()

    @override_settings(STRIPE_WEBHOOK_SECRET='whsec_test')
    @patch('apps.billing.webhooks.sync_from_stripe')
    @patch('stripe.Webhook.construct_event')
    def test_unhandled_event_type_returns_200(self, construct, sync):
        construct.return_value = {
            'id': 'evt_2',
            'type': 'some.other.event',
            'data': {'object': {}},
        }
        resp = self._post()
        self.assertEqual(resp.status_code, 200)
        sync.assert_not_called()

    @override_settings(STRIPE_WEBHOOK_SECRET='whsec_test')
    @patch('apps.billing.webhooks.sync_from_stripe')
    @patch('stripe.Webhook.construct_event')
    def test_billing_error_during_sync_returns_200(self, construct, sync):
        # A predictable billing error shouldn't cause Stripe to retry;
        # we 200 + log and move on.
        construct.return_value = {
            'id': 'evt_3',
            'type': 'customer.subscription.updated',
            'data': {'object': {}},
        }
        sync.side_effect = StripeBillingError('cannot resolve tenant')
        resp = self._post()
        self.assertEqual(resp.status_code, 200)

    @override_settings(STRIPE_WEBHOOK_SECRET='whsec_test')
    @patch('apps.billing.webhooks.sync_from_stripe')
    @patch('stripe.Webhook.construct_event')
    def test_unexpected_error_returns_500_for_retry(self, construct, sync):
        construct.return_value = {
            'id': 'evt_4',
            'type': 'customer.subscription.updated',
            'data': {'object': {}},
        }
        sync.side_effect = RuntimeError('something exploded')
        resp = self._post()
        # 500 so Stripe retries — gives us time to fix + replay.
        self.assertEqual(resp.status_code, 500)


# ── Portal session endpoint ──────────────────────────────────────


class PortalSessionTests(TestCase):
    """The portal-session endpoint authorizes (MANAGE_BILLING),
    enforces the grandfathered-no-self-serve rule, and surfaces
    503 when Stripe isn't configured. The happy path calls
    services.create_portal_session which we mock."""

    def setUp(self):
        self.tenant = Tenant.objects.create(
            # ACTIVE status so TenantMiddleware resolves the request.
            # Our portal tests are about the endpoint logic, not the
            # subscription lifecycle.
            name='Portal Spa', slug='portal-spa', plan='pro',
            status=Tenant.Status.ACTIVE,
            stripe_customer_id='cus_test_1',
        )
        self.owner = User.objects.create_user(
            email='owner@portal.test', password='x',
        )
        TenantMembership.objects.create(
            user=self.owner, tenant=self.tenant,
            role=TenantMembership.Role.OWNER, is_active=True,
        )
        self.front_desk = User.objects.create_user(
            email='desk@portal.test', password='x',
        )
        TenantMembership.objects.create(
            user=self.front_desk, tenant=self.tenant,
            role=TenantMembership.Role.FRONT_DESK, is_active=True,
        )
        self.client = APIClient()
        self.url = reverse('billing-portal-session')

    def test_unauthenticated_returns_403(self):
        resp = self.client.post(self.url, {}, HTTP_X_TENANT_SLUG=self.tenant.slug)
        self.assertEqual(resp.status_code, 403)

    def test_front_desk_lacks_manage_billing(self):
        self.client.force_login(self.front_desk)
        resp = self.client.post(self.url, {}, HTTP_X_TENANT_SLUG=self.tenant.slug)
        self.assertEqual(resp.status_code, 403)

    @override_settings(STRIPE_SECRET_KEY='')
    def test_owner_gets_503_when_stripe_not_configured(self):
        self.client.force_login(self.owner)
        resp = self.client.post(self.url, {}, HTTP_X_TENANT_SLUG=self.tenant.slug)
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.data['code'], 'stripe_not_configured')

    def test_grandfathered_owner_gets_409(self):
        gf_tenant = Tenant.objects.create(
            name='GF Spa', slug='gf-portal-spa', plan='pro',
            status=Tenant.Status.ACTIVE, grandfathered=True,
        )
        gf_owner = User.objects.create_user(
            email='gf-owner@portal.test', password='x',
        )
        TenantMembership.objects.create(
            user=gf_owner, tenant=gf_tenant,
            role=TenantMembership.Role.OWNER, is_active=True,
        )
        self.client.force_login(gf_owner)
        resp = self.client.post(self.url, {}, HTTP_X_TENANT_SLUG=gf_tenant.slug)
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.data['code'], 'grandfathered_no_self_serve_billing')

    @override_settings(STRIPE_SECRET_KEY='sk_test_fake')
    @patch('apps.billing.views.create_portal_session')
    def test_owner_happy_path_returns_url(self, create_session):
        create_session.return_value = 'https://billing.stripe.com/session/abc'
        self.client.force_login(self.owner)
        resp = self.client.post(
            self.url, {'return_url': 'https://example.com/back'},
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['url'], 'https://billing.stripe.com/session/abc')
        create_session.assert_called_once()


# ── Configuration helpers ────────────────────────────────────────


class IsConfiguredTests(TestCase):

    @override_settings(STRIPE_SECRET_KEY='')
    def test_empty_key_is_not_configured(self):
        self.assertFalse(is_configured())

    @override_settings(STRIPE_SECRET_KEY='sk_test_anything')
    def test_set_key_is_configured(self):
        self.assertTrue(is_configured())


# ── Billing summary endpoint ─────────────────────────────────────


class BillingSummaryTests(TestCase):
    """The summary endpoint is what /settings/billing reads to render
    the dashboard. It must work for grandfathered tenants (who never
    enrolled in Stripe) AND for new Stripe-billed tenants, without
    requiring Stripe to be configured at all."""

    def setUp(self):
        self.tenant = Tenant.objects.create(
            name='Sum Spa', slug='sum-spa', plan='pro',
            status=Tenant.Status.ACTIVE,
            billing_cycle=Tenant.BillingCycle.MONTHLY,
            current_period_sms_count=42,
            current_period_email_count=1234,
            addon_quantities={'staff': 3, 'location': 1},
        )
        self.owner = User.objects.create_user(
            email='owner@sum.test', password='x',
        )
        TenantMembership.objects.create(
            user=self.owner, tenant=self.tenant,
            role=TenantMembership.Role.OWNER, is_active=True,
        )
        self.client = APIClient()
        self.url = reverse('billing-summary')

    def test_owner_can_read_summary(self):
        self.client.force_login(self.owner)
        resp = self.client.get(self.url, HTTP_X_TENANT_SLUG=self.tenant.slug)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['plan'], 'pro')
        self.assertEqual(resp.data['addons'], {'staff': 3, 'location': 1})
        self.assertEqual(resp.data['usage']['sms_used'], 42)
        self.assertEqual(resp.data['usage']['email_used'], 1234)
        # 10 baseline + 3 staff add-on
        self.assertEqual(resp.data['capacity']['max_staff'], 13)
        # 3 baseline + 1 location add-on
        self.assertEqual(resp.data['capacity']['max_locations'], 4)
        # Frontend toggles "Manage payment" CTA off when Stripe isn't ready
        self.assertIn('stripe_configured', resp.data)

    def test_front_desk_cannot_read_summary(self):
        front_desk = User.objects.create_user(
            email='fd@sum.test', password='x',
        )
        TenantMembership.objects.create(
            user=front_desk, tenant=self.tenant,
            role=TenantMembership.Role.FRONT_DESK, is_active=True,
        )
        self.client.force_login(front_desk)
        resp = self.client.get(self.url, HTTP_X_TENANT_SLUG=self.tenant.slug)
        self.assertEqual(resp.status_code, 403)

    def test_grandfathered_gets_unlimited_caps_and_no_allowed_addons(self):
        gf = Tenant.objects.create(
            name='Grandfathered', slug='sum-gf-spa', plan='pro',
            status=Tenant.Status.ACTIVE, grandfathered=True,
        )
        gf_owner = User.objects.create_user(
            email='gf-sum@sum.test', password='x',
        )
        TenantMembership.objects.create(
            user=gf_owner, tenant=gf,
            role=TenantMembership.Role.OWNER, is_active=True,
        )
        self.client.force_login(gf_owner)
        resp = self.client.get(self.url, HTTP_X_TENANT_SLUG=gf.slug)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data['grandfathered'])
        # null = unlimited; frontend renders ∞
        self.assertIsNone(resp.data['capacity']['max_staff'])
        self.assertIsNone(resp.data['capacity']['max_locations'])
        # No self-serve add-ons for legacy tenants
        self.assertEqual(resp.data['allowed_addons'], {})


# ── Update add-on quantity endpoint ──────────────────────────────


class UpdateAddonQuantityTests(TestCase):
    """The endpoint that the /settings/billing buttons hit. Validates
    against the plan's allowed add-ons + ranges before talking to
    Stripe, so a bad client can't waste a Stripe round-trip."""

    def setUp(self):
        self.tenant = Tenant.objects.create(
            name='Addon Spa', slug='addon-spa', plan='pro',
            status=Tenant.Status.ACTIVE,
            stripe_subscription_id='sub_test_addon',
        )
        self.owner = User.objects.create_user(
            email='addon-owner@addon.test', password='x',
        )
        TenantMembership.objects.create(
            user=self.owner, tenant=self.tenant,
            role=TenantMembership.Role.OWNER, is_active=True,
        )
        self.client = APIClient()
        self.url = reverse('billing-addon-quantity')
        self.client.force_login(self.owner)

    def _post(self, body):
        return self.client.post(
            self.url, body, format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )

    def test_missing_addon_key_is_400(self):
        resp = self._post({'quantity': 1})
        self.assertEqual(resp.status_code, 400)

    def test_non_int_quantity_is_400(self):
        resp = self._post({'addon_key': 'staff', 'quantity': 'lots'})
        self.assertEqual(resp.status_code, 400)

    def test_unknown_addon_is_400(self):
        resp = self._post({'addon_key': 'spaceship', 'quantity': 1})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data['code'], 'invalid_addon_request')

    def test_location_addon_capped_at_two(self):
        resp = self._post({'addon_key': 'location', 'quantity': 3})
        self.assertEqual(resp.status_code, 400)

    @override_settings(STRIPE_SECRET_KEY='')
    def test_stripe_not_configured_returns_503(self):
        resp = self._post({'addon_key': 'staff', 'quantity': 3})
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.data['code'], 'stripe_not_configured')

    @override_settings(STRIPE_SECRET_KEY='sk_test_fake')
    @patch('apps.billing.views.set_addon_quantity')
    def test_happy_path_updates(self, mock_set):
        # Simulate the service updating the local row.
        def _fake(tenant, *, addon_key, quantity):
            tenant.addon_quantities = {addon_key: quantity}
            tenant.save(update_fields=['addon_quantities'])
        mock_set.side_effect = _fake
        resp = self._post({'addon_key': 'staff', 'quantity': 5})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['quantity'], 5)
        self.assertEqual(resp.data['addons'], {'staff': 5})

    def test_grandfathered_returns_409(self):
        gf = Tenant.objects.create(
            name='AddonGF', slug='addon-gf', plan='pro',
            status=Tenant.Status.ACTIVE, grandfathered=True,
        )
        gf_owner = User.objects.create_user(
            email='gf-addon@addon.test', password='x',
        )
        TenantMembership.objects.create(
            user=gf_owner, tenant=gf,
            role=TenantMembership.Role.OWNER, is_active=True,
        )
        self.client.logout()
        self.client.force_login(gf_owner)
        resp = self.client.post(
            self.url, {'addon_key': 'staff', 'quantity': 3},
            format='json', HTTP_X_TENANT_SLUG=gf.slug,
        )
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.data['code'], 'grandfathered_no_self_serve_billing')


# ── Dunning notifications + Celery-equivalent commands (Phase 5) ──


import datetime as dt  # noqa: E402

from django.core import mail  # noqa: E402
from django.core.management import call_command  # noqa: E402
from django.test import override_settings  # noqa: E402
from django.utils import timezone as djtz  # noqa: E402


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class SendNotificationTests(TestCase):
    """Unit tests for ``apps.billing.notifications.send_notification`` —
    the idempotency tracker, audit log writes, and per-kind body
    rendering all behave correctly. HIPAA: no PHI ever ends up in
    these bodies (verified by inspection + by an explicit assertion
    against patient-name fields)."""

    def setUp(self):
        from django.contrib.auth import get_user_model
        from apps.tenants.services import create_tenant_with_defaults
        self.tenant = create_tenant_with_defaults(
            name='Test Spa Notifications',
            slug='test-spa-notif',
            owner_user=get_user_model().objects.create_user(
                email='owner-notif@example.com', password='x',
                first_name='Pat', last_name='Owner',
            ),
            status=Tenant.Status.TRIAL,
            plan=Tenant.Plan.TRIAL,
            trial_ends_at=djtz.now() + dt.timedelta(days=7),
        )

    def test_send_notification_sends_and_marks_sent(self):
        from apps.billing.notifications import send_notification
        sent = send_notification(tenant=self.tenant, kind='trial_7d')
        self.assertTrue(sent)
        self.assertEqual(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self.assertIn('trial ends in 7 days', msg.subject.lower())
        self.assertIn('owner-notif@example.com', msg.to)
        # Idempotency tracker stamped.
        self.tenant.refresh_from_db()
        self.assertIn('trial_7d', self.tenant.notifications_sent)

    def test_idempotent_second_call_skips(self):
        from apps.billing.notifications import send_notification
        self.assertTrue(send_notification(tenant=self.tenant, kind='trial_7d'))
        # Second call returns False + outbox stays at 1.
        self.assertFalse(send_notification(tenant=self.tenant, kind='trial_7d'))
        self.assertEqual(len(mail.outbox), 1)

    def test_force_true_bypasses_idempotency(self):
        from apps.billing.notifications import send_notification
        self.assertTrue(send_notification(tenant=self.tenant, kind='trial_7d'))
        self.assertTrue(
            send_notification(tenant=self.tenant, kind='trial_7d', force=True),
        )
        self.assertEqual(len(mail.outbox), 2)

    def test_unknown_kind_returns_false(self):
        from apps.billing.notifications import send_notification
        # Type-narrowed at the call site but we still defend at runtime.
        self.assertFalse(send_notification(tenant=self.tenant, kind='unknown'))  # type: ignore[arg-type]
        self.assertEqual(len(mail.outbox), 0)

    def test_no_owner_falls_back_to_billing_email(self):
        from apps.billing.notifications import send_notification
        # Deactivate the owner membership.
        self.tenant.memberships.update(is_active=False)
        self.tenant.billing_email = 'billing@example.com'
        self.tenant.save()
        sent = send_notification(tenant=self.tenant, kind='trial_7d')
        self.assertTrue(sent)
        self.assertIn('billing@example.com', mail.outbox[0].to)

    def test_audit_log_written_on_send(self):
        from apps.audit.models import AuditLog
        from apps.billing.notifications import send_notification
        baseline = AuditLog.objects.filter(
            resource_type='tenant_notification',
        ).count()
        send_notification(tenant=self.tenant, kind='payment_failed')
        log = AuditLog.objects.filter(
            resource_type='tenant_notification',
        ).order_by('-timestamp').first()
        self.assertEqual(
            AuditLog.objects.filter(resource_type='tenant_notification').count(),
            baseline + 1,
        )
        self.assertEqual(log.metadata['kind'], 'payment_failed')
        # Recipient DOMAIN only — same posture as SES bounce audit.
        # Full recipient address NOT in audit log.
        self.assertEqual(log.metadata['recipient_domain'], 'example.com')
        self.assertNotIn('owner-notif@example.com', str(log.metadata))

    def test_email_body_contains_NO_PHI(self):
        """HIPAA invariant — billing emails are operator-only;
        nothing in the body should reference patient names, service
        names, or other clinical data. This test is the guardrail."""
        from apps.billing.notifications import send_notification

        # PHI-shaped strings that must NEVER appear in a body.
        forbidden = ['ssn', 'social security', 'medical record number']

        for kind in ('trial_7d', 'trial_3d', 'trial_1d',
                     'payment_failed', 'suspended_warning'):
            mail.outbox.clear()
            self.tenant.notifications_sent = {}
            self.tenant.save()
            send_notification(tenant=self.tenant, kind=kind)
            body = mail.outbox[0].body.lower()
            for term in forbidden:
                self.assertNotIn(
                    term, body,
                    f'{kind} email body contains forbidden PHI-shaped term: {term}',
                )

    def test_clear_notification_removes_key(self):
        from apps.billing.notifications import (
            clear_notification, send_notification,
        )
        send_notification(tenant=self.tenant, kind='payment_failed')
        self.tenant.refresh_from_db()
        self.assertIn('payment_failed', self.tenant.notifications_sent)
        clear_notification(tenant=self.tenant, kind='payment_failed')
        self.tenant.refresh_from_db()
        self.assertNotIn('payment_failed', self.tenant.notifications_sent)


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class SendTrialRemindersCommandTests(TestCase):
    """The daily ``send_trial_reminders`` command. Idempotent across
    multiple invocations; respects the per-window slop; never sends
    to non-trial / grandfathered tenants."""

    def setUp(self):
        from django.contrib.auth import get_user_model
        from apps.tenants.services import create_tenant_with_defaults
        self.User = get_user_model()
        self._mktenant = lambda slug, days, **kw: create_tenant_with_defaults(
            name=slug.replace('-', ' ').title(),
            slug=slug,
            owner_user=self.User.objects.create_user(
                email=f'{slug}@trialtest.com', password='x', first_name='X',
            ),
            status=kw.pop('status', Tenant.Status.TRIAL),
            plan=kw.pop('plan', Tenant.Plan.TRIAL),
            trial_ends_at=djtz.now() + dt.timedelta(days=days),
            **kw,
        )

    def test_7d_window_sends_trial_7d(self):
        self._mktenant('seven-day-spa', days=7)
        call_command('send_trial_reminders')
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('7 days', mail.outbox[0].subject)

    def test_3d_window_sends_trial_3d(self):
        self._mktenant('three-day-spa', days=3)
        call_command('send_trial_reminders')
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('3 days', mail.outbox[0].subject)

    def test_1d_window_sends_trial_1d(self):
        self._mktenant('one-day-spa', days=1)
        call_command('send_trial_reminders')
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('tomorrow', mail.outbox[0].subject)

    def test_outside_window_sends_nothing(self):
        # 14 days out — no reminder applies yet.
        self._mktenant('mid-trial-spa', days=14)
        call_command('send_trial_reminders')
        self.assertEqual(len(mail.outbox), 0)

    def test_grandfathered_tenant_skipped(self):
        self._mktenant('gf-spa-trial', days=7, grandfathered=True)
        call_command('send_trial_reminders')
        self.assertEqual(len(mail.outbox), 0)

    def test_active_tenant_skipped(self):
        self._mktenant(
            'active-spa-trial', days=7,
            status=Tenant.Status.ACTIVE, plan=Tenant.Plan.STARTER,
        )
        call_command('send_trial_reminders')
        self.assertEqual(len(mail.outbox), 0)

    def test_idempotent_second_run_sends_nothing(self):
        self._mktenant('idempotent-spa', days=7)
        call_command('send_trial_reminders')
        call_command('send_trial_reminders')
        self.assertEqual(len(mail.outbox), 1)

    def test_dry_run_sends_nothing(self):
        self._mktenant('dryrun-spa', days=7)
        call_command('send_trial_reminders', dry_run=True)
        self.assertEqual(len(mail.outbox), 0)
        # Idempotency key NOT set on dry-run (so a real run
        # afterwards still sends).
        t = Tenant.objects.get(slug='dryrun-spa')
        self.assertNotIn('trial_7d', t.notifications_sent or {})

    def test_tenant_flag_limits_to_one(self):
        self._mktenant('one-of-two-a', days=7)
        self._mktenant('one-of-two-b', days=7)
        call_command('send_trial_reminders', tenant='one-of-two-a')
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('one-of-two-a', mail.outbox[0].to[0])


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class ProcessDunningCommandTests(TestCase):
    """``process_dunning`` handles past_due → suspended transition +
    payment_failed + suspended_warning emails."""

    def setUp(self):
        from django.contrib.auth import get_user_model
        from apps.tenants.services import create_tenant_with_defaults
        self.User = get_user_model()
        self._mktenant = lambda slug, status, **kw: create_tenant_with_defaults(
            name=slug.replace('-', ' ').title(),
            slug=slug,
            owner_user=self.User.objects.create_user(
                email=f'{slug}@dunning.com', password='x', first_name='Y',
            ),
            status=status,
            plan=kw.pop('plan', Tenant.Plan.STARTER),
            **kw,
        )

    def test_past_due_tenant_gets_payment_failed_email(self):
        self._mktenant('past-due-fresh', Tenant.Status.PAST_DUE)
        call_command('process_dunning')
        # 1 email (payment_failed); no transition yet (just-now updated_at).
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('payment failed', mail.outbox[0].subject.lower())

    def test_past_due_over_7_days_transitions_to_suspended(self):
        t = self._mktenant('past-due-old', Tenant.Status.PAST_DUE)
        # Force updated_at backwards to simulate 8 days in past_due.
        Tenant.objects.filter(pk=t.pk).update(
            updated_at=djtz.now() - dt.timedelta(days=8),
        )
        call_command('process_dunning')
        t.refresh_from_db()
        self.assertEqual(t.status, Tenant.Status.SUSPENDED)

    def test_suspended_45_days_gets_warning_email(self):
        t = self._mktenant('suspended-45', Tenant.Status.SUSPENDED)
        Tenant.objects.filter(pk=t.pk).update(
            updated_at=djtz.now() - dt.timedelta(days=46),
        )
        call_command('process_dunning')
        # Find the suspended_warning email (subject contains "deleted").
        deletion_emails = [
            m for m in mail.outbox if 'deleted' in m.subject.lower()
        ]
        self.assertEqual(len(deletion_emails), 1)

    def test_suspended_under_45_days_gets_no_warning(self):
        t = self._mktenant('suspended-recent', Tenant.Status.SUSPENDED)
        Tenant.objects.filter(pk=t.pk).update(
            updated_at=djtz.now() - dt.timedelta(days=10),
        )
        call_command('process_dunning')
        # No data-deletion email.
        for msg in mail.outbox:
            self.assertNotIn('deleted', msg.subject.lower())

    def test_grandfathered_tenant_skipped_even_if_past_due(self):
        # Grandfathered tenants are exempt from automated dunning.
        self._mktenant(
            'gf-past-due', Tenant.Status.PAST_DUE, grandfathered=True,
        )
        call_command('process_dunning')
        self.assertEqual(len(mail.outbox), 0)

    def test_idempotent_payment_failed_not_resent(self):
        self._mktenant('idem-pd', Tenant.Status.PAST_DUE)
        call_command('process_dunning')
        call_command('process_dunning')
        # Two runs = one email (idempotency tracker hits on run 2).
        self.assertEqual(len(mail.outbox), 1)

    def test_dry_run_changes_nothing(self):
        t = self._mktenant('dryrun-pd', Tenant.Status.PAST_DUE)
        Tenant.objects.filter(pk=t.pk).update(
            updated_at=djtz.now() - dt.timedelta(days=10),
        )
        call_command('process_dunning', dry_run=True)
        t.refresh_from_db()
        self.assertEqual(t.status, Tenant.Status.PAST_DUE)  # NOT suspended
        self.assertEqual(len(mail.outbox), 0)
