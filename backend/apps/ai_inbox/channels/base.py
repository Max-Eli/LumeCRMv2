"""Channel adapter protocol for the AI agent.

The agent loop (``agents/runner.run_agent``) is channel-agnostic.
Everything channel-specific — how an inbound message is read, how
history is built, how an outbound reply is sent + persisted, which
tools + system prompt apply — lives behind a ``ChannelAdapter``.

Two implementations:
  - ``channels/sms.SMSAdapter``       — Twilio + messaging.Message (full tool set, BAA-covered)
  - ``channels/instagram.InstagramAdapter`` — Meta + integrations.SocialMessage
                                         (booking-only tool set, NOT BAA-covered → no PHI tool)

The adapter is constructed with the raw inbound row and exposes a
uniform surface to the runner. This keeps the SMS behavior exactly
as it was while letting Instagram reuse the same loop.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import datetime as dt

    from apps.ai_inbox.models import AIConfig, AIConversation
    from apps.customers.models import Customer
    from apps.tenants.models import Tenant


class ChannelAdapter(ABC):
    """Per-channel I/O for one inbound message + its agent turn."""

    #: AIConversation.Channel value, e.g. 'sms' or 'instagram'.
    channel: str

    #: Resolved from the inbound row in __init__.
    tenant: 'Tenant'
    customer: 'Customer'

    #: The integrations.SocialThread this conversation belongs to, or
    #: None for SMS. Set on the AIConversation at create time.
    social_thread = None

    @abstractmethod
    def inbound_text(self) -> str:
        """The customer's message body for this turn."""

    @abstractmethod
    def inbound_id(self) -> int:
        """PK of the inbound row — used for per-inbound idempotency
        (parent_inbound_message_id on the outbound row)."""

    @abstractmethod
    def triggered_by_message(self):
        """The messaging.Message to attach to AIToolCall rows, or None.

        AIToolCall.triggered_by_message FKs to messaging.Message
        specifically, so non-SMS channels return None (the audit row
        still records the conversation + tool input/output)."""

    @abstractmethod
    def link_inbound(self, conversation: 'AIConversation') -> None:
        """Attach the inbound row to its AIConversation (for the inbox
        AI badge), if not already linked."""

    @abstractmethod
    def build_history(self) -> list[dict[str, Any]]:
        """Last N messages mapped to Anthropic [{role, content}] turns,
        ascending. The current inbound is the final user turn."""

    @abstractmethod
    def send(self, conversation: 'AIConversation', body: str, *, model_used: str) -> None:
        """Send an outbound reply on this channel + persist the row
        (generated_by_ai=True, ai_conversation, parent_inbound_message_id)
        + bump conversation counters + usage."""

    @abstractmethod
    def system_prompt(self, config: 'AIConfig', now: 'dt.datetime') -> str:
        """The channel's system prompt, rendered from tenant config."""

    @abstractmethod
    def tool_schemas(self) -> list[dict[str, Any]]:
        """The tool set available on this channel. Instagram omits
        get_customer_context (PHI) — Meta is not BAA-covered."""

    @abstractmethod
    def post_booking_ack(self, result: dict) -> str:
        """Message sent after a successful digit-fast-path booking.
        ``result`` is the run_confirm_booking payload
        ({appointment_id, service, human_label, ...}). SMS defers the
        formal confirmation 60s so its ack is just a heads-up;
        Instagram has no deferred channel, so its ack IS the
        confirmation and includes the date/time."""

    def post_reschedule_ack(self, result: dict) -> str:
        """Message sent after a successful digit-fast-path RESCHEDULE.
        Unlike a new booking, a reschedule fires NO deferred confirmation
        signal — so this message IS the confirmation and must carry the
        new date/time. Concrete (not abstract): every channel gets a sane
        default; override only for channel-specific phrasing."""
        service = result.get('service')
        label = result.get('human_label')
        if service and label:
            return (
                f"All set — your {service} is moved to {label}. See you then! "
                f"Reply here if you need anything else."
            )
        return "All set — your appointment has been rescheduled. See you then!"

    @abstractmethod
    def handoff_message(self) -> str:
        """The 'a teammate will follow up' message sent on escalation."""

    @abstractmethod
    def max_outbound_len(self) -> int:
        """Per-message length cap for this channel."""
