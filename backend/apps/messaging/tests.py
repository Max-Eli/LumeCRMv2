"""Tests for the customer messaging surface (apps.messaging).

Covers six invariants:

  1. Auth — operator endpoints require `IsAuthenticated`; anonymous
     gets 403/401.
  2. Tenant scoping — threads / conversations / send only ever see
     rows from `request.tenant`.
  3. Inbound webhook — signature is verified outside test mode;
     unknown TFN / unknown customer / duplicate SID all return 200
     so Twilio doesn't retry.
  4. Outbound send — gated by phone-on-file + `customer.sms_opt_in`;
     Twilio errors mark the row FAILED + raise 400 to the operator.
  5. Read-state — `mark-read` flips `read_at` on inbound messages
     only; unread-count surfaces in threads list.
  6. PHI audit — every operator read / write writes an AuditLog row
     with redacted metadata (no full phone, no body).

Mirrors the test posture used in `apps.marketing.tests` so this
suite reads the same way to anyone who's worked on the campaign
tests.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.audit.models import AuditLog
from apps.customers.models import Customer
from apps.tenants.models import Tenant
from apps.tenants.services import create_tenant_with_defaults

from .models import Direction, Message, MessageStatus

User = get_user_model()


# ── Fixtures ─────────────────────────────────────────────────────────


def _make_user(email: str) -> User:
    return User.objects.create_user(email=email, password='test-pw')


def _make_tenant(slug: str, *, tfn: str = '+18445550000') -> tuple[Tenant, User]:
    owner = _make_user(f'{slug}-owner@test.local')
    tenant = create_tenant_with_defaults(
        name=slug.title(), slug=slug, owner_user=owner,
        status=Tenant.Status.ACTIVE,
    )
    tenant.twilio_from_number = tfn
    tenant.save(update_fields=['twilio_from_number'])
    return tenant, owner


def _make_customer(
    tenant: Tenant, *,
    phone: str = '+15551234567',
    sms_opt_in: bool = True,
) -> Customer:
    return Customer.objects.create(
        tenant=tenant,
        first_name='Pat', last_name='Patient',
        phone=phone, sms_opt_in=sms_opt_in,
    )


def _client_for(user) -> APIClient:
    c = APIClient()
    c.force_login(user)
    return c


# ── Permission gating ────────────────────────────────────────────────


class MessagingPermissionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant, cls.owner = _make_tenant('perm-spa')
        cls.customer = _make_customer(cls.tenant)

    def test_threads_requires_auth(self):
        response = APIClient().get(
            reverse('messaging-threads'),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertIn(response.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))

    def test_conversation_requires_auth(self):
        response = APIClient().get(
            reverse('messaging-conversation-detail', kwargs={'pk': self.customer.pk}),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertIn(response.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))

    def test_send_requires_auth(self):
        response = APIClient().post(
            reverse('messaging-conversation-send', kwargs={'pk': self.customer.pk}),
            data={'body': 'hi'}, format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertIn(response.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))


# ── Threads list ─────────────────────────────────────────────────────


class ThreadsListTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant, cls.owner = _make_tenant('threads-spa')
        cls.other_tenant, _ = _make_tenant('other-spa', tfn='+18445559999')
        cls.alice = _make_customer(cls.tenant, phone='+15550000001')
        cls.bob = _make_customer(cls.tenant, phone='+15550000002')
        cls.foreign = _make_customer(cls.other_tenant, phone='+15550000003')

        # Alice: 2 outbound + 1 unread inbound.
        Message.objects.create(
            tenant=cls.tenant, customer=cls.alice,
            direction=Direction.OUTBOUND, body='earlier outbound',
            status=MessageStatus.SENT,
        )
        Message.objects.create(
            tenant=cls.tenant, customer=cls.alice,
            direction=Direction.INBOUND, body='alice reply (unread)',
            status=MessageStatus.RECEIVED,
        )
        cls.alice_latest = Message.objects.create(
            tenant=cls.tenant, customer=cls.alice,
            direction=Direction.OUTBOUND, body='alice latest',
            status=MessageStatus.SENT,
        )
        # Bob: 1 read inbound.
        cls.bob_latest = Message.objects.create(
            tenant=cls.tenant, customer=cls.bob,
            direction=Direction.INBOUND, body='bob hi',
            status=MessageStatus.RECEIVED,
        )
        # Foreign-tenant message — MUST NOT appear in our list.
        Message.objects.create(
            tenant=cls.other_tenant, customer=cls.foreign,
            direction=Direction.OUTBOUND, body='not ours',
            status=MessageStatus.SENT,
        )

    def setUp(self):
        self.client = _client_for(self.owner)

    def test_threads_lists_one_row_per_customer(self):
        response = self.client.get(
            reverse('messaging-threads'),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        customer_ids = [row['customer_id'] for row in response.data]
        self.assertEqual(sorted(customer_ids), sorted([self.alice.pk, self.bob.pk]))

    def test_threads_preview_is_latest_message(self):
        response = self.client.get(
            reverse('messaging-threads'),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        by_cid = {row['customer_id']: row for row in response.data}
        self.assertEqual(by_cid[self.alice.pk]['last_message_body'], 'alice latest')
        self.assertEqual(by_cid[self.alice.pk]['last_message_direction'], Direction.OUTBOUND)
        self.assertEqual(by_cid[self.bob.pk]['last_message_body'], 'bob hi')

    def test_threads_unread_count_only_inbound(self):
        response = self.client.get(
            reverse('messaging-threads'),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        by_cid = {row['customer_id']: row for row in response.data}
        self.assertEqual(by_cid[self.alice.pk]['unread_inbound_count'], 1)
        self.assertEqual(by_cid[self.bob.pk]['unread_inbound_count'], 1)

    def test_threads_tenant_scoped(self):
        # Other tenant has its own message; ours shouldn't see the foreign customer.
        response = self.client.get(
            reverse('messaging-threads'),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        customer_ids = [row['customer_id'] for row in response.data]
        self.assertNotIn(self.foreign.pk, customer_ids)

    def test_threads_audit_log_written(self):
        before = AuditLog.objects.filter(resource_type='messaging_threads').count()
        self.client.get(
            reverse('messaging-threads'),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        after = AuditLog.objects.filter(resource_type='messaging_threads').count()
        self.assertEqual(after, before + 1)


# ── Conversation detail ─────────────────────────────────────────────


class ConversationDetailTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant, cls.owner = _make_tenant('conv-spa')
        cls.customer = _make_customer(cls.tenant)
        Message.objects.create(
            tenant=cls.tenant, customer=cls.customer,
            direction=Direction.OUTBOUND, body='first',
            status=MessageStatus.SENT,
        )
        Message.objects.create(
            tenant=cls.tenant, customer=cls.customer,
            direction=Direction.INBOUND, body='reply',
            status=MessageStatus.RECEIVED,
        )

    def setUp(self):
        self.client = _client_for(self.owner)

    def test_conversation_returns_messages_chronological(self):
        response = self.client.get(
            reverse('messaging-conversation-detail', kwargs={'pk': self.customer.pk}),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        bodies = [m['body'] for m in response.data['messages']]
        self.assertEqual(bodies, ['first', 'reply'])
        self.assertEqual(response.data['customer']['id'], self.customer.pk)

    def test_conversation_404_for_other_tenant_customer(self):
        other_tenant, _ = _make_tenant('other-conv', tfn='+18445558888')
        foreign = _make_customer(other_tenant, phone='+15559876543')
        response = self.client.get(
            reverse('messaging-conversation-detail', kwargs={'pk': foreign.pk}),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_conversation_audit_log_written(self):
        before = AuditLog.objects.filter(resource_type='messaging_conversation').count()
        self.client.get(
            reverse('messaging-conversation-detail', kwargs={'pk': self.customer.pk}),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        after = AuditLog.objects.filter(resource_type='messaging_conversation').count()
        self.assertEqual(after, before + 1)


# ── Mark read ────────────────────────────────────────────────────────


class MarkReadTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant, cls.owner = _make_tenant('markread-spa')
        cls.customer = _make_customer(cls.tenant)
        cls.inbound = Message.objects.create(
            tenant=cls.tenant, customer=cls.customer,
            direction=Direction.INBOUND, body='unread',
            status=MessageStatus.RECEIVED,
        )
        cls.outbound = Message.objects.create(
            tenant=cls.tenant, customer=cls.customer,
            direction=Direction.OUTBOUND, body='out',
            status=MessageStatus.SENT,
        )

    def setUp(self):
        self.client = _client_for(self.owner)

    def test_mark_read_flips_inbound_only(self):
        response = self.client.post(
            reverse('messaging-conversation-mark-read', kwargs={'pk': self.customer.pk}),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.inbound.refresh_from_db()
        self.outbound.refresh_from_db()
        self.assertIsNotNone(self.inbound.read_at)
        self.assertIsNone(self.outbound.read_at)
        self.assertEqual(response.data['rows_updated'], 1)

    def test_mark_read_404_when_customer_not_in_tenant(self):
        other_tenant, _ = _make_tenant('other-mr', tfn='+18445557777')
        foreign = _make_customer(other_tenant, phone='+15558887777')
        response = self.client.post(
            reverse('messaging-conversation-mark-read', kwargs={'pk': foreign.pk}),
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


# ── Send endpoint ───────────────────────────────────────────────────


@override_settings(
    TWILIO_ACCOUNT_SID='ACtest',
    TWILIO_AUTH_TOKEN='test-token',
)
class SendMessageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant, cls.owner = _make_tenant('send-spa', tfn='+18445551111')
        cls.customer = _make_customer(cls.tenant, phone='+15554443333', sms_opt_in=True)

    def setUp(self):
        self.client = _client_for(self.owner)

    def test_send_creates_outbound_row_with_twilio_sid(self):
        fake_msg = MagicMock(sid='SMmsgtest')
        fake_client = MagicMock()
        fake_client.messages.create.return_value = fake_msg

        with patch('twilio.rest.Client', return_value=fake_client):
            response = self.client.post(
                reverse('messaging-conversation-send', kwargs={'pk': self.customer.pk}),
                data={'body': 'hello from the spa'}, format='json',
                HTTP_X_TENANT_SLUG=self.tenant.slug,
            )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        row = Message.objects.get(pk=response.data['id'])
        self.assertEqual(row.direction, Direction.OUTBOUND)
        self.assertEqual(row.status, MessageStatus.SENT)
        self.assertEqual(row.provider_message_id, 'SMmsgtest')
        self.assertEqual(row.from_number, '+18445551111')
        self.assertEqual(row.to_number, '+15554443333')
        self.assertEqual(row.sent_by, self.owner)

        kwargs = fake_client.messages.create.call_args.kwargs
        self.assertEqual(kwargs['from_'], '+18445551111')
        self.assertEqual(kwargs['to'], '+15554443333')
        self.assertEqual(kwargs['body'], 'hello from the spa')

    def test_send_blocked_when_customer_has_no_phone(self):
        no_phone = Customer.objects.create(
            tenant=self.tenant, first_name='X', last_name='Y',
            phone='', sms_opt_in=True,
        )
        response = self.client.post(
            reverse('messaging-conversation-send', kwargs={'pk': no_phone.pk}),
            data={'body': 'hi'}, format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(Message.objects.filter(customer=no_phone).exists())

    def test_send_blocked_when_sms_opt_in_false(self):
        opted_out = _make_customer(self.tenant, phone='+15551110000', sms_opt_in=False)
        response = self.client.post(
            reverse('messaging-conversation-send', kwargs={'pk': opted_out.pk}),
            data={'body': 'hi'}, format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(Message.objects.filter(customer=opted_out).exists())

    def test_send_empty_body_rejected(self):
        response = self.client.post(
            reverse('messaging-conversation-send', kwargs={'pk': self.customer.pk}),
            data={'body': '   '}, format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_send_twilio_failure_marks_row_failed(self):
        from twilio.base.exceptions import TwilioRestException

        fake_client = MagicMock()
        fake_client.messages.create.side_effect = TwilioRestException(
            uri='/test', msg='Number not in service', code=30005, status=400,
        )

        with patch('twilio.rest.Client', return_value=fake_client):
            response = self.client.post(
                reverse('messaging-conversation-send', kwargs={'pk': self.customer.pk}),
                data={'body': 'will fail'}, format='json',
                HTTP_X_TENANT_SLUG=self.tenant.slug,
            )

        # Operator-facing 400 — the row is still persisted in FAILED state
        # so the thread still shows the attempt for context.
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        row = Message.objects.filter(customer=self.customer).first()
        self.assertIsNotNone(row)
        self.assertEqual(row.status, MessageStatus.FAILED)
        self.assertIn('30005', row.failure_reason)

    def test_send_404_for_other_tenant_customer(self):
        other_tenant, _ = _make_tenant('other-send', tfn='+18445552222')
        foreign = _make_customer(other_tenant, phone='+15552223344')
        response = self.client.post(
            reverse('messaging-conversation-send', kwargs={'pk': foreign.pk}),
            data={'body': 'hi'}, format='json',
            HTTP_X_TENANT_SLUG=self.tenant.slug,
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_send_audit_log_written_with_redacted_metadata(self):
        fake_msg = MagicMock(sid='SMaudittest')
        fake_client = MagicMock()
        fake_client.messages.create.return_value = fake_msg

        with patch('twilio.rest.Client', return_value=fake_client):
            self.client.post(
                reverse('messaging-conversation-send', kwargs={'pk': self.customer.pk}),
                data={'body': 'audit me'}, format='json',
                HTTP_X_TENANT_SLUG=self.tenant.slug,
            )

        log = AuditLog.objects.filter(resource_type='messaging_message').last()
        self.assertIsNotNone(log)
        self.assertEqual(log.action, AuditLog.Action.CREATE)
        # Recipient is redacted to last-4 only, body length not body.
        self.assertEqual(log.metadata.get('recipient_last4'), '3333')
        self.assertNotIn('body', log.metadata)
        self.assertEqual(log.metadata.get('body_length'), len('audit me'))

    def test_send_stub_mode_when_twilio_not_configured(self):
        # No TWILIO_ACCOUNT_SID + AUTH_TOKEN — the sender hits the stub
        # branch and returns ''. Row stays QUEUED, provider_message_id empty.
        with override_settings(TWILIO_ACCOUNT_SID='', TWILIO_AUTH_TOKEN=''):
            response = self.client.post(
                reverse('messaging-conversation-send', kwargs={'pk': self.customer.pk}),
                data={'body': 'stub'}, format='json',
                HTTP_X_TENANT_SLUG=self.tenant.slug,
            )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        row = Message.objects.get(pk=response.data['id'])
        self.assertEqual(row.provider_message_id, '')
        self.assertEqual(row.status, MessageStatus.QUEUED)


# ── Inbound webhook ─────────────────────────────────────────────────


class TwilioInboundTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tenant, cls.owner = _make_tenant('inbound-spa', tfn='+18443334444')
        cls.customer = _make_customer(cls.tenant, phone='+15557778899')

    @override_settings(TWILIO_TEST_MODE=True)
    def test_inbound_creates_message_row(self):
        anon = APIClient()
        response = anon.post(
            reverse('messaging-twilio-incoming'),
            data={
                'From': '+15557778899',
                'To': '+18443334444',
                'Body': 'hello back',
                'MessageSid': 'SMinbound1',
                'NumMedia': '0',
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        row = Message.objects.get(provider_message_id='SMinbound1')
        self.assertEqual(row.tenant, self.tenant)
        self.assertEqual(row.customer, self.customer)
        self.assertEqual(row.direction, Direction.INBOUND)
        self.assertEqual(row.status, MessageStatus.RECEIVED)
        self.assertEqual(row.body, 'hello back')

    @override_settings(TWILIO_TEST_MODE=True)
    def test_inbound_matches_customer_via_phone_normalisation(self):
        # Operator-entered phone is `(555) 777-8899`; Twilio sends E.164.
        # Should still match.
        c = Customer.objects.create(
            tenant=self.tenant, first_name='Z', last_name='Z',
            phone='(555) 111-2233', sms_opt_in=True,
        )
        anon = APIClient()
        response = anon.post(
            reverse('messaging-twilio-incoming'),
            data={
                'From': '+15551112233',
                'To': '+18443334444',
                'Body': 'parens form',
                'MessageSid': 'SMnorm',
                'NumMedia': '0',
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(
            Message.objects.filter(provider_message_id='SMnorm', customer=c).exists(),
        )

    @override_settings(TWILIO_TEST_MODE=True)
    def test_inbound_unknown_tenant_no_row(self):
        anon = APIClient()
        response = anon.post(
            reverse('messaging-twilio-incoming'),
            data={
                'From': '+15557778899',
                'To': '+18889990000',  # not assigned to any tenant
                'Body': 'whoops',
                'MessageSid': 'SMunknowntfn',
                'NumMedia': '0',
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data.get('unmatched'), 'tenant')
        self.assertFalse(Message.objects.filter(provider_message_id='SMunknowntfn').exists())

    @override_settings(TWILIO_TEST_MODE=True)
    def test_inbound_unknown_customer_no_row(self):
        anon = APIClient()
        response = anon.post(
            reverse('messaging-twilio-incoming'),
            data={
                'From': '+15550000000',  # no customer on tenant has this
                'To': '+18443334444',
                'Body': 'who are you',
                'MessageSid': 'SMnocust',
                'NumMedia': '0',
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data.get('unmatched'), 'customer')
        self.assertFalse(Message.objects.filter(provider_message_id='SMnocust').exists())

    @override_settings(TWILIO_TEST_MODE=True)
    def test_inbound_duplicate_sid_idempotent(self):
        Message.objects.create(
            tenant=self.tenant, customer=self.customer,
            direction=Direction.INBOUND, body='first',
            status=MessageStatus.RECEIVED,
            provider_message_id='SMdup',
        )
        anon = APIClient()
        response = anon.post(
            reverse('messaging-twilio-incoming'),
            data={
                'From': '+15557778899',
                'To': '+18443334444',
                'Body': 'first (replayed)',
                'MessageSid': 'SMdup',
                'NumMedia': '0',
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data.get('duplicate'))
        self.assertEqual(
            Message.objects.filter(provider_message_id='SMdup').count(), 1,
        )

    @override_settings(TWILIO_TEST_MODE=True)
    def test_inbound_mms_stores_media_urls(self):
        anon = APIClient()
        response = anon.post(
            reverse('messaging-twilio-incoming'),
            data={
                'From': '+15557778899',
                'To': '+18443334444',
                'Body': 'pic attached',
                'MessageSid': 'SMmms1',
                'NumMedia': '2',
                'MediaUrl0': 'https://twilio.example/m1.jpg',
                'MediaUrl1': 'https://twilio.example/m2.jpg',
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        row = Message.objects.get(provider_message_id='SMmms1')
        urls = row.media_urls.split('\n')
        self.assertEqual(urls, ['https://twilio.example/m1.jpg', 'https://twilio.example/m2.jpg'])

    def test_inbound_unsigned_request_rejected_in_prod_mode(self):
        with override_settings(TWILIO_TEST_MODE=False, TWILIO_AUTH_TOKEN='real-token'):
            anon = APIClient()
            response = anon.post(
                reverse('messaging-twilio-incoming'),
                data={
                    'From': '+15557778899',
                    'To': '+18443334444',
                    'Body': 'unsigned',
                    'MessageSid': 'SMunsigned',
                    'NumMedia': '0',
                },
            )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(Message.objects.filter(provider_message_id='SMunsigned').exists())
