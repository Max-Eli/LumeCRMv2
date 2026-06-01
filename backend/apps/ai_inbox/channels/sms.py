"""SMS channel adapter — Twilio + messaging.Message.

Wraps the original SMS agent behavior verbatim: full tool set
(including get_customer_context, since SMS via Twilio is BAA-covered),
the SMS system prompt, history from messaging.Message, outbound via
apps.appointments.sms.send_sms.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import TYPE_CHECKING, Any

from django.utils import timezone as djtz

from apps.ai_inbox.agents import prompts, tools
from apps.ai_inbox.channels.base import ChannelAdapter
from apps.ai_inbox.models import AIConversation
from apps.ai_inbox.services import usage
from apps.messaging.models import Direction, Message, MessageKind, MessageStatus

if TYPE_CHECKING:
    from apps.ai_inbox.models import AIConfig

logger = logging.getLogger(__name__)

HISTORY_TURN_LIMIT = 20
HISTORY_BODY_TRUNC = 1000
MAX_OUTBOUND_LEN = 320  # ~2 SMS segments


class SMSAdapter(ChannelAdapter):
    channel = AIConversation.Channel.SMS

    def __init__(self, message: Message):
        self._message = message
        self.tenant = message.tenant
        self.customer = message.customer

    def inbound_text(self) -> str:
        return self._message.body or ''

    def inbound_id(self) -> int:
        return self._message.id

    def triggered_by_message(self):
        return self._message

    def link_inbound(self, conversation: AIConversation) -> None:
        if self._message.ai_conversation_id is None:
            self._message.ai_conversation = conversation
            self._message.save(update_fields=['ai_conversation', 'updated_at'])

    def build_history(self) -> list[dict[str, Any]]:
        rows = list(
            Message.objects
            .filter(tenant=self.tenant, customer=self.customer)
            .order_by('-created_at')[:HISTORY_TURN_LIMIT]
        )
        rows.reverse()
        out: list[dict[str, Any]] = []
        for r in rows:
            role = 'user' if r.direction == Direction.INBOUND else 'assistant'
            body = (r.body or '')[:HISTORY_BODY_TRUNC]
            if not body:
                continue
            out.append({'role': role, 'content': body})
        return out

    def send(self, conversation: AIConversation, body: str, *, model_used: str) -> None:
        from apps.appointments.sms import send_sms

        try:
            sid = send_sms(tenant=self.tenant, to=self.customer.phone, body=body)
        except Exception:
            logger.exception(
                'ai_inbox.send_sms_failed tenant=%s customer_id=%s',
                self.tenant.slug, self.customer.id,
            )
            sid = ''

        Message.objects.create(
            tenant=self.tenant, customer=self.customer,
            direction=Direction.OUTBOUND,
            body=body,
            status=MessageStatus.SENT if sid else MessageStatus.FAILED,
            kind=MessageKind.AI,
            provider_message_id=sid,
            from_number=self.tenant.twilio_from_number or '',
            to_number=self.customer.phone or '',
            sent_by=None,
            generated_by_ai=True,
            ai_conversation=conversation,
            parent_inbound_message_id=self._message.id,
        )

        conversation.last_ai_at = djtz.now()
        conversation.message_count = (conversation.message_count or 0) + 1
        conversation.exchange_count = (conversation.exchange_count or 0) + 1
        conversation.save(update_fields=[
            'last_ai_at', 'message_count', 'exchange_count', 'updated_at',
        ])
        usage.record_outbound_message(self.tenant)

    def system_prompt(self, config: 'AIConfig', now: dt.datetime) -> str:
        return prompts.render_system_prompt(tenant=self.tenant, config=config, now=now)

    def tool_schemas(self) -> list[dict[str, Any]]:
        return tools.TOOL_SCHEMAS

    def post_booking_ack(self, result: dict) -> str:
        # SMS defers the formal confirmation 60s (appointment signal),
        # so the in-flow ack is just a heads-up.
        return "Got it — sending you the confirmation in a moment."

    def handoff_message(self) -> str:
        return "Thanks — I'm getting a teammate to help. They'll text you shortly."

    def max_outbound_len(self) -> int:
        return MAX_OUTBOUND_LEN
