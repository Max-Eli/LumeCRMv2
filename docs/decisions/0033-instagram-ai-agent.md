# ADR 0033 — Instagram AI Agent: booking-only, no PHI over a non-BAA channel

Status: accepted (2026-06-01) · extends ADR 0032 (AI SMS agent) and ADR 0027 (Meta Instagram DM integration)

## Context

The SMS AI agent (ADR 0032, `apps/ai_inbox`) books appointments, surfaces
package/membership credits, and escalates to staff over SMS. Instagram DM is
the highest-volume lead channel for medspas, and the spa already has a working
Instagram DM integration (ADR 0027): inbound webhook ingestion, a social inbox,
and a send-DM API. We're adding the AI agent layer on top of Instagram.

The decisive difference from SMS:

- **Twilio (SMS) signs a BAA.** SMS is an authorized channel for PHI under our
  HIPAA posture, so the SMS agent may reveal appointment history, package
  balances, etc. via the `get_customer_context` tool.
- **Meta (Instagram) does NOT sign a BAA.** Instagram DM is not a HIPAA-secure
  channel. Revealing any PHI over Instagram would be a HIPAA violation.

## Decision

### 1. The Instagram agent is booking-only and structurally PHI-free

The Instagram tool set is the SMS tool set **minus `get_customer_context`**
(the only PHI-read tool) **plus `capture_lead_info`** (a write-only
lead-capture tool). Excluding the read tool means the model has **no mechanism**
to fetch PHI — the safety is structural, not merely prompt-level. The system
prompt additionally instructs the agent that it cannot look up accounts over
Instagram and must direct account questions to a phone call
(`AIConfig.business_phone`, falling back to the primary Location phone).

What the agent CAN do over Instagram: discuss services + catalog prices, answer
general questions, capture a new lead's contact info, and book appointments.
What it CANNOT do: reveal appointment history, packages, memberships, balances,
or any account-specific data. Clinical-suitability questions escalate to staff
(`clinical_question`).

### 2. One agent, two channels — channel adapter pattern

Rather than a parallel app, `apps/ai_inbox` was generalized:

- `AIConversation` gained a `channel` field (`sms` | `instagram`) and a
  `social_thread` FK; identity is now `(tenant, customer, channel)`.
- The agent loop moved to `agents/runner.run_agent(adapter)`, driven by a
  `ChannelAdapter` (`channels/base.py`). `channels/sms.py` preserves the
  original SMS behavior verbatim; `channels/instagram.py` reads history from
  `SocialMessage`, sends via `integrations.meta.send_instagram_dm`, and uses
  the Instagram tool set + prompt.
- `services/dispatch.maybe_dispatch_to_ai_instagram` is hooked into the Meta
  webhook ingestion (`integrations.meta._process_messaging_event`). It runs
  inline (no Celery — same call as SMS) and is **idempotent per inbound
  SocialMessage** (`parent_inbound_message_id`), so Meta's aggressive webhook
  retries cannot double-reply or double-book.

### 3. New-vs-existing customer + Instagram-sourced lead capture

The Meta webhook already auto-creates a social-guest `Customer` with
`acquisition_source=INSTAGRAM` for unknown senders. The agent asks whether the
person is new; for new leads it collects name + phone + email via
`capture_lead_info`, which fleshes out the record and flips
`is_social_guest=False` (promoting them to a real Instagram-sourced lead). It
never overwrites an existing phone/email and never reads existing account data.

### 4. Booking confirmation routing

Instagram bookings use `source='instagram_ai'`. The appointment post-save
signal SKIPS the SMS confirmation for that source (social guests have no phone /
SMS opt-in, and SMS-confirming an Instagram booking is the wrong channel). The
agent confirms **in-channel** via DM at booking time, including the service +
date/time.

### 5. No client-side 24h reply-window block

Meta's policy governs send eligibility; tools like ManyChat message beyond 24h
via human-agent / message-tag mechanisms. We removed the client-side 24h
pre-check from both the AI agent path and the staff manual-reply view
(2026-06). If Meta rejects a late send, `send_instagram_dm` surfaces the error;
we no longer block the attempt ourselves. (The agent only ever replies
immediately after an inbound, so it is always within any window regardless.)

### 6. Gating + kill switches

- Requires **both** `F_AI_INBOX` (Pro+) and `F_SOCIAL_INTEGRATIONS`
  (grandfathered-only, pending Meta App Review) — demo has both.
- `AIConfig.instagram_enabled` is a separate switch from SMS `enabled`.
- `AIConfig.instagram_test_mode` + `instagram_test_username` sandbox the agent
  to a single IG handle until go-live.
- `AIConfig.platform_disabled_at` (the shared platform-admin global kill switch)
  blocks Instagram dispatch too.
- Shared daily send cap + per-conversation 5s reply lock.

## Consequences

- A customer can have two independent AI conversations (one per channel); they
  merge only when staff merge the social-guest into a real customer record.
- `EscalationAlert`/`AIConversation` now carry channel, so the dashboard
  escalation notifier deep-links Instagram escalations to `/social?thread=` and
  SMS to `/inbox?customer=`.
- The outbound PII scanner (`services/scrub.outbound_pii_check`) still runs on
  every Instagram reply as defense-in-depth.
- If Meta webhook latency becomes an issue under load, dispatch moves to
  SQS+ECS — a one-file change in `services/dispatch.py`.

## Related
- ADR 0032 — AI SMS agent (the brain this reuses)
- ADR 0027 — Meta Instagram DM integration (the transport this rides on)
- `apps/ai_inbox/README.md` — operator runbook
