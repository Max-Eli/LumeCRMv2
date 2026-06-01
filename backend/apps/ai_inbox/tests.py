"""Tests for the ai_inbox app — Phase 1.

Scope of Phase 1 tests:

  - Guardrail matrix: every check in services/guardrails.evaluate
    fires the expected reason code.
  - Dispatcher contract: maybe_dispatch_to_ai never raises; writes
    the right audit-log row on skip and on would-dispatch.
  - Model invariants: AIConversation unique per (tenant, customer);
    AIConfig unique per tenant; AIUsageDay unique per (tenant, date).

The agent loop + Bedrock invocation aren't covered here — that's
Phase 2. The Bedrock client raises NotImplementedError on chat()
in Phase 1, which IS exercised by the import-and-call smoke test
below to confirm we caught accidental Phase-1 invocations.
"""

from __future__ import annotations

import datetime as dt
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db.utils import IntegrityError
from django.test import TestCase
from django.utils import timezone as djtz

from apps.ai_inbox.models import (
    AIConfig,
    AIConversation,
    AIToolCall,
    AIUsageDay,
    EscalationAlert,
)
from apps.ai_inbox.services import dispatch, guardrails
from apps.audit.models import AuditLog
from apps.customers.models import Customer
from apps.messaging.models import Direction, Message, MessageKind, MessageStatus
from apps.tenants.models import Tenant
from apps.tenants.services import create_tenant_with_defaults

User = get_user_model()


# ── helpers ──────────────────────────────────────────────────────


def _make_tenant(slug='ai-test-tenant', tfn='+18005551234', grandfathered=False):
    """Create a tenant set up to receive AI inbound by default.

    Grandfathered + Pro so the F_AI_INBOX feature flag check passes
    (grandfathered tenants get every feature in apps/tenants/plans.py).
    """
    owner = User.objects.create_user(
        email=f'owner+{slug}@example.com', password='x',
        first_name='Pat', last_name='Owner',
    )
    tenant = create_tenant_with_defaults(
        name='Test Spa AI', slug=slug, owner_user=owner,
        status=Tenant.Status.ACTIVE, plan=Tenant.Plan.PRO,
    )
    tenant.twilio_from_number = tfn
    tenant.grandfathered = grandfathered or True   # pass plan feature gate
    tenant.save(update_fields=['twilio_from_number', 'grandfathered'])
    return tenant, owner


def _make_customer(tenant, phone='+15555550100'):
    return Customer.objects.create(
        tenant=tenant, first_name='Cust', last_name='Omer',
        phone=phone, sms_opt_in=True, status=Customer.Status.ACTIVE,
    )


def _make_inbound(tenant, customer, body='hi'):
    return Message.objects.create(
        tenant=tenant, customer=customer,
        direction=Direction.INBOUND, body=body,
        status=MessageStatus.RECEIVED,
        from_number=customer.phone, to_number=tenant.twilio_from_number,
        kind=MessageKind.MANUAL,
    )


def _make_config(tenant, **overrides):
    defaults = dict(
        enabled=True, test_mode=True,
        test_mode_number='+15555550100',
        persona='You are a friendly assistant.',
    )
    defaults.update(overrides)
    return AIConfig.objects.create(tenant=tenant, **defaults)


# ── guardrails ───────────────────────────────────────────────────


class GuardrailsTests(TestCase):

    def setUp(self):
        self.tenant, self.owner = _make_tenant()
        self.customer = _make_customer(self.tenant)
        self.message = _make_inbound(self.tenant, self.customer)

    def test_no_config_blocks_dispatch(self):
        d = guardrails.evaluate(
            tenant=self.tenant, customer=self.customer,
            inbound_message=self.message,
        )
        self.assertFalse(d.proceed)
        self.assertEqual(d.reason, 'no_ai_config')

    def test_disabled_config_blocks_dispatch(self):
        _make_config(self.tenant, enabled=False)
        d = guardrails.evaluate(
            tenant=self.tenant, customer=self.customer,
            inbound_message=self.message,
        )
        self.assertFalse(d.proceed)
        self.assertEqual(d.reason, 'ai_not_enabled_for_tenant')

    def test_platform_kill_switch_blocks_dispatch(self):
        _make_config(self.tenant, platform_disabled_at=djtz.now())
        d = guardrails.evaluate(
            tenant=self.tenant, customer=self.customer,
            inbound_message=self.message,
        )
        self.assertFalse(d.proceed)
        self.assertEqual(d.reason, 'platform_kill_switch_engaged')

    def test_test_mode_rejects_other_numbers(self):
        _make_config(self.tenant, test_mode_number='+15559998888')
        d = guardrails.evaluate(
            tenant=self.tenant, customer=self.customer,
            inbound_message=self.message,  # from +15555550100, not 9988
        )
        self.assertFalse(d.proceed)
        self.assertEqual(d.reason, 'test_mode_number_mismatch')

    def test_test_mode_accepts_configured_number(self):
        _make_config(self.tenant)  # test_mode_number defaults to +15555550100 = customer phone
        d = guardrails.evaluate(
            tenant=self.tenant, customer=self.customer,
            inbound_message=self.message,
        )
        self.assertTrue(d.proceed)

    def test_blocked_customer_blocks_dispatch(self):
        _make_config(self.tenant)
        self.customer.status = Customer.Status.BLOCKED
        self.customer.save(update_fields=['status'])
        d = guardrails.evaluate(
            tenant=self.tenant, customer=self.customer,
            inbound_message=self.message,
        )
        self.assertFalse(d.proceed)
        self.assertEqual(d.reason, 'customer_blocked')

    def test_sms_opt_out_blocks_dispatch(self):
        _make_config(self.tenant)
        self.customer.sms_opt_in = False
        self.customer.save(update_fields=['sms_opt_in'])
        d = guardrails.evaluate(
            tenant=self.tenant, customer=self.customer,
            inbound_message=self.message,
        )
        self.assertFalse(d.proceed)
        self.assertEqual(d.reason, 'customer_sms_opt_out')

    def test_paused_conversation_blocks_dispatch(self):
        _make_config(self.tenant)
        AIConversation.objects.create(
            tenant=self.tenant, customer=self.customer,
            status=AIConversation.Status.PAUSED,
        )
        d = guardrails.evaluate(
            tenant=self.tenant, customer=self.customer,
            inbound_message=self.message,
        )
        self.assertFalse(d.proceed)
        self.assertEqual(d.reason, 'conversation_paused')

    def test_escalated_conversation_blocks_dispatch(self):
        _make_config(self.tenant)
        AIConversation.objects.create(
            tenant=self.tenant, customer=self.customer,
            status=AIConversation.Status.ESCALATED,
        )
        d = guardrails.evaluate(
            tenant=self.tenant, customer=self.customer,
            inbound_message=self.message,
        )
        self.assertFalse(d.proceed)
        self.assertEqual(d.reason, 'conversation_escalated')

    def test_rate_limit_blocks_within_gap(self):
        _make_config(self.tenant)
        AIConversation.objects.create(
            tenant=self.tenant, customer=self.customer,
            status=AIConversation.Status.ACTIVE,
            # Less than PER_CONVERSATION_REPLY_GAP_SECONDS — a Twilio
            # webhook retry, not a real customer reply.
            last_ai_at=djtz.now() - dt.timedelta(seconds=1),
        )
        d = guardrails.evaluate(
            tenant=self.tenant, customer=self.customer,
            inbound_message=self.message,
        )
        self.assertFalse(d.proceed)
        self.assertEqual(d.reason, 'rate_limited')

    def test_rate_limit_allows_after_gap(self):
        _make_config(self.tenant)
        AIConversation.objects.create(
            tenant=self.tenant, customer=self.customer,
            status=AIConversation.Status.ACTIVE,
            # Comfortably past the gap — normal customer reply latency.
            last_ai_at=djtz.now() - dt.timedelta(seconds=15),
        )
        d = guardrails.evaluate(
            tenant=self.tenant, customer=self.customer,
            inbound_message=self.message,
        )
        self.assertTrue(d.proceed)

    def test_daily_cap_blocks_dispatch(self):
        config = _make_config(self.tenant, daily_send_cap=5)
        AIUsageDay.objects.create(
            tenant=self.tenant, date=djtz.localdate(),
            ai_messages_sent=5,
        )
        d = guardrails.evaluate(
            tenant=self.tenant, customer=self.customer,
            inbound_message=self.message,
        )
        self.assertFalse(d.proceed)
        self.assertEqual(d.reason, 'daily_cap_exceeded')

    def test_idempotency_blocks_duplicate(self):
        _make_config(self.tenant)
        # Pretend an outbound was already sent for this inbound.
        Message.objects.create(
            tenant=self.tenant, customer=self.customer,
            direction=Direction.OUTBOUND, body='already replied',
            status=MessageStatus.SENT,
            parent_inbound_message_id=self.message.id,
        )
        d = guardrails.evaluate(
            tenant=self.tenant, customer=self.customer,
            inbound_message=self.message,
        )
        self.assertFalse(d.proceed)
        self.assertEqual(d.reason, 'idempotency_already_replied')

    def test_unknown_sender_without_customer_row_bails(self):
        # The messaging webhook auto-creates a Customer for unknown
        # numbers when AI inbox is enabled, so reaching the guardrail
        # layer with customer=None is a legacy / defensive path. Bail
        # explicitly rather than NPE downstream.
        _make_config(self.tenant)
        d = guardrails.evaluate(
            tenant=self.tenant, customer=None,
            inbound_message=self.message,
        )
        self.assertFalse(d.proceed)
        self.assertEqual(d.reason, 'unknown_sender_no_customer_row')

    def test_missing_tfn_blocks_dispatch(self):
        _make_config(self.tenant)
        self.tenant.twilio_from_number = ''
        self.tenant.save(update_fields=['twilio_from_number'])
        d = guardrails.evaluate(
            tenant=self.tenant, customer=self.customer,
            inbound_message=self.message,
        )
        self.assertFalse(d.proceed)
        self.assertEqual(d.reason, 'tenant_missing_tfn')


# ── dispatch ─────────────────────────────────────────────────────


class DispatchTests(TestCase):

    def setUp(self):
        self.tenant, _ = _make_tenant()
        self.customer = _make_customer(self.tenant)
        self.message = _make_inbound(self.tenant, self.customer)

    def test_dispatch_never_raises_on_error(self):
        # Force evaluate to blow up. Dispatcher must swallow.
        with patch('apps.ai_inbox.services.dispatch.evaluate', side_effect=RuntimeError('boom')):
            dispatch.maybe_dispatch_to_ai(message=self.message)
        # No exception leaked.

    def test_skip_writes_audit_row(self):
        dispatch.maybe_dispatch_to_ai(message=self.message)  # no AIConfig → skip
        log = AuditLog.objects.filter(
            tenant=self.tenant, resource_type='ai_dispatch',
        ).latest('timestamp')
        self.assertEqual(log.metadata.get('event'), 'ai_dispatch_skipped')
        self.assertEqual(log.metadata.get('reason'), 'no_ai_config')

    def test_dispatch_writes_audit_row_and_calls_agent(self):
        _make_config(self.tenant)
        with patch('apps.ai_inbox.agents.sms_agent.run_agent') as mock_run:
            dispatch.maybe_dispatch_to_ai(message=self.message)
        mock_run.assert_called_once()
        log = AuditLog.objects.filter(
            tenant=self.tenant, resource_type='ai_dispatch',
        ).latest('timestamp')
        self.assertEqual(log.metadata.get('event'), 'ai_dispatch_run')

    def test_outbound_message_is_ignored(self):
        outbound = Message.objects.create(
            tenant=self.tenant, customer=self.customer,
            direction=Direction.OUTBOUND, body='hi back',
            status=MessageStatus.SENT,
            from_number=self.tenant.twilio_from_number, to_number=self.customer.phone,
        )
        dispatch.maybe_dispatch_to_ai(message=outbound)
        self.assertFalse(
            AuditLog.objects.filter(
                tenant=self.tenant, resource_type='ai_dispatch',
            ).exists()
        )


# ── model invariants ─────────────────────────────────────────────


class ModelInvariantsTests(TestCase):

    def setUp(self):
        self.tenant, _ = _make_tenant(slug='inv-test')
        self.customer = _make_customer(self.tenant)

    def test_aiconfig_unique_per_tenant(self):
        AIConfig.objects.create(tenant=self.tenant)
        with self.assertRaises(IntegrityError):
            AIConfig.objects.create(tenant=self.tenant)

    def test_aiconversation_unique_per_tenant_customer(self):
        AIConversation.objects.create(tenant=self.tenant, customer=self.customer)
        with self.assertRaises(IntegrityError):
            AIConversation.objects.create(tenant=self.tenant, customer=self.customer)

    def test_aiusageday_unique_per_tenant_date(self):
        today = djtz.localdate()
        AIUsageDay.objects.create(tenant=self.tenant, date=today)
        with self.assertRaises(IntegrityError):
            AIUsageDay.objects.create(tenant=self.tenant, date=today)


# ── bedrock client smoke ─────────────────────────────────────────


class BedrockClientTests(TestCase):
    """Bedrock client invokes boto3 with the expected Messages-API body shape."""

    def test_chat_builds_messages_body_and_parses_response(self):
        from unittest.mock import MagicMock

        from apps.ai_inbox.llm.base import LLMResponse

        fake_boto = MagicMock()
        fake_body = b'{"content":[{"type":"text","text":"hi"}],"stop_reason":"end_turn","usage":{"input_tokens":5,"output_tokens":2}}'
        fake_boto.invoke_model.return_value = {'body': MagicMock(read=MagicMock(return_value=fake_body))}

        with patch('boto3.client', return_value=fake_boto):
            from apps.ai_inbox.llm.bedrock_client import BedrockClient
            client = BedrockClient()
            resp = client.chat(system='S', messages=[{'role': 'user', 'content': 'hi'}])

        self.assertIsInstance(resp, LLMResponse)
        self.assertEqual(resp.stop_reason, 'end_turn')
        self.assertEqual(resp.text_blocks(), ['hi'])
        self.assertEqual(resp.input_tokens, 5)
        self.assertEqual(resp.output_tokens, 2)

        # Body should be JSON containing system + messages.
        call_kwargs = fake_boto.invoke_model.call_args.kwargs
        import json as _json
        body = _json.loads(call_kwargs['body'])
        self.assertEqual(body['system'], 'S')
        self.assertEqual(body['messages'][0]['content'], 'hi')


class DirectAnthropicClientTests(TestCase):
    """Anthropic direct client converts SDK objects into the LLMResponse shape."""

    def test_chat_calls_sdk_and_parses_response(self):
        from unittest.mock import MagicMock

        from django.test import override_settings

        from apps.ai_inbox.llm.base import LLMResponse, LLMTransportError

        # Build a fake SDK response shape — content blocks + usage + stop_reason.
        text_block = MagicMock()
        text_block.model_dump.return_value = {'type': 'text', 'text': 'hi back'}
        usage = MagicMock(input_tokens=12, output_tokens=4)
        fake_response = MagicMock(
            content=[text_block],
            stop_reason='end_turn',
            model='claude-sonnet-4-6',
            usage=usage,
        )
        fake_response.model_dump.return_value = {'fake': True}

        fake_anthropic_client = MagicMock()
        fake_anthropic_client.messages.create.return_value = fake_response

        with patch('anthropic.Anthropic', return_value=fake_anthropic_client), \
                override_settings(ANTHROPIC_API_KEY='sk-test-key'):
            from apps.ai_inbox.llm.anthropic_direct_client import DirectAnthropicClient
            client = DirectAnthropicClient()
            resp = client.chat(
                system='S', messages=[{'role': 'user', 'content': 'hi'}],
                tools=[{'name': 't', 'description': 'd', 'input_schema': {'type': 'object'}}],
            )

        self.assertIsInstance(resp, LLMResponse)
        self.assertEqual(resp.text_blocks(), ['hi back'])
        self.assertEqual(resp.stop_reason, 'end_turn')
        self.assertEqual(resp.input_tokens, 12)
        self.assertEqual(resp.output_tokens, 4)
        self.assertEqual(resp.model, 'claude-sonnet-4-6')

        # SDK was called with the messages-API kwargs.
        call_kwargs = fake_anthropic_client.messages.create.call_args.kwargs
        self.assertEqual(call_kwargs['system'], 'S')
        self.assertEqual(call_kwargs['messages'], [{'role': 'user', 'content': 'hi'}])
        self.assertEqual(call_kwargs['model'], 'claude-sonnet-4-6')
        self.assertEqual(len(call_kwargs['tools']), 1)

    def test_init_raises_when_api_key_missing(self):
        from django.test import override_settings
        with patch('anthropic.Anthropic'), override_settings(ANTHROPIC_API_KEY=''):
            from apps.ai_inbox.llm.anthropic_direct_client import DirectAnthropicClient
            with self.assertRaises(RuntimeError):
                DirectAnthropicClient()

    def test_chat_wraps_sdk_exceptions(self):
        from unittest.mock import MagicMock

        from django.test import override_settings

        from apps.ai_inbox.llm.base import LLMTransportError

        fake_anthropic_client = MagicMock()
        fake_anthropic_client.messages.create.side_effect = RuntimeError('boom')

        with patch('anthropic.Anthropic', return_value=fake_anthropic_client), \
                override_settings(ANTHROPIC_API_KEY='sk-test-key'):
            from apps.ai_inbox.llm.anthropic_direct_client import DirectAnthropicClient
            client = DirectAnthropicClient()
            with self.assertRaises(LLMTransportError):
                client.chat(system='S', messages=[{'role': 'user', 'content': 'hi'}])


# ── HTTP endpoints (operator pause/resume + config + escalations) ──


class AIConversationEndpointTests(TestCase):
    """Inbox operator controls — pause / resume / status."""

    def setUp(self):
        self.tenant, self.owner = _make_tenant(slug='ep-test')
        self.customer = _make_customer(self.tenant)
        from rest_framework.test import APIClient
        self.client = APIClient()
        # force_login (Django session cookie) — NOT force_authenticate.
        # The latter is DRF-only and runs after middleware, so
        # TenantMiddleware sees AnonymousUser and tenant_membership
        # stays None → IsTenantStaff 403s.
        self.client.force_login(self.owner)
        # X-Tenant-Slug header is the dev/test path the TenantMiddleware
        # uses to resolve request.tenant (subdomain lookup is the prod
        # path). Without it, IsTenantStaff 403s because the middleware
        # never populates request.tenant_membership.
        self.headers = {'HTTP_X_TENANT_SLUG': self.tenant.slug}

    def _url(self, customer_id: int, suffix: str = '') -> str:
        return f'/api/ai-inbox/conversations/{customer_id}/{suffix}'

    def _assert_status(self, response, expected_code):
        self.assertEqual(
            response.status_code, expected_code,
            msg=f'unexpected {response.status_code}: {getattr(response, "data", response.content)!r}',
        )

    def test_get_creates_conversation_lazily(self):
        r = self.client.get(self._url(self.customer.id), **self.headers)
        self._assert_status(r, 200)
        self.assertEqual(r.data['status'], 'active')
        self.assertEqual(r.data['customer_id'], self.customer.id)
        self.assertEqual(AIConversation.objects.count(), 1)

    def test_pause_flips_status_and_audits(self):
        r = self.client.post(self._url(self.customer.id, 'pause/'), **self.headers)
        self._assert_status(r, 200)
        self.assertEqual(r.data['status'], 'paused')
        conv = AIConversation.objects.get(tenant=self.tenant, customer=self.customer)
        self.assertEqual(conv.paused_by, self.owner)
        self.assertIsNotNone(conv.paused_at)
        # Audit row exists.
        self.assertTrue(
            AuditLog.objects.filter(
                tenant=self.tenant, resource_type='ai_conversation',
                metadata__event='paused',
            ).exists()
        )

    def test_pause_is_idempotent(self):
        self.client.post(self._url(self.customer.id, 'pause/'), **self.headers)
        r = self.client.post(self._url(self.customer.id, 'pause/'), **self.headers)
        self._assert_status(r, 200)
        self.assertEqual(r.data['status'], 'paused')

    def test_resume_clears_pause_state(self):
        self.client.post(self._url(self.customer.id, 'pause/'), **self.headers)
        r = self.client.post(self._url(self.customer.id, 'resume/'), **self.headers)
        self._assert_status(r, 200)
        self.assertEqual(r.data['status'], 'active')
        conv = AIConversation.objects.get(tenant=self.tenant, customer=self.customer)
        self.assertIsNone(conv.paused_by)
        self.assertIsNone(conv.paused_at)

    def test_resume_resolves_open_escalations(self):
        conv = AIConversation.objects.create(
            tenant=self.tenant, customer=self.customer,
            status=AIConversation.Status.ESCALATED,
            escalated_at=djtz.now(), escalation_reason='requested_human',
        )
        EscalationAlert.objects.create(
            tenant=self.tenant, conversation=conv, customer=self.customer,
            reason='requested_human',
        )
        r = self.client.post(self._url(self.customer.id, 'resume/'), **self.headers)
        self._assert_status(r, 200)
        alert = EscalationAlert.objects.get(conversation=conv)
        self.assertIsNotNone(alert.resolved_at)
        self.assertIsNotNone(alert.acknowledged_at)

    def test_other_tenant_customer_returns_404(self):
        other_tenant, other_owner = _make_tenant(slug='ep-other')
        other_customer = _make_customer(other_tenant)
        # Auth as the first tenant's owner (with their tenant in the
        # X-Tenant-Slug header) but hit a customer from the OTHER tenant.
        # The tenant-scoped queryset filter must return 404.
        r = self.client.get(self._url(other_customer.id), **self.headers)
        self._assert_status(r, 404)


class AIConfigEndpointTests(TestCase):
    def setUp(self):
        self.tenant, self.owner = _make_tenant(slug='cfg-test')
        from rest_framework.test import APIClient
        self.client = APIClient()
        # force_login (Django session cookie) — NOT force_authenticate.
        # The latter is DRF-only and runs after middleware, so
        # TenantMiddleware sees AnonymousUser and tenant_membership
        # stays None → IsTenantStaff 403s.
        self.client.force_login(self.owner)
        self.headers = {'HTTP_X_TENANT_SLUG': self.tenant.slug}

    def test_get_creates_lazily(self):
        r = self.client.get('/api/ai-inbox/config/', **self.headers)
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.data['enabled'])
        self.assertTrue(r.data['test_mode'])

    def test_patch_persona_succeeds(self):
        r = self.client.patch(
            '/api/ai-inbox/config/',
            data={'persona': 'You are Avery.'}, format='json',
            **self.headers,
        )
        self.assertEqual(r.status_code, 200)
        config = AIConfig.objects.get(tenant=self.tenant)
        self.assertEqual(config.persona, 'You are Avery.')

    def test_enable_without_tfn_rejected(self):
        self.tenant.twilio_from_number = ''
        self.tenant.save(update_fields=['twilio_from_number'])
        r = self.client.patch(
            '/api/ai-inbox/config/',
            data={'enabled': True}, format='json',
            **self.headers,
        )
        self.assertEqual(r.status_code, 400)
        self.assertIn('enabled', r.data)

    def test_enable_test_mode_requires_test_number(self):
        r = self.client.patch(
            '/api/ai-inbox/config/',
            data={'enabled': True, 'test_mode': True, 'test_mode_number': ''},
            format='json',
            **self.headers,
        )
        self.assertEqual(r.status_code, 400)


class LLMClientFactoryTests(TestCase):
    """get_llm_client() routes by AI_LLM_PROVIDER setting."""

    def test_bedrock_provider(self):
        from django.test import override_settings
        with patch('boto3.client'), override_settings(AI_LLM_PROVIDER='bedrock'):
            from apps.ai_inbox.llm import get_llm_client
            from apps.ai_inbox.llm.bedrock_client import BedrockClient
            self.assertIsInstance(get_llm_client(), BedrockClient)

    def test_anthropic_provider(self):
        from django.test import override_settings
        with patch('anthropic.Anthropic'), \
                override_settings(AI_LLM_PROVIDER='anthropic', ANTHROPIC_API_KEY='sk-x'):
            from apps.ai_inbox.llm import get_llm_client
            from apps.ai_inbox.llm.anthropic_direct_client import DirectAnthropicClient
            self.assertIsInstance(get_llm_client(), DirectAnthropicClient)

    def test_unknown_provider_raises(self):
        from django.test import override_settings
        with override_settings(AI_LLM_PROVIDER='not-a-provider'):
            from apps.ai_inbox.llm import get_llm_client
            with self.assertRaises(ValueError):
                get_llm_client()


# ── Instagram channel ─────────────────────────────────────────────


def _make_ig_connection(tenant):
    from apps.integrations.models import Connection
    return Connection.objects.create(
        tenant=tenant, provider='instagram', status='connected',
        external_id='ig-page-123', external_name='@demo_spa',
    )


def _make_ig_thread(tenant, connection, customer, username='lead_handle'):
    from apps.integrations.models import SocialThread
    return SocialThread.objects.create(
        tenant=tenant, connection=connection, customer=customer,
        provider='instagram', external_thread_id='psid-abc-123',
        external_username=username,
        last_inbound_at=djtz.now(),
        last_message_at=djtz.now(),
    )


def _make_ig_inbound(tenant, thread, body='hi', mid='mid-1'):
    from apps.integrations.models import SocialMessage
    return SocialMessage.objects.create(
        tenant=tenant, thread=thread,
        direction=SocialMessage.Direction.INBOUND,
        body=body, external_message_id=mid,
        status=SocialMessage.Status.RECEIVED,
        received_at=djtz.now(),
    )


class InstagramGuardrailsTests(TestCase):
    def setUp(self):
        # Grandfathered tenant → has F_AI_INBOX + F_SOCIAL_INTEGRATIONS.
        self.tenant, _ = _make_tenant(slug='ig-guard')
        self.customer = _make_customer(self.tenant, phone='')
        self.customer.is_social_guest = True
        self.customer.save(update_fields=['is_social_guest'])
        self.conn = _make_ig_connection(self.tenant)
        self.thread = _make_ig_thread(self.tenant, self.conn, self.customer, username='lead_handle')
        self.msg = _make_ig_inbound(self.tenant, self.thread)

    def _eval(self):
        from apps.ai_inbox.services import guardrails
        return guardrails.evaluate_instagram(
            tenant=self.tenant, customer=self.customer,
            thread=self.thread, inbound_message=self.msg,
        )

    def test_no_config_blocks(self):
        self.assertEqual(self._eval().reason, 'no_ai_config')

    def test_instagram_not_enabled_blocks(self):
        _make_config(self.tenant, instagram_enabled=False)
        self.assertEqual(self._eval().reason, 'instagram_not_enabled')

    def test_platform_kill_blocks(self):
        _make_config(self.tenant, instagram_enabled=True,
                     instagram_test_username='lead_handle',
                     platform_disabled_at=djtz.now())
        self.assertEqual(self._eval().reason, 'platform_kill_switch_engaged')

    def test_test_username_mismatch_blocks(self):
        _make_config(self.tenant, instagram_enabled=True,
                     instagram_test_mode=True,
                     instagram_test_username='someone_else')
        self.assertEqual(self._eval().reason, 'instagram_test_username_mismatch')

    def test_test_username_match_proceeds(self):
        _make_config(self.tenant, instagram_enabled=True,
                     instagram_test_mode=True,
                     instagram_test_username='lead_handle')
        self.assertTrue(self._eval().proceed)

    def test_at_prefix_and_case_insensitive_match(self):
        _make_config(self.tenant, instagram_enabled=True,
                     instagram_test_mode=True,
                     instagram_test_username='@Lead_Handle')
        self.assertTrue(self._eval().proceed)

    def test_blocked_customer_blocks(self):
        _make_config(self.tenant, instagram_enabled=True, instagram_test_mode=False)
        self.customer.status = Customer.Status.BLOCKED
        self.customer.save(update_fields=['status'])
        self.assertEqual(self._eval().reason, 'customer_blocked')

    def test_paused_conversation_blocks(self):
        _make_config(self.tenant, instagram_enabled=True, instagram_test_mode=False)
        AIConversation.objects.create(
            tenant=self.tenant, customer=self.customer,
            channel=AIConversation.Channel.INSTAGRAM,
            status=AIConversation.Status.PAUSED,
        )
        self.assertEqual(self._eval().reason, 'conversation_paused')

    def test_idempotency_blocks_duplicate(self):
        from apps.integrations.models import SocialMessage
        _make_config(self.tenant, instagram_enabled=True, instagram_test_mode=False)
        SocialMessage.objects.create(
            tenant=self.tenant, thread=self.thread,
            direction=SocialMessage.Direction.OUTBOUND,
            body='already replied', external_message_id='mid-out-1',
            status=SocialMessage.Status.SENT,
            parent_inbound_message_id=self.msg.id,
        )
        self.assertEqual(self._eval().reason, 'idempotency_already_replied')

    def test_no_24h_window_block(self):
        # 24h window removed — an old last_inbound_at must NOT block.
        import datetime as _dt
        self.thread.last_inbound_at = djtz.now() - _dt.timedelta(days=10)
        self.thread.save(update_fields=['last_inbound_at'])
        _make_config(self.tenant, instagram_enabled=True, instagram_test_mode=False)
        self.assertTrue(self._eval().proceed)

    def test_sms_enabled_does_not_enable_instagram(self):
        # SMS enabled but instagram_enabled False → IG still blocked.
        _make_config(self.tenant, enabled=True, instagram_enabled=False)
        self.assertEqual(self._eval().reason, 'instagram_not_enabled')


class InstagramToolSetTests(TestCase):
    def test_excludes_get_customer_context(self):
        from apps.ai_inbox.agents import tools
        names = {s['name'] for s in tools.TOOL_SCHEMAS_INSTAGRAM}
        self.assertNotIn('get_customer_context', names)

    def test_includes_capture_lead_info_and_booking_tools(self):
        from apps.ai_inbox.agents import tools
        names = {s['name'] for s in tools.TOOL_SCHEMAS_INSTAGRAM}
        self.assertIn('capture_lead_info', names)
        self.assertIn('find_service', names)
        self.assertIn('check_availability', names)
        self.assertIn('confirm_booking', names)
        self.assertIn('escalate_to_human', names)

    def test_sms_set_still_has_context(self):
        from apps.ai_inbox.agents import tools
        names = {s['name'] for s in tools.TOOL_SCHEMAS}
        self.assertIn('get_customer_context', names)
        self.assertNotIn('capture_lead_info', names)


class CaptureLeadInfoTests(TestCase):
    def setUp(self):
        self.tenant, _ = _make_tenant(slug='ig-lead')
        self.customer = _make_customer(self.tenant, phone='')
        self.customer.is_social_guest = True
        self.customer.acquisition_source = Customer.AcquisitionSource.INSTAGRAM
        self.customer.save(update_fields=['is_social_guest', 'acquisition_source'])
        self.conv = AIConversation.objects.create(
            tenant=self.tenant, customer=self.customer,
            channel=AIConversation.Channel.INSTAGRAM,
        )

    def _capture(self, **inp):
        from apps.ai_inbox.agents import tools
        return tools._tool_capture_lead_info(
            tool_input=inp, tenant=self.tenant,
            customer=self.customer, conversation=self.conv,
        )

    def test_captures_name_phone_email_and_promotes(self):
        result = self._capture(first_name='Mia', last_name='Lee',
                               phone='+13474443333', email='mia@x.com')
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.first_name, 'Mia')
        self.assertEqual(self.customer.phone, '+13474443333')
        self.assertEqual(self.customer.email, 'mia@x.com')
        self.assertFalse(self.customer.is_social_guest)
        # acquisition_source stays INSTAGRAM (immutable, set by webhook)
        self.assertEqual(self.customer.acquisition_source,
                         Customer.AcquisitionSource.INSTAGRAM)
        self.assertIn('phone', result['captured'])

    def test_does_not_overwrite_existing_phone(self):
        self.customer.phone = '+15550001111'
        self.customer.save(update_fields=['phone'])
        self._capture(first_name='Mia', phone='+19999999999')
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.phone, '+15550001111')


class InstagramBookingChannelTests(TestCase):
    def test_book_appointment_for_ai_instagram_source(self):
        from apps.booking.services_ai import book_appointment_for_ai
        from apps.appointments.models import Appointment
        import datetime as _dt
        from apps.tenants.models import Location, TenantMembership
        from apps.services.models import Service

        tenant, owner = _make_tenant(slug='ig-book')
        customer = _make_customer(tenant, phone='')
        location = Location.objects.filter(tenant=tenant).first()
        provider = TenantMembership.objects.filter(tenant=tenant).first()
        service = Service.objects.create(
            tenant=tenant, name='Facial', duration_minutes=60,
            price_cents=10000, is_bookable_online=True,
        )
        start = djtz.now() + _dt.timedelta(days=1)
        appt = book_appointment_for_ai(
            tenant=tenant, customer=customer, service=service,
            provider=provider, location=location,
            start_time=start, end_time=start + _dt.timedelta(minutes=60),
            channel='instagram',
        )
        self.assertEqual(appt.source, 'instagram_ai')

    def test_instagram_booking_skips_sms_confirmation(self):
        # The appointment signal must NOT send an SMS for instagram_ai.
        from apps.appointments.models import Appointment
        import datetime as _dt
        from apps.tenants.models import Location, TenantMembership
        from apps.services.models import Service

        tenant, _ = _make_tenant(slug='ig-nosms')
        customer = _make_customer(tenant, phone='+15551234567')
        location = Location.objects.filter(tenant=tenant).first()
        provider = TenantMembership.objects.filter(tenant=tenant).first()
        service = Service.objects.create(
            tenant=tenant, name='Laser', duration_minutes=30,
            price_cents=20000, is_bookable_online=True,
        )
        start = djtz.now() + _dt.timedelta(days=2)
        with patch('apps.appointments.sms.send_confirmation_sms') as mock_send:
            Appointment.objects.create(
                tenant=tenant, customer=customer, provider=provider,
                service=service, location=location,
                start_time=start, end_time=start + _dt.timedelta(minutes=30),
                status=Appointment.Status.BOOKED, source='instagram_ai',
            )
        mock_send.assert_not_called()
