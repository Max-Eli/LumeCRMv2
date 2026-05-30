"""Django app config for the AI SMS inbox.

The ai_inbox app owns the AI-agent layer that sits on top of the
existing ``apps.messaging`` 2-way SMS infrastructure. It does NOT
replace messaging — every AI-generated message is still a row in
``messaging.Message`` (tagged ``generated_by_ai=True``); this app
owns the agent state, the LLM client, the tool calls, and the
escalation surface.

Provider: Claude via Amazon Bedrock under AWS's existing BAA. The
LLM client layer is abstracted (``llm/base.py``) so a future direct-
Anthropic swap is a one-file change.

HIPAA framing lives in ``apps/ai_inbox/README.md`` and the
companion ADR. The system prompt is PHI-free; PHI flows to Claude
only via explicitly-constructed tool results (``get_customer_context``
with an allow-list).
"""

from django.apps import AppConfig


class AIInboxConfig(AppConfig):
    name = 'apps.ai_inbox'
    verbose_name = 'AI SMS Inbox'
