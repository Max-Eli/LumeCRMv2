# ADR 0032 — AI SMS Agent: HIPAA posture + provider choice

Status: accepted (2026-05-30) · Phase 2 of `apps/ai_inbox`

## Context

The Pro+ tier includes a 2-way SMS inbox + per-tenant Twilio toll-free
number. Operators reply by hand today. We're shipping an AI agent
(`apps.ai_inbox`) that responds to inbound SMS, proposes booking
slots, and escalates to a human when needed — matching Podium /
Birdeye / Boulevard parity. Medspa workflows touch PHI (appointment
history, package balances, medical context); a SOC-2-ready,
HIPAA-grade posture is non-negotiable for the agent.

This ADR documents the BAA path we picked, what data crosses the
process boundary, and what does not.

## Decision

### Provider: Claude (Sonnet 4.5) via Amazon Bedrock

We use Anthropic's Claude models exposed via **Amazon Bedrock**, in
the same AWS region as our RDS + Fargate (`us-east-1`).

- **BAA**: AWS's existing BAA (signed when the prod AWS account was
  set up for HIPAA workloads) covers Bedrock for HIPAA-eligible
  services. No new Anthropic BAA is required.
- **Auth**: IAM role attached to the ECS task; no API key in
  Secrets Manager.
- **Topology**: PHI never leaves the VPC. Bedrock VPC endpoints are
  the deployment-time topology.
- **Provider abstraction**: [`apps/ai_inbox/llm/base.py`](../../backend/apps/ai_inbox/llm/base.py)
  defines `LLMClient`. The Bedrock implementation is the v1 driver;
  a future direct-Anthropic driver is a drop-in swap if we later
  sign a direct BAA for cheaper per-token rates.

### What flows to Claude (and what does not)

| Carrier              | Contents                          | PHI?  |
|----------------------|-----------------------------------|-------|
| System prompt        | Tenant name, persona, hours, escalation rules | **No** |
| Conversation history | Last ~20 SMS bodies for this customer | **Yes** (the messaging app already classifies `Message.body` as PHI at rest) |
| Tool results         | Output of `get_customer_context`, `check_availability`, etc. | **Some** (see allow-list below) |

**`get_customer_context` allow-list** — the only PHI-bearing tool.
Returns ONLY:
- Recent appointments (date, service name, provider first name, status)
- Upcoming appointments (date, time, service name, provider first name, status)
- Active packages (name, remaining sessions, expiry)
- Active membership (plan name, status)
- Outstanding balance total (cents)
- Gift card balance total (cents)

**Hard exclusions** (the tool never returns these, full stop):
- Chart notes / clinical observations
- Treatment records (dose, drug, lot)
- Intake form answers
- Medical history
- Insurance information
- Payment-method detail (last4, brand, etc.)
- Audit log entries

### What we log + what we redact

- `messaging.Message.body` remains the PHI-of-record store. Every
  inbound + every AI outbound is persisted there.
- `AIToolCall.input_json` + `output_json` are **scrubbed** by
  [`apps/ai_inbox/services/scrub.scrub_for_log`](../../backend/apps/ai_inbox/services/scrub.py)
  before persistence — regex redaction of SSN / DOB / email / phone /
  card-number patterns.
- `AuditLog` rows written by the dispatch layer are PHI-free by
  design — they carry a reason code (`feature_not_on_plan`,
  `ai_not_enabled_for_tenant`, etc.) + the inbound `message_id` +
  the `customer_id`. No body content.
- Outbound SMS bodies pass through `outbound_pii_check` before
  send. Detected SSN / DOB / card-number patterns block the send
  and escalate with `reason=safety_outbound_blocked`.

### Default-off safety contract

- `AIConfig.enabled` defaults `False`. Created via
  `enable_ai_for_tenant` mgmt cmd; opted in via Settings UI.
- `AIConfig.test_mode` defaults `True`. Only the configured
  `test_mode_number` can interact in sandbox.
- `AIConfig.platform_disabled_at` is the platform-admin global kill
  switch — non-null blocks everything regardless of other state.
- `tenant.twilio_from_number` must be non-empty before enable is
  permitted; the CLI rejects, the future API enable will reject.
- Daily send cap (`AIConfig.daily_send_cap`, default 100) prevents
  runaway loops or compromised systems from blasting SMS.
- Per-conversation reply lock (30s gap minimum) prevents the agent
  from talking over itself.

### What the agent CANNOT do in v1

Out-of-scope actions escalate instead of attempting:
- Rescheduling an existing appointment → `unsupported_request`
- Canceling an appointment → `unsupported_request`
- Processing payments / refunds → `payment_dispute`
- Giving medical advice / interpreting symptoms / confirming dosage →
  `clinical_question`
- Discussing other patients → blocked by tool layer (only ever
  operates on the conversation's own customer)

## Alternatives considered

- **Direct Anthropic API + new BAA** — cheaper per token, but
  requires a separate BAA conversation with Anthropic (1–2 weeks of
  legal review). Deferred; the LLM provider abstraction means we
  can swap later for $0 of refactor.
- **OpenAI** — different BAA (Enterprise tier required), separate
  vendor relationship, slightly weaker tool-use reliability in our
  spot checks. Not chosen.
- **In-process LLM (open-source on Fargate)** — operationally
  expensive (model weights, GPU instances, scaling); no advantage
  for our volume. Not chosen.

## Consequences

- We're locked to Bedrock's model catalog + Bedrock pricing for v1.
  Bedrock typically lags direct-Anthropic by 1–2 weeks on new
  model releases; the abstraction lets us escape that if it becomes
  a competitive issue.
- Customer-deletion cascade now flows through `AIConversation` →
  `AIToolCall` + `EscalationAlert`. `purge_tenant_customers` is
  updated in Phase 5 to include these tables in the delete plan.
- Operators get one new mental model — "an AI is replying for me" —
  which lives behind the `generated_by_ai` flag in the existing
  inbox so they never lose the chronological view.

## Related

- [apps/ai_inbox/README.md](../../backend/apps/ai_inbox/README.md) — operator runbook
- [Plan: AI SMS Agent for Lumè CRM (v1)](../../../../.claude/plans/abstract-bouncing-trinket.md)
- ADR 0026 — Tenant isolation enforcement (the AI agent operates
  strictly inside the conversation's tenant)
- ADR 0023 — Messaging polish + templates + review (the AI agent
  appends to the same conversation transcript)
