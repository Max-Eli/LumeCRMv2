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

    def test_rate_limit_blocks_within_30s(self):
        _make_config(self.tenant)
        AIConversation.objects.create(
            tenant=self.tenant, customer=self.customer,
            status=AIConversation.Status.ACTIVE,
            last_ai_at=djtz.now() - dt.timedelta(seconds=10),
        )
        d = guardrails.evaluate(
            tenant=self.tenant, customer=self.customer,
            inbound_message=self.message,
        )
        self.assertFalse(d.proceed)
        self.assertEqual(d.reason, 'rate_limited')

    def test_rate_limit_allows_after_30s(self):
        _make_config(self.tenant)
        AIConversation.objects.create(
            tenant=self.tenant, customer=self.customer,
            status=AIConversation.Status.ACTIVE,
            last_ai_at=djtz.now() - dt.timedelta(seconds=60),
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

    def test_unknown_sender_blocks_in_v1(self):
        _make_config(self.tenant)
        d = guardrails.evaluate(
            tenant=self.tenant, customer=None,
            inbound_message=self.message,
        )
        self.assertFalse(d.proceed)
        self.assertEqual(d.reason, 'unknown_sender_v1_drop')

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
