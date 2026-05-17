"""Marketing data models — Phase 1L session 1.

Four models cover the marketing surface:

  - `Audience` — saved customer segment defined by a JSON filter
    spec. Operators name the segment, set the filter, and the
    list/create/preview UI shows live counts. Read-only after a
    Campaign references it (mutating a used audience would
    corrupt audit attribution).
  - `MarketingTemplate` — email or SMS template with mustache-style
    `{{tokens}}` for personalization. Token allowlist locks down
    which Customer fields are renderable; clinical fields are
    blocked outright per HIPAA discipline.
  - `Campaign` — audience × template × channel × schedule. Status
    machine: draft → scheduled → sending → sent (or → cancelled
    from draft / scheduled).
  - `MarketingSendLog` — per-customer-per-campaign send record.
    Aggregates roll up to Campaign; the row is the audit trail
    that survives forever.

The actual send work + provider wiring (SES, Twilio) lands in
session 3. Models are stable as of session 1 so UI work can
proceed in parallel.

See [ADR 0016 — Email + SMS marketing](../../../docs/decisions/0016-email-and-sms-marketing.md)
for the design rationale, TCPA + CAN-SPAM compliance posture, and
intentional deferrals.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.tenants.abstract_models import TenantedModel


class Channel(models.TextChoices):
    """Where a marketing message goes. Email vs SMS."""

    EMAIL = 'email', 'Email'
    SMS = 'sms', 'SMS'


# ── Audience ─────────────────────────────────────────────────────────


class Audience(TenantedModel):
    """A saved customer segment used to target campaigns.

    The filter spec is JSON for forward-compat — we add new filter
    dimensions over time without schema changes. The serializer
    validates the spec against an allowlist of dimensions, so
    arbitrary garbage doesn't get persisted.

    Read-only-after-use: once a Campaign references an Audience, the
    serializer rejects updates to the filter spec. Operators clone
    instead. This keeps the audit answer to "who got included in the
    May 12 blast" stable.
    """

    name = models.CharField(max_length=100)
    description = models.CharField(max_length=200, blank=True, default='')

    # Filter spec — JSON. Validated by serializer against an
    # allowlist; see apps.marketing.audiences.execute_filter for the
    # supported dimensions in v1.
    filter_spec = models.JSONField(default=dict, blank=True)

    # Cached count for the list-page UI label ("X members"). The
    # live-count endpoint recomputes on demand and updates this; the
    # list endpoint reads from cache to avoid N+1 query expansion
    # when there are many audiences.
    last_member_count = models.PositiveIntegerField(default=0)
    last_counted_at = models.DateTimeField(null=True, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='audiences_created',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        unique_together = [('tenant', 'name')]
        indexes = [
            models.Index(fields=['tenant', 'name']),
        ]

    def __str__(self):
        return self.name


# ── Template ─────────────────────────────────────────────────────────


class MarketingTemplate(TenantedModel):
    """An email or SMS template with `{{token}}` personalization.

    Token allowlist (see ADR 0016 § "MarketingTemplate model"):

        first_name, last_name, tenant_name, last_appointment_date,
        birthday_month, unsubscribe_url

    Clinical fields like `last_appointment_service` are intentionally
    NOT in the allowlist — they're PHI when paired with the spa as
    sender. The template-editor validator rejects unknown tokens at
    save time so we never queue a campaign that would expand to
    PHI in the body.
    """

    name = models.CharField(max_length=100)
    channel = models.CharField(max_length=20, choices=Channel.choices)

    # Email-only. SMS templates leave this blank.
    subject = models.CharField(max_length=200, blank=True, default='')

    body = models.TextField()

    is_active = models.BooleanField(default=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='marketing_templates_created',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']
        unique_together = [('tenant', 'name')]
        indexes = [
            models.Index(fields=['tenant', 'channel', 'is_active']),
        ]

    def __str__(self):
        return f'{self.name} ({self.get_channel_display()})'


# ── Campaign ─────────────────────────────────────────────────────────


class Campaign(TenantedModel):
    """One marketing send job — audience × template × schedule.

    Status transitions are guarded by serializer validation, not
    just convention:

        draft → scheduled (operator commits + recipient list
                          snapshot taken at this moment)
        draft → cancelled
        scheduled → sending (worker picks up at scheduled_at)
        scheduled → cancelled (operator pulls back; allowed up
                              until status flips to sending)
        sending → sent (worker completes per-customer dispatches)

    `recipient_count_snapshot` is locked at the draft → scheduled
    transition so a late audience edit doesn't silently expand the
    blast. The audience filter is re-evaluated AT SEND TIME on the
    worker, but the operator's commit-time understanding of "X
    customers" is what gets recorded for audit.
    """

    class Status(models.TextChoices):
        DRAFT = 'draft', 'Draft'
        SCHEDULED = 'scheduled', 'Scheduled'
        SENDING = 'sending', 'Sending'
        SENT = 'sent', 'Sent'
        CANCELLED = 'cancelled', 'Cancelled'

    name = models.CharField(max_length=100)

    audience = models.ForeignKey(
        Audience,
        on_delete=models.PROTECT,
        related_name='campaigns',
    )
    template = models.ForeignKey(
        MarketingTemplate,
        on_delete=models.PROTECT,
        related_name='campaigns',
    )
    channel = models.CharField(max_length=20, choices=Channel.choices)

    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.DRAFT,
        db_index=True,
    )

    # Scheduled send time. Null means "send now on draft → scheduled."
    scheduled_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    # Recipient list snapshot. Locked at draft → scheduled so the
    # audience can't silently expand the blast after the operator
    # committed.
    recipient_count_snapshot = models.PositiveIntegerField(default=0)

    # Send aggregates — populated by the worker from the per-row
    # MarketingSendLog table.
    sent_count = models.PositiveIntegerField(default=0)
    failed_count = models.PositiveIntegerField(default=0)
    suppressed_count = models.PositiveIntegerField(default=0)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='campaigns_created',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['tenant', 'status', '-created_at']),
            models.Index(fields=['tenant', 'audience']),
            models.Index(fields=['tenant', 'scheduled_at']),
        ]

    def __str__(self):
        return f'{self.name} ({self.get_status_display()})'


# ── Send log ─────────────────────────────────────────────────────────


class MarketingSendLog(TenantedModel):
    """Per-customer-per-campaign send record.

    The row is the audit trail. Even when a customer was suppressed
    (consent / opt-out / bounce), we write a row with status=SUPPRESSED
    and the reason — that's the "we attempted to send but didn't"
    record that satisfies HIPAA + CAN-SPAM auditing.

    Recipient identifier: domain only for email (per ADR 0012);
    last-4 only for SMS. The full address lives on Customer; the
    send log is a queryable surface that should not accumulate raw
    PII at high volume.
    """

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        SENT = 'sent', 'Sent'
        DELIVERED = 'delivered', 'Delivered'
        FAILED = 'failed', 'Failed'
        SUPPRESSED = 'suppressed', 'Suppressed'

    campaign = models.ForeignKey(
        Campaign, on_delete=models.PROTECT,
        related_name='send_log',
    )
    customer = models.ForeignKey(
        'customers.Customer', on_delete=models.PROTECT,
        related_name='marketing_sends',
    )
    channel = models.CharField(max_length=20, choices=Channel.choices)

    # Domain-only / last-4 — PII-light. The full identifier lives
    # on Customer; this is the audit-friendly subset.
    recipient_email_domain = models.CharField(max_length=120, blank=True, default='')
    recipient_phone_last4 = models.CharField(max_length=4, blank=True, default='')

    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING,
        db_index=True,
    )
    suppression_reason = models.CharField(
        max_length=50, blank=True, default='',
        help_text=(
            "e.g. 'no_consent', 'suppressed_unsubscribe', 'suppressed_bounce', "
            "'suppressed_complaint', 'quiet_hours' (sms only)"
        ),
    )

    # Provider tracking ID — SES message-id, Twilio SID. Lets the
    # webhook ingest correlate delivered/bounced/complained events
    # back to the source send.
    provider_message_id = models.CharField(max_length=200, blank=True, default='')

    sent_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    failed_at = models.DateTimeField(null=True, blank=True)
    failure_reason = models.CharField(max_length=500, blank=True, default='')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            # Hot path: "did Jane get the May 12 promo?"
            models.Index(fields=['tenant', 'customer', '-created_at']),
            # Campaign aggregate rollup.
            models.Index(fields=['tenant', 'campaign', 'status']),
            # Provider-webhook correlation.
            models.Index(fields=['tenant', 'provider_message_id']),
        ]

    def __str__(self):
        return f'#{self.pk} · {self.campaign.name} → {self.customer.full_name} ({self.status})'


# ── Automations (always-on triggered campaigns) ─────────────────────


class Automation(TenantedModel):
    """Trigger-based always-on campaign — fires when a customer
    becomes eligible for a defined trigger and respects a per-customer
    dedup window so the same automation doesn't blast someone twice.

    Examples:

      - **Birthday** — fire in the customer's birthday MONTH (not
        on the day, to give the spa a full month to land the
        message). Once per year per customer.
      - **No-visit-in-N-days** (win-back) — fire when a customer's
        last completed appointment crossed N days. Dedup window
        prevents weekly nagging.
      - **First-visit-anniversary** — fire one year after the
        customer's first completed appointment. Annual cadence.

    `trigger_config` is JSON for forward-compat — different trigger
    types need different params (no_visit_days needs `days`;
    birthday needs nothing). The validator in the serializer
    enforces the per-type contract.
    """

    class TriggerType(models.TextChoices):
        BIRTHDAY = 'birthday', 'Birthday month'
        NO_VISIT_DAYS = 'no_visit_days', 'No visit in N days (win-back)'
        FIRST_VISIT_ANNIVERSARY = 'first_visit_anniversary', 'First-visit anniversary'

    name = models.CharField(max_length=100)
    description = models.CharField(max_length=200, blank=True, default='')

    trigger_type = models.CharField(max_length=40, choices=TriggerType.choices)
    trigger_config = models.JSONField(default=dict, blank=True)

    template = models.ForeignKey(
        MarketingTemplate, on_delete=models.PROTECT,
        related_name='automations',
    )
    channel = models.CharField(max_length=20, choices=Channel.choices)

    # Optional ADDITIONAL audience filter — narrows trigger
    # eligibility further. Example: "win-back, but only for VIP-
    # tagged customers." Null = trigger eligibility alone.
    audience = models.ForeignKey(
        Audience, on_delete=models.PROTECT,
        related_name='automations',
        null=True, blank=True,
    )

    # Don't fire the same automation for the same customer within
    # this many days. Default 365 (annual cadence for birthday +
    # anniversary; sufficient for win-back since the eligibility
    # event itself shifts over time).
    dedup_window_days = models.PositiveIntegerField(default=365)

    is_active = models.BooleanField(
        default=False,
        db_index=True,
        help_text=(
            'Operator toggle. New automations land disabled — turn '
            'on after testing the trigger eval + previewing the '
            'template + verifying suppression-eligible counts.'
        ),
    )

    # Per-run aggregates so the list page can show "last fired N
    # days ago, sent X, suppressed Y" without re-evaluating the
    # trigger.
    last_run_at = models.DateTimeField(null=True, blank=True)
    last_run_eligible_count = models.PositiveIntegerField(default=0)
    last_run_sent_count = models.PositiveIntegerField(default=0)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='automations_created',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']
        unique_together = [('tenant', 'name')]
        indexes = [
            models.Index(fields=['tenant', 'is_active', 'trigger_type']),
        ]

    def __str__(self):
        return f'{self.name} ({self.get_trigger_type_display()})'


# ── Unsubscribe tokens ──────────────────────────────────────────────


class UnsubscribeToken(TenantedModel):
    """Tokenized URL for one-click marketing unsubscribe.

    Each token is per-customer-per-channel and lasts forever —
    once a token unsubscribes its target, subsequent visits are
    idempotent (the page still renders the "you're unsubscribed"
    state). Generated lazily when a marketing send happens; the
    `{{unsubscribe_url}}` token expansion uses or creates one for
    the (customer, channel) pair.

    Why a separate row instead of stuffing the customer ID in the
    URL: a customer-ID-based link would let a bad actor bulk-
    unsubscribe everyone by iterating IDs. The 256-bit random
    token is unguessable.

    Why never expire: customers sometimes unsubscribe from a promo
    email they received months ago. Expired tokens leave them
    frustrated (or worse, complaining to the FTC). Tokens-that-
    never-expire is the legally-friendly default.
    """

    customer = models.ForeignKey(
        'customers.Customer',
        on_delete=models.PROTECT,
        related_name='unsubscribe_tokens',
    )
    channel = models.CharField(max_length=20, choices=Channel.choices)
    token = models.CharField(max_length=64, unique=True, db_index=True)

    # Optional provenance — which send issued this token. Helps the
    # audit answer "this customer unsubscribed from THIS campaign."
    source_campaign = models.ForeignKey(
        Campaign, on_delete=models.SET_NULL, null=True, blank=True,
    )
    source_automation = models.ForeignKey(
        Automation, on_delete=models.SET_NULL, null=True, blank=True,
    )

    used_at = models.DateTimeField(null=True, blank=True)
    used_ip = models.GenericIPAddressField(null=True, blank=True)
    used_user_agent = models.CharField(max_length=500, blank=True, default='')

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['tenant', 'customer', 'channel']),
        ]

    def __str__(self):
        return f'unsubscribe:{self.channel}:{self.customer.full_name}'


# ── Email suppression (platform-wide) ───────────────────────────────


class EmailSuppression(models.Model):
    """Addresses we MUST NOT send email to.

    Platform-wide (no tenant FK) because SES sender reputation is
    shared across all tenants under `mail.xn--lumcrm-5ua.com`. A
    permanent bounce on tenant A's send means the address is bad
    for everyone; a complaint on tenant A means the user marked
    *Lumè* as spam, and continuing to send from any tenant erodes
    the shared reputation pool. See [ADR 0029] for the full
    rationale and the alternative-considered (per-tenant overrides).

    Populated automatically by the SES → SNS webhook receiver
    (`apps.marketing.views_aws_ses.SnsEventReceiverView`) on:

      - `Bounce` event with `bounceType == 'Permanent'` — every
        bounced address is added with `reason='bounce_permanent'`.
        Transient bounces are logged but never recorded here.
      - `Complaint` event — every complained address is added with
        `reason='complaint'` regardless of subtype. A complaint is
        a binding "stop sending to me."

    Plus a manual path (`reason='manual'`) gated by
    `MANAGE_TENANT_SETTINGS` for the rare operator-initiated case.

    Idempotency: repeat events on the same address bump
    `last_seen_at` + `event_count`, never create duplicate rows.

    PHI posture: the full email address lives in this table because
    it IS the lookup key — domain-only suppression would let bad
    addresses through. Audit-log metadata downstream continues to
    record `recipient_email_domain` only; this table is the single
    place a full address is persisted in the deliverability subsystem.
    """

    class Reason(models.TextChoices):
        BOUNCE_PERMANENT = 'bounce_permanent', 'Permanent bounce'
        COMPLAINT = 'complaint', 'Complaint'
        MANUAL = 'manual', 'Manual'

    email = models.EmailField(
        max_length=254,
        unique=True,
        db_index=True,
        help_text='Lowercased recipient address. The lookup key.',
    )
    reason = models.CharField(
        max_length=32, choices=Reason.choices, db_index=True,
    )

    # SES vocab preserved verbatim — "general", "no-email",
    # "suppressed", "on-account-suppression-list" for bounces;
    # "abuse", "auth-failure", "fraud", "not-spam", "other", "virus"
    # for complaints. Empty for manual.
    bounce_subtype = models.CharField(max_length=64, blank=True, default='')
    complaint_subtype = models.CharField(max_length=64, blank=True, default='')

    first_seen_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)
    event_count = models.PositiveIntegerField(default=1)

    # SES `mail.messageId` from the FIRST event that suppressed this
    # address. Lets ops trace "what message did this stem from."
    ses_message_id = models.CharField(max_length=200, blank=True, default='')

    # Forensic snapshot of the SNS payload. May carry the full
    # address — see PHI posture in the class docstring.
    raw_event = models.JSONField(default=dict, blank=True)

    # Manual additions only — null for webhook-driven rows.
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='email_suppressions_created',
    )
    notes = models.TextField(
        blank=True, default='',
        help_text='Operator notes (manual additions); SES event summary otherwise.',
    )

    class Meta:
        ordering = ['-last_seen_at']
        indexes = [
            models.Index(fields=['reason', '-last_seen_at']),
        ]

    def __str__(self):
        return f'{self.email} ({self.reason})'
