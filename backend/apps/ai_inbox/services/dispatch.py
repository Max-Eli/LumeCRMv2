"""Public dispatch entrypoint — called from the messaging webhook.

This is the ONE line the messaging app needs to call after persisting
an inbound Message:

    from apps.ai_inbox.services.dispatch import maybe_dispatch_to_ai
    maybe_dispatch_to_ai(message=msg, request=request)

Contract:
    - NEVER raises. Any error (DB, guardrail, agent) is logged + audited;
      the messaging webhook completes normally regardless.
    - Either skips (writes an ``AuditLog`` row with the reason) or
      hands off to the agent loop (synchronously — Phase 1 it's a
      no-op stub, Phase 2 the real Bedrock loop).
    - All decisions are PHI-free in their audit metadata.

Phase 1 (this commit) stops at the guardrail layer + writes the audit
row. The actual ``run_agent(message)`` call lands in Phase 2 — see the
TODO at the bottom of this file.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from apps.audit.models import AuditLog
from apps.audit.services import record

from .guardrails import evaluate, evaluate_instagram

if TYPE_CHECKING:
    from rest_framework.request import Request

    from apps.integrations.models import Connection, SocialMessage, SocialThread
    from apps.messaging.models import Message


logger = logging.getLogger(__name__)


def maybe_dispatch_to_ai(
    *,
    message: 'Message',
    request: 'Request | None' = None,
) -> None:
    """Run guardrails on an inbound Message; hand off to the agent if all pass.

    Never raises. The messaging webhook is the caller; its response
    to Twilio must not depend on AI state.
    """
    try:
        _dispatch_inner(message=message, request=request)
    except Exception:  # noqa: BLE001  — defensive catch at boundary
        logger.exception(
            'ai_inbox.dispatch_failed tenant=%s message_id=%s',
            getattr(message.tenant, 'slug', '?'),
            message.id,
        )


def _dispatch_inner(
    *,
    message: 'Message',
    request: 'Request | None',
) -> None:
    # Only inbound messages dispatch — outbound rows are AI replies
    # we already produced (or staff sends, which the AI never reacts to).
    if message.direction != 'inbound':
        return

    decision = evaluate(
        tenant=message.tenant,
        customer=message.customer,
        inbound_message=message,
    )

    if not decision.proceed:
        _audit_skip(
            tenant=message.tenant,
            message=message,
            reason=decision.reason,
            metadata=decision.metadata,
            request=request,
        )
        return

    # All guardrails passed. Hand off to the agent loop synchronously.
    # run_agent never raises; it owns its own error handling +
    # emergency-escalation path.
    record(
        action=AuditLog.Action.READ,
        resource_type='ai_dispatch',
        resource_id=message.id,
        tenant=message.tenant,
        request=request,
        metadata={
            'event': 'ai_dispatch_run',
            'message_id': message.id,
            'customer_id': message.customer_id,
        },
    )
    from apps.ai_inbox.agents.sms_agent import run_agent
    run_agent(message=message)


def _audit_skip(
    *,
    tenant,
    message: 'Message',
    reason: str,
    metadata: dict | None,
    request,
) -> None:
    record(
        action=AuditLog.Action.READ,  # informational; AuditLog.Action has no SKIP
        resource_type='ai_dispatch',
        resource_id=message.id,
        tenant=tenant,
        request=request,
        metadata={
            'event': 'ai_dispatch_skipped',
            'reason': reason,
            'message_id': message.id,
            'customer_id': message.customer_id,
            **(metadata or {}),
        },
    )


# ── Instagram dispatch ───────────────────────────────────────────


def maybe_dispatch_to_ai_instagram(
    *,
    message: 'SocialMessage',
    thread: 'SocialThread',
    connection: 'Connection',
) -> None:
    """Run guardrails on an inbound Instagram DM; hand off to the agent
    if all pass. Called from the Meta webhook ingestion.

    NEVER raises — the webhook must return 200 to Meta regardless, and
    a slow/failed agent run must not fail message ingestion. Idempotent
    per inbound SocialMessage (parent_inbound_message_id), so a retried
    Meta delivery can't double-reply or double-book.
    """
    try:
        _dispatch_instagram_inner(message=message, thread=thread, connection=connection)
    except Exception:  # noqa: BLE001 — defensive at the webhook boundary
        logger.exception(
            'ai_inbox.instagram_dispatch_failed tenant=%s social_message_id=%s',
            getattr(message.tenant, 'slug', '?'),
            getattr(message, 'id', '?'),
        )


def _dispatch_instagram_inner(
    *,
    message: 'SocialMessage',
    thread: 'SocialThread',
    connection: 'Connection',
) -> None:
    from apps.integrations.models import SocialMessage

    # Only inbound DMs dispatch. Outbound rows are our own replies.
    if message.direction != SocialMessage.Direction.INBOUND:
        return
    # Empty-body events (a like, a story reply with no text, an
    # attachment-only message) have nothing for the agent to act on.
    if not (message.body or '').strip():
        return

    tenant = message.tenant
    customer = thread.customer

    decision = evaluate_instagram(
        tenant=tenant, customer=customer, thread=thread, inbound_message=message,
    )

    if not decision.proceed:
        record(
            action=AuditLog.Action.READ,
            resource_type='ai_dispatch',
            resource_id=message.id,
            tenant=tenant,
            metadata={
                'event': 'ai_dispatch_skipped',
                'channel': 'instagram',
                'reason': decision.reason,
                'social_message_id': message.id,
                'thread_id': thread.id,
                'customer_id': thread.customer_id,
                **(decision.metadata or {}),
            },
        )
        return

    record(
        action=AuditLog.Action.READ,
        resource_type='ai_dispatch',
        resource_id=message.id,
        tenant=tenant,
        metadata={
            'event': 'ai_dispatch_run',
            'channel': 'instagram',
            'social_message_id': message.id,
            'thread_id': thread.id,
            'customer_id': thread.customer_id,
        },
    )

    from apps.ai_inbox.agents.runner import run_agent
    from apps.ai_inbox.channels.instagram import InstagramAdapter
    run_agent(adapter=InstagramAdapter(message, thread, connection))
