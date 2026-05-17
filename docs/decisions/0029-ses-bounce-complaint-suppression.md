# ADR 0029 — SES bounce + complaint suppression pipeline

## Status

Accepted (2026-05-17).

## Context

§4.55 of `PROJECT_PLAN.md` listed three SES launch-debt items we
committed to AWS in the production-access request as "within one
week of going live":

1. SES bounce/complaint → SNS pipeline + `EmailSuppression` model +
   send-path enforcement.
2. SES configuration set referenced on every outbound message —
   without it the SNS topic above receives nothing.
3. CloudWatch alarms on SES bounce rate (3% warn / 5% critical) —
   5% is where SES starts pausing accounts.

The risk if any of these are missing is concrete:

- **Bounce loop**: a permanently invalid address ingests through
  Zenoti migration or a typo at booking; we keep retrying;
  bounce rate climbs past 5%; SES suspends our entire sending
  identity; every tenant loses transactional + marketing email
  simultaneously.
- **Complaint loop**: a user marks a Lumè email as spam; without
  the SNS pipeline we never know; we keep sending; complaint
  rate climbs; same suspension outcome.
- **No alarms**: by the time we notice the suspension, deliverability
  has already collapsed and reputation rebuild takes weeks.

The marketing app shipped earlier with a `MarketingSendLog.Status
.SUPPRESSED` enum and a `suppression_reason` field referencing
`'suppressed_bounce'` / `'suppressed_complaint'` values — but the
table those should consult never existed. This ADR fills that gap.

## Decision

### 1. `EmailSuppression` model — platform-wide, not tenant-scoped

A new model in `apps.marketing.models`:

```
EmailSuppression
  email                 lowercased, indexed, unique
  reason                bounce_permanent | complaint | manual
  bounce_subtype        general | no-email | suppressed | on-account-suppression-list
                        (set when reason=bounce_permanent; SES vocab preserved)
  complaint_subtype     abuse | auth-failure | fraud | not-spam | other | virus
                        (set when reason=complaint; SES vocab preserved)
  first_seen_at         datetime
  last_seen_at          datetime         # bumped on repeat events
  event_count           int              # incremented on repeat events
  ses_message_id        string           # the original message that triggered first event
  raw_event             jsonb            # snapshot of the SNS payload (forensics)
  created_by            User FK nullable # set when manual; null otherwise
  notes                 text             # operator notes (manual additions)
```

**Why platform-wide and not per-tenant:** SES sender reputation lives
on the IP + sending identity (`mail.xn--lumcrm-5ua.com`), shared by
every tenant. A permanent bounce on tenant A's send means the address
is bad for everyone; a complaint on tenant A means the user marked
*Lumè* as spam, and continuing to send from any tenant erodes the
shared reputation pool. Tenant-scoping the suppression would let
tenant B re-send to an address tenant A already burned the
reputation for — wrong outcome.

A future per-tenant override (operator says "this customer cleared
the bounce, please reactivate for our spa only") would land as a
separate `EmailSuppressionOverride` table with a tenant FK, but is
deferred — not needed at launch.

### 2. `SuppressionCheckingSESBackend` — transparent recipient filter

A custom Django email backend in `apps.marketing.deliverability` that
subclasses `django_ses.SESBackend`:

```
class SuppressionCheckingSESBackend(SESBackend):
    def send_messages(self, email_messages):
        sendable = []
        for msg in email_messages:
            msg.to = [addr for addr in msg.to if not is_suppressed(addr)]
            msg.cc = [addr for addr in (msg.cc or []) if not is_suppressed(addr)]
            msg.bcc = [addr for addr in (msg.bcc or []) if not is_suppressed(addr)]
            if msg.to or msg.cc or msg.bcc:
                sendable.append(msg)
            else:
                logger.info('email.suppressed.all_recipients', ...)
        return super().send_messages(sendable)
```

**Why a backend wrapper instead of refactoring callsites:** there are
already 7 `EmailMultiAlternatives` callsites across portal, forms,
invoices, booking, tenants, and marketing. Refactoring each to call
a `lume_send_mail(...)` helper is achievable but invasive and easy
to forget on the next feature. A backend wrapper means every
existing AND future send through Django's mail subsystem is
suppression-aware with zero callsite churn. Defense in depth: the
marketing sender ALSO checks `is_suppressed()` up-front so it can
write a `MarketingSendLog.SUPPRESSED` audit row (the backend would
otherwise silently drop with only an info log).

### 3. `AWS_SES_CONFIGURATION_SET` — one global knob

`django-ses` reads `AWS_SES_CONFIGURATION_SET` from settings and
attaches the configuration set to every outbound SES SendEmail call
automatically. We set it once in `lume_crm/settings/prod.py`:

```
AWS_SES_CONFIGURATION_SET = env('AWS_SES_CONFIGURATION_SET', default=None)
```

Dev defaults to None (no config set in development; matches the
console / filebased EMAIL_BACKEND there). Prod env sets it to
`lume-ses-events`. Without this setting, none of the bounce /
complaint webhooks below would ever fire, because SES only emits
events for messages tagged with a configuration set.

### 4. SNS webhook receiver at `/api/aws/ses-events/`

A new `SnsEventReceiverView` in `apps.marketing.views_aws_ses`.
Public (no Django auth) — the security boundary is AWS's X.509
signature on every SNS message.

Two message types handled:

- **`SubscriptionConfirmation`**: when SNS first attaches to our
  endpoint, it sends this with a `SubscribeURL`. We GET the URL
  to confirm. Idempotent.
- **`Notification`**: contains the SES event in `Message` (a
  nested JSON-string). We parse `eventType` and dispatch:
  - `Bounce` → if `bounceType == 'Permanent'`, add every
    `bouncedRecipients[].emailAddress` to suppression.
    Transient bounces (mailbox full, server down) are logged but
    NOT suppressed — they may recover.
  - `Complaint` → suppress every `complainedRecipients[]
    .emailAddress` regardless of subtype. ISP-cooperative
    posture: a complaint is a binding "stop sending to me."
  - `Delivery` / `Send` / `Open` / `Click` → logged at info
    level for ops visibility, no DB writes (we have other
    audit trails for deliverability investigations).
  - Unknown `eventType` → logged + 200 OK (NEVER 4xx to AWS —
    same posture as ADR 0027 §3 for Meta webhooks).

**X.509 signature verification** — we verify every notification
against AWS's signing certificate using the algorithm in the SNS
docs:

1. Reject if `SigningCertURL` doesn't match
   `^https://sns\.[a-z0-9-]+\.amazonaws\.com/.*\.pem$` (prevents
   attacker-hosted cert spoofing).
2. Fetch + cache the cert (it changes ~yearly).
3. Reconstruct the canonical string-to-sign per AWS's spec.
4. RSA-SHA1 verify with the cert's public key against the
   base64-decoded `Signature`.
5. Reject if `Type`/`MessageId` claim doesn't match the body.

Implemented inline in `apps.marketing.deliverability.verify_sns_signature`
— ~50 lines, fully tested. Choosing inline over a third-party
package (`sns-message-validator`) because (a) this is security-critical
code we want to own end-to-end and (b) the algorithm is small and
stable.

### 5. CloudWatch alarms

Two alarms in Terraform, both on the SES configuration set's
`Reputation.BounceRate` and `Reputation.ComplaintRate` metrics:

- **Warn at 3% bounces / 0.1% complaints** — SNS topic the founder
  is subscribed to. Catch early so we have time to investigate.
- **Critical at 5% bounces / 0.3% complaints** — same SNS topic,
  but framed as "SES will pause us shortly." Pager / PagerDuty
  later; email today.

The 0.1% / 0.3% thresholds for complaints come from the same
AWS guidance that drives the 5% bounce ceiling.

### 6. Reactivation policy

- **Complaints are permanent.** A complaint == the user marked us
  as spam. We never auto-reactivate. A manual API exists for the
  case where the user explicitly contacts the spa to re-subscribe,
  but it requires `MANAGE_TENANT_SETTINGS` (owner) + a free-text
  reason + writes an audit log + sets `EmailSuppression.notes`
  to the reason.
- **Permanent bounces are permanent until evidence otherwise.** Same
  reactivation path — manual, owner-gated, audited.
- **Transient bounces are never added to the table.** They're logged;
  if a transient bounce becomes chronic, SES eventually escalates
  it to a `bounceType=Permanent, bounceSubType=Suppressed` event
  (SES's own suppression list), at which point we suppress.

## HIPAA + SOC 2 posture

- **`EmailSuppression.email` is stored full-form.** It's the lookup
  key; hashing would let suppression lookups stay fast but breaks
  the operator's ability to investigate "why didn't Jane get her
  appointment confirmation?" — operators need to find Jane's row.
- **`raw_event` JSON snapshots may carry full addresses.** SES
  payloads include the bounced/complained address; we keep them
  for forensics. Access to the model is gated by `MANAGE_TENANT
  _SETTINGS` (platform-level for now; per-tenant view if and when
  we need it).
- **Send logs continue to record domain-only** (`recipient_email
  _domain`) — the suppression table is the single place a full
  address is persisted in the email-audit-trail subsystem.
- **Audit log entries** on every suppression add (auto or manual),
  every reactivation, every send blocked by the backend. Metadata
  is `{reason, email_domain, source}` — domain not full address.
- **SOC 2 §CC7.2 — system monitoring** — the CloudWatch alarms are
  the audit evidence that bounce/complaint rates are continuously
  monitored.

## Out of scope (this ADR)

- **Per-tenant overrides** — see "platform-wide" rationale above.
  Land as `EmailSuppressionOverride` when a real tenant asks.
- **Twilio SMS suppression parity** — SMS opt-out via STOP keyword
  is a Twilio platform feature (auto-honored). A future ADR
  formalizes SMS suppression once the same shape of webhook
  ingestion is needed for SMS bounces.
- **Reputation-rebuild playbook** — runbook 23 (to write) covers
  the "we got suspended; here's the recovery path." This ADR
  prevents the suspension; the recovery path is a separate
  concern.
- **Per-tenant SES sending identity** — see §P2 in `PROJECT_PLAN
  .md`. When/if a tenant wants their own from-domain, sender
  reputation isolates per tenant and the platform-wide suppression
  model needs the `EmailSuppressionOverride` extension.

## Consequences

- Every outbound email is now policy-gated. The cost is one Postgres
  point-lookup per recipient per send (~100µs on the hot path).
- The 7 existing `EmailMultiAlternatives` callsites need zero
  changes today, and the same is true for any future callsite
  that uses Django's mail subsystem.
- `EMAIL_BACKEND` in prod swaps from `django_ses.SESBackend` to
  `apps.marketing.deliverability.SuppressionCheckingSESBackend`.
  Dev stays on console/filebased (no change).
- Once Terraform applies + the SNS subscription confirmation
  round-trips, SES will start publishing every send event to our
  endpoint. The webhook is idempotent (repeat events bump
  `event_count` + `last_seen_at`, never duplicate rows).
- A 30-day clean-DMARC + clean-bounce window is now visible in
  the same CloudWatch dashboard the alarms live on. We tighten
  DMARC from `quarantine` to `reject` after that window — also a
  §4.55 line.

## References

- AWS docs: [SES event publishing](https://docs.aws.amazon.com/ses/latest/dg/monitor-using-event-publishing.html),
  [SNS message signing](https://docs.aws.amazon.com/sns/latest/dg/sns-verify-signature-of-message.html),
  [SES sender reputation](https://docs.aws.amazon.com/ses/latest/dg/sending-resources.html).
- [ADR 0012 — Email infrastructure and signed-form copy](0012-email-infrastructure-and-signed-form-copy.md) — sets the SES BAA baseline.
- [ADR 0016 — Email + SMS marketing](0016-email-and-sms-marketing.md) — defines `MarketingSendLog` + the `suppression_reason` enum this ADR fulfils.
- [ADR 0027 — Meta Instagram DM integration](0027-meta-instagram-dm-integration.md) §3 — same "never 4xx to the provider" webhook posture borrowed here.
- `PROJECT_PLAN.md` §4.55 — the launch-debt list this ADR retires three items from.
- `docs/runbooks/20-prod-launch-checklist.md` §Email — checkboxes this ADR unblocks.
