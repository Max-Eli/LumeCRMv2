"""Instagram channel adapter — Meta + integrations.SocialMessage.

Booking-only. Meta is NOT BAA-covered, so the Instagram agent never
gets the get_customer_context (PHI) tool — see ADR 0033. History
comes from SocialMessage; outbound goes through Meta's Send API
(``integrations.meta.send_instagram_dm``). A send failure (e.g. Meta
rejects it) is caught and the row is marked FAILED — it never breaks
the agent turn.
"""

from __future__ import annotations

import datetime as dt
import logging
import uuid
from typing import TYPE_CHECKING, Any

from django.utils import timezone as djtz

from apps.ai_inbox.agents import prompts, tools
from apps.ai_inbox.channels.base import ChannelAdapter
from apps.ai_inbox.models import AIConversation
from apps.ai_inbox.services import usage
from apps.integrations.models import SocialMessage

if TYPE_CHECKING:
    from apps.ai_inbox.models import AIConfig
    from apps.integrations.models import Connection, SocialThread

logger = logging.getLogger(__name__)

HISTORY_TURN_LIMIT = 20
HISTORY_BODY_TRUNC = 1000
# Instagram has no hard SMS-style segment limit, but keep replies
# tight + readable in a DM thread.
MAX_OUTBOUND_LEN = 900


class InstagramAdapter(ChannelAdapter):
    channel = AIConversation.Channel.INSTAGRAM

    def __init__(self, message: SocialMessage, thread: 'SocialThread', connection: 'Connection'):
        self._message = message
        self._thread = thread
        self._connection = connection
        self.tenant = message.tenant
        self.customer = thread.customer
        self.social_thread = thread

    def inbound_text(self) -> str:
        return self._message.body or ''

    def inbound_id(self) -> int:
        return self._message.id

    def triggered_by_message(self):
        # AIToolCall.triggered_by_message FKs to messaging.Message, not
        # SocialMessage — so Instagram tool-call rows carry no inbound
        # message link (the conversation FK + tool I/O still record it).
        return None

    def link_inbound(self, conversation: AIConversation) -> None:
        if self._message.ai_conversation_id is None:
            self._message.ai_conversation = conversation
            self._message.save(update_fields=['ai_conversation', 'updated_at'])

    def build_history(self) -> list[dict[str, Any]]:
        rows = list(
            SocialMessage.objects
            .filter(tenant=self.tenant, thread=self._thread)
            .order_by('-created_at')[:HISTORY_TURN_LIMIT]
        )
        rows.reverse()
        out: list[dict[str, Any]] = []
        for r in rows:
            role = 'user' if r.direction == SocialMessage.Direction.INBOUND else 'assistant'
            body = (r.body or '')[:HISTORY_BODY_TRUNC]
            if not body:
                continue
            out.append({'role': role, 'content': body})
        return out

    def send(self, conversation: AIConversation, body: str, *, model_used: str) -> None:
        from apps.integrations import meta as meta_oauth

        # Persist the outbound row up-front (QUEUED) so we have a stable
        # id even if the Meta call fails. external_message_id needs a
        # unique placeholder until Meta returns the real mid.
        msg = SocialMessage.objects.create(
            tenant=self.tenant,
            thread=self._thread,
            direction=SocialMessage.Direction.OUTBOUND,
            body=body,
            external_message_id=f'pending-ai-{uuid.uuid4().hex}',
            status=SocialMessage.Status.QUEUED,
            sent_by=None,
            generated_by_ai=True,
            ai_conversation=conversation,
            parent_inbound_message_id=self._message.id,
        )

        try:
            payload = self._connection.auth_data_dict
            ig_user_id = payload.get('ig_user_id', '')
            access_token = payload.get('access_token', '')
            if not (ig_user_id and access_token):
                raise RuntimeError('instagram_tokens_incomplete')
            resp = meta_oauth.send_instagram_dm(
                ig_user_id=ig_user_id,
                access_token=access_token,
                recipient_psid=self._thread.external_thread_id,
                body=body,
            )
            now = djtz.now()
            mid = resp.get('message_id', '')
            msg.external_message_id = mid or msg.external_message_id
            msg.status = SocialMessage.Status.SENT
            msg.sent_at = now
            msg.save(update_fields=['external_message_id', 'status', 'sent_at', 'updated_at'])

            # Bump thread aggregates so the inbox sort surfaces activity.
            self._thread.last_message_at = now
            self._thread.save(update_fields=['last_message_at', 'updated_at'])
        except Exception:
            logger.exception(
                'ai_inbox.instagram_send_failed tenant=%s thread_id=%s',
                self.tenant.slug, self._thread.id,
            )
            msg.status = SocialMessage.Status.FAILED
            msg.save(update_fields=['status', 'updated_at'])

        conversation.last_ai_at = djtz.now()
        conversation.message_count = (conversation.message_count or 0) + 1
        conversation.exchange_count = (conversation.exchange_count or 0) + 1
        conversation.save(update_fields=[
            'last_ai_at', 'message_count', 'exchange_count', 'updated_at',
        ])
        usage.record_outbound_message(self.tenant)

    def system_prompt(self, config: 'AIConfig', now: dt.datetime) -> str:
        return prompts.render_instagram_system_prompt(
            tenant=self.tenant, config=config, now=now,
        )

    def tool_schemas(self) -> list[dict[str, Any]]:
        return tools.TOOL_SCHEMAS_INSTAGRAM

    def post_booking_ack(self, result: dict) -> str:
        # Instagram confirms in-channel — there's no deferred SMS for
        # social guests (no phone / no sms_opt_in). This ack IS the
        # confirmation, so include the service + date/time.
        service = result.get('service')
        label = result.get('human_label')
        if service and label:
            return f"You're all set — {service} on {label}. See you then! Reply here if you need to make a change."
        return "You're all set — I've got you booked. See you then!"

    def handoff_message(self) -> str:
        return "Thanks! I'm getting a teammate to help — they'll follow up with you here shortly."

    def max_outbound_len(self) -> int:
        return MAX_OUTBOUND_LEN
