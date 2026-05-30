"""Claude via the Anthropic API direct (NOT Bedrock).

Slots into the same ``LLMClient`` abstraction as ``BedrockClient``;
which provider is active is driven by ``settings.AI_LLM_PROVIDER``.

When to use which:
    - ``bedrock``      — default for production. PHI traffic stays
                         inside the VPC, covered by AWS's existing BAA.
    - ``anthropic``    — cheaper per token, faster onboarding (no
                         AWS quota provisioning), supports new models
                         day-of-release. NOT BAA-covered out of the
                         box — only use against tenants with zero
                         real PHI (demo, sandbox) OR after signing
                         an Anthropic BAA directly.

The API key is read from ``settings.ANTHROPIC_API_KEY``, which is
populated from the AWS Secrets Manager secret
``lume-prod/anthropic-api-key`` via the ECS task def's ``secrets``
list. The key is NEVER read from the environment without going
through ``settings`` first — that's the canonical configuration
surface for the app.
"""

from __future__ import annotations

import logging
from typing import Any

from django.conf import settings

from .base import LLMClient, LLMResponse, LLMTransportError

logger = logging.getLogger(__name__)


# Default model. Override via settings.ANTHROPIC_CLAUDE_MODEL_ID at
# deploy time when graduating to a newer model. Sonnet 4.6 is the
# current default for the AI inbox (matches what's documented in
# ADR 0032 + the Bedrock provider).
DEFAULT_MODEL_ID = 'claude-sonnet-4-6'


class DirectAnthropicClient(LLMClient):
    """Anthropic Messages API client wrapped to the LLMClient contract."""

    def __init__(self) -> None:
        # Lazy import so the SDK isn't a hard dependency for installs
        # that only use the Bedrock provider.
        import anthropic

        api_key = getattr(settings, 'ANTHROPIC_API_KEY', '') or ''
        if not api_key.strip():
            raise RuntimeError(
                'ANTHROPIC_API_KEY is not configured. Either set '
                'AI_LLM_PROVIDER=bedrock or wire the secret into the '
                'ECS task def.'
            )
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model_id = getattr(
            settings, 'ANTHROPIC_CLAUDE_MODEL_ID', DEFAULT_MODEL_ID,
        )

    def chat(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.4,
    ) -> LLMResponse:
        """Invoke Claude. Returns an LLMResponse shaped like Bedrock's.

        The Anthropic SDK is the upstream definition of the Messages
        API; Bedrock proxies that contract. So the call shape and
        response shape are essentially identical between providers —
        we only need to translate the SDK's typed objects into the
        plain-dict content blocks the agent loop already consumes.
        """
        kwargs: dict[str, Any] = {
            'model': self._model_id,
            'max_tokens': max_tokens,
            'temperature': temperature,
            'system': system,
            'messages': messages,
        }
        if tools:
            kwargs['tools'] = tools

        try:
            response = self._client.messages.create(**kwargs)
        except Exception as exc:  # noqa: BLE001 — wrap anthropic SDK exception classes
            logger.exception(
                'ai_inbox.anthropic_invoke_failed model=%s', self._model_id,
            )
            raise LLMTransportError(str(exc)) from exc

        # The SDK returns typed objects — convert to the dict shape the
        # agent loop expects. .model_dump() is provided by pydantic on
        # every response object in the SDK >= 0.30.
        content = [_to_block_dict(block) for block in response.content]
        usage = getattr(response, 'usage', None)
        return LLMResponse(
            content=content,
            stop_reason=getattr(response, 'stop_reason', None) or 'end_turn',
            model=getattr(response, 'model', self._model_id),
            input_tokens=int(getattr(usage, 'input_tokens', 0) or 0),
            output_tokens=int(getattr(usage, 'output_tokens', 0) or 0),
            raw=_safe_dump(response),
        )


def _to_block_dict(block: Any) -> dict[str, Any]:
    """Convert a single SDK content block to a plain dict."""
    if hasattr(block, 'model_dump'):
        return block.model_dump()
    # Fallback for older SDK versions or unexpected block shapes —
    # keep working rather than crash the agent turn.
    return {
        'type': getattr(block, 'type', 'unknown'),
        'text': getattr(block, 'text', ''),
        'id': getattr(block, 'id', ''),
        'name': getattr(block, 'name', ''),
        'input': getattr(block, 'input', {}),
    }


def _safe_dump(response: Any) -> dict[str, Any]:
    if hasattr(response, 'model_dump'):
        try:
            return response.model_dump()
        except Exception:  # noqa: BLE001
            return {}
    return {}
