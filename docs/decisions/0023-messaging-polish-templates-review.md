# ADR 0023 — Messaging polish: saved replies, editable templates, review-request automation

## Status

Accepted (2026-05-15).

## Context

ADR 0022 shipped the customer SMS / MMS inbox v1 — operators could see threads, reply manually, and configure the popout window. After running it against the demo tenant, three gaps surfaced before onboarding the first real spa:

1. **Operators retype the same answers all day.** "Where are you located?" / "Are you open Sunday?" / "Do I need to wash off makeup?" — same question 30× a week, same answer typed from scratch each time. Every comparable CRM (Boulevard, Mindbody, Fresha) ships canned-reply templates as a baseline feature.
2. **Automated SMS bodies (booking confirmation + 24h reminder) were hard-coded** in `apps.appointments.sms`. Spas have their own voice; a generic "Hi {first_name}, your appointment is confirmed for {time}" feels like a robot wrote it.
3. **Post-appointment review-request SMS was missing entirely.** Plan had this in Phase 3C, but the first real tenant needs it on day one — their growth depends on Google reviews. We pulled it forward.
4. **Automated SMS didn't appear in the inbox thread.** From the customer's phone there's one thread per spa-phone-pair; the automated confirmation and the operator's manual reply are interleaved on their screen. The operator only seeing the manual half is a truthfulness gap that creates surprises ("why is the customer asking about an appointment I haven't confirmed?").

This ADR captures all four pieces because they ship together and reinforce each other.

## Decision

### 1. `SavedReply` model — tenant-shared canned templates

New `apps.messaging.SavedReply` model:

- Tenant-scoped via the standard `TenantedModel` base.
- Unique `(tenant, name)` so the picker doesn't have two "Address" entries.
- `body` capped at 1600 chars (same as the manual send endpoint — both feed the same outbound path).
- `created_by` FK to User (nullable so the row outlives the author).

Visibility is **tenant-wide**, not per-user. Real spas hand threads off between front-desk staff; the canonical answer to "where are you located?" can't depend on which receptionist is on shift. If individual-private templates ever become a real ask we add an `owner` FK + a `visibility` choice — not pre-built because YAGNI.

Body content is **not** PHI: these are brand-voice templates ("our address is …"), not patient-specific content. The PHI substitution still happens at send-time when the operator types the customer-specific personalisation into the composer. The mutation audit log captures who changed the address reply (a normal change-management concern), but reads aren't audit-logged (would clutter the trail with template-pulls).

UI integration:
- Composer gets a `MessageSquareQuote` icon button → opens a popover with search + reply list.
- Click a reply → inserts at cursor (or replaces selection) in the textarea. Smart whitespace handling (no double-spaces when inserting adjacent to existing text).
- Foot-rail link in the thread list opens the full **Manage** dialog (full CRUD, edit-in-place).

### 2. Editable automated SMS templates — tenant fields on `Tenant`

Three new template fields plus three settings fields on `Tenant`:

```
confirmation_sms_template   — TextField, blank = default
reminder_sms_template       — TextField, blank = default
review_request_sms_template — TextField, blank = default
review_request_enabled      — Boolean, default False
review_request_hours_after  — PositiveSmallInteger, default 24
google_review_url           — URLField, blank
```

A `render_template(template, *, appointment, review_url)` helper does literal `str.replace` substitution on a fixed vocabulary of tokens:

- `{{first_name}}` — customer first name
- `{{spa_name}}` — tenant name
- `{{appointment_time}}` — formatted local time
- `{{review_url}}` — review template only

**No templating engine.** Operator-typed text never executes any Python expression — `str.replace` is the boundary. Tokens we don't recognise pass through verbatim so a tenant who types `{{my_typo}}` sees their typo and can fix it (vs. a silent empty substitution that would be much harder to debug).

Tenant-singleton settings live as fields on the `Tenant` row itself, exposed via a `GET / PATCH /api/messaging/automated-templates/` endpoint. No separate model — these are one-of-each-per-tenant settings, not records you list. The endpoint GET surfaces the platform defaults read-only so the UI can show "this is what would be sent if I leave the field blank" + offer a "reset to default" link.

UI: a three-tab settings dialog (Confirmation / Reminder / Review request) reachable from the inbox foot-rail. Each tab shows the textarea, the available tokens as `<code>` chips, character count, and a "reset to default" link when customised. The Review tab additionally exposes the enable toggle + Google review URL field + hours-after input.

### 3. Review-request automation — new transactional SMS surface

New `send_review_request_sms(appointment)` mirrors the existing `send_confirmation_sms` / `send_reminder_sms` posture:

- Gates beyond the shared consent check: `tenant.review_request_enabled` AND `tenant.google_review_url` set AND appointment in `COMPLETED` status.
- Idempotent on `Appointment.review_request_sms_sent_at` (new field).
- Same audit-log shape as the other two paths.
- Renders the tenant's template (or default) with `{{review_url}}` substituted.

Trigger: `manage.py send_review_requests` management command. Iterates tenants where `review_request_enabled=True` AND `google_review_url != ''`, then their completed appointments whose `completed_at` falls within `tenant.review_request_hours_after ± slop` ago and haven't yet been sent. Cron-invoked every ~30 minutes alongside the existing reminder runner.

**Why explicit opt-in by default**: shipping `review_request_enabled = True` everywhere would mean any tenant whose `completed_at` flows through suddenly starts texting customers — including spas that don't have a Google Business Profile, don't want the review SMS at all, or have customers who'd find it presumptuous. Opt-in keeps the surprise blast radius at zero.

**Why Google review URL specifically**: per AskUserQuestion exchange, Google is what Mindbody / Boulevard / Fresha default to because that's where local-search customers convert. Future tenants who want Yelp / custom URLs can paste theirs into the same field — the field is just a URL, the "Google" framing is about discovery + setup help.

### 4. Mirror automated SMS into the inbox thread

The transactional-SMS path lives in `apps.appointments.sms` (distinct consent semantics, no quiet-hours, no unsubscribe token). But the **customer** experiences ALL these messages as one thread on their phone — there's no separation at the SMS layer. The operator's inbox view was missing half the conversation.

Fix: a new `Message.kind` field with choices `MANUAL` (default) | `CONFIRMATION` | `REMINDER` | `REVIEW_REQUEST`. The three automated senders call a shared `_mirror_automated_to_inbox(appointment, kind, body, sid)` helper that writes a `Message` row tagged with the appropriate kind alongside the existing audit-log entry and Appointment-row stamp.

Existing rows default to `MANUAL` via the migration. Idempotency is enforced at the caller (each `send_*` function won't be invoked twice for the same appointment-kind combination), so the mirror is just a row-write — no second idempotency check needed.

UI: the conversation pane renders an `Auto · Confirmation` / `Auto · Reminder` / `Auto · Review request` chip above each automated bubble, using a system-toned background (not the bright accent colour reserved for operator-typed messages). Visually identifies what the customer saw without distracting from manual replies.

This effectively gives the operator the per-customer log of all automated messages the user asked for — every Message row IS a log entry, queryable / scrollable in the thread, persisted indefinitely, and audit-logged on read.

## Consequences

### Good

- Operators reply faster with consistent brand voice (saved replies).
- Tenants can customise their voice (editable templates) without engineering touching the code per spa.
- Review-request automation drives Google reviews — the single most-requested marketing surface in pre-sales calls.
- Threads now show the full truth — confirmation + reminder + review interleaved with manual replies. No more "where's the confirmation?" surprises during operator handoffs.

### Bad / Deferred

- **Tokens are fixed**, not extensible per tenant. If a spa wants `{{provider_first_name}}` we add it to the render helper. Per-tenant token registries are over-engineering for v1.
- **No per-thread filter** ("show me only automated", "show me only manual") — every message lives in one timeline. Acceptable: each message is already badged, and operators almost always want the full chronological view.
- **No A/B testing of templates** — one template per tenant per kind. Phase 3C polish if it becomes a real ask.
- **Saved replies are tenant-shared only.** Per-user "favourites" or "private" templates can land later if staff request them.
- **Review-request cron isn't yet scheduled.** Manual `manage.py send_review_requests` works in dev; production EventBridge → ECS RunTask job to invoke every 30 min ships with the broader cron infra (alongside the existing reminder runner that's already on this list).

### Acknowledged

- Mirror logic doubles the database writes for every automated send (one Appointment row update + one Message row insert + one AuditLog insert). Acceptable at expected scale — the bottleneck is Twilio rate limits, not Postgres throughput.
- The `Message.kind` discriminator is the right shape for the eventual social-DM path (Phase 3F): same Message model with a `channel` field (sms / instagram / facebook / whatsapp) AND a `kind` for what triggered the send. Cleanly extensible.

## Alternatives considered

### One unified `MessageTemplate` table (saved replies + automated templates in one model)

Considered. Rejected because the two surfaces have **different invariants**: saved replies have a tenant-scoped unique `name`, support multiple per tenant, and are operator-pasted; automated templates are exactly one of each kind per tenant, support a fixed token vocabulary, and feed the cron sender. Forcing them into one model would mean a `kind` discriminator + nullable columns + conditional validation — more code, less clarity. Two models is the cleaner shape.

### Mirror via the existing Twilio status callback rather than at send-time

Considered: rely on Twilio's delivery webhook to be the trigger that creates the inbox row. Rejected because the status callback runs async — the row wouldn't exist until Twilio's webhook fires, which could be seconds-to-minutes after the send. Operators reload the inbox immediately after triggering a manual confirmation (or watching the thread when a reminder is due) and would see a gap. Mirroring at send-time is synchronous: the row exists by the time the function returns.

### Per-tenant token registry (allow tenants to define their own tokens)

Considered for the editable-templates path. Rejected: the template render runs server-side at SMS send time and a per-tenant token registry would mean variable resolution becomes config-driven, which is a much larger trust-boundary question (what data can a token reference? PHI? Other customers? Cross-tenant?). The fixed vocabulary is safer and covers the realistic use cases (first name, spa name, time, review URL). Phase 3F polish if a customer asks for a specific token we haven't shipped.
