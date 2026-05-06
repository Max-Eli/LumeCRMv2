# ADR 0016 — Email and SMS marketing (Phase 1L, session 1)

## Status

Accepted (2026-05-05 — Phase 1L session 1; written at design time
per the discipline locked in for compliance-heavy surfaces.
Sessions 2+ will append updates as scope expands.)

## Context

Every spa we sell to expects three things from a CRM marketing
surface:

1. **Birthday + win-back automations** — "Hi Jane, you haven't been
   in for 90 days, here's $25 off."
2. **Promo blasts** — "Mother's Day weekend: 20% off all facials."
3. **Treatment-plan nudges** — "Your last filler was 5 months ago;
   typical refresh is 6."

Phase 1F transactional plumbing (SMS reminders, booking
confirmations) is a different problem — those are auto-triggered,
tied to a specific appointment, and consent is implicit in booking.
Marketing is **operator-composed, segmentable, and consent-explicit
per channel.** Conflating the two would be cheaper to build but
would muddle the consent + opt-out semantics in ways that get fines
written.

This ADR covers session 1 of Phase 1L: the **data model**,
**consent + suppression architecture**, and the **Audience surface**
that lets operators build saved customer segments. Templates,
Campaigns, and the actual send wiring land in sessions 2+. The
heavy compliance scaffolding lives here so all later session
work is bounded by it.

### Compliance landscape (the actual reason this is a separate
phase from 1F)

**TCPA (Telephone Consumer Protection Act)** — federal law governing
SMS to US recipients:

- Marketing SMS requires **prior express written consent**. A
  default-true checkbox on the customer profile is NOT consent.
  Consent must be a deliberate, affirmative act tied to clear
  disclosure of what the customer is opting into.
- **Quiet hours**: marketing SMS prohibited 9pm – 8am in the
  recipient's local timezone. Federal floor; some states tighter.
- **STOP keyword**: STOP / UNSUB / END / CANCEL / QUIT must
  immediately suppress the recipient. Twilio handles inbound STOP
  routing per-number; we have to honor the suppression on next send.
- **Identification**: every marketing SMS must identify the sender
  (the spa, not Lumè).
- **Penalties**: $500 per violation; $1,500 if willful.
  **Per-message**, and aggregated as class actions. Real fines have
  hit $40M+ for repeat offenders.

**CAN-SPAM** — federal law governing commercial email:

- **Truthful From + Subject lines**. Misleading the recipient
  about who sent or what's inside is a violation.
- **Visible unsubscribe link** in every commercial email; one-click
  honored within 10 business days.
- **Physical postal address** of the sender in every email.
- **Penalties**: up to $51,744 per email.

**Twilio HIPAA Eligibility + 10DLC**:

- Marketing SMS in the US requires the sending number to be
  registered with The Campaign Registry (TCR) under a 10DLC
  campaign. Unregistered numbers get throttled or outright blocked
  by carriers.
- Twilio has a **separate "HIPAA Eligibility" program** for
  customers handling PHI; standard Twilio is NOT HIPAA-covered.
  Even when marketing copy itself doesn't carry PHI, the
  **fact-of-sending** combined with appointment-context can be
  PHI-equivalent.

### HIPAA framing

Marketing tokens (`{{first_name}}`, `{{last_appointment_service}}`)
expand to customer-bound values at send time. Some are PHI by
HIPAA's definition (treatment received), some aren't (first name).
This ADR locks down which tokens are allowed and rejects clinical
fields outright in the template editor.

Audit posture: every send writes a per-customer `MarketingSendLog`
row with the channel, recipient identifier (email domain only for
email per ADR 0012; phone last-4 for SMS), and the campaign that
triggered it. The actual content body lives on the Campaign + the
rendered-at-send-time payload in the provider's send queue, NOT
duplicated into the audit log.

## Decision

**Build Phase 1L as a dedicated `apps.marketing` Django app with
four models (`Audience`, `MarketingTemplate`, `Campaign`,
`MarketingSendLog`). Add four new fields to `Customer` for
marketing-specific opt-in + suppression — separate from the
existing `email_opt_in` / `sms_opt_in` which are transactional
defaults. New marketing fields default to FALSE (consent-first).
Suppression survives all re-imports and overrides explicit opt-in.
Permission gating: `SEND_MARKETING_CAMPAIGN` for sends,
`VIEW_AUDIENCE_SEGMENTS` for read. Both already in the catalog.**

### New Customer fields

```python
class Customer(TenantedModel):
    # Existing (transactional). Default True.
    email_opt_in = BooleanField(default=True)
    sms_opt_in = BooleanField(default=True)

    # NEW — marketing-specific. Default FALSE per TCPA/CAN-SPAM.
    email_marketing_opt_in = BooleanField(default=False)
    sms_marketing_opt_in = BooleanField(default=False)
    email_marketing_consent_at = DateTimeField(null=True, blank=True)
    sms_marketing_consent_at = DateTimeField(null=True, blank=True)
    email_marketing_consent_source = CharField(max_length=50, blank=True, default='')
    sms_marketing_consent_source = CharField(max_length=50, blank=True, default='')
    # Common consent_source values:
    #   'booking_form'  — opted in at booking-page checkbox
    #   'manual_entry'  — staff added manually with verbal/written consent
    #   'import'        — migrated from prior CRM with consent on file
    # The audit log captures the user-id of staff who recorded
    # 'manual_entry' or 'import' so disputed consent has provenance.

    # Suppression. Once set, this OVERRIDES explicit opt-in. The
    # suppression list survives re-imports + profile-form edits.
    # The `_at` timestamps are the legal record; the `_source`
    # captures HOW the customer opted out so we can debug
    # disputed sends.
    email_marketing_suppressed_at = DateTimeField(null=True, blank=True)
    sms_marketing_suppressed_at = DateTimeField(null=True, blank=True)
    email_marketing_suppression_source = CharField(max_length=50, blank=True, default='')
    sms_marketing_suppression_source = CharField(max_length=50, blank=True, default='')
    # Common suppression_source values:
    #   'unsubscribe_link'   — clicked link in an email
    #   'reply_stop'         — replied STOP / UNSUB / END / QUIT
    #   'manual'             — staff marked them opted-out
    #   'bounce'             — hard bounce; can never re-mail
    #   'complaint'          — marked as spam (SES complaint webhook)
```

The send-eligibility check is therefore:

```python
def can_email_market(customer) -> bool:
    return (
        customer.email_marketing_opt_in
        and customer.email_marketing_suppressed_at is None
        and bool(customer.email)
    )
```

Same shape for SMS. **Both conditions must be true.** Suppression
beats opt-in; that's the legally-defensible posture.

### `Audience` model

A saved customer segment defined by a filter spec. The spec is
JSON for forward-compat (we add filter dimensions over time
without schema changes), but the editor + executor only allow a
known set of dimensions per the validator.

```python
class Audience(TenantedModel):
    name = CharField(max_length=100)                   # operator-named
    description = CharField(max_length=200, blank=True)

    # Filter spec — JSON shape validated by serializer.
    # Allowed dimensions in v1:
    #   tag_ids: [int]                  # has any of these CustomerTag rows
    #   last_visit_within_days: int     # had appt in last N days
    #   last_visit_more_than_days: int  # NO appt in last N days (win-back)
    #   email_marketing_opt_in: bool    # respect channel-specific consent
    #   sms_marketing_opt_in: bool
    #   created_within_days: int        # signed up recently
    filter_spec = JSONField(default=dict)

    # Cached count + cached_at for the "X members" UI label.
    # Recompute on demand (live-count endpoint) so the operator
    # sees real-time counts when editing; cache so list pages
    # don't N+1.
    last_member_count = PositiveIntegerField(default=0)
    last_counted_at = DateTimeField(null=True, blank=True)

    created_at, updated_at, created_by
```

Audiences are **read-only after a campaign references them** —
mutating an audience that's already been used to send campaigns
would muddy the audit trail of who-was-sent-what. This is enforced
in the serializer's update path: rejected with 400 if any
non-cancelled `Campaign` exists pointing at the audience. To
"edit" a used audience, the operator clones it.

### `MarketingTemplate` model

```python
class MarketingTemplate(TenantedModel):
    class Channel(TextChoices):
        EMAIL = 'email'
        SMS = 'sms'

    name = CharField(max_length=100)
    channel = CharField(choices=Channel.choices)
    subject = CharField(max_length=200, blank=True)  # email-only
    body = TextField()                               # mustache-style {{tokens}}
    is_active = BooleanField(default=True)

    created_at, updated_at, created_by
```

Personalization tokens follow Mustache-lite syntax: `{{first_name}}`,
`{{last_appointment_service}}`. The validator allows ONLY a
known-safe set:

| Token | Source | PHI? |
|---|---|---|
| `{{first_name}}` | Customer.first_name | No |
| `{{last_name}}` | Customer.last_name | No |
| `{{tenant_name}}` | Tenant.name | No |
| `{{last_appointment_date}}` | most recent Appointment.start_time | Borderline — combined with sender (the spa), implies a treatment relationship. Allowed because spa is the sender and the customer already knows about their appointments with them. |
| `{{last_appointment_service}}` | most recent Appointment.service.name | **CLINICAL — NOT ALLOWED in v1.** Token will be rejected by the validator. |
| `{{birthday_month}}` | Customer.date_of_birth | No |
| `{{unsubscribe_url}}` | system-generated | No |

Clinical service names exposed in marketing copy is a HIPAA
problem. We explicitly allow date-only references (the customer
knows when they last saw the spa) but block the diagnostic /
treatment specifics. This is a product principle, not a polish
item.

### `Campaign` model

```python
class Campaign(TenantedModel):
    class Status(TextChoices):
        DRAFT = 'draft'
        SCHEDULED = 'scheduled'    # waiting for scheduled_at
        SENDING = 'sending'        # worker actively dispatching
        SENT = 'sent'              # all dispatched (per-customer status in send log)
        CANCELLED = 'cancelled'    # operator cancelled before send

    name = CharField(max_length=100)
    audience = FK(Audience, PROTECT)
    template = FK(MarketingTemplate, PROTECT)
    channel = CharField(choices=Channel.choices)  # must match template.channel

    status = CharField(choices=Status.choices, default=DRAFT)
    scheduled_at = DateTimeField(null=True, blank=True)  # null for send-now
    started_at = DateTimeField(null=True, blank=True)
    completed_at = DateTimeField(null=True, blank=True)

    # Snapshot at send-time. Audience could change after send was
    # queued; we lock the recipient list at the moment the campaign
    # transitions DRAFT→SCHEDULED so a late audience edit doesn't
    # silently expand the blast.
    recipient_count_snapshot = PositiveIntegerField(default=0)

    # Per-channel send aggregates, populated by the worker.
    sent_count = PositiveIntegerField(default=0)
    failed_count = PositiveIntegerField(default=0)
    suppressed_count = PositiveIntegerField(default=0)  # opted out / no consent

    created_at, updated_at, created_by
```

Status transitions:

```
draft → scheduled (operator commits + recipient list snapshot taken)
draft → cancelled
scheduled → sending (worker picks up)
scheduled → cancelled (operator pulls back; allowed up until sending)
sending → sent (all per-customer dispatches complete)
```

`PROTECT` on `audience` + `template` so a deleted audience/template
that's been used in a campaign can't orphan the historical record.
The audit trail must survive retirement of the segment definition.

### `MarketingSendLog` model

Per-customer-per-campaign send record. The audit row that survives
forever; campaign aggregates roll up from these.

```python
class MarketingSendLog(TenantedModel):
    class Status(TextChoices):
        PENDING = 'pending'        # worker hasn't dispatched yet
        SENT = 'sent'              # provider acknowledged
        DELIVERED = 'delivered'    # provider webhook confirms delivery
        FAILED = 'failed'          # transient/permanent send failure
        SUPPRESSED = 'suppressed'  # gated by consent / suppression

    campaign = FK(Campaign, PROTECT)
    customer = FK(Customer, PROTECT)
    channel = CharField(choices=Channel.choices)

    # Recipient identifier — DOMAIN ONLY for email per ADR 0012;
    # last-4 for SMS. Full address lives on Customer; the send log
    # is a queryable surface that should not accumulate raw PII.
    recipient_email_domain = CharField(max_length=120, blank=True, default='')
    recipient_phone_last4 = CharField(max_length=4, blank=True, default='')

    status = CharField(choices=Status.choices, default=PENDING)
    suppression_reason = CharField(max_length=50, blank=True, default='')

    # Provider tracking ID (SES message-id, Twilio SID) so we can
    # correlate webhook events back to our send.
    provider_message_id = CharField(max_length=200, blank=True, default='')

    sent_at, delivered_at, failed_at
    failure_reason = CharField(max_length=500, blank=True, default='')

    created_at, updated_at
```

Per-customer rows let us answer "did Jane get the May 12 promo?"
in a single indexed lookup without scanning campaign aggregates
or rebuilding state from provider webhook history.

### Audience filter execution

The filter executor lives in `apps.marketing.audiences.execute_filter()`
and converts the JSON spec into a `Customer` queryset. Validation
in the serializer rejects unknown dimensions; the executor handles
known dimensions and returns the queryset (deferred for paginated
list, materialized for live count).

The "**suppression always wins**" rule lives in the executor — even
if an Audience filter doesn't include `email_marketing_opt_in:
True`, the executor adds it implicitly when the audience is
attached to an email campaign. Same for SMS. Operator can't
accidentally bypass consent by forgetting to check the box.

### Quiet hours + scheduling

Marketing SMS sends respect TCPA quiet hours: 8am – 9pm in the
RECIPIENT's local time, not the operator's. v1 stores the
recipient's timezone on a best-effort basis (defaulting to the
spa's location timezone if the customer's tz isn't otherwise known).
The send worker (Phase 1L session 3) checks this at dispatch
time and queues for the next allowed window if outside.

Email is exempt from federal quiet-hours requirements but
operationally the worker honors the same window — promotional
email at 3am converts worse than promotional email at 10am, so
this is a UX win on top of being safe.

### Why a dedicated app

Marketing is a heavy compliance surface and the data model is
substantial. Embedding it inside `apps.notifications` (where
Phase 1F transactional reminders will live) would muddle the
consent + opt-out semantics; a single `Notification` model
trying to cover both transactional and marketing always ends up
with confusing fields like "is_marketing" and inconsistent
default-opt-in semantics. Better to split:

- `apps.notifications` (Phase 1F) — transactional. Booking
  confirmations, reminders. Tied to a specific appointment.
  Implicit consent via the booking. No suppression list.
- `apps.marketing` (Phase 1L) — marketing. Audiences,
  templates, campaigns. Explicit consent. Suppression list.
  No appointment FK.

The two apps share the `MarketingSendLog`-equivalent shape but
DON'T share the model. Different tables, different access tiers,
different audit posture.

## Consequences

### What's covered today (Session 1 of 1L)

- Customer model carries marketing-specific consent + suppression
  fields with TCPA/CAN-SPAM-correct defaults (False).
- `Audience` model + CRUD API + live-count endpoint.
- `MarketingTemplate`, `Campaign`, `MarketingSendLog` models with
  migrations — APIs land in subsequent sessions but the schema is
  stable.
- Permission gating: `VIEW_AUDIENCE_SEGMENTS` for read,
  `SEND_MARKETING_CAMPAIGN` for writes that produce sends.
- Tenant-scoped throughout; cross-tenant resource references
  rejected.
- Audit log on every audience CRUD action.
- Frontend: top-level **Marketing** nav item + landing page +
  Audiences list/create/preview UI.

### What lands in Session 2 of 1L

- `MarketingTemplate` CRUD + UI (token validator, channel-aware
  preview, character-count for SMS, allowed-token list)
- Per-channel preview (render with a sample customer's data so
  the operator sees what gets dispatched)
- Token validation: clinical fields blocked outright.

### What lands in Session 3 of 1L

- `Campaign` create + schedule + cancel flows.
- Send worker (Celery beat for scheduled; Celery worker for
  dispatch).
- AWS SES integration with per-tenant verified from-domain.
- Twilio integration once HIPAA-eligibility approved + per-tenant
  10DLC registered.
- Webhooks for SES bounces + complaints, Twilio status callbacks
  + inbound STOP.
- Quiet-hours enforcement at dispatch time.
- Suppression-on-bounce + suppression-on-complaint auto-handlers.
- Customer-facing unsubscribe page (one-click + landing).

### What lands in Session 4 of 1L (polish)

- Automation triggers (birthday this month, no-visit-in-N-days)
  — replaces manual one-shot campaigns with rule-based triggers.
- Per-tenant from-domain DKIM/SPF/DMARC verification flow in the
  org settings.
- A/B testing — out of scope for v1, polish item.
- Per-campaign analytics (open rate, click rate, reply rate)
  — depends on SES open-tracking pixels + Twilio webhook
  ingestion.

### Out of scope permanently

- Drip / multi-step campaigns. Triggers fire one message; sequences
  are a 2.0 product.
- AI-generated copy. Operator authors templates; the system
  doesn't synthesize copy. (Token expansion only.)
- Patient self-service preference center. The booking page +
  customer profile both have opt-in toggles; a dedicated portal
  with granular topic-by-topic preferences is post-v1.

## See also

- [ADR 0001 — Multi-tenancy strategy](0001-multi-tenancy-strategy.md)
  for `TenantedModel`. All marketing models inherit it; cross-
  tenant queries impossible.
- [ADR 0003 — Permission model](0003-permission-model.md) for
  `SEND_MARKETING_CAMPAIGN` and `VIEW_AUDIENCE_SEGMENTS`. Both
  pre-existing in the catalog.
- [ADR 0004 — Audit logging](0004-audit-logging.md) for the
  shape of audit entries. Every marketing CRUD + send writes one.
- [ADR 0012 — Email infrastructure](0012-email-infrastructure-and-signed-form-copy.md)
  for the SES posture this ADR builds on.  Marketing campaigns
  use the same `EMAIL_BACKEND` swap; the per-tenant from-domain
  verification work in Session 3 of 1L is the missing piece.
