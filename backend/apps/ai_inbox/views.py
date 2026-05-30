"""HTTP surface for the AI inbox app.

Three concerns:

  1. Per-conversation operator controls — pause / resume / status.
     Mounted under /api/ai-inbox/conversations/<customer_id>/...
  2. Tenant-level config CRUD — get / patch AIConfig.
     Mounted under /api/ai-inbox/config/
  3. Escalation alerts — list + acknowledge + resolve.
     Mounted under /api/ai-inbox/escalations/...

All gated by ``IsTenantStaff + PlanFeatureRequired(F_AI_INBOX)`` so a
tenant without the feature flag can't poll the endpoints (returns
402, consistent with the rest of plan-gated surfaces).

Every state-changing call writes an ``AuditLog`` row via
``apps.audit.services.record`` — operator action attribution is part
of the safety story (see ADR 0032 §"Default-off safety contract").
"""

from __future__ import annotations

import logging

from django.shortcuts import get_object_or_404
from django.utils import timezone as djtz
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import ViewSet

from apps.audit.models import AuditLog
from apps.audit.services import record
from apps.customers.models import Customer
from apps.tenants.api_permissions import IsTenantStaff
from apps.tenants.plan_permissions import PlanFeatureRequired
from apps.tenants.plans import F_AI_INBOX

from .models import AIConfig, AIConversation, EscalationAlert
from .serializers import (
    AIConfigSerializer,
    AIConversationStatusSerializer,
    EscalationAlertSerializer,
)

logger = logging.getLogger(__name__)


_AI_GATE = PlanFeatureRequired(F_AI_INBOX)


# ── Per-conversation controls ────────────────────────────────────


class AIConversationViewSet(ViewSet):
    """Operator controls for one (tenant, customer) AI conversation.

    Routed by customer_id (not AIConversation.id) so the inbox UI —
    which natively knows the customer — doesn't have to round-trip
    to find the conversation row first.
    """

    permission_classes = [IsTenantStaff, _AI_GATE]
    lookup_value_regex = r'\d+'

    def _get_conversation(self, request, customer_id: int) -> AIConversation:
        """Resolve the AIConversation for (current tenant, customer).

        Auto-creates the conversation row if it doesn't exist yet —
        the operator clicked a thread for a customer the AI hasn't
        engaged with, but it could be enabled mid-flight. Returns
        the row in ACTIVE state.
        """
        tenant = request.tenant
        # Customer must belong to this tenant (defense in depth — the
        # IsTenantStaff permission scopes the user to the tenant but
        # explicit Customer lookup prevents URL-fuzzing across tenants).
        customer = get_object_or_404(
            Customer, tenant=tenant, id=customer_id,
        )
        conversation, _ = AIConversation.objects.get_or_create(
            tenant=tenant, customer=customer,
            defaults={'status': AIConversation.Status.ACTIVE},
        )
        return conversation

    def retrieve(self, request, pk: str | None = None):
        """GET /api/ai-inbox/conversations/<customer_id>/

        Returns the AI status for the conversation: status enum,
        when paused / escalated, escalation reason, when last AI
        message landed, exchange count.
        """
        conv = self._get_conversation(request, int(pk))
        return Response(AIConversationStatusSerializer(conv).data)

    @action(detail=True, methods=['post'], url_path='pause')
    def pause(self, request, pk: str | None = None):
        """POST /api/ai-inbox/conversations/<customer_id>/pause/

        Flips the conversation to PAUSED so guardrails block AI
        replies. Idempotent — pausing an already-paused conversation
        is a no-op (returns the current state).
        """
        conv = self._get_conversation(request, int(pk))
        if conv.status == AIConversation.Status.PAUSED:
            return Response(AIConversationStatusSerializer(conv).data)
        conv.status = AIConversation.Status.PAUSED
        conv.paused_by = request.user
        conv.paused_at = djtz.now()
        conv.save(update_fields=['status', 'paused_by', 'paused_at', 'updated_at'])
        record(
            action=AuditLog.Action.UPDATE,
            resource_type='ai_conversation',
            resource_id=conv.id,
            user=request.user, tenant=request.tenant, request=request,
            metadata={'event': 'paused', 'customer_id': conv.customer_id},
        )
        return Response(AIConversationStatusSerializer(conv).data)

    @action(detail=True, methods=['post'], url_path='resume')
    def resume(self, request, pk: str | None = None):
        """POST /api/ai-inbox/conversations/<customer_id>/resume/

        Flips PAUSED (or ESCALATED) back to ACTIVE. Clears the
        paused_by / paused_at / escalated_at fields so the AI takes
        over from the next inbound. Escalations are also resolvable
        via the dedicated escalations endpoint; this one is the
        inbox-side shortcut.
        """
        conv = self._get_conversation(request, int(pk))
        if conv.status == AIConversation.Status.ACTIVE:
            return Response(AIConversationStatusSerializer(conv).data)
        conv.status = AIConversation.Status.ACTIVE
        conv.paused_by = None
        conv.paused_at = None
        conv.escalated_at = None
        conv.escalation_reason = ''
        conv.save(update_fields=[
            'status', 'paused_by', 'paused_at',
            'escalated_at', 'escalation_reason', 'updated_at',
        ])
        # Auto-resolve any open escalation alerts on this conversation —
        # the operator's manual resume IS the resolution.
        EscalationAlert.objects.filter(
            conversation=conv, resolved_at__isnull=True,
        ).update(
            resolved_at=djtz.now(),
            acknowledged_at=djtz.now(),
            acknowledged_by=request.user,
        )
        record(
            action=AuditLog.Action.UPDATE,
            resource_type='ai_conversation',
            resource_id=conv.id,
            user=request.user, tenant=request.tenant, request=request,
            metadata={'event': 'resumed', 'customer_id': conv.customer_id},
        )
        return Response(AIConversationStatusSerializer(conv).data)


# ── AIConfig CRUD ────────────────────────────────────────────────


class AIConfigView(APIView):
    """GET + PATCH the per-tenant AIConfig.

    Creates the row lazily on GET so the Settings UI doesn't need a
    separate "initialize" call. PATCH allows updating any field; the
    Go-Live gate (enabling out of test_mode without a real TFN, etc.)
    is enforced via field-level validation in the serializer.
    """

    permission_classes = [IsTenantStaff, _AI_GATE]

    def get(self, request):
        config, _ = AIConfig.objects.get_or_create(tenant=request.tenant)
        return Response(AIConfigSerializer(config).data)

    def patch(self, request):
        config, _ = AIConfig.objects.get_or_create(tenant=request.tenant)
        serializer = AIConfigSerializer(
            config, data=request.data, partial=True,
            context={'tenant': request.tenant},
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        record(
            action=AuditLog.Action.UPDATE,
            resource_type='ai_config',
            resource_id=config.id,
            user=request.user, tenant=request.tenant, request=request,
            metadata={
                'event': 'ai_config_updated',
                'fields_changed': sorted(serializer.validated_data.keys()),
            },
        )
        return Response(serializer.data)


# ── Escalation alerts ────────────────────────────────────────────


class EscalationAlertViewSet(ViewSet):
    """Open + closed escalation alerts. Drives the dashboard widget."""

    permission_classes = [IsTenantStaff, _AI_GATE]

    def list(self, request):
        """GET /api/ai-inbox/escalations/?status=open|all

        Default: status=open (acknowledged_at IS NULL). status=all
        returns the last 100 alerts in either state.
        """
        qs = EscalationAlert.objects.filter(tenant=request.tenant)
        status_filter = (request.query_params.get('status') or 'open').lower()
        if status_filter == 'open':
            qs = qs.filter(acknowledged_at__isnull=True)
        qs = qs.select_related('customer').order_by('-created_at')[:100]
        return Response(EscalationAlertSerializer(qs, many=True).data)

    @action(detail=True, methods=['post'], url_path='acknowledge')
    def acknowledge(self, request, pk: str | None = None):
        alert = get_object_or_404(
            EscalationAlert, tenant=request.tenant, id=int(pk),
        )
        if alert.acknowledged_at is None:
            alert.acknowledged_at = djtz.now()
            alert.acknowledged_by = request.user
            alert.save(update_fields=['acknowledged_at', 'acknowledged_by'])
        return Response(EscalationAlertSerializer(alert).data)

    @action(detail=True, methods=['post'], url_path='resolve')
    def resolve(self, request, pk: str | None = None):
        alert = get_object_or_404(
            EscalationAlert, tenant=request.tenant, id=int(pk),
        )
        now = djtz.now()
        update_fields = []
        if alert.acknowledged_at is None:
            alert.acknowledged_at = now
            alert.acknowledged_by = request.user
            update_fields += ['acknowledged_at', 'acknowledged_by']
        if alert.resolved_at is None:
            alert.resolved_at = now
            update_fields.append('resolved_at')
        if update_fields:
            alert.save(update_fields=update_fields)
        return Response(EscalationAlertSerializer(alert).data)
