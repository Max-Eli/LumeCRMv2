"""Abstract LLM client interface.

Every provider (Bedrock today, direct-Anthropic potentially later)
implements ``LLMClient.chat`` and returns an ``LLMResponse`` shaped
like the Anthropic Messages API response — content blocks, stop
reason, token usage. Callers (``agents.sms_agent``) only ever see
this shape, so swapping providers is a one-line change in
``llm/__init__.py::get_llm_client``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class LLMResponse:
    """Provider-agnostic representation of an LLM chat completion.

    Shaped to match Anthropic's Messages API so the agent loop can
    handle tool_use blocks + text blocks the same way regardless of
    transport (Bedrock InvokeModel vs direct Anthropic POST).
    """

    content: list[dict[str, Any]]
    """List of content blocks. Each block is one of:
        {"type": "text",     "text": "..."}
        {"type": "tool_use", "id": "...", "name": "...", "input": {...}}
    """

    stop_reason: str
    """One of: 'end_turn', 'tool_use', 'max_tokens', 'stop_sequence'."""

    model: str
    """Resolved model ID the provider actually invoked."""

    input_tokens: int = 0
    output_tokens: int = 0

    raw: dict[str, Any] = field(default_factory=dict)
    """Original provider response (for debugging / future tracing)."""

    def text_blocks(self) -> list[str]:
        return [b['text'] for b in self.content if b.get('type') == 'text']

    def tool_use_blocks(self) -> list[dict[str, Any]]:
        return [b for b in self.content if b.get('type') == 'tool_use']


class LLMClient(ABC):
    """Abstract chat interface every provider implements."""

    @abstractmethod
    def chat(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.4,
    ) -> LLMResponse:
        """Send one chat turn to the provider and return the response.

        Args:
            system: System prompt (no PHI — tenant config only).
            messages: Conversation history as
                ``[{"role": "user"|"assistant", "content": "..."|[blocks]}]``.
                Tool results are passed as user-role content blocks with
                ``{"type": "tool_result", "tool_use_id": "...", "content": "..."}``.
            tools: Optional list of tool schemas in Anthropic format
                ``[{"name": "...", "description": "...", "input_schema": {...}}]``.
            max_tokens: Response cap. v1 default 1024 — plenty for SMS-length replies.
            temperature: Default 0.4 — low enough for predictable booking flow,
                high enough that replies don't feel canned.

        Returns:
            LLMResponse with content blocks + stop reason + token usage.

        Raises:
            LLMTransportError: provider-layer failures (network, auth, throttling).
                Callers should retry once then escalate.
        """


class LLMTransportError(Exception):
    """Wrapped provider-side failure. Caller should retry once then escalate."""
