"""Channel-agnostic AI agent loop.

``run_agent(adapter)`` runs one inbound message through the agent:
re-acquire/create the conversation, try the digit fast-path, then
loop Claude + tools until a text reply or an escalation. All channel
specifics (transport in/out, history, tool set, prompt) live behind
the ``ChannelAdapter`` — see ``channels/base.py``.

Synchronous + blocking. NEVER raises — the caller is a webhook that
must complete normally regardless. Any crash → emergency escalation.

This is the extracted, shared core of the former ``sms_agent.py``;
the SMS path now runs through here via ``SMSAdapter`` with identical
behavior. Instagram runs through here via ``InstagramAdapter``.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

from django.utils import timezone as djtz

from apps.ai_inbox.agents import tools
from apps.ai_inbox.llm import get_llm_client
from apps.ai_inbox.llm.base import LLMTransportError
from apps.ai_inbox.models import AIConfig, AIConversation, EscalationAlert
from apps.ai_inbox.services import scrub, usage

if TYPE_CHECKING:
    from apps.ai_inbox.channels.base import ChannelAdapter

logger = logging.getLogger(__name__)

# Hard cap on tool-call iterations per inbound. Exceeded → escalate.
MAX_TOOL_ITERATIONS = 6

_DIGIT_FAST_PATH_RE = re.compile(r'^\s*([1-9])\s*$')


def run_agent(*, adapter: 'ChannelAdapter') -> None:
    """Top-level agent entrypoint. Never raises."""
    try:
        _run_inner(adapter)
    except Exception:
        logger.exception(
            'ai_inbox.agent_crashed tenant=%s channel=%s inbound_id=%s',
            getattr(adapter.tenant, 'slug', '?'),
            getattr(adapter, 'channel', '?'),
            _safe_inbound_id(adapter),
        )
        _emergency_escalate(adapter=adapter, reason='agent_error')


def _run_inner(adapter: 'ChannelAdapter') -> None:
    tenant = adapter.tenant
    customer = adapter.customer
    config = AIConfig.objects.get(tenant=tenant)

    conversation = _get_or_create_conversation(adapter)

    # Stamp inbound activity for telemetry + link the inbound row.
    conversation.last_inbound_at = djtz.now()
    conversation.message_count = (conversation.message_count or 0) + 1
    adapter.link_inbound(conversation)
    conversation.save(update_fields=[
        'last_inbound_at', 'message_count', 'updated_at',
    ])

    usage.ensure_today_row(tenant)

    # ── Digit fast-path (no Claude) ──────────────────────────────
    if _try_digit_fast_path(adapter, conversation):
        return

    # ── Claude loop ──────────────────────────────────────────────
    system_prompt = adapter.system_prompt(config, djtz.now())
    schemas = adapter.tool_schemas()
    history: list[dict[str, Any]] = adapter.build_history()
    client = get_llm_client()
    messages = history.copy()
    model_used = ''

    for _ in range(MAX_TOOL_ITERATIONS):
        try:
            response = client.chat(
                system=system_prompt,
                messages=messages,
                tools=schemas,
                max_tokens=1024,
                temperature=0.2,
            )
        except LLMTransportError:
            _emergency_escalate(adapter=adapter, reason='agent_error',
                                summary='LLM call failed')
            return

        model_used = response.model or model_used
        usage.record_tokens(
            tenant=tenant,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
        )

        if response.stop_reason == 'tool_use':
            tool_results: list[dict[str, Any]] = []
            for tu in response.tool_use_blocks():
                tool_name = tu.get('name')
                result = tools.dispatch_tool(
                    tool_name=tool_name,
                    tool_input=tu.get('input') or {},
                    tenant=tenant, customer=customer,
                    conversation=conversation,
                    triggered_by_message=adapter.triggered_by_message(),
                    model_used=model_used,
                )
                usage.record_tool_call(tenant)
                tool_results.append({
                    'type': 'tool_result',
                    'tool_use_id': tu.get('id'),
                    'content': _serialize_tool_result(result),
                })
                if tool_name == 'escalate_to_human' and result.get('escalated'):
                    adapter.send(conversation, adapter.handoff_message(),
                                 model_used=model_used)
                    return
            messages.append({'role': 'assistant', 'content': response.content})
            messages.append({'role': 'user', 'content': tool_results})
            continue

        # Plain text — Claude is done.
        body = '\n'.join(response.text_blocks()).strip()
        if not body:
            _emergency_escalate(adapter=adapter, reason='agent_error',
                                summary='Empty assistant response')
            return

        scrub_reason = scrub.outbound_pii_check(body)
        if scrub_reason is not None:
            _emergency_escalate(adapter=adapter, reason='safety_outbound_blocked',
                                summary=f'Outbound blocked: {scrub_reason}')
            return

        adapter.send(conversation, body[:adapter.max_outbound_len()],
                     model_used=model_used)
        return

    _emergency_escalate(adapter=adapter, reason='agent_loop_limit',
                        summary=f'Hit {MAX_TOOL_ITERATIONS}-tool-call cap')


# ── helpers ──────────────────────────────────────────────────────


def _get_or_create_conversation(adapter: 'ChannelAdapter') -> AIConversation:
    conversation, _ = AIConversation.objects.get_or_create(
        tenant=adapter.tenant,
        customer=adapter.customer,
        channel=adapter.channel,
        defaults={
            'status': AIConversation.Status.ACTIVE,
            'social_thread': adapter.social_thread,
        },
    )
    # Backfill the social_thread link if the conversation predates it.
    if adapter.social_thread is not None and conversation.social_thread_id is None:
        conversation.social_thread = adapter.social_thread
        conversation.save(update_fields=['social_thread', 'updated_at'])
    return conversation


def _try_digit_fast_path(adapter: 'ChannelAdapter', conversation: AIConversation) -> bool:
    """Single 1..9 digit + unexpired pending proposal → book directly.
    Returns True if the fast path handled the turn."""
    match = _DIGIT_FAST_PATH_RE.match(adapter.inbound_text() or '')
    if not match or not conversation.pending_proposal:
        return False
    expires_at = conversation.pending_proposal_expires_at
    if expires_at is None or expires_at < djtz.now():
        return False

    result = tools.run_confirm_booking(
        slot_index=int(match.group(1)),
        tenant=adapter.tenant, customer=adapter.customer,
        conversation=conversation,
    )
    if 'error' in result:
        # Let Claude handle recovery instead of a canned error.
        return False

    adapter.send(conversation, adapter.post_booking_ack(result), model_used='fast_path_digit')
    return True


def _serialize_tool_result(result: Any) -> str:
    import json as _json
    try:
        return _json.dumps(result, default=str)
    except (TypeError, ValueError):
        return _json.dumps({'error': 'serialization_failed'})


def _emergency_escalate(*, adapter: 'ChannelAdapter', reason: str, summary: str = '') -> None:
    """Create an EscalationAlert + send a hand-off message without Claude.

    Cheap + un-failable. Sets channel + social_thread on the
    conversation so the inbox + notifier route correctly.
    triggering_message is only set for SMS (AIToolCall/EscalationAlert
    FK points at messaging.Message)."""
    try:
        conversation = _get_or_create_conversation(adapter)
        EscalationAlert.objects.create(
            tenant=adapter.tenant,
            conversation=conversation,
            customer=adapter.customer,
            reason=reason,
            reason_detail=summary or '',
            triggering_message=adapter.triggered_by_message(),
        )
        conversation.status = AIConversation.Status.ESCALATED
        conversation.escalated_at = djtz.now()
        conversation.escalation_reason = reason
        conversation.save(update_fields=[
            'status', 'escalated_at', 'escalation_reason', 'updated_at',
        ])
        adapter.send(conversation, adapter.handoff_message(),
                     model_used='emergency_escalate')
    except Exception:
        logger.exception(
            'ai_inbox.emergency_escalate_failed tenant=%s channel=%s',
            getattr(adapter.tenant, 'slug', '?'),
            getattr(adapter, 'channel', '?'),
        )


def _safe_inbound_id(adapter: 'ChannelAdapter'):
    try:
        return adapter.inbound_id()
    except Exception:
        return '?'
