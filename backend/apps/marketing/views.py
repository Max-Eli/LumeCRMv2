"""Marketing API — Phase 1L sessions 1 + 2.

Surface (under `/api/marketing/`):

    GET    /audiences/                List the tenant's audiences.
    POST   /audiences/                Create.
    GET    /audiences/<id>/           Retrieve.
    PATCH  /audiences/<id>/           Update; rejected if used in a campaign.
    DELETE /audiences/<id>/           Delete; rejected if used in a campaign.
    POST   /audiences/<id>/preview/   Live count + per-channel breakdown.

    GET    /templates/                List templates.
    POST   /templates/                Create with token allowlist + CAN-SPAM check.
    GET    /templates/<id>/           Retrieve.
    PATCH  /templates/<id>/           Update.
    DELETE /templates/<id>/           Delete.
    POST   /templates/<id>/preview/   Render against sample / real customer.

    GET    /campaigns/                List.
    POST   /campaigns/                Create as DRAFT.
    GET    /campaigns/<id>/           Retrieve detail (audience + template inlined).
    PATCH  /campaigns/<id>/           Update name / scheduled_at while DRAFT.
    DELETE /campaigns/<id>/           Delete (DRAFT + CANCELLED only).
    POST   /campaigns/<id>/schedule/  DRAFT → SCHEDULED (locks recipient list).
    POST   /campaigns/<id>/cancel/    DRAFT|SCHEDULED → CANCELLED.
    GET    /campaigns/<id>/send_log/  Per-customer send rows for this campaign.

Permission gating: `MarketingWritePermission` on the viewsets means
`VIEW_AUDIENCE_SEGMENTS` for read, `SEND_MARKETING_CAMPAIGN` for
writes that produce sends.

Automations endpoints land alongside this session — see
AutomationViewSet below.
"""

from __future__ import annotations

from django.db import IntegrityError
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from apps.audit.models import AuditLog
from apps.audit.services import record
from apps.tenants.context import get_current_tenant

from .audiences import count_audience, execute_filter
from .automations import preview_automation
from .sender import dispatch_campaign, fire_automation
from .models import (
    Audience,
    Automation,
    Campaign,
    Channel,
    MarketingSendLog,
    MarketingTemplate,
)
from .permissions import MarketingWritePermission
from .serializers import (
    AudienceCountSerializer,
    AudienceSerializer,
    AutomationPreviewSerializer,
    AutomationSerializer,
    CampaignCreateSerializer,
    CampaignListSerializer,
    CampaignScheduleSerializer,
    CampaignSerializer,
    MarketingSendLogSerializer,
    MarketingTemplatePreviewResultSerializer,
    MarketingTemplatePreviewSerializer,
    MarketingTemplateSerializer,
)
from .templates_tokens import discover_tokens, render_preview


class AudienceViewSet(viewsets.ModelViewSet):
    """CRUD + preview for `Audience` rows, scoped per tenant."""

    serializer_class = AudienceSerializer
    permission_classes = [MarketingWritePermission]
    http_method_names = ['get', 'post', 'patch', 'delete', 'head', 'options']

    def get_queryset(self):
        return Audience.objects.for_current_tenant().select_related('created_by')

    # ── CRUD ────────────────────────────────────────────────────────

    def create(self, request, *args, **kwargs):  # noqa: ARG002
        tenant = get_current_tenant()
        if tenant is None:
            raise PermissionDenied('No tenant context resolved for this request.')

        ser = self.get_serializer(data=request.data)
        ser.is_valid(raise_exception=True)

        # Tenant + name uniqueness is enforced at the DB layer; the
        # serializer doesn't see `tenant` (auto-set), so we catch the
        # collision here and surface it as a clean 400 with a useful
        # field-level error rather than a 500.
        try:
            audience = Audience.objects.create(
                tenant=tenant,
                created_by=request.user if request.user.is_authenticated else None,
                **ser.validated_data,
            )
        except IntegrityError:
            raise ValidationError({
                'name': 'An audience with this name already exists.',
            })
        # Compute the cached count on create so the list page renders
        # a useful number immediately rather than 0.
        audience.last_member_count = count_audience(
            tenant=tenant, spec=audience.filter_spec or {},
        )
        audience.last_counted_at = timezone.now()
        audience.save(update_fields=['last_member_count', 'last_counted_at'])

        record(
            action=AuditLog.Action.CREATE,
            resource_type='audience',
            resource_id=audience.pk,
            request=request,
            metadata={
                'name': audience.name,
                'filter_dimensions': sorted((audience.filter_spec or {}).keys()),
                'initial_member_count': audience.last_member_count,
            },
        )

        return Response(
            self.get_serializer(audience).data,
            status=status.HTTP_201_CREATED,
        )

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        partial = kwargs.pop('partial', False)
        ser = self.get_serializer(instance, data=request.data, partial=partial)
        ser.is_valid(raise_exception=True)

        old_filter = instance.filter_spec or {}
        updated = ser.save()

        new_filter = updated.filter_spec or {}
        if new_filter != old_filter:
            updated.last_member_count = count_audience(
                tenant=updated.tenant, spec=new_filter,
            )
            updated.last_counted_at = timezone.now()
            updated.save(update_fields=['last_member_count', 'last_counted_at'])

        record(
            action=AuditLog.Action.UPDATE,
            resource_type='audience',
            resource_id=updated.pk,
            request=request,
            metadata={
                'fields_changed': sorted(ser.validated_data.keys()),
                'filter_changed': new_filter != old_filter,
            },
        )
        return Response(self.get_serializer(updated).data)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        # Reject destroy if the audience is used in any non-cancelled
        # campaign. Same posture as the read-only-after-use rule on
        # update — keeps the audit attribution stable.
        if instance.campaigns.exclude(
            status__in=[Campaign.Status.DRAFT, Campaign.Status.CANCELLED],
        ).exists():
            raise ValidationError({
                'detail': (
                    'This audience has been used in a campaign and cannot be '
                    'deleted. Archive it instead by removing all draft / '
                    'cancelled campaign references first.'
                ),
            })

        record(
            action=AuditLog.Action.DELETE,
            resource_type='audience',
            resource_id=instance.pk,
            request=request,
            metadata={'name': instance.name},
        )
        return super().destroy(request, *args, **kwargs)

    # ── Preview / live count ───────────────────────────────────────

    @action(detail=True, methods=['post'])
    def preview(self, request, pk=None):
        """`POST /api/marketing/audiences/<id>/preview/` — live count.

        Returns three numbers:
          - `total_count` — the unfiltered audience size (operator's
            "I have X customers in this segment" view)
          - `email_eligible_count` — how many of those have email
            marketing consent + no suppression + an email on file
            (the count that would actually receive an email send)
          - `sms_eligible_count` — same shape for SMS

        The two channel-eligible counts give the operator a clear
        picture of how much of the segment is actually reachable
        through each channel before they commit to a campaign.

        Persists the freshly-computed `total_count` as the cached
        value on the row so the list page reflects the latest
        number.
        """
        audience = self.get_object()
        tenant = audience.tenant
        spec = audience.filter_spec or {}

        total = count_audience(tenant=tenant, spec=spec)
        email_eligible = count_audience(
            tenant=tenant, spec=spec, apply_channel_consent='email',
        )
        sms_eligible = count_audience(
            tenant=tenant, spec=spec, apply_channel_consent='sms',
        )

        # Refresh the cached value while we're at it.
        audience.last_member_count = total
        audience.last_counted_at = timezone.now()
        audience.save(update_fields=['last_member_count', 'last_counted_at'])

        record(
            action=AuditLog.Action.READ,
            resource_type='audience',
            resource_id=audience.pk,
            request=request,
            metadata={
                'event': 'preview',
                'total_count': total,
                'email_eligible_count': email_eligible,
                'sms_eligible_count': sms_eligible,
            },
        )

        return Response(AudienceCountSerializer({
            'total_count': total,
            'email_eligible_count': email_eligible,
            'sms_eligible_count': sms_eligible,
        }).data)


# ── Marketing templates ─────────────────────────────────────────────


class MarketingTemplateViewSet(viewsets.ModelViewSet):
    """CRUD for marketing email + SMS templates with the token
    allowlist validator wired in the serializer.

    The preview action lets the operator render the template against
    a sample (or real) customer to see what gets dispatched —
    catches typo'd tokens and missing fields before scheduling.
    """

    serializer_class = MarketingTemplateSerializer
    permission_classes = [MarketingWritePermission]
    http_method_names = ['get', 'post', 'patch', 'delete', 'head', 'options']

    def get_queryset(self):
        qs = MarketingTemplate.objects.for_current_tenant().select_related('created_by')
        params = self.request.query_params
        channel_param = (params.get('channel') or '').strip().lower()
        if channel_param in {'email', 'sms'}:
            qs = qs.filter(channel=channel_param)
        active_param = (params.get('active') or '').strip().lower()
        if active_param in {'true', '1'}:
            qs = qs.filter(is_active=True)
        return qs

    def create(self, request, *args, **kwargs):  # noqa: ARG002
        tenant = get_current_tenant()
        if tenant is None:
            raise PermissionDenied('No tenant context resolved for this request.')
        ser = self.get_serializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            template = MarketingTemplate.objects.create(
                tenant=tenant,
                created_by=request.user if request.user.is_authenticated else None,
                **ser.validated_data,
            )
        except IntegrityError:
            raise ValidationError({'name': 'A template with this name already exists.'})

        record(
            action=AuditLog.Action.CREATE,
            resource_type='marketing_template',
            resource_id=template.pk,
            request=request,
            metadata={
                'channel': template.channel,
                'name': template.name,
                'tokens': sorted(set(discover_tokens(template.body))),
            },
        )
        return Response(
            self.get_serializer(template).data,
            status=status.HTTP_201_CREATED,
        )

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        partial = kwargs.pop('partial', False)
        ser = self.get_serializer(instance, data=request.data, partial=partial)
        ser.is_valid(raise_exception=True)
        updated = ser.save()
        record(
            action=AuditLog.Action.UPDATE,
            resource_type='marketing_template',
            resource_id=updated.pk,
            request=request,
            metadata={'fields_changed': sorted(ser.validated_data.keys())},
        )
        return Response(self.get_serializer(updated).data)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        # Reject delete if any non-cancelled campaign references the
        # template — historical campaigns need their template intact
        # for audit reconstruction. Operator deactivates instead
        # (`is_active=False`) to retire a template.
        if instance.campaigns.exclude(
            status__in=[Campaign.Status.DRAFT, Campaign.Status.CANCELLED],
        ).exists():
            raise ValidationError({
                'detail': (
                    'This template has been used in a campaign and cannot '
                    'be deleted. Set is_active=false to retire it instead.'
                ),
            })
        record(
            action=AuditLog.Action.DELETE,
            resource_type='marketing_template',
            resource_id=instance.pk,
            request=request,
            metadata={'name': instance.name},
        )
        return super().destroy(request, *args, **kwargs)

    @action(detail=True, methods=['post'])
    def preview(self, request, pk=None):
        """Render the template against a sample customer + return the
        expanded body. When `customer_id` is supplied, render against
        that real record; otherwise build a synthetic sample so the
        operator can preview without picking a row."""
        template = self.get_object()
        tenant = template.tenant
        ser = MarketingTemplatePreviewSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        customer_id = ser.validated_data.get('customer_id')

        from apps.customers.models import Customer
        from types import SimpleNamespace

        if customer_id:
            try:
                customer = Customer.objects.get(pk=customer_id, tenant=tenant)
            except Customer.DoesNotExist:
                raise ValidationError({'customer_id': 'Customer not found.'})
        else:
            # Synthetic sample — covers all the allowlisted tokens
            # without any real PHI.
            import datetime as dt
            customer = SimpleNamespace(
                first_name='Jane',
                last_name='Sample',
                date_of_birth=dt.date(1990, 5, 15),
            )

        rendered_body = render_preview(template.body, customer=customer, tenant=tenant)
        # Subject is also tokenizable (mostly for "Hi {{first_name}}!"
        # subject lines) — same allowlist, same renderer.
        rendered_subject = render_preview(
            template.subject or '', customer=customer, tenant=tenant,
        )
        return Response(MarketingTemplatePreviewResultSerializer({
            'subject': rendered_subject,
            'body': rendered_body,
            'discovered_tokens': sorted(set(discover_tokens(template.body or ''))),
        }).data)


# ── Campaigns ───────────────────────────────────────────────────────


class CampaignViewSet(viewsets.ModelViewSet):
    """CRUD + status-transition actions for Campaigns.

    Status flow:

        draft → scheduled (via /schedule/ — locks recipient list)
        draft → cancelled (via /cancel/)
        scheduled → cancelled (via /cancel/)
        scheduled → sending → sent (worker; not in v1 — see Session 3)

    Direct PATCH on `status` is rejected; transitions go through
    dedicated action endpoints so the audit log + side-effects
    (snapshot, email-send, etc.) all run.
    """

    permission_classes = [MarketingWritePermission]
    http_method_names = ['get', 'post', 'patch', 'delete', 'head', 'options']

    def get_queryset(self):
        qs = (
            Campaign.objects
            .for_current_tenant()
            .select_related('audience', 'template', 'created_by')
        )
        params = self.request.query_params
        status_param = (params.get('status') or '').strip()
        if status_param:
            qs = qs.filter(status=status_param)
        channel_param = (params.get('channel') or '').strip().lower()
        if channel_param in {'email', 'sms'}:
            qs = qs.filter(channel=channel_param)
        return qs

    def get_serializer_class(self):
        if self.action == 'create':
            return CampaignCreateSerializer
        if self.action == 'list':
            return CampaignListSerializer
        return CampaignSerializer

    def create(self, request, *args, **kwargs):  # noqa: ARG002
        tenant = get_current_tenant()
        if tenant is None:
            raise PermissionDenied('No tenant context resolved for this request.')
        ser = CampaignCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        # Tenant-scope FK validation — DRF's PrimaryKeyRelatedField
        # walks the queryset, but we verify the tenant explicitly
        # since the serializer doesn't see request.tenant.
        if data['audience'].tenant_id != tenant.pk:
            raise ValidationError({'audience': 'Not found in this tenant.'})
        if data['template'].tenant_id != tenant.pk:
            raise ValidationError({'template': 'Not found in this tenant.'})

        # Channel auto-derives from template — the create form
        # doesn't ask for it.
        campaign = Campaign.objects.create(
            tenant=tenant,
            channel=data['template'].channel,
            status=Campaign.Status.DRAFT,
            created_by=request.user if request.user.is_authenticated else None,
            **data,
        )
        record(
            action=AuditLog.Action.CREATE,
            resource_type='marketing_campaign',
            resource_id=campaign.pk,
            request=request,
            metadata={
                'name': campaign.name,
                'channel': campaign.channel,
                'audience_id': campaign.audience_id,
                'template_id': campaign.template_id,
            },
        )
        return Response(
            CampaignSerializer(campaign).data,
            status=status.HTTP_201_CREATED,
        )

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        # Only DRAFT campaigns are editable. Once SCHEDULED, the
        # recipient list snapshot is locked; once SENDING/SENT/
        # CANCELLED, the campaign is terminal-ish for any field
        # except the audit aggregates.
        if instance.status != Campaign.Status.DRAFT:
            raise ValidationError({
                'detail': (
                    f'Only DRAFT campaigns can be edited '
                    f'(status: {instance.status}). Cancel and clone if '
                    f'changes are needed.'
                ),
            })
        # Allow editing name + scheduled_at only.
        allowed = {'name', 'scheduled_at'}
        invalid = set(request.data.keys()) - allowed
        if invalid:
            raise ValidationError({
                k: 'Cannot edit this field after creation.' for k in invalid
            })
        partial = kwargs.pop('partial', True)  # PATCH-only
        ser = CampaignSerializer(instance, data=request.data, partial=partial)
        ser.is_valid(raise_exception=True)
        updated = ser.save()
        record(
            action=AuditLog.Action.UPDATE,
            resource_type='marketing_campaign',
            resource_id=updated.pk,
            request=request,
            metadata={'fields_changed': sorted(allowed & set(request.data.keys()))},
        )
        return Response(CampaignSerializer(updated).data)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        # Only DRAFT + CANCELLED campaigns are deletable. SCHEDULED /
        # SENDING / SENT carry audit weight; deleting them would
        # destroy the record of who-was-sent-what.
        if instance.status not in (Campaign.Status.DRAFT, Campaign.Status.CANCELLED):
            raise ValidationError({
                'detail': (
                    f'Cannot delete a {instance.status} campaign. '
                    f'Cancel it first if not yet sent.'
                ),
            })
        record(
            action=AuditLog.Action.DELETE,
            resource_type='marketing_campaign',
            resource_id=instance.pk,
            request=request,
            metadata={'name': instance.name, 'status': instance.status},
        )
        return super().destroy(request, *args, **kwargs)

    @action(detail=True, methods=['post'])
    def schedule(self, request, pk=None):
        """`POST /campaigns/<id>/schedule/` — DRAFT → SCHEDULED.

        Snapshots the recipient list count so a late audience edit
        doesn't silently expand the blast. The actual recipient set
        is re-resolved at send time (worker, Session 3) — what we
        snapshot here is the *count* the operator agreed to.

        Pass `send_now=true` to queue for immediate dispatch
        regardless of `scheduled_at`. v1 doesn't actually send (no
        SES/Twilio yet) — the campaign stays SCHEDULED until the
        worker is wired in Session 3.
        """
        campaign = self.get_object()
        if campaign.status != Campaign.Status.DRAFT:
            raise ValidationError({
                'detail': (
                    f'Only DRAFT campaigns can be scheduled '
                    f'(status: {campaign.status}).'
                ),
            })
        ser = CampaignScheduleSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        send_now = ser.validated_data['send_now']

        # Snapshot the recipient count with the channel-consent gate
        # applied — that's the real "X people will get this" number,
        # not the unfiltered audience size.
        consent_channel = campaign.channel  # 'email' or 'sms'
        recipient_count = count_audience(
            tenant=campaign.tenant,
            spec=campaign.audience.filter_spec or {},
            apply_channel_consent=consent_channel,
        )
        campaign.recipient_count_snapshot = recipient_count
        campaign.status = Campaign.Status.SCHEDULED
        if send_now:
            campaign.scheduled_at = timezone.now()
        campaign.save(update_fields=[
            'recipient_count_snapshot', 'status', 'scheduled_at', 'updated_at',
        ])

        record(
            action=AuditLog.Action.UPDATE,
            resource_type='marketing_campaign',
            resource_id=campaign.pk,
            request=request,
            metadata={
                'event': 'scheduled',
                'send_now': send_now,
                'scheduled_at': campaign.scheduled_at.isoformat() if campaign.scheduled_at else None,
                'recipient_count_snapshot': recipient_count,
            },
        )
        return Response(CampaignSerializer(campaign).data)

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        """`POST /campaigns/<id>/cancel/` — DRAFT|SCHEDULED → CANCELLED.

        Idempotent on already-cancelled. Once SENDING or SENT, cancel
        is rejected — the message is on its way / out the door.
        """
        campaign = self.get_object()
        if campaign.status == Campaign.Status.CANCELLED:
            return Response(CampaignSerializer(campaign).data)
        if campaign.status not in (Campaign.Status.DRAFT, Campaign.Status.SCHEDULED):
            raise ValidationError({
                'detail': (
                    f'Cannot cancel a {campaign.status} campaign. '
                    f'It has already started sending.'
                ),
            })
        previous_status = campaign.status
        campaign.status = Campaign.Status.CANCELLED
        campaign.save(update_fields=['status', 'updated_at'])
        record(
            action=AuditLog.Action.UPDATE,
            resource_type='marketing_campaign',
            resource_id=campaign.pk,
            request=request,
            metadata={
                'event': 'cancelled',
                'from_status': previous_status,
            },
        )
        return Response(CampaignSerializer(campaign).data)

    @action(detail=True, methods=['get'], url_path='send-log')
    def send_log(self, request, pk=None):
        """`GET /campaigns/<id>/send-log/` — per-customer send rows.

        Read-only. Used by the campaign detail page's send-log
        section. Empty until the worker dispatches (Session 3); at
        v1 the rows are written in stub mode when a SCHEDULED
        campaign hits its `scheduled_at` (no actual provider call).
        """
        campaign = self.get_object()
        rows = (
            MarketingSendLog.objects
            .filter(tenant=campaign.tenant, campaign=campaign)
            .select_related('customer')
            .order_by('-created_at')
        )
        return Response(MarketingSendLogSerializer(rows, many=True).data)

    @action(detail=True, methods=['post'], url_path='dispatch')
    def dispatch_now(self, request, pk=None):
        """`POST /campaigns/<id>/dispatch/` — trigger the send worker.

        Synchronously dispatches the campaign right now. In v1 this
        is a manual operator action ("Send now"). In production
        Celery beat picks up SCHEDULED campaigns at their
        `scheduled_at` and calls this internally.

        Idempotent: campaigns past SCHEDULED are no-ops. Stub-mode
        sends (no SES/Twilio wired) write SendLog rows with
        synthetic provider IDs so the audit trail flows end-to-end
        — the day the providers are connected, the same code paths
        run real API calls.
        """
        campaign = self.get_object()
        if campaign.status not in (Campaign.Status.SCHEDULED, Campaign.Status.SENDING):
            raise ValidationError({
                'detail': (
                    f'Campaign must be SCHEDULED before dispatch '
                    f'(currently {campaign.status}). Schedule it first.'
                ),
            })

        result = dispatch_campaign(campaign)
        record(
            action=AuditLog.Action.UPDATE,
            resource_type='marketing_campaign',
            resource_id=campaign.pk,
            request=request,
            metadata={
                'event': 'dispatched',
                **result,
            },
        )
        # Refetch to get the fresh aggregates.
        campaign.refresh_from_db()
        return Response(CampaignSerializer(campaign).data)


# ── Automations (always-on triggered campaigns) ─────────────────────


class AutomationViewSet(viewsets.ModelViewSet):
    """CRUD for `Automation` rows + a preview action that returns
    eligibility counts (with vs without dedup + consent gating).

    Channel auto-derives from the chosen template; the serializer
    rejects a template/audience cross-tenant pairing. New
    automations land with `is_active=False` so the operator
    previews the eligibility count + template + dedup window
    before turning the automation on.
    """

    serializer_class = AutomationSerializer
    permission_classes = [MarketingWritePermission]
    http_method_names = ['get', 'post', 'patch', 'delete', 'head', 'options']

    def get_queryset(self):
        qs = (
            Automation.objects
            .for_current_tenant()
            .select_related('template', 'audience', 'created_by')
        )
        params = self.request.query_params
        active = (params.get('active') or '').strip().lower()
        if active in {'true', '1'}:
            qs = qs.filter(is_active=True)
        elif active in {'false', '0'}:
            qs = qs.filter(is_active=False)
        return qs

    def create(self, request, *args, **kwargs):  # noqa: ARG002
        tenant = get_current_tenant()
        if tenant is None:
            raise PermissionDenied('No tenant context resolved for this request.')
        ser = self.get_serializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        template = data['template']
        if template.tenant_id != tenant.pk:
            raise ValidationError({'template': 'Not found in this tenant.'})
        if data.get('audience') and data['audience'].tenant_id != tenant.pk:
            raise ValidationError({'audience': 'Not found in this tenant.'})

        try:
            automation = Automation.objects.create(
                tenant=tenant,
                channel=template.channel,
                created_by=request.user if request.user.is_authenticated else None,
                **data,
            )
        except IntegrityError:
            raise ValidationError({'name': 'An automation with this name already exists.'})

        record(
            action=AuditLog.Action.CREATE,
            resource_type='marketing_automation',
            resource_id=automation.pk,
            request=request,
            metadata={
                'name': automation.name,
                'trigger_type': automation.trigger_type,
                'channel': automation.channel,
                'is_active': automation.is_active,
            },
        )
        return Response(
            self.get_serializer(automation).data,
            status=status.HTTP_201_CREATED,
        )

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        partial = kwargs.pop('partial', False)
        ser = self.get_serializer(instance, data=request.data, partial=partial)
        ser.is_valid(raise_exception=True)
        old_active = instance.is_active
        updated = ser.save()
        record(
            action=AuditLog.Action.UPDATE,
            resource_type='marketing_automation',
            resource_id=updated.pk,
            request=request,
            metadata={
                'fields_changed': sorted(ser.validated_data.keys()),
                'is_active_changed': old_active != updated.is_active,
                'is_active': updated.is_active,
            },
        )
        return Response(self.get_serializer(updated).data)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        record(
            action=AuditLog.Action.DELETE,
            resource_type='marketing_automation',
            resource_id=instance.pk,
            request=request,
            metadata={'name': instance.name},
        )
        return super().destroy(request, *args, **kwargs)

    @action(detail=True, methods=['post'])
    def preview(self, request, pk=None):
        """`POST /automations/<id>/preview/` — eligibility counts.

        Returns `total_count` (raw trigger eligibility),
        `consent_eligible_count` (after applying channel-consent
        + suppression), and `final_count` (after dedup against
        recent sends). The drop from consent to final tells the
        operator how much of the eligible set was already sent
        recently — i.e., how busy the trigger is."""
        automation = self.get_object()
        result = preview_automation(automation)
        record(
            action=AuditLog.Action.READ,
            resource_type='marketing_automation',
            resource_id=automation.pk,
            request=request,
            metadata={
                'event': 'preview',
                **result,
            },
        )
        return Response(AutomationPreviewSerializer(result).data)

    @action(detail=True, methods=['post'])
    def fire(self, request, pk=None):
        """`POST /automations/<id>/fire/` — manually fire the
        automation right now.

        In production a Celery beat task calls `fire_automation()`
        on a daily schedule for each active automation. In v1
        operators trigger fires manually via this endpoint while
        testing — and via the management command
        `fire_due_automations` for dev/staging cron jobs. Same
        eligibility evaluation; same SendLog audit posture.

        Stays open even on inactive automations — operators
        sometimes manually fire a paused automation as a one-off
        send. The is_active flag gates the scheduled cadence,
        not manual triggers.
        """
        automation = self.get_object()
        result = fire_automation(automation)
        record(
            action=AuditLog.Action.UPDATE,
            resource_type='marketing_automation',
            resource_id=automation.pk,
            request=request,
            metadata={
                'event': 'manually_fired',
                **result,
            },
        )
        automation.refresh_from_db()
        return Response({
            **result,
            'automation': self.get_serializer(automation).data,
        })


# ── Customer marketing history ──────────────────────────────────────


class CustomerMarketingHistoryView(viewsets.ViewSet):
    """`GET /marketing/customer-sends/?customer=<id>` — per-customer
    marketing send history.

    Used by the customer profile's Marketing tab. Returns the most
    recent 50 rows (campaigns + automation-fired campaigns alike)
    for the requested customer in the current tenant. Rows include
    `status` (sent / delivered / failed / suppressed) so an operator
    can see which messages reached the customer and which were
    suppressed (no consent, unsubscribed, bounced).

    Tenant-scoped via the request membership; only readable to
    users with VIEW_AUDIENCE_SEGMENTS.
    """

    permission_classes = [MarketingWritePermission]

    def list(self, request):
        membership = getattr(request, 'tenant_membership', None)
        if not membership and not request.user.is_superuser:
            raise PermissionDenied('No tenant context resolved.')

        raw = (request.query_params.get('customer') or '').strip()
        if not raw:
            raise ValidationError({'customer': 'customer query param is required.'})
        try:
            customer_id = int(raw)
        except (TypeError, ValueError) as exc:
            raise ValidationError({'customer': 'must be an integer.'}) from exc

        tenant_id = (
            membership.tenant_id if membership
            else (get_current_tenant().pk if get_current_tenant() else None)
        )

        rows = (
            MarketingSendLog.objects
            .filter(tenant_id=tenant_id, customer_id=customer_id)
            .select_related('campaign', 'customer')
            .order_by('-created_at')[:50]
        )
        return Response(MarketingSendLogSerializer(rows, many=True).data)
