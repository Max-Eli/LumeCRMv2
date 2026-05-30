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

from .guardrails import PROCEED, evaluate

if TYPE_CHECKING:
    from rest_framework.request import Request

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

    # All guardrails passed. Hand off to the agent loop.
    #
    # Phase 1: stub no-op + a "would dispatch" audit row, so we have
    # full observability of when the guardrails WOULD have fired the
    # agent. Lets us tail the audit log during sandbox testing to
    # verify the dispatch path before the Phase-2 agent lands.
    #
    # Phase 2 will replace this with:
    #   from apps.ai_inbox.agents.sms_agent import run_agent
    #   run_agent(message=message)
    record(
        action=AuditLog.Action.READ,  # 'read' as a generic "noop dispatch" until Phase 2
        resource_type='ai_dispatch',
        resource_id=message.id,
        tenant=message.tenant,
        request=request,
        metadata={
            'event': 'ai_dispatch_would_run',
            'phase': 'phase_1_noop',
            'message_id': message.id,
            'customer_id': message.customer_id,
        },
    )


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
