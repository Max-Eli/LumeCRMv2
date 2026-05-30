"""Guardrails for AI dispatch.

Every inbound SMS that lands in the messaging webhook passes through
this layer BEFORE the agent ever runs. The cheapest possible kill
switches fire first; the most expensive (DB writes) last. Every skip
writes one ``AuditLog`` row with a PHI-free reason so we can answer
"why didn't the AI reply to this inbound" without grepping logs.

The checks below are the safety contract this whole feature lives
under. Treat them as load-bearing.

Default-off contract:
    - tenant must have F_AI_INBOX
    - AIConfig must exist and have enabled=True
    - AIConfig.platform_disabled_at must be null
    - tenant.twilio_from_number must be non-empty (belt-and-suspenders;
      a tenant without a TFN literally can't receive inbound)
    - if AIConfig.test_mode, inbound `From` must equal test_mode_number

Customer-level:
    - Customer.status != BLOCKED
    - Customer.sms_opt_in is True

Per-conversation:
    - AIConversation.status not in {PAUSED, ESCALATED}

Capacity:
    - AIUsageDay.ai_messages_sent < AIConfig.daily_send_cap

Rate-limit (DB-backed, no Redis):
    - AIConversation.last_ai_at older than 30s

Idempotency:
    - no existing outbound Message with parent_inbound_message_id == inbound.id
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.utils import timezone as djtz

from apps.tenants.plans import F_AI_INBOX, tenant_has_feature

if TYPE_CHECKING:
    from apps.customers.models import Customer
    from apps.messaging.models import Message
    from apps.tenants.models import Tenant

    from apps.ai_inbox.models import AIConfig, AIConversation


logger = logging.getLogger(__name__)


# Min seconds between consecutive AI replies on the same conversation.
# Guards against runaway loops + double-fired Twilio retries.
PER_CONVERSATION_REPLY_GAP_SECONDS = 30


# Sentinel object returned when guardrails block dispatch — never
# raised, so the messaging webhook stays unaffected by any AI
# dispatch failure. The reason string is what goes into the audit
# log and the skip metrics.
@dataclass(frozen=True)
class GuardrailDecision:
    proceed: bool
    reason: str
    metadata: dict | None = None


PROCEED = GuardrailDecision(proceed=True, reason='ok')


def evaluate(
    *,
    tenant: 'Tenant',
    customer: 'Customer | None',
    inbound_message: 'Message',
) -> GuardrailDecision:
    """Run every guardrail in order. First non-PROCEED short-circuits.

    No DB writes happen here — caller is responsible for persisting
    the audit log row + (if PROCEED) handing off to the agent loop.

    ``customer`` may be None if the inbound is from an unknown number
    (cold inbound). v1: we drop unknown-number inbound at this layer
    rather than build the lead-creation flow inside guardrails. Phase
    2 of the rollout adds cold-inbound handling — for now, unknown
    sender = no AI reply.
    """
    # Cheapest kill switches first.

    if not tenant_has_feature(tenant, F_AI_INBOX):
        return GuardrailDecision(False, 'feature_not_on_plan')

    if not (tenant.twilio_from_number or '').strip():
        # Shouldn't happen — the inbound webhook resolves the tenant
        # by matching the To number against this field, so an empty
        # value would have meant the inbound never reached us. Cheap
        # second check anyway.
        return GuardrailDecision(False, 'tenant_missing_tfn')

    # AIConfig must exist + be enabled + not platform-killed.
    config = _get_config(tenant)
    if config is None:
        return GuardrailDecision(False, 'no_ai_config')
    if not config.enabled:
        return GuardrailDecision(False, 'ai_not_enabled_for_tenant')
    if config.platform_disabled_at is not None:
        return GuardrailDecision(False, 'platform_kill_switch_engaged')

    if config.test_mode:
        if (inbound_message.from_number or '').strip() != (config.test_mode_number or '').strip():
            return GuardrailDecision(False, 'test_mode_number_mismatch')

    if customer is None:
        # Cold inbound from an unknown number. v1: drop. Phase 2:
        # create a placeholder Customer + engage.
        return GuardrailDecision(False, 'unknown_sender_v1_drop')

    if customer.status == 'blocked':
        return GuardrailDecision(False, 'customer_blocked')

    if not customer.sms_opt_in:
        return GuardrailDecision(False, 'customer_sms_opt_out')

    # Per-conversation gates.
    conversation = _get_conversation(tenant, customer)
    if conversation is not None:
        if conversation.status in ('paused', 'escalated', 'closed'):
            return GuardrailDecision(False, f'conversation_{conversation.status}')

        # Rate limit: min N seconds since last AI reply.
        if conversation.last_ai_at is not None:
            gap = djtz.now() - conversation.last_ai_at
            if gap < dt.timedelta(seconds=PER_CONVERSATION_REPLY_GAP_SECONDS):
                return GuardrailDecision(
                    False, 'rate_limited',
                    metadata={'seconds_since_last_ai': gap.total_seconds()},
                )

    # Daily cap.
    if not _under_daily_cap(tenant, config):
        return GuardrailDecision(False, 'daily_cap_exceeded')

    # Idempotency — don't double-send for a retried Twilio webhook.
    if _already_replied_to(inbound_message):
        return GuardrailDecision(False, 'idempotency_already_replied')

    return PROCEED


# ── internal helpers ─────────────────────────────────────────────


def _get_config(tenant: 'Tenant') -> 'AIConfig | None':
    from apps.ai_inbox.models import AIConfig
    return AIConfig.objects.filter(tenant=tenant).first()


def _get_conversation(tenant: 'Tenant', customer: 'Customer') -> 'AIConversation | None':
    from apps.ai_inbox.models import AIConversation
    return AIConversation.objects.filter(tenant=tenant, customer=customer).first()


def _under_daily_cap(tenant: 'Tenant', config: 'AIConfig') -> bool:
    from apps.ai_inbox.models import AIUsageDay
    today = djtz.localdate()
    row = AIUsageDay.objects.filter(tenant=tenant, date=today).first()
    if row is None:
        return True
    return row.ai_messages_sent < config.daily_send_cap


def _already_replied_to(inbound: 'Message') -> bool:
    from apps.messaging.models import Message
    return Message.objects.filter(
        tenant=inbound.tenant,
        parent_inbound_message_id=inbound.id,
    ).exists()
