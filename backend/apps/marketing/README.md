# apps.marketing

Email + SMS marketing campaigns. Distinct from `apps.notifications`
(Phase 1F transactional reminders) because marketing has fundamentally
different consent semantics: TCPA + CAN-SPAM require **explicit
opt-in per channel**, suppression must survive re-imports, and
every send is per-message audit-logged.

**Sessions shipped:**
- **Session 1** — data model (4 models), Audience CRUD with live
  per-channel count preview, suppression-always-wins consent gate.
- **Session 2** — `MarketingTemplate` CRUD with HIPAA + CAN-SPAM
  token validator + sample-render preview. `Campaign` CRUD +
  status flow (DRAFT → SCHEDULED → SENDING → SENT) + per-customer
  send-log read endpoint. `Automation` model + CRUD + trigger
  evaluator (birthday, no-visit-N-days, first-visit-anniversary).
  Public tokenized unsubscribe endpoint with one-click
  suppression. Frontend: top-level Marketing nav with Audiences,
  Templates, Campaigns, Automations + public unsubscribe page.
- **Session 3** — pending: send worker + AWS SES + Twilio
  HIPAA-eligible integration; webhooks for bounces / complaints
  / inbound STOP; quiet-hours enforcement at dispatch time.
- **Session 4** — pending: per-tenant from-domain DKIM/SPF/DMARC
  verification flow; per-campaign analytics (open, click, reply
  rates); automation scheduler (Celery beat).

## What's in here (Session 1)

- **[models.py](models.py)** — `Audience`, `MarketingTemplate`,
  `Campaign`, `MarketingSendLog`. Templates + Campaigns + SendLog
  models exist as of session 1 so future schema work doesn't
  require a migration; their APIs land in subsequent sessions.
- **[audiences.py](audiences.py)** — the filter executor.
  `validate_filter_spec()` rejects unknown dimensions at save time;
  `execute_filter(... apply_channel_consent=...)` returns a
  Customer queryset. The `apply_channel_consent` parameter is the
  load-bearing safety: when set to `'email'` or `'sms'`, the
  executor adds `*_marketing_opt_in=True` AND
  `*_marketing_suppressed_at__isnull=True` filters automatically,
  so the campaign worker can't accidentally bypass consent.
- **[serializers.py](serializers.py)** — `AudienceSerializer`
  (read + write; rejects filter mutations on used audiences),
  `AudienceCountSerializer` (preview response shape).
- **[permissions.py](permissions.py)** — `MarketingReadPermission`
  for `VIEW_AUDIENCE_SEGMENTS`, `MarketingWritePermission` adds
  `SEND_MARKETING_CAMPAIGN` for writes.
- **[views.py](views.py)** — `AudienceViewSet` with list / create
  / retrieve / update / destroy + `preview` action.
- **[urls.py](urls.py)** — `/api/marketing/audiences/`.
- **[tests.py](tests.py)** — 25 tests covering permission gating,
  filter spec validation, tenant scoping, audit log shape, the
  read-only-after-use rule, suppression-always-wins, and last-
  visit dimensions (recent + win-back + no-show-doesn't-count).

See:

- [ADR 0016 — Email + SMS marketing](../../../docs/decisions/0016-email-and-sms-marketing.md)
  for the full design rationale, TCPA + CAN-SPAM compliance posture,
  and intentional deferrals.

## Mental model

```
Audience (saved segment, JSON filter spec)
  ↓ snapshot at draft → scheduled
Campaign (audience × template × channel × schedule)
  ↓ worker dispatches per-customer
MarketingSendLog (per-customer-per-campaign audit row)
  ↓ provider webhooks update status (delivered / bounced / etc.)

Customer (carries marketing consent + suppression fields)
  ├── email_marketing_opt_in: bool      # default False (TCPA/CAN-SPAM)
  ├── sms_marketing_opt_in: bool        # default False
  ├── *_marketing_consent_at + source   # legal record of when + how
  ├── *_marketing_suppressed_at         # opt-out beats opt-in
  └── *_marketing_suppression_source    # 'unsubscribe_link', 'reply_stop', ...
```

Suppression-always-wins is enforced in the audience executor —
when `apply_channel_consent` is passed, the queryset cannot
include a suppressed customer, no matter what the spec says.
This is the load-bearing compliance gate.

## Compliance posture

### TCPA (SMS)

- Marketing SMS requires **explicit prior written consent**. Default
  `sms_marketing_opt_in=False`; flipped True only by deliberate
  customer action recorded with `consent_at` + `consent_source`.
- **STOP keyword** (STOP / UNSUB / END / QUIT) auto-suppresses on
  reply via Twilio's per-number routing → our webhook ingests the
  status callback and sets `sms_marketing_suppressed_at` (Session 3).
- **Quiet hours**: 8am – 9pm in the recipient's local time. Worker
  re-queues outside-window sends to the next allowed slot
  (Session 3).
- **10DLC registration**: each tenant must register a brand +
  campaign with The Campaign Registry before sending. Not a Lumè
  config; tenant + Twilio handle externally. Onboarding workflow
  in Session 3.

### CAN-SPAM (email)

- **Visible unsubscribe link** in every marketing email — Session 2
  template editor injects `{{unsubscribe_url}}` automatically;
  validator rejects emails without it.
- **Physical postal address** of the sender in every email — pulled
  from `Tenant.location.address_*` at render time.
- **Truthful From + Subject** — operator-authored; we don't
  inject misleading wrappers.
- **One-click unsubscribe handler** — public token-based endpoint
  (Session 3) that flips `email_marketing_suppressed_at` and
  records `'unsubscribe_link'` as the source.

### HIPAA

- **Token allowlist** in templates blocks clinical fields.
  `{{last_appointment_service}}` is rejected at save time because
  service names are PHI when paired with the spa as sender.
  `{{last_appointment_date}}` is allowed (less sensitive; the
  customer already knows about their visits).
- **Twilio HIPAA Eligibility** required before sending PHI-adjacent
  SMS. Standard Twilio is NOT HIPAA-covered.
- **Audit log** captures every send, every consent change, every
  suppression. Recipient identifier is domain-only for email
  (per ADR 0012) + last-4 for SMS — full PII lives on Customer,
  not the audit log.

## Building on this

## Session 3 deltas (send worker + always-on automations)

- **`sender.py`** — `dispatch_campaign(campaign)` (manual-trigger
  campaigns) + `fire_automation(automation)` (always-on, called
  by `fire_due_automations` cron). Both share `_dispatch_one()`
  which re-checks consent + writes the `MarketingSendLog` row.
  Stub mode (no SES/Twilio wired) writes rows with synthetic
  provider IDs so the audit trail flows end-to-end. Flipping the
  env vars (`EMAIL_BACKEND=django_ses.SESBackend`, Twilio
  credentials) is the only switch needed for real sends.
- **`management/commands/fire_due_automations.py`** — the daily
  Celery-beat-equivalent. Iterates active `Automation` rows and
  calls `fire_automation()` on each. Idempotent within a
  per-customer dedup window (default 365 days).
- **Booking-flow consent capture** — `apps/booking/services.py`
  now accepts `email_marketing_opt_in` / `sms_marketing_opt_in`
  kwargs and stamps `consent_at` + `consent_source='booking_form'`
  on the customer record when set. Both default False — the
  public booking page (`/book/<slug>/<service>/details`) renders
  unchecked checkboxes per TCPA + CAN-SPAM.
- **Operator-flip consent capture** — `CustomerDetailSerializer`
  stamps `consent_at` + `consent_source='manual'` when an operator
  flips an opt-in from False → True via the customer profile
  Marketing tab. Suppression metadata is read-only here; only
  the unsubscribe link + bounce ingest can flip it.
- **Customer marketing history endpoint** — `GET
  /api/marketing/customer-sends/?customer=<id>` returns the most
  recent 50 `MarketingSendLog` rows for the customer. Drives the
  customer profile Marketing tab's send history list.
- **`CampaignViewSet.dispatch_now`** — `POST
  /api/marketing/campaigns/<id>/dispatch/` triggers the worker
  synchronously. Manual operator action; production cron fires
  scheduled campaigns automatically.

## Frontend surfaces (Session 3)

- `/marketing/automations/` — list + create + edit + preview +
  fire automations.
- `/book/<slug>/<service>/details/` — opt-in checkboxes for
  email + SMS marketing, both default unchecked.
- `/clients/<id>?tab=marketing` — operator view of consent state
  per channel + suppression posture (read-only with timestamp +
  source) + send history (last 50, with status + reason).

When wiring SES (Session 3):

1. Verify the sending domain in SES (DNS records: SPF, DKIM, DMARC).
2. Sign the SES BAA in AWS Artifact.
3. Set `EMAIL_BACKEND=django_ses.SESBackend` + AWS keys in env.
4. Add SNS topic + Django webhook view for bounce + complaint
   ingestion — auto-suppress customers from these.
5. Marketing emails use the same Django mail API; the backend
   swap is transparent.

When wiring Twilio (Session 3):

1. Apply for Twilio HIPAA Eligibility (sales contact, days–weeks).
2. Sign Twilio BAA.
3. Per-tenant 10DLC brand + campaign registration via Twilio
   console + The Campaign Registry.
4. Provision phone numbers per tenant (or use a messaging service
   pool).
5. Wire the send worker to `twilio.Client.messages.create()`.
6. Twilio status callback webhook → updates `MarketingSendLog`
   delivery status.
7. Inbound STOP webhook → sets `sms_marketing_suppressed_at`.

When adding a new filter dimension (Session 2+):

1. Add `(validate, description)` to `DIMENSIONS` dict in
   `audiences.py`.
2. Add the filter logic in `execute_filter()`.
3. Add the dimension to `AudienceFilterSpec` in `lib/marketing.ts`.
4. Add a row to the create-audience UI in `audiences/new/page.tsx`.
5. Add a test exercising the new dimension end-to-end.
