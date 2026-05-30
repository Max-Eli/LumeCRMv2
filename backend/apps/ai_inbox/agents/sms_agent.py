"""The SMS agent loop.

Public entrypoint: ``run_agent(message)``. Called by
``services.dispatch.maybe_dispatch_to_ai`` AFTER guardrails pass.
Synchronous, blocking — the Twilio webhook waits for it to finish
before returning the empty TwiML (Twilio gives us up to 15s; Claude
on Bedrock typically returns in 3–8s).

What this function does per inbound:
    1. Re-acquire the AIConversation (defense in depth — state
       may have drifted since guardrails fired).
    2. Fast-path: if the inbound body is a single digit AND
       AIConversation.pending_proposal is unexpired, call
       confirm_booking directly, no Claude. This is the highest-
       stakes branch — strict-digit matching keeps it 100% reliable.
    3. Otherwise build the Claude payload and loop:
         - send to Bedrock
         - if stop_reason=tool_use, execute each tool, append results, loop
         - if Claude returns text, that's the outbound SMS body
         - hard cap of 6 tool iterations → escalate if exceeded
    4. Send the outbound SMS via the existing
       ``apps.appointments.sms.send_sms`` (which writes its own
       Message row; we then patch generated_by_ai + ai_conversation
       + parent_inbound_message_id onto that row OR — when send_sms
       returns just a SID — we create the Message ourselves with the
       AI flags set).
    5. Update AIUsageDay + AIConversation.last_ai_at + exchange_count.

The function NEVER raises — caller is the messaging webhook and
must complete normally regardless.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
from typing import TYPE_CHECKING, Any

from django.utils import timezone as djtz

from apps.ai_inbox.agents import prompts, tools
from apps.ai_inbox.llm import get_llm_client
from apps.ai_inbox.llm.base import LLMTransportError
from apps.ai_inbox.models import AIConfig, AIConversation, EscalationAlert
from apps.ai_inbox.services import scrub, usage
from apps.messaging.models import Direction, Message, MessageKind, MessageStatus

if TYPE_CHECKING:
    from apps.tenants.models import Tenant


logger = logging.getLogger(__name__)


# Hard cap on agent loop iterations per inbound. Exceeded → escalate
# with reason=agent_loop_limit.
MAX_TOOL_ITERATIONS = 6

# Cap on SMS body length sent outbound. 320 chars = ~2 segments.
MAX_OUTBOUND_LEN = 320

# How many prior Message rows we feed to Claude as context.
HISTORY_TURN_LIMIT = 20

# Per-message body truncation when building history.
HISTORY_BODY_TRUNC = 1000

_DIGIT_FAST_PATH_RE = re.compile(r'^\s*([1-9])\s*$')


def run_agent(*, message: Message) -> None:
    """Top-level agent entrypoint. Never raises.

    Idempotent on the inbound message — duplicate calls for the same
    message become a no-op because guardrails check
    `parent_inbound_message_id` before reaching here, and the
    Message create below sets that field.
    """
    try:
        _run_inner(message=message)
    except Exception:
        logger.exception(
            'ai_inbox.agent_crashed tenant=%s message_id=%s',
            getattr(message.tenant, 'slug', '?'), message.id,
        )
        # Best-effort escalation so the operator notices.
        _emergency_escalate(message=message, reason='agent_error')


def _run_inner(*, message: Message) -> None:
    tenant = message.tenant
    customer = message.customer
    config = AIConfig.objects.get(tenant=tenant)

    conversation, _ = AIConversation.objects.get_or_create(
        tenant=tenant, customer=customer,
        defaults={'status': AIConversation.Status.ACTIVE},
    )

    # Stamp inbound activity for telemetry.
    conversation.last_inbound_at = djtz.now()
    conversation.message_count = (conversation.message_count or 0) + 1
    # Link the inbound Message to this conversation for the inbox UI badge.
    if message.ai_conversation_id is None:
        message.ai_conversation = conversation
        message.save(update_fields=['ai_conversation', 'updated_at'])
    conversation.save(update_fields=[
        'last_inbound_at', 'message_count', 'updated_at',
    ])

    usage.ensure_today_row(tenant)

    # ── Digit fast-path ──────────────────────────────────────────
    digit = _try_digit_fast_path(
        message=message, conversation=conversation,
    )
    if digit is not None:
        return  # _try_digit_fast_path handles its own send + escalation paths

    # ── Build Claude payload ─────────────────────────────────────
    system_prompt = prompts.render_system_prompt(
        tenant=tenant, config=config, now=djtz.now(),
    )
    history = _build_history(tenant=tenant, customer=customer)

    client = get_llm_client()
    messages: list[dict[str, Any]] = history.copy()
    model_used = ''

    for iteration in range(MAX_TOOL_ITERATIONS):
        try:
            response = client.chat(
                system=system_prompt,
                messages=messages,
                tools=tools.TOOL_SCHEMAS,
                max_tokens=1024,
                # Lower temperature for the booking flow — we want
                # predictable tool-call behaviour and minimal model
                # creativity around schedule confirmations. 0.4 was
                # producing the occasional fabricated "you're booked"
                # claim; 0.2 keeps replies grounded in tool results.
                temperature=0.2,
            )
        except LLMTransportError:
            # One retry on the next iteration — but only once. To
            # keep this simple, we just escalate on first failure
            # for v1; turn this into a true retry-with-backoff in v2.
            _emergency_escalate(message=message, reason='agent_error',
                                summary='Bedrock call failed')
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
                tool_input = tu.get('input') or {}
                tool_name = tu.get('name')
                result = tools.dispatch_tool(
                    tool_name=tool_name,
                    tool_input=tool_input,
                    tenant=tenant, customer=customer,
                    conversation=conversation,
                    triggered_by_message=message,
                    model_used=model_used,
                )
                usage.record_tool_call(tenant)
                tool_results.append({
                    'type': 'tool_result',
                    'tool_use_id': tu.get('id'),
                    'content': _serialize_tool_result(result),
                })
                # If the agent escalated, stop here — the escalate tool
                # already wrote the SMS-of-record path; we send one final
                # acknowledgement text below.
                if tool_name == 'escalate_to_human' and result.get('escalated'):
                    _send_outbound(
                        tenant=tenant, customer=customer, conversation=conversation,
                        inbound_message=message,
                        body="Thanks — I'm getting a teammate to help. They'll text you shortly.",
                        model_used=model_used,
                    )
                    return
            # Continue the loop with the assistant turn + tool results.
            messages.append({'role': 'assistant', 'content': response.content})
            messages.append({'role': 'user', 'content': tool_results})
            continue

        # Stop reason is end_turn / max_tokens / stop_sequence — Claude is done.
        body = '\n'.join(response.text_blocks()).strip()
        if not body:
            # The model returned no text and no tools — unusual. Escalate
            # rather than send an empty SMS.
            _emergency_escalate(message=message, reason='agent_error',
                                summary='Empty assistant response')
            return

        # Outbound safety scan.
        scrub_reason = scrub.outbound_pii_check(body)
        if scrub_reason is not None:
            _emergency_escalate(
                message=message, reason='safety_outbound_blocked',
                summary=f'Outbound blocked: {scrub_reason}',
            )
            return

        # Truncate if the model produced something long.
        body = body[:MAX_OUTBOUND_LEN]
        _send_outbound(
            tenant=tenant, customer=customer, conversation=conversation,
            inbound_message=message, body=body, model_used=model_used,
        )
        return

    # Loop exhausted — escalate.
    _emergency_escalate(
        message=message, reason='agent_loop_limit',
        summary=f'Hit {MAX_TOOL_ITERATIONS}-tool-call cap',
    )


# ── helpers ──────────────────────────────────────────────────────


def _build_history(*, tenant: 'Tenant', customer) -> list[dict[str, Any]]:
    """Build the Claude `messages` array from recent SMS history.

    Last N messages, ascending. INBOUND → user, OUTBOUND → assistant.
    Bodies truncated to keep token usage reasonable. The CURRENT
    inbound is already in the queryset (it was persisted before
    dispatch fired), so it appears at the end.
    """
    rows = list(
        Message.objects
        .filter(tenant=tenant, customer=customer)
        .order_by('-created_at')[:HISTORY_TURN_LIMIT]
    )
    rows.reverse()  # ascending
    out = []
    for r in rows:
        role = 'user' if r.direction == Direction.INBOUND else 'assistant'
        body = (r.body or '')[:HISTORY_BODY_TRUNC]
        if not body:
            continue
        out.append({'role': role, 'content': body})
    return out


def _try_digit_fast_path(
    *,
    message: Message,
    conversation: AIConversation,
) -> dict | None:
    """If the inbound is a single 1..9 digit + we have an active proposal,
    confirm the booking directly (no Claude). Returns truthy if the
    fast path was taken (caller bails)."""
    match = _DIGIT_FAST_PATH_RE.match(message.body or '')
    if not match:
        return None
    if not conversation.pending_proposal:
        return None
    expires_at = conversation.pending_proposal_expires_at
    if expires_at is None or expires_at < djtz.now():
        return None

    slot_index = int(match.group(1))
    result = tools.run_confirm_booking(
        slot_index=slot_index,
        tenant=message.tenant, customer=message.customer,
        conversation=conversation,
    )

    if 'error' in result:
        # Let Claude handle the recovery rather than send a canned error.
        return None

    # Brief acknowledgement so the customer sees an immediate response
    # to their digit. The platform's official confirmation SMS (with
    # date/time/STOP language) fires 60s LATER via
    # apps.appointments.signals.send_confirmation_sms_on_create (the
    # AI-source branch). This gives the customer two clean touches —
    # instant ack + formal confirmation a minute later — without two
    # overlapping confirmations within seconds of each other.
    body = "Got it — sending you the confirmation in a moment."
    _send_outbound(
        tenant=message.tenant, customer=message.customer,
        conversation=conversation, inbound_message=message,
        body=body, model_used='fast_path_digit',
    )
    return result


def _send_outbound(
    *,
    tenant: 'Tenant',
    customer,
    conversation: AIConversation,
    inbound_message: Message,
    body: str,
    model_used: str,
) -> None:
    """Send via the existing Twilio path + persist the outbound Message row.

    apps.appointments.sms.send_sms returns the Twilio SID (or '' if
    creds missing — dev mode). We persist the Message row OURSELVES
    so we can set generated_by_ai + ai_conversation + parent_inbound_message_id
    in one INSERT.
    """
    from apps.appointments.sms import send_sms

    try:
        sid = send_sms(tenant=tenant, to=customer.phone, body=body)
    except Exception:
        logger.exception(
            'ai_inbox.send_sms_failed tenant=%s customer_id=%s',
            tenant.slug, customer.id,
        )
        sid = ''

    Message.objects.create(
        tenant=tenant, customer=customer,
        direction=Direction.OUTBOUND,
        body=body,
        status=MessageStatus.SENT if sid else MessageStatus.FAILED,
        kind=MessageKind.AI,
        provider_message_id=sid,
        from_number=tenant.twilio_from_number or '',
        to_number=customer.phone or '',
        sent_by=None,
        generated_by_ai=True,
        ai_conversation=conversation,
        parent_inbound_message_id=inbound_message.id,
    )

    conversation.last_ai_at = djtz.now()
    conversation.message_count = (conversation.message_count or 0) + 1
    conversation.exchange_count = (conversation.exchange_count or 0) + 1
    conversation.save(update_fields=[
        'last_ai_at', 'message_count', 'exchange_count', 'updated_at',
    ])
    usage.record_outbound_message(tenant)


def _serialize_tool_result(result: Any) -> str:
    """Tool results in Anthropic API land as strings on the tool_result block."""
    import json as _json
    try:
        return _json.dumps(result, default=str)
    except (TypeError, ValueError):
        return _json.dumps({'error': 'serialization_failed'})


def _emergency_escalate(
    *,
    message: Message,
    reason: str,
    summary: str = '',
) -> None:
    """Create an EscalationAlert + send a hand-off SMS without going through Claude.

    Used when the agent crashes, the outbound scanner blocks, or the
    tool-loop cap fires. Designed to be cheap + un-failable.
    """
    try:
        tenant = message.tenant
        customer = message.customer
        conv, _ = AIConversation.objects.get_or_create(
            tenant=tenant, customer=customer,
            defaults={'status': AIConversation.Status.ACTIVE},
        )
        EscalationAlert.objects.create(
            tenant=tenant, conversation=conv, customer=customer,
            reason=reason, reason_detail=summary or '',
            triggering_message=message,
        )
        conv.status = AIConversation.Status.ESCALATED
        conv.escalated_at = djtz.now()
        conv.escalation_reason = reason
        conv.save(update_fields=[
            'status', 'escalated_at', 'escalation_reason', 'updated_at',
        ])
        _send_outbound(
            tenant=tenant, customer=customer, conversation=conv,
            inbound_message=message,
            body="Thanks — I'm getting a teammate to help. They'll text you shortly.",
            model_used='emergency_escalate',
        )
    except Exception:
        logger.exception(
            'ai_inbox.emergency_escalate_failed tenant=%s message_id=%s',
            getattr(message.tenant, 'slug', '?'), message.id,
        )
