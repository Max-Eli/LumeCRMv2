# apps/ai_inbox — AI SMS Agent

AI-powered front-desk concierge that responds to inbound SMS via the
tenant's Twilio toll-free number, books appointments, and escalates
to a human when needed. Sits on top of `apps.messaging` — every AI
message is still a row in `messaging.Message` (tagged
`generated_by_ai=True`).

## At a glance

- **LLM provider**: Claude (Sonnet 4.5) via Amazon Bedrock, under
  AWS's existing BAA. PHI traffic stays inside the VPC. IAM-role
  auth via the ECS task role — no API key in Secrets Manager.
  Swap to direct-Anthropic later is a one-line change in
  [llm/__init__.py](./llm/__init__.py).
- **Plan tier**: Pro + Enterprise (`F_AI_INBOX` in
  [apps/tenants/plans.py](../tenants/plans.py)).
- **Default state**: OFF at every level. `AIConfig.enabled=False`,
  `test_mode=True`. Operators opt in.
- **The only tenant with a TFN in prod is `demo`** (`+18447380519`).
  The four other live tenants can't receive AI inbound at all — no
  TFN configured.

## HIPAA framing

PHI flows in exactly one direction: from the database to Claude, via
**explicitly-constructed tool results**. The system prompt
([agents/prompts.py](./agents/prompts.py)) is PHI-free — tenant
config only. The customer-context tool
([agents/tools.py](./agents/tools.py) `get_customer_context`)
operates on a hard **allow-list** — it never returns chart notes,
treatment records, intake form answers, medical history, insurance,
or payment-method detail. If a future engineer adds a field to
that list, they must update the HIPAA ADR (`docs/decisions/0021-...`)
in the same change.

Audit logs (`AIToolCall.input_json` / `output_json` and dispatch
skips) are scrubbed by
[services/scrub.py](./services/scrub.py) before persistence
(SSN/DOB/email/phone/card regex redaction). The PHI of record stays
on `messaging.Message.body` where it's been since the messaging app
shipped.

The outbound PHI scanner in `services/scrub.outbound_pii_check`
runs before every AI-authored SMS is sent. If the model ever
produces an SSN/DOB/card-number-looking sequence (prompt injection,
model error), the send is blocked and the conversation escalates
with `reason=safety_outbound_blocked`.

## Architecture

```
                            ┌───────────────────────────┐
   Twilio inbound webhook → │ apps/messaging/views.py   │
                            │   TwilioInboundView.post  │
                            └────────────┬──────────────┘
                                         │
                                         ▼
                            ┌───────────────────────────┐
                            │ services/dispatch.py      │
                            │ maybe_dispatch_to_ai      │
                            └────────────┬──────────────┘
                                         │
                                         ▼
                            ┌───────────────────────────┐
                            │ services/guardrails.py    │
                            │ 11 checks, in order:      │
                            │   feature flag, TFN,      │
                            │   AIConfig.enabled,       │
                            │   platform kill switch,   │
                            │   test-mode number match, │
                            │   customer not blocked,   │
                            │   sms_opt_in,             │
                            │   conversation status,    │
                            │   30s reply gap,          │
                            │   daily cap,              │
                            │   per-inbound idempotency │
                            └────────────┬──────────────┘
                                         │ proceed
                                         ▼
                            ┌───────────────────────────┐
                            │ agents/sms_agent.run_agent│
                            │  - digit fast-path        │
                            │  - else Claude loop:      │
                            │      ⤵ tool calls ⤴       │
                            │  - send outbound SMS      │
                            └────────────┬──────────────┘
                                         │
                                         ▼
                            ┌───────────────────────────┐
                            │ appointments.sms.send_sms │
                            │  (existing Twilio path)   │
                            └───────────────────────────┘
```

## The kill switches

In priority order (any one blocks dispatch):

1. **Platform-admin global**: `AIConfig.platform_disabled_at` (set
   from `/platform/tenants/<id>/disable-ai/` in Phase 3). Trumps
   everything below.
2. **Tenant master**: `AIConfig.enabled=False`. Operator-facing
   toggle in Settings → AI Inbox (Phase 3).
3. **Per-conversation pause**: `AIConversation.status=paused`. Staff
   button in the existing inbox (Phase 3).
4. **Escalation**: `AIConversation.status=escalated` (set by
   `escalate_to_human` tool or emergency escalation).
5. **Sandbox/test mode**: only `AIConfig.test_mode_number` can talk
   to the AI; everything else is audit-logged + dropped.
6. **Daily send cap**: `AIConfig.daily_send_cap` vs
   `AIUsageDay.ai_messages_sent`.
7. **Per-conversation rate limit**: 30 seconds between AI replies.
8. **Per-inbound idempotency**: `Message.parent_inbound_message_id`
   prevents double-fires from Twilio retries.

## Incident response — "the AI said something it shouldn't"

1. **Kill the conversation now**: from `/platform/tenants/<slug>/`,
   click "Disable AI" — sets `AIConfig.platform_disabled_at` for
   the tenant. Every further inbound is dropped at guardrail layer.
2. **Pull the trail**: every AI message is a `Message` row with
   `generated_by_ai=True` linked to an `AIConversation` row; every
   tool call is an `AIToolCall` row with scrubbed input/output.
3. **Reproduce locally**: re-run the inbound message ID through the
   agent with the captured tenant config to confirm + classify.
4. **Notify the customer + the tenant operator**.
5. **Tighten the prompt or the tool allow-list**. Don't ship a fix
   that papers over a deeper issue — escalate to the HIPAA ADR if
   the surface needs to change.

## Files

- [models.py](./models.py) — AIConfig, AIConversation, AIToolCall,
  EscalationAlert, AIUsageDay.
- [services/dispatch.py](./services/dispatch.py) — webhook entrypoint.
- [services/guardrails.py](./services/guardrails.py) — the 11-check chain.
- [services/scrub.py](./services/scrub.py) — PHI redaction + outbound scanner.
- [services/usage.py](./services/usage.py) — AIUsageDay counters.
- [services/locks.py](./services/locks.py) — DB-backed per-conversation lock.
- [agents/sms_agent.py](./agents/sms_agent.py) — the agent loop.
- [agents/prompts.py](./agents/prompts.py) — system prompt template.
- [agents/tools.py](./agents/tools.py) — 6 tools + dispatcher.
- [llm/base.py](./llm/base.py) — `LLMClient` ABC.
- [llm/bedrock_client.py](./llm/bedrock_client.py) — Claude via Bedrock.

## Settings

- `AI_LLM_PROVIDER` — default `'bedrock'`.
- `BEDROCK_REGION` — default `'us-east-1'`.
- `BEDROCK_CLAUDE_MODEL_ID` — Bedrock model identifier (set per
  environment in ECS task def; defaults to a Sonnet 4.5 model ID).

## Enabling for a tenant

```bash
# Seed only (safe — does NOT enable):
python manage.py enable_ai_for_tenant --tenant demo

# Enable in sandbox bound to your cell:
python manage.py enable_ai_for_tenant --tenant demo --enable \
    --test-mode-number +14155551234 \
    --persona "You're Avery, the front-desk assistant for the demo medspa."
```
