# ADR 0022 — Customer messaging inbox (two-way SMS / MMS)

## Status

Accepted (2026-05-15).

## Context

ADR 0021 shipped one-way transactional SMS (booking confirmation + 24h reminder). Customers immediately start texting back — "can I move to 4pm?", "do I need to wash off makeup?", "running 10 min late." Without an inbox, those replies land in the void: Twilio captures them but there's no UI to surface them to the front desk.

Every comparable CRM (Mindbody, Boulevard, Fresha, Square Appointments) ships a unified inbox. The user explicitly asked for SMS / MMS now, and a **separate** menu surface for social DMs (Instagram, Facebook, WhatsApp) later. That separation matters: different channels have different consent semantics, different rate limits, different opt-out vocabularies (`STOP` for SMS, "block" for Meta DMs), and different PHI postures (Meta's terms forbid sending PHI through their APIs even though carriers will accept it via SMS under our BAA).

## Decision

### 1. New `apps.messaging` app — distinct from marketing & appointments

Two existing SMS surfaces already live in the codebase:

- `apps.marketing.sender` — bulk promotional SMS, audience-driven, TCPA quiet-hours-gated, opt-in via `sms_marketing_opt_in`.
- `apps.appointments.sms` — transactional reminders, healthcare-exception under TCPA, opt-in via `sms_opt_in`.

Customer-initiated conversations (this ADR) are a **third** surface with its own semantics:

- The customer initiates by texting our toll-free; consent is implicit (they texted us).
- Operator replies are gated on `sms_opt_in = True` AND a phone-on-file (same gate as transactional SMS — the customer who texted us is by definition reachable, but `sms_opt_in` reflects active consent on file).
- No quiet-hours block on operator replies (the customer is in the conversation; carrier-level STOP is the opt-out path).
- No `MarketingSendLog`: every message lives as a `Message` row on the new model.

Putting these alongside campaigns or appointments in `apps.marketing` or `apps.appointments` would have meant chasing every "is this a marketing send?" branch through the dispatch code. Keeping them separate keeps each app's invariants legible.

### 2. Model — one row per message, threading derived

`apps.messaging.Message`:

- `customer` FK (PROTECT — message history outlives a customer soft-delete; audit trail is non-negotiable for PHI).
- `direction` — `OUTBOUND` / `INBOUND`.
- `body` — plaintext (encrypted at rest via the RDS-storage KMS key like every other PHI surface; we don't add column-level encryption because that breaks search/audit).
- `status` — Twilio lifecycle state (`queued / sent / delivered / failed / received`).
- `provider_message_id` — Twilio Message SID, indexed for status-callback lookup AND inbound idempotency.
- `from_number` / `to_number` — E.164, both stored so the audit trail survives a customer phone change.
- `media_urls` — newline-separated list of MMS attachment URLs hosted by Twilio. V1 stores Twilio's URLs verbatim; future polish copies to our own S3 + signs (Twilio retains for ~24h).
- `sent_by` — User who composed (outbound only).
- `read_at` — when the operator marked the thread read; nullable.

No separate `Conversation` entity: each customer can only have one ongoing SMS thread with the spa (it's their phone number), so threading is derived from `(tenant_id, customer_id)` ordered by `created_at`. Indexes match the two hot queries: thread fetch + inbox list.

### 3. Per-tenant toll-free numbers (shipped in c9d5c3d)

The marketing-SMS work originally assumed a single platform-wide `TWILIO_FROM_NUMBER`. ADR 0021's per-tenant change moved every send path to `_resolve_from_number(tenant)` which prefers `Tenant.twilio_from_number` and falls back to the platform default. The inbox uses the same helper so a tenant's customers see the same toll-free for transactional, marketing, and conversational SMS — confusion-avoidance + brand consistency.

Inbound matching: the Twilio webhook's `To` header identifies the tenant by lookup on `Tenant.twilio_from_number`, and `From` identifies the customer by normalised-E.164 phone match scoped to that tenant. The `_normalize_e164` helper handles operator-entered phones in `(555) 123-4567` / `5551234567` / `+15551234567` form.

### 4. Twilio inbound webhook — same posture as the status callback

`POST /api/messaging/twilio/incoming/` mirrors `apps.marketing.views_public.TwilioStatusCallbackView`:

- `AllowAny` permission (Twilio doesn't carry a session cookie).
- X-Twilio-Signature verified via `RequestValidator` over the URL + form params.
- `TWILIO_TEST_MODE=True` bypasses the signature check for unit tests.
- Returns 200 even for unmatched tenant / unmatched customer / duplicate SID, so Twilio doesn't retry (retry storms are the most common Twilio webhook pitfall).
- Empty `<Response/>` TwiML — no auto-reply. Operator-typed replies are the only outbound; "auto-replies" are a marketing surface, not an inbox.

STOP / START handling: Twilio's account-level **Advanced Opt-Out** handles the carrier side automatically — STOP short-circuits at Twilio, fires a carrier-mandated confirmation, and flags the number as opted-out on our account. We never see the STOP webhook. The single-source-of-truth for the "is this customer reachable?" question stays in Twilio, not in our DB — flipping `customer.sms_opt_in` on STOP would create two sources of truth that drift.

### 5. Operator endpoints — minimal surface

Four authenticated endpoints (`IsAuthenticated`):

- `GET /api/messaging/threads/` — inbox list. One row per customer with messaging activity. Each row carries the latest message preview + unread inbound count for the left rail.
- `GET /api/messaging/conversations/<customer_id>/` — full thread, chronological. Audit-logged.
- `POST /api/messaging/conversations/<customer_id>/send/` — operator sends. Gated on phone + `sms_opt_in`. Persists row first (so a Twilio failure still leaves the thread showing the attempt + FAILED state for context). Audit-logged with redacted metadata (`recipient_last4`, `body_length` — never the full phone or body).
- `POST /api/messaging/conversations/<customer_id>/mark-read/` — flips `read_at = now` on every inbound message in this thread. Fires automatically when the operator opens the thread.

The send action uses the same `apps.appointments.sms.send_sms(tenant, to, body)` helper as transactional confirmations + reminders, keeping the per-tenant TFN resolution and Twilio error mapping in one place.

### 6. Frontend — three-pane inbox at `/messages`

Top-level sidebar entry (not buried under Calendar) because messaging is its own workflow. The page layout mirrors what Mindbody / Boulevard / Fresha use because front-desk staff already know the pattern:

- Left rail: thread list with search + unread badges.
- Right: conversation header (client name → deep-link to `/clients/<id>` for fuller context), scrollback with chat bubbles, compose box.
- Selected thread persists in the URL (`?c=<customer_id>`) so the calendar right-rail can deep-link.

The calendar right-rail "Messages" tool tile previously rendered a "coming soon" placeholder. Now it renders a preview of the top-5 threads with unread counts + an "Open inbox" button that deep-links to `/messages`. Same data hook (`useThreads`) as the full page — React Query dedupes the request.

A separate top-level `/social` route is wired into the sidebar as a `comingSoon: true` placeholder for the eventual Instagram / Facebook / WhatsApp inbox (Phase 3F). Keeping it separate at the route level avoids forking the SMS UI mid-implementation when those channels land.

Polling at 15s — not aggressive; front-desk staff don't expect sub-second freshness, and the page already auto-marks-read on thread open. SSE / websocket upgrade is deferred until either DM channels land (which need lower latency) or operators ask for it.

### 7. HIPAA + SOC 2 posture

PHI: every SMS body is PHI in the medspa context — they routinely reference appointments, services, treatments, and identifying details. Posture:

- **At rest:** plaintext in Postgres, encrypted via RDS's storage-encryption KMS key (same posture as `Customer.medical_history`, `chart_note.body`, etc.). Column-level encryption would break search + audit + admin.
- **In transit:** TLS 1.2+ everywhere (ALB termination → ECS internal hop is over private subnets; Twilio's API is HTTPS-only).
- **Audit logging:** every operator read (threads list + conversation detail) and every operator write (send + mark-read) writes an `AuditLog` row with redacted metadata. The `body` itself is never logged; only `body_length` for diagnostic purposes. Recipient phone is captured as `recipient_last4` only (per the redaction convention in `apps.appointments.sms._phone_redact`).
- **BAA coverage:** Twilio has a HIPAA BAA in place at the account level; this is a precondition of using SMS/MMS for PHI at all.
- **Access control:** `IsAuthenticated` only in v1. A future tighten-to-`VIEW_CLIENT_PHI` polish would mirror the chart-notes posture (ADR 0017). Documented as Phase 1 polish.
- **Retention:** unbounded for v1 — message history is part of the patient record and is bound by the same retention policy as other PHI (a HIPAA-required minimum of 6 years; we have no policy yet that explicitly trims past that).

SOC 2: change captured here (CC8.1 — change management). All endpoints land in the existing audit trail. No new third-party services beyond the already-signed Twilio BAA.

## Consequences

### Good

- Operators can finally reply to customer texts without resorting to their personal phone — the most common feature gap raised in customer feedback after appointment SMS shipped.
- Per-tenant TFN architecture unlocked in ADR 0021 carries through cleanly: same number for transactional, marketing, and conversational SMS.
- Foundation for the social-DM unified inbox: the same Message model can later carry a `channel` discriminator when IG/FB/WA land, with channel-specific webhook handlers writing into the same table.

### Bad / Deferred

- **No real-time updates.** 15s polling on both threads list + open conversation. Acceptable for v1; visible latency only on conversations being actively typed-into from both sides. Upgrade path: SSE on the conversation detail endpoint.
- **MMS attachments are Twilio-hosted.** Twilio retains for ~24h. After that the URLs return 404. Acceptable for the first weeks of operation; addressed by a future "copy MMS to tenant-scoped S3 + sign URLs" job (Phase 3F polish).
- **No quick-reply templates.** Every send is typed from scratch. Boulevard / Fresha both ship templates; we'll add when an operator asks.
- **No outbound-from-customer-detail action yet.** v1 requires the operator to land on `/messages` first. A "Message" button on `/clients/<id>` that opens the thread is a small follow-up.
- **`IsAuthenticated` only — no PHI-view gate.** Per-role tightening is a Phase 1 polish item (matching ADR 0017's posture for chart notes). All staff with active sessions can read every message.

### Acknowledged

- Inbound messages from unknown phones don't create rows (returns 200, logs the attempt). If an operator wants to start a thread with someone who texted them anonymously, they have to create the Customer first, then the next inbound matches. This is intentional: auto-creating "unknown sender" Customers would clutter the CRM with one-off prospects who happened to text the spa's number.
- Polling burns ~4 req/min/operator while `/messages` is open. At an estimated 10 concurrent operators per tenant, that's well within RDS / ALB headroom — but noted so we don't forget it when traffic grows.

## Alternatives considered

### A single unified-Message model with a `channel` discriminator from day one

Tempting because it scales to IG / FB / WA. Rejected for v1: those channels have non-trivial differences (Meta's 24-hour messaging window, link-shortener requirements, attachment formats, message-template approval for outbound-out-of-window) and modelling the union prematurely would force compromises on the SMS schema. We can add a `channel` field as a non-null default + new TextChoices when DM integration lands; the migration is straightforward.

### Putting the inbox under the Calendar surface only

Rejected because messaging is its own workflow — front-desk staff often work from the inbox without the calendar open (e.g. catching up on overnight texts before opening). Top-level navigation is correct. The calendar right-rail preview is a complementary affordance, not the primary entry point.

### Auto-replying to inbound with TwiML

Twilio supports returning TwiML on the webhook to send a synchronous reply ("Got your message, we'll be with you shortly"). Rejected because the operator is the one composing replies — an auto-reply would either repeat what the operator types or fight with it. STOP/START handling lives at the Twilio account level so we don't need TwiML to handle opt-out either.
