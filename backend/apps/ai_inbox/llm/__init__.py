"""LLM client layer for the AI inbox.

Two-layer abstraction:

  ``base.LLMClient``        — abstract chat interface every provider implements
  ``bedrock_client.BedrockClient`` — Claude via Amazon Bedrock (the v1 provider)

``get_llm_client()`` is the single entrypoint everything else uses;
it reads ``settings.AI_LLM_PROVIDER`` and returns a configured
client. Today the only legal value is ``'bedrock'`` — a future
``'direct_anthropic'`` value would slot in here without touching
any caller code.
"""

from __future__ import annotations

from django.conf import settings

from .base import LLMClient


def get_llm_client() -> LLMClient:
    """Return the configured LLM client for this process.

    Routed by ``settings.AI_LLM_PROVIDER``:
      - ``bedrock``    — Claude via Amazon Bedrock (AWS BAA, prod default)
      - ``anthropic``  — Claude via direct Anthropic API (no BAA out of the
                         box — only use for tenants with zero real PHI)

    Caching lives on each client (it stores its SDK / boto3 session)
    so this function is cheap to call repeatedly.
    """
    provider = getattr(settings, 'AI_LLM_PROVIDER', 'bedrock')
    if provider == 'bedrock':
        from .bedrock_client import BedrockClient
        return BedrockClient()
    if provider == 'anthropic':
        from .anthropic_direct_client import DirectAnthropicClient
        return DirectAnthropicClient()
    raise ValueError(f'Unknown AI_LLM_PROVIDER: {provider!r}')
