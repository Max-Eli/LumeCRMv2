"""AIUsageDay counters — atomic increments.

One row per (tenant, date). Incremented by the agent loop when:

  - An AI outbound message is sent  → ai_messages_sent + 1, ai_exchanges + 1
  - A tool call completes            → ai_tool_calls + 1
  - The LLM responds                 → bedrock_input_tokens + N, bedrock_output_tokens + M

Daily-cap check is in guardrails.py; this module owns the writes.
Used by the Phase-5 Stripe overage reporter.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.db.models import F
from django.utils import timezone as djtz

from apps.ai_inbox.models import AIUsageDay

if TYPE_CHECKING:
    from apps.tenants.models import Tenant


def _row_for_today(tenant: 'Tenant') -> AIUsageDay:
    row, _ = AIUsageDay.objects.get_or_create(
        tenant=tenant, date=djtz.localdate(),
    )
    return row


def record_outbound_message(tenant: 'Tenant') -> None:
    """One AI outbound completed → +1 send, +1 exchange."""
    AIUsageDay.objects.filter(
        tenant=tenant, date=djtz.localdate(),
    ).update(
        ai_messages_sent=F('ai_messages_sent') + 1,
        ai_exchanges=F('ai_exchanges') + 1,
    )


def record_tool_call(tenant: 'Tenant') -> None:
    AIUsageDay.objects.filter(
        tenant=tenant, date=djtz.localdate(),
    ).update(ai_tool_calls=F('ai_tool_calls') + 1)


def record_tokens(tenant: 'Tenant', *, input_tokens: int, output_tokens: int) -> None:
    AIUsageDay.objects.filter(
        tenant=tenant, date=djtz.localdate(),
    ).update(
        bedrock_input_tokens=F('bedrock_input_tokens') + input_tokens,
        bedrock_output_tokens=F('bedrock_output_tokens') + output_tokens,
    )


def ensure_today_row(tenant: 'Tenant') -> AIUsageDay:
    """Call once at the top of each agent turn so subsequent F-updates target an existing row."""
    return _row_for_today(tenant)
