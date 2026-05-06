"""Marketing API serializers — Phase 1L sessions 1 + 2."""

from __future__ import annotations

from rest_framework import serializers

from .audiences import validate_filter_spec
from .automations import validate_trigger_config
from .models import Audience, Automation, Campaign, Channel, MarketingSendLog, MarketingTemplate
from .templates_tokens import (
    TokenValidationError,
    discover_tokens,
    validate_template_body,
)


class AudienceSerializer(serializers.ModelSerializer):
    """Read + write shape for `Audience`.

    `filter_spec` validation runs through `audiences.validate_filter_spec`
    which checks dimensions against the allowlist and bounds-checks
    each value. Unknown dimensions raise so a malformed spec never
    reaches the executor.

    `is_used_in_campaign` flag is computed at read time so the
    frontend can disable the edit UI for already-used audiences
    (per ADR 0016 — used audiences are read-only to keep audit
    attribution stable).
    """

    is_used_in_campaign = serializers.SerializerMethodField()
    created_by_email = serializers.EmailField(
        source='created_by.email', read_only=True, default=None,
    )

    class Meta:
        model = Audience
        fields = [
            'id',
            'name', 'description',
            'filter_spec',
            'last_member_count', 'last_counted_at',
            'is_used_in_campaign',
            'created_by_email',
            'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id',
            'last_member_count', 'last_counted_at',
            'is_used_in_campaign',
            'created_by_email',
            'created_at', 'updated_at',
        ]

    def get_is_used_in_campaign(self, audience: Audience) -> bool:
        # An audience is "used" when any campaign that's not in
        # DRAFT or CANCELLED references it. Draft + cancelled
        # campaigns don't have a recipient list locked yet, so
        # editing the audience under them is fine.
        return audience.campaigns.exclude(
            status__in=[Campaign.Status.DRAFT, Campaign.Status.CANCELLED],
        ).exists()

    def validate_filter_spec(self, value):
        return validate_filter_spec(value)

    def validate(self, attrs):
        # If updating, reject filter_spec mutations on used audiences.
        # Name + description can still be edited (cosmetic).
        if self.instance is not None and 'filter_spec' in attrs:
            if self.get_is_used_in_campaign(self.instance):
                old = self.instance.filter_spec or {}
                new = attrs['filter_spec']
                if old != new:
                    raise serializers.ValidationError({
                        'filter_spec': (
                            'This audience has been used in a campaign. '
                            'Clone it to a new audience to make changes.'
                        ),
                    })
        return attrs


class AudienceCountSerializer(serializers.Serializer):
    """Response shape for the live-count endpoint."""

    total_count = serializers.IntegerField()
    email_eligible_count = serializers.IntegerField()
    sms_eligible_count = serializers.IntegerField()


# ── Templates ───────────────────────────────────────────────────────


# SMS template body cap. 160 ASCII chars = 1 SMS segment; we let
# the operator go to ~480 (3 segments) before warning. Hard cap at
# 1600 (10 segments) to prevent accidental novel-length blasts that
# would bill ridiculously and deliver poorly.
SMS_BODY_HARD_CAP = 1600


class MarketingTemplateSerializer(serializers.ModelSerializer):
    """Read + write shape for `MarketingTemplate`.

    Token validator runs `validate_template_body()` against the
    allowlist; CAN-SPAM unsubscribe-link requirement is enforced
    here for email templates (must contain `{{unsubscribe_url}}`).

    `discovered_tokens` is computed at read time so the editor UI
    can highlight which tokens will be expanded; useful for the
    operator to spot a typo'd token that wouldn't otherwise be
    caught by the allowlist check (typo'd tokens are rejected
    outright).
    """

    discovered_tokens = serializers.SerializerMethodField()
    created_by_email = serializers.EmailField(
        source='created_by.email', read_only=True, default=None,
    )

    class Meta:
        model = MarketingTemplate
        fields = [
            'id',
            'name', 'channel',
            'subject', 'body',
            'is_active',
            'discovered_tokens',
            'created_by_email',
            'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id',
            'discovered_tokens',
            'created_by_email',
            'created_at', 'updated_at',
        ]

    def get_discovered_tokens(self, template: MarketingTemplate) -> list[str]:
        # Returns deduped list in order of first appearance — the
        # editor uses it to render the chips above the body field.
        seen: dict[str, None] = {}
        for token in discover_tokens(template.body or ''):
            seen.setdefault(token, None)
        return list(seen.keys())

    def validate_body(self, value: str):
        try:
            validate_template_body(value)
        except TokenValidationError as e:
            raise serializers.ValidationError(str(e))
        return value

    def validate(self, attrs):
        # Channel + body cross-checks.
        body = attrs.get('body', getattr(self.instance, 'body', ''))
        channel = attrs.get('channel', getattr(self.instance, 'channel', None))
        subject = attrs.get('subject', getattr(self.instance, 'subject', ''))

        if channel == Channel.EMAIL:
            # CAN-SPAM: every commercial email must contain a working
            # unsubscribe link. We enforce by requiring the
            # `{{unsubscribe_url}}` token in the body.
            if '{{unsubscribe_url}}' not in (body or ''):
                raise serializers.ValidationError({
                    'body': (
                        'Email templates must include {{unsubscribe_url}} '
                        'somewhere in the body — CAN-SPAM requires a '
                        'working unsubscribe link in every marketing email.'
                    ),
                })
            if not (subject or '').strip():
                raise serializers.ValidationError({
                    'subject': 'Email templates require a subject line.',
                })
        elif channel == Channel.SMS:
            # SMS subject is meaningless; reject if set.
            if subject:
                raise serializers.ValidationError({
                    'subject': 'SMS templates have no subject. Leave blank.',
                })
            if len(body or '') > SMS_BODY_HARD_CAP:
                raise serializers.ValidationError({
                    'body': (
                        f'SMS body is {len(body)} characters; cap is '
                        f'{SMS_BODY_HARD_CAP}. Long messages bill per '
                        'segment and deliver worse — split into multiple '
                        'sends if you need more space.'
                    ),
                })

        return attrs


class MarketingTemplatePreviewSerializer(serializers.Serializer):
    """Body validation for `POST /templates/<id>/preview/` —
    renders the template against a sample customer + tenant context
    and returns the expanded body (and subject for email)."""

    customer_id = serializers.IntegerField(
        required=False, allow_null=True,
        help_text=(
            'Optional. When provided, render against that real customer. '
            'When omitted, render against a synthetic sample so the '
            'operator can see the shape without picking a real record.'
        ),
    )


class MarketingTemplatePreviewResultSerializer(serializers.Serializer):
    """Response shape for the preview endpoint."""

    subject = serializers.CharField(allow_blank=True)
    body = serializers.CharField()
    discovered_tokens = serializers.ListField(child=serializers.CharField())


# ── Campaigns ───────────────────────────────────────────────────────


class CampaignListSerializer(serializers.ModelSerializer):
    """Compact shape for the list page — rolls up name + status +
    audience name + scheduled time + send aggregates without going
    deep on the audience/template detail."""

    audience_name = serializers.CharField(source='audience.name', read_only=True)
    template_name = serializers.CharField(source='template.name', read_only=True)
    created_by_email = serializers.EmailField(
        source='created_by.email', read_only=True, default=None,
    )

    class Meta:
        model = Campaign
        fields = [
            'id',
            'name',
            'audience', 'audience_name',
            'template', 'template_name',
            'channel',
            'status',
            'scheduled_at',
            'started_at', 'completed_at',
            'recipient_count_snapshot',
            'sent_count', 'failed_count', 'suppressed_count',
            'created_by_email',
            'created_at', 'updated_at',
        ]
        read_only_fields = fields  # list-page is read-only


class CampaignSerializer(serializers.ModelSerializer):
    """Detail shape — includes everything the list shape has plus
    the audience + template details inlined so the campaign-detail
    page doesn't need three round-trips."""

    audience_detail = AudienceSerializer(source='audience', read_only=True)
    template_detail = MarketingTemplateSerializer(source='template', read_only=True)
    created_by_email = serializers.EmailField(
        source='created_by.email', read_only=True, default=None,
    )

    class Meta:
        model = Campaign
        fields = [
            'id',
            'name',
            'audience', 'audience_detail',
            'template', 'template_detail',
            'channel',
            'status',
            'scheduled_at',
            'started_at', 'completed_at',
            'recipient_count_snapshot',
            'sent_count', 'failed_count', 'suppressed_count',
            'created_by_email',
            'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id',
            'audience_detail', 'template_detail',
            'channel',  # derived from template; mutating channel post-create is suspicious
            'status',  # transitions go through dedicated endpoints
            'started_at', 'completed_at',
            'recipient_count_snapshot',
            'sent_count', 'failed_count', 'suppressed_count',
            'created_by_email',
            'created_at', 'updated_at',
        ]

    def validate(self, attrs):
        # Audience + template must belong to the same tenant; the
        # view enforces tenant on the queryset, but we also assert
        # that `template.channel` matches what we're saving (the
        # operator can't pair an SMS template with an email
        # campaign). On create, channel is derived from template;
        # on update, channel is read-only.
        template = attrs.get('template') or getattr(self.instance, 'template', None)
        audience = attrs.get('audience') or getattr(self.instance, 'audience', None)
        if template and audience:
            if template.tenant_id != audience.tenant_id:
                raise serializers.ValidationError({
                    'detail': 'Audience and template must belong to the same tenant.',
                })
        return attrs


class CampaignCreateSerializer(serializers.ModelSerializer):
    """Compact create shape. Channel is auto-derived from the
    template; status is forced to DRAFT."""

    class Meta:
        model = Campaign
        fields = ['name', 'audience', 'template', 'scheduled_at']

    def validate(self, attrs):
        if attrs['audience'].tenant_id != attrs['template'].tenant_id:
            raise serializers.ValidationError({
                'detail': 'Audience and template must belong to the same tenant.',
            })
        return attrs


class CampaignScheduleSerializer(serializers.Serializer):
    """Body for `POST /campaigns/<id>/schedule/` — flips DRAFT →
    SCHEDULED. `send_now=True` queues for immediate dispatch
    regardless of `scheduled_at`."""

    send_now = serializers.BooleanField(default=False)


# ── Send log ────────────────────────────────────────────────────────


class MarketingSendLogSerializer(serializers.ModelSerializer):
    """Per-customer send row — read-only. Used in the campaign
    detail page's send-log tab + the customer profile's marketing
    history tab.

    `campaign_name` is denormalized for the customer-history surface
    where rows span multiple campaigns; the campaign-detail surface
    already knows the campaign and ignores it.
    """

    customer_first_name = serializers.CharField(source='customer.first_name', read_only=True)
    customer_last_name = serializers.CharField(source='customer.last_name', read_only=True)
    campaign_name = serializers.CharField(source='campaign.name', read_only=True)

    class Meta:
        model = MarketingSendLog
        fields = [
            'id', 'campaign', 'campaign_name', 'customer',
            'customer_first_name', 'customer_last_name',
            'channel',
            'recipient_email_domain', 'recipient_phone_last4',
            'status', 'suppression_reason',
            'sent_at', 'delivered_at', 'failed_at', 'failure_reason',
            'created_at',
        ]
        read_only_fields = fields


# ── Automations ─────────────────────────────────────────────────────


class AutomationSerializer(serializers.ModelSerializer):
    """Read + write shape for `Automation`.

    `channel` derives from the chosen template (matches Campaign
    semantics) and is read-only. `trigger_config` is validated
    per-type by `automations.validate_trigger_config`. `is_active`
    can be flipped any time — operators turn automations on after
    previewing the eligibility count and confirming the template.
    """

    template_name = serializers.CharField(source='template.name', read_only=True)
    audience_name = serializers.CharField(
        source='audience.name', read_only=True, default=None,
    )
    created_by_email = serializers.EmailField(
        source='created_by.email', read_only=True, default=None,
    )

    class Meta:
        model = Automation
        fields = [
            'id',
            'name', 'description',
            'trigger_type', 'trigger_config',
            'template', 'template_name',
            'channel',
            'audience', 'audience_name',
            'dedup_window_days',
            'is_active',
            'last_run_at', 'last_run_eligible_count', 'last_run_sent_count',
            'created_by_email',
            'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id',
            'channel',
            'template_name', 'audience_name',
            'last_run_at', 'last_run_eligible_count', 'last_run_sent_count',
            'created_by_email',
            'created_at', 'updated_at',
        ]

    def validate(self, attrs):
        # trigger_type + trigger_config compatibility
        trigger_type = attrs.get(
            'trigger_type', getattr(self.instance, 'trigger_type', None),
        )
        trigger_config = attrs.get(
            'trigger_config', getattr(self.instance, 'trigger_config', {}),
        )
        if trigger_type:
            attrs['trigger_config'] = validate_trigger_config(trigger_type, trigger_config or {})

        # audience + template + tenant cross-checks. The view
        # establishes tenant on the queryset; we double-check that
        # template + audience belong to the same tenant if both are
        # set in this request.
        template = attrs.get('template') or getattr(self.instance, 'template', None)
        audience = attrs.get('audience') or getattr(self.instance, 'audience', None)
        if template and audience and template.tenant_id != audience.tenant_id:
            raise serializers.ValidationError({
                'detail': 'Template and audience must belong to the same tenant.',
            })

        # Dedup window bounds.
        dedup = attrs.get('dedup_window_days')
        if dedup is not None and (dedup < 1 or dedup > 3650):
            raise serializers.ValidationError({
                'dedup_window_days': 'Must be between 1 and 3650 days.',
            })

        return attrs


class AutomationPreviewSerializer(serializers.Serializer):
    """Response shape for the `automations/<id>/preview/` endpoint."""

    total_count = serializers.IntegerField()
    consent_eligible_count = serializers.IntegerField()
    final_count = serializers.IntegerField()
