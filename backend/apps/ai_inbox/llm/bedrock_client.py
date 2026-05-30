"""Claude on Amazon Bedrock — HIPAA-eligible LLM transport.

The v1 LLM provider. Sits under AWS's existing BAA, so PHI traffic
never leaves the VPC (private VPC endpoint to Bedrock is the
deployment topology). Uses IAM role auth via the ECS task role —
NO API key in Secrets Manager.

The actual ``invoke_model`` call ships in Phase 2 alongside the
agent loop; this file lands the client shape + the boto3 session +
the model-ID lookup so the dispatcher can instantiate one and the
IAM policy can be wired up without the agent loop existing yet.

Settings the client reads:
    BEDROCK_REGION             — AWS region (default 'us-east-1' to
                                  match RDS / Fargate)
    BEDROCK_CLAUDE_MODEL_ID    — Bedrock model identifier (e.g.
                                  'anthropic.claude-sonnet-4-5-20250929-v1:0')

Required IAM permission on the ECS task role (added in a separate
deployment step):
    bedrock:InvokeModel on the specific Claude model ARN(s).
"""

from __future__ import annotations

import json
import logging
from typing import Any

from django.conf import settings

from .base import LLMClient, LLMResponse, LLMTransportError

logger = logging.getLogger(__name__)


class BedrockClient(LLMClient):
    """Claude via boto3 bedrock-runtime."""

    def __init__(self) -> None:
        # Lazy boto3 import so the rest of the LLM layer can be
        # imported in tests / dev without boto3 dependency surprises.
        import boto3

        region = getattr(settings, 'BEDROCK_REGION', 'us-east-1')
        self._client = boto3.client('bedrock-runtime', region_name=region)
        self._model_id = getattr(
            settings, 'BEDROCK_CLAUDE_MODEL_ID',
            # Conservative default pointing at a Sonnet variant; the
            # exact ID is environment-specific (Bedrock has regional
            # variations + cross-region inference profiles). The
            # caller in production sets BEDROCK_CLAUDE_MODEL_ID
            # explicitly via Secrets Manager / ECS task def.
            'anthropic.claude-sonnet-4-5-20250929-v1:0',
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
        """Invoke Claude via Bedrock InvokeModel with the Messages API body shape.

        Wire-level: Bedrock proxies the Anthropic Messages API; the
        body is the same JSON Anthropic's own API accepts (minus the
        api_key + headers), with an additional ``anthropic_version``
        field naming the API contract.
        """
        body: dict[str, Any] = {
            'anthropic_version': 'bedrock-2023-05-31',
            'max_tokens': max_tokens,
            'temperature': temperature,
            'system': system,
            'messages': messages,
        }
        if tools:
            body['tools'] = tools

        try:
            response = self._client.invoke_model(
                modelId=self._model_id,
                contentType='application/json',
                accept='application/json',
                body=json.dumps(body),
            )
        except Exception as exc:  # noqa: BLE001  — wrap boto exception class hierarchy
            logger.exception(
                'ai_inbox.bedrock_invoke_failed model=%s', self._model_id,
            )
            raise LLMTransportError(str(exc)) from exc

        payload = json.loads(response['body'].read())
        usage = payload.get('usage') or {}
        return LLMResponse(
            content=payload.get('content', []),
            stop_reason=payload.get('stop_reason', 'end_turn'),
            model=payload.get('model', self._model_id),
            input_tokens=int(usage.get('input_tokens') or 0),
            output_tokens=int(usage.get('output_tokens') or 0),
            raw=payload,
        )
