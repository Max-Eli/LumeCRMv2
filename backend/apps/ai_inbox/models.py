"""Models for the AI SMS inbox.

The ai_inbox app owns the AI-agent layer that sits on top of the
existing ``apps.messaging`` 2-way SMS infrastructure. Every AI-
generated SMS is still persisted as a row in ``messaging.Message``
(with ``generated_by_ai=True`` and an FK back here); this app owns
the per-tenant config, the per-conversation agent state, the
audit trail of every tool call, and the escalation surface.

Models in delete order (deepest dependency first — matches
``purge_tenant_customers``):

  - ``EscalationAlert``        — per-event escalation row, FK to AIConversation (CASCADE)
  - ``AIToolCall``             — per-tool-invocation audit row, FK to AIConversation (CASCADE)
  - ``AIConversation``         — per-(tenant, customer) ongoing agent state, FK to Customer (PROTECT)
  - ``AIUsageDay``             — per-(tenant, date) usage counters, no Customer FK
  - ``AIConfig``               — per-tenant config (unique on tenant), no Customer FK

HIPAA framing:

  - The system prompt + tenant config carry NO PHI. Tenant name,
    persona text, business hours — that's it.
  - PHI flows to Claude only via ``get_customer_context`` tool
    results we construct here (allow-list — chart notes / treatment
    records / intake answers / insurance NEVER returned).
  - ``AIToolCall.input_json`` / ``output_json`` are scrubbed of
    raw phone/email/SSN/DOB before persistence — the PHI-of-record
    stays on ``messaging.Message.body``.
  - Customer deletion cascades correctly because ``AIConversation``
    PROTECT-references Customer (so the conversation is purged
    first), and AIToolCall + EscalationAlert CASCADE off the
    conversation.

Safety + kill switches live in ``services/guardrails.py``:

  - ``AIConfig.enabled`` is False at creation; staff must opt in.
  - ``AIConfig.test_mode`` is True at creation; only the configured
    ``test_mode_number`` can interact until the Go-Live modal flips
    it off.
  - ``AIConfig.platform_disabled_at`` is the platform-admin global
    kill switch — settable from the platform tenants page; trumps
    every other check.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.tenants.abstract_models import TenantedModel


class AIConfig(TenantedModel):
    """Per-tenant AI-agent configuration. Exactly one row per tenant.

    Created lazily by ``ensure_ai_config(tenant)`` the first time
    F_AI_INBOX is accessed (or by the ``enable_ai_for_tenant``
    management command). NEVER created with ``enabled=True`` — flip
    it manually after sandbox testing.

    The ``platform_disabled_at`` field is the global kill switch
    set by platform admins from the tenants UI. Any non-null value
    bypasses every other check and blocks AI dispatch entirely
    until cleared.
    """

    tenant = models.OneToOneField(
        'tenants.Tenant',
        on_delete=models.CASCADE,
        related_name='ai_config',
    )

    enabled = models.BooleanField(
        default=False,
        db_index=True,
        help_text=(
            'Master switch for the tenant. Default False — operator '
            'must opt in through the Go-Live modal in /settings/ai-inbox '
            'after successful sandbox testing. The API + admin both '
            'reject enabling on a tenant whose twilio_from_number is empty.'
        ),
    )
    test_mode = models.BooleanField(
        default=True,
        help_text=(
            'When True, only inbound SMS from test_mode_number is '
            'processed; all other inbound numbers are audit-logged '
            'and dropped. Always True at row creation.'
        ),
    )
    test_mode_number = models.CharField(
        max_length=20,
        blank=True,
        default='',
        help_text='E.164 phone number that may interact with the AI in test mode.',
    )

    persona = models.TextField(
        blank=True,
        default='',
        max_length=2000,
        help_text=(
            'Free-text persona description merged into the system '
            "prompt (e.g. \"You're Avery, the friendly front-desk "
            'assistant for the demo medspa"). Must contain NO PHI.'
        ),
    )

    business_hours_json = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            'Hours during which the AI will reply. Mirrors the shape '
            'of Location.business_hours_json. Outside hours the AI '
            'either stays silent or sends one "we\'re closed" reply '
            'per night (config flag, future work).'
        ),
    )

    booking_lead_minutes = models.PositiveIntegerField(
        default=120,
        help_text=(
            'Minimum minutes between now and the earliest bookable '
            'slot. Adds friction so an inbound at 8:55am does not '
            'book 9:00am.'
        ),
    )
    propose_slot_count = models.PositiveSmallIntegerField(
        default=3,
        help_text='How many slots the agent may propose per turn (1-9).',
    )

    daily_send_cap = models.PositiveIntegerField(
        default=100,
        help_text=(
            'Hard daily ceiling on outbound AI messages per tenant. '
            'Exceeded → escalate, no further sends today.'
        ),
    )
    monthly_exchange_cap = models.PositiveIntegerField(
        default=500,
        help_text=(
            'Included monthly exchanges for the tenant\'s plan tier. '
            'Pro 500, Enterprise 2000. Overage billed via Stripe '
            'metered usage (Phase 5).'
        ),
    )

    escalation_keywords = models.JSONField(
        default=list,
        blank=True,
        help_text=(
            'Extra phrases that force escalation, e.g. '
            '["refund","manager","cancel my card"]. Matched '
            'case-insensitively against the inbound body before '
            'Claude is called.'
        ),
    )

    platform_disabled_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=(
            'GLOBAL KILL SWITCH. Settable by platform admins from '
            '/platform/tenants/<id>. Non-null = AI dispatch is fully '
            'blocked regardless of enabled / test_mode / per-conversation '
            'state. Clear by setting back to null (manual operator action). '
            'Applies to BOTH SMS and Instagram channels.'
        ),
    )
    platform_disabled_reason = models.CharField(
        max_length=500,
        blank=True,
        default='',
    )

    # ── Instagram channel (separate enable from SMS) ──────────────
    # Instagram runs through Meta, which is NOT BAA-covered, so the
    # Instagram agent is booking-only: it never gets the
    # get_customer_context (PHI) tool. A tenant can run SMS AI and
    # Instagram AI independently.
    instagram_enabled = models.BooleanField(
        default=False,
        db_index=True,
        help_text=(
            'Master switch for the Instagram DM agent. Default False. '
            'Requires the tenant to also have a connected Instagram '
            'channel (apps.integrations.Connection) and the '
            'F_SOCIAL_INTEGRATIONS feature.'
        ),
    )
    instagram_test_mode = models.BooleanField(
        default=True,
        help_text=(
            'When True, only inbound DMs from instagram_test_username '
            'are answered; all others are audit-logged + dropped. '
            'Always True at row creation.'
        ),
    )
    instagram_test_username = models.CharField(
        max_length=120,
        blank=True,
        default='',
        help_text=(
            'Instagram @handle (without the @) allowed to interact '
            'with the agent while instagram_test_mode is on.'
        ),
    )
    business_phone = models.CharField(
        max_length=32,
        blank=True,
        default='',
        help_text=(
            'Phone number the Instagram agent tells customers to call '
            'for account questions (which it cannot answer over a '
            'non-BAA channel). Falls back to the primary Location '
            'phone when blank.'
        ),
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        flag = 'on' if self.enabled else 'off'
        sandbox = ' (test_mode)' if self.test_mode else ''
        return f'AIConfig({self.tenant.slug}: {flag}{sandbox})'


class AIConversation(TenantedModel):
    """Ongoing AI-agent state for one (tenant, customer) pair.

    Created lazily by the dispatcher on the first inbound that
    passes the guardrails. Status transitions:

      ACTIVE   → PAUSED      (staff clicks "Pause AI" in the inbox)
      ACTIVE   → ESCALATED   (AI calls escalate_to_human; or staff escalates)
      PAUSED   → ACTIVE      (staff clicks "Resume AI")
      ESCALATED → ACTIVE     (staff clicks "Mark resolved" on the alert)
      *        → CLOSED      (manual ops action; conversation archived)

    ``last_ai_at`` doubles as the per-conversation reply lock — the
    dispatcher refuses to fire a second AI reply within 30s of the
    last one (defense against runaway loops or duplicate inbound
    Twilio retries).

    ``pending_proposal`` carries the two-step booking state. When
    non-null + unexpired, an inbound matching ``^\\s*[1-9]\\s*$``
    fast-paths to ``confirm_booking(N)`` without re-calling Claude.
    """

    class Status(models.TextChoices):
        ACTIVE = 'active', 'Active'
        PAUSED = 'paused', 'Paused by staff'
        ESCALATED = 'escalated', 'Escalated to human'
        CLOSED = 'closed', 'Closed'

    class Channel(models.TextChoices):
        SMS = 'sms', 'SMS'
        INSTAGRAM = 'instagram', 'Instagram DM'

    tenant = models.ForeignKey(
        'tenants.Tenant',
        on_delete=models.CASCADE,
        related_name='ai_conversations',
    )
    customer = models.ForeignKey(
        'customers.Customer',
        on_delete=models.PROTECT,
        related_name='ai_conversations',
        help_text=(
            'PROTECT so customer deletion forces the conversation '
            'to be deleted first (purge_tenant_customers handles '
            'the ordering).'
        ),
    )

    channel = models.CharField(
        max_length=12,
        choices=Channel.choices,
        default=Channel.SMS,
        db_index=True,
        help_text=(
            'Which transport this conversation runs over. SMS goes '
            'through Twilio (BAA-covered, PHI-safe); Instagram goes '
            'through Meta (NOT BAA-covered — booking-only, no PHI '
            'tools). Part of the conversation identity so the same '
            'customer can have separate AI state per channel.'
        ),
    )
    social_thread = models.ForeignKey(
        'integrations.SocialThread',
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='ai_conversations',
        help_text=(
            'The Instagram/social thread this conversation replies '
            'into. Null for SMS conversations. SET_NULL so deleting '
            'a thread does not cascade away the AI audit trail.'
        ),
    )

    status = models.CharField(
        max_length=12,
        choices=Status.choices,
        default=Status.ACTIVE,
        db_index=True,
    )

    paused_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
        help_text='Staff user who clicked "Pause AI" (null if not paused or user since deleted).',
    )
    paused_at = models.DateTimeField(null=True, blank=True)

    escalated_at = models.DateTimeField(null=True, blank=True)
    escalation_reason = models.CharField(max_length=120, blank=True, default='')

    last_ai_at = models.DateTimeField(
        null=True, blank=True,
        help_text=(
            'Timestamp of the most recent outbound AI message. Used '
            'by services/locks.py as the per-conversation reply lock '
            '(min 30s between AI sends).'
        ),
    )
    last_inbound_at = models.DateTimeField(null=True, blank=True)

    message_count = models.PositiveIntegerField(
        default=0,
        help_text='Cumulative count of inbound + outbound messages in this conversation.',
    )
    exchange_count = models.PositiveIntegerField(
        default=0,
        help_text=(
            'Cumulative count of inbound→outbound exchanges. One '
            'exchange = one inbound + one outbound. Used as the '
            'unit of billing for AI overage.'
        ),
    )

    pending_proposal = models.JSONField(
        null=True, blank=True,
        help_text=(
            'Two-step booking state. Schema: {service_id, location_id, '
            'provider_id, proposed_at, slots: [{index, start_iso, end_iso}]}. '
            'Cleared on confirm_booking or expiry.'
        ),
    )
    pending_proposal_expires_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'customer', 'channel'],
                name='aiconversation_tenant_customer_channel_unique',
            ),
        ]
        indexes = [
            models.Index(fields=['tenant', 'status', '-updated_at']),
        ]

    def __str__(self) -> str:
        return f'AIConversation({self.tenant.slug}/{self.customer_id}/{self.channel}: {self.status})'


class AIToolCall(TenantedModel):
    """Append-only audit row per tool invocation.

    Every call the agent makes to a tool (check_availability,
    propose_slots, confirm_booking, etc.) writes one row here. The
    inputs + outputs are scrubbed of raw phone/email/SSN/DOB by
    ``services/scrub.py`` before persistence — the PHI-of-record
    lives on ``messaging.Message.body``, not in audit metadata.

    ``triggered_by_message`` links back to the inbound Message that
    started the agent turn. Useful for replaying a single turn end-
    to-end during incident investigation.
    """

    tenant = models.ForeignKey(
        'tenants.Tenant',
        on_delete=models.CASCADE,
        related_name='+',
    )
    conversation = models.ForeignKey(
        AIConversation,
        on_delete=models.CASCADE,
        related_name='tool_calls',
    )
    triggered_by_message = models.ForeignKey(
        'messaging.Message',
        on_delete=models.PROTECT,
        related_name='+',
        null=True, blank=True,
    )

    tool_name = models.CharField(max_length=64, db_index=True)
    input_json = models.JSONField(default=dict, blank=True)
    output_json = models.JSONField(default=dict, blank=True)

    success = models.BooleanField(default=True, db_index=True)
    error_message = models.CharField(max_length=500, blank=True, default='')

    latency_ms = models.PositiveIntegerField(default=0)
    model_used = models.CharField(
        max_length=64,
        blank=True,
        default='',
        help_text='Bedrock model ID that produced this tool call, if applicable.',
    )

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=['tenant', '-created_at']),
            models.Index(fields=['conversation', '-created_at']),
        ]


class EscalationAlert(TenantedModel):
    """One row per escalation event — drives the dashboard widget.

    The agent (or a staff manual escalation) creates an EscalationAlert
    AND flips the AIConversation to status=ESCALATED. Resolving the
    alert flips the conversation back to ACTIVE.

    ``reason`` is the machine-readable enum value matching the
    ``escalate_to_human(reason=...)`` argument. ``reason_detail``
    is the free-text summary the agent generated.
    """

    class Reason(models.TextChoices):
        REQUESTED_HUMAN = 'requested_human', 'Customer asked for a person'
        CLINICAL_QUESTION = 'clinical_question', 'Clinical question'
        PAYMENT_DISPUTE = 'payment_dispute', 'Payment / refund dispute'
        COMPLAINT = 'complaint', 'Complaint'
        AGENT_LOOP_LIMIT = 'agent_loop_limit', 'Agent hit tool-call cap'
        DAILY_CAP_EXCEEDED = 'daily_cap_exceeded', 'Tenant daily cap exceeded'
        SAFETY_OUTBOUND_BLOCKED = 'safety_outbound_blocked', 'Outbound PHI scanner blocked send'
        UNSUPPORTED_REQUEST = 'unsupported_request', 'Out-of-scope (reschedule / cancel)'
        MANUAL_STAFF = 'manual_staff', 'Staff manually escalated'
        AGENT_ERROR = 'agent_error', 'Agent crashed or LLM failed twice'

    tenant = models.ForeignKey(
        'tenants.Tenant',
        on_delete=models.CASCADE,
        related_name='+',
    )
    conversation = models.ForeignKey(
        AIConversation,
        on_delete=models.CASCADE,
        related_name='alerts',
    )
    customer = models.ForeignKey(
        'customers.Customer',
        on_delete=models.PROTECT,
        related_name='+',
    )

    reason = models.CharField(max_length=120, choices=Reason.choices)
    reason_detail = models.TextField(blank=True, default='')
    triggering_message = models.ForeignKey(
        'messaging.Message',
        on_delete=models.PROTECT,
        related_name='+',
        null=True, blank=True,
    )

    acknowledged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
    )
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=['tenant', 'acknowledged_at', '-created_at']),
        ]


class AIUsageDay(TenantedModel):
    """Per-(tenant, date) counter for AI activity.

    Incremented atomically by ``services/usage.py``. Read by the
    daily Stripe overage reporter (Phase 5) and by the Settings →
    AI Inbox usage panel.

    No PHI here — pure counters.
    """

    tenant = models.ForeignKey(
        'tenants.Tenant',
        on_delete=models.CASCADE,
        related_name='+',
    )
    date = models.DateField(db_index=True)

    ai_messages_sent = models.PositiveIntegerField(default=0)
    ai_exchanges = models.PositiveIntegerField(default=0)
    ai_tool_calls = models.PositiveIntegerField(default=0)

    bedrock_input_tokens = models.PositiveIntegerField(default=0)
    bedrock_output_tokens = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'date'],
                name='aiusageday_tenant_date_unique',
            ),
        ]

    def __str__(self) -> str:
        return f'AIUsageDay({self.tenant.slug}/{self.date}: {self.ai_exchanges}x)'
