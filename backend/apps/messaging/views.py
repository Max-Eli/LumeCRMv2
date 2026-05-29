"""Customer messaging API.

Four operator-facing endpoints + one Twilio inbound webhook:

    GET    /api/messaging/threads/                  — inbox list
    GET    /api/messaging/conversations/<cid>/       — full thread
    POST   /api/messaging/conversations/<cid>/send/  — operator sends SMS
    POST   /api/messaging/conversations/<cid>/mark-read/ — clear unread
    POST   /api/messaging/twilio/incoming/           — Twilio inbound webhook
                                                       (no auth; signed)

Permission model:

  - Operator paths are gated by `IsAuthenticated`. SMS bodies are
    PHI; every read writes an `AuditLog` entry. A future tighten-
    behind-`VIEW_CLIENT_PHI` polish would mirror what we did for
    the customer detail endpoint (ADR 0017).
  - The Twilio webhook is `AllowAny` — Twilio doesn't carry a
    session cookie. Authenticity is enforced by the X-Twilio-
    Signature HMAC (same pattern as the marketing status-callback
    in `apps.marketing.views_public.TwilioStatusCallbackView`).

See [ADR 0022 — Customer messaging inbox].
"""

from __future__ import annotations

import logging
import re

from django.conf import settings
from django.db.models import Max, OuterRef, Q, Subquery
from django.utils import timezone as djtz
from rest_framework import status, viewsets
from rest_framework.decorators import action

from apps.tenants.plan_permissions import PlanFeatureRequired
from apps.tenants.plans import F_SMS_INBOX

# Plan gate: the 2-way SMS inbox is a Pro+ feature. The Twilio webhook
# (AllowAny) is NOT gated — Twilio doesn't know about plans + we need
# to accept inbound replies for compliance regardless of tier; sends
# are what's blocked. The MessagingViewSet covers the sends, and
# SavedReplyViewSet drives the templates. Both gated below.
_SMS_INBOX_GATE = PlanFeatureRequired(F_SMS_INBOX)
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny

from apps.tenants.api_permissions import IsTenantStaff
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.models import AuditLog
from apps.audit.services import record
from apps.customers.models import Customer
from apps.tenants.context import get_current_tenant
from apps.tenants.models import Tenant

from .models import Direction, Message, MessageStatus, SavedReply
from .serializers import (
    AutomatedTemplatesSerializer,
    MessageSerializer,
    SavedReplySerializer,
    SendMessageInputSerializer,
    ThreadSummarySerializer,
)

logger = logging.getLogger(__name__)


# ── Phone normalisation ───────────────────────────────────────────────


_DIGITS_RE = re.compile(r'\D+')


def _normalize_e164(phone: str) -> str:
    """Best-effort E.164 normalisation for North American numbers.

    Twilio webhooks always send E.164 (`+15551234567`). Customer phones
    in our DB are operator-typed and could be anything: `(555) 123-4567`,
    `555.123.4567`, `5551234567`, `+15551234567`. We strip everything
    non-digit, then prepend `+1` if it's 10 digits or `+` if it's 11
    digits starting with 1.

    Non-NANP numbers (international) would need country-code logic;
    we cross that bridge when a US medspa needs Canadian SMS support.
    """
    if not phone:
        return ''
    digits = _DIGITS_RE.sub('', phone.strip())
    if len(digits) == 10:
        return f'+1{digits}'
    if len(digits) == 11 and digits.startswith('1'):
        return f'+{digits}'
    if phone.startswith('+'):
        return f'+{digits}'
    return digits  # unrecognised; caller can decide


# ── Threads list + conversation detail ───────────────────────────────


class MessagingViewSet(viewsets.ViewSet):
    """Inbox + conversation detail + send + mark-read.

    Modelled as a ViewSet so the URLs share a common prefix and DRF
    auto-routes the standard verbs; the routes themselves are
    detail-on-customer-id (not on message-id) because there's no
    consumer of an individual-message URL.
    """

    permission_classes = [IsTenantStaff, _SMS_INBOX_GATE]
    http_method_names = ['get', 'post', 'head', 'options']

    # `list` → /threads/ : inbox view, one row per customer.
    def list(self, request):
        tenant = get_current_tenant()
        if tenant is None:
            return Response([])

        # Most-recent message per customer, scoped to tenant. Done with
        # a subquery + window-ish aggregate: get the max created_at per
        # customer, then fetch the matching row.
        latest_per_customer = (
            Message.objects
            .filter(tenant=tenant)
            .values('customer_id')
            .annotate(latest=Max('created_at'))
        )

        threads_qs = (
            Message.objects
            .filter(tenant=tenant)
            .filter(
                customer_id__in=Subquery(latest_per_customer.values('customer_id')),
                created_at__in=Subquery(latest_per_customer.values('latest')),
            )
            .select_related('customer')
            .order_by('-created_at')
        )

        # Unread counts per customer (inbound + read_at IS NULL).
        unread_rows = (
            Message.objects
            .filter(
                tenant=tenant,
                direction=Direction.INBOUND,
                read_at__isnull=True,
            )
            .values('customer_id')
            .annotate(c=Max('id'))  # count would do; using max-of-id as the cheap shape
        )
        unread_by_customer = {
            row['customer_id']: Message.objects.filter(
                tenant=tenant,
                customer_id=row['customer_id'],
                direction=Direction.INBOUND,
                read_at__isnull=True,
            ).count()
            for row in unread_rows
        }

        data = [
            {
                'customer_id': m.customer_id,
                'customer_first_name': m.customer.first_name,
                'customer_last_name': m.customer.last_name,
                'customer_phone': m.customer.phone,
                'last_message_id': m.id,
                'last_message_body': m.body,
                'last_message_direction': m.direction,
                'last_message_at': m.created_at,
                'unread_inbound_count': unread_by_customer.get(m.customer_id, 0),
            }
            for m in threads_qs
        ]

        record(
            action=AuditLog.Action.READ,
            resource_type='messaging_threads',
            request=request,
            metadata={'count': len(data)},
        )

        return Response(ThreadSummarySerializer(data, many=True).data)

    # `retrieve` → /conversations/<customer_id>/ : full message history.
    def retrieve(self, request, pk=None):
        tenant = get_current_tenant()
        if tenant is None:
            raise PermissionDenied('No tenant context.')

        try:
            customer = Customer.objects.get(pk=pk, tenant=tenant)
        except Customer.DoesNotExist:
            return Response({'detail': 'Customer not found.'}, status=status.HTTP_404_NOT_FOUND)

        # Chronological ascending so the UI can render top-to-bottom
        # without re-reversing.
        msgs = (
            Message.objects
            .filter(tenant=tenant, customer=customer)
            .order_by('created_at')
            .select_related('sent_by')
        )

        data = MessageSerializer(msgs, many=True).data

        record(
            action=AuditLog.Action.READ,
            resource_type='messaging_conversation',
            resource_id=customer.id,
            request=request,
            metadata={'count': len(data)},
        )

        return Response({
            'customer': {
                'id': customer.id,
                'first_name': customer.first_name,
                'last_name': customer.last_name,
                'phone': customer.phone,
                'sms_opt_in': customer.sms_opt_in,
            },
            'messages': data,
        })

    @action(detail=True, methods=['post'], url_path='send')
    def send(self, request, pk=None):
        """Operator sends an SMS to the customer.

        Validates the body, checks consent + reachability (same gate
        as the appointment-SMS path: phone on file + `sms_opt_in=True`),
        renders nothing (no token substitution — operator types the
        actual message), routes through the per-tenant TFN via
        `apps.appointments.sms.send_sms`, persists the row, returns
        it for the frontend to render optimistically.
        """
        tenant = get_current_tenant()
        if tenant is None:
            raise PermissionDenied('No tenant context.')

        try:
            customer = Customer.objects.get(pk=pk, tenant=tenant)
        except Customer.DoesNotExist:
            return Response({'detail': 'Customer not found.'}, status=status.HTTP_404_NOT_FOUND)

        ser = SendMessageInputSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        body = ser.validated_data['body']

        if not (customer.phone or '').strip():
            raise ValidationError({'detail': 'Customer has no phone number on file.'})
        if not customer.sms_opt_in:
            raise ValidationError({
                'detail': (
                    'Customer has not consented to SMS. Toggle "Send SMS '
                    'confirmations and reminders" on their profile first.'
                ),
            })

        # Resolve the From: number through the same per-tenant
        # helper the appointment-SMS path uses so the resolution
        # logic stays in one place.
        from apps.appointments.sms import (
            SMSDispatchError,
            _phone_redact,
            _resolve_from_number,
            send_sms,
        )

        from_number = _resolve_from_number(tenant)

        message = Message.objects.create(
            tenant=tenant,
            customer=customer,
            direction=Direction.OUTBOUND,
            body=body,
            status=MessageStatus.QUEUED,
            from_number=from_number,
            to_number=customer.phone,
            sent_by=request.user if request.user.is_authenticated else None,
        )

        try:
            sid = send_sms(tenant=tenant, to=customer.phone, body=body)
        except SMSDispatchError as e:
            message.status = MessageStatus.FAILED
            message.failure_reason = str(e)[:500]
            message.failed_at = djtz.now()
            message.save(update_fields=['status', 'failure_reason', 'failed_at', 'updated_at'])
            record(
                action=AuditLog.Action.UPDATE,
                resource_type='messaging_message',
                resource_id=message.id,
                request=request,
                metadata={
                    'event': 'send_failed',
                    'customer_id': customer.id,
                    'recipient_last4': _phone_redact(customer.phone)[-4:],
                    'error': str(e)[:300],
                },
            )
            raise ValidationError({'detail': f'Could not send: {e}'})

        # Empty SID == stub mode (Twilio creds not configured). Mark
        # status anyway so the row reflects "attempted" and the
        # operator doesn't think nothing happened.
        message.provider_message_id = sid
        message.status = MessageStatus.SENT if sid else MessageStatus.QUEUED
        message.sent_at = djtz.now() if sid else None
        message.save(update_fields=['provider_message_id', 'status', 'sent_at', 'updated_at'])

        record(
            action=AuditLog.Action.CREATE,
            resource_type='messaging_message',
            resource_id=message.id,
            request=request,
            metadata={
                'event': 'sent',
                'customer_id': customer.id,
                'recipient_last4': _phone_redact(customer.phone)[-4:],
                'provider_message_id': sid,
                'body_length': len(body),
            },
        )

        return Response(MessageSerializer(message).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'], url_path='mark-read')
    def mark_read(self, request, pk=None):
        """Clear unread state — sets `read_at = now` on every inbound
        message in this thread that hasn't been read yet."""
        tenant = get_current_tenant()
        if tenant is None:
            raise PermissionDenied('No tenant context.')

        # Validate the customer is in this tenant (404 instead of
        # silently no-op'ing a cross-tenant request).
        if not Customer.objects.filter(pk=pk, tenant=tenant).exists():
            return Response({'detail': 'Customer not found.'}, status=status.HTTP_404_NOT_FOUND)

        now = djtz.now()
        updated = (
            Message.objects
            .filter(
                tenant=tenant, customer_id=pk,
                direction=Direction.INBOUND,
                read_at__isnull=True,
            )
            .update(read_at=now, updated_at=now)
        )
        record(
            action=AuditLog.Action.UPDATE,
            resource_type='messaging_conversation',
            resource_id=pk,
            request=request,
            metadata={'event': 'marked_read', 'rows_updated': updated},
        )
        return Response({'rows_updated': updated})


# ── Twilio inbound webhook ───────────────────────────────────────────


class TwilioInboundView(APIView):
    """`POST /api/messaging/twilio/incoming/` — receives inbound SMS / MMS.

    Twilio POSTs form-encoded data when a customer texts our TFN.
    Same signature-verification posture as the marketing status-
    callback endpoint (`X-Twilio-Signature` HMAC over URL + body).

    Inbound matching:
      - `To` = our TFN → identifies the tenant (we look up by
        `Tenant.twilio_from_number`).
      - `From` = the customer's phone → we look up Customer by
        normalised phone scoped to that tenant.
      - If the tenant has no matching customer, the row is still
        stored (with `customer=None` won't work because the FK is
        required) — we ATTACH to a synthetic "unknown sender"
        customer record? No — we drop with a log, surface in
        CloudWatch, and rely on the operator to add the customer
        manually if they want to keep the thread.

    For v1: unknown-sender → 200 OK to Twilio (no retry) but no
    row stored, log captures the phone. Operators can search audit
    logs to recover any missed messages.

    HTTP STOP / START handling: Twilio takes care of carrier opt-
    out automatically (their "Advanced Opt-Out" feature). When a
    customer texts STOP, Twilio short-circuits the message + sends
    a confirmation reply on our behalf + flags the number as
    opted-out for our account. We never see the STOP on this
    webhook. (If we did, we'd flip `customer.sms_opt_in=False`.)
    """

    permission_classes = [AllowAny]
    authentication_classes: list = []

    def post(self, request):
        if not _verify_twilio_signature(request):
            return Response({'detail': 'Bad signature.'}, status=status.HTTP_403_FORBIDDEN)

        from_number = (request.data.get('From') or '').strip()
        to_number = (request.data.get('To') or '').strip()
        body = (request.data.get('Body') or '').strip()
        message_sid = (request.data.get('MessageSid') or '').strip()
        try:
            num_media = int(request.data.get('NumMedia') or 0)
        except (TypeError, ValueError):
            num_media = 0
        media_urls = [
            (request.data.get(f'MediaUrl{i}') or '').strip()
            for i in range(num_media)
        ]
        media_urls = [u for u in media_urls if u]

        if not from_number or not to_number:
            return Response({'detail': 'Missing From/To.'}, status=status.HTTP_400_BAD_REQUEST)

        # Identify the tenant by the destination number (our TFN).
        tenant = Tenant.objects.filter(twilio_from_number=to_number).first()
        if tenant is None:
            logger.warning(
                'messaging.inbound.unknown_tenant_tfn',
                extra={'to': to_number, 'sid': message_sid},
            )
            return Response({'ok': True, 'unmatched': 'tenant'})

        # Identify the customer by phone within the tenant's customer
        # list. Normalise both sides to E.164 for comparison so
        # operator-typed numbers (with parens, dashes, dots) match.
        e164_from = _normalize_e164(from_number)
        customer = None
        for c in Customer.objects.filter(tenant=tenant).only('id', 'phone'):
            if _normalize_e164(c.phone) == e164_from:
                customer = c
                break

        if customer is None:
            logger.warning(
                'messaging.inbound.unknown_customer',
                extra={
                    'tenant_slug': tenant.slug,
                    'from_last4': from_number[-4:],
                    'sid': message_sid,
                },
            )
            return Response({'ok': True, 'unmatched': 'customer'})

        # Idempotency: if we've already recorded this MessageSid,
        # don't duplicate. Twilio retries on 5xx; we return 200 either
        # way to break the retry loop.
        if message_sid and Message.objects.filter(
            tenant=tenant, provider_message_id=message_sid,
        ).exists():
            return Response({'ok': True, 'duplicate': True})

        Message.objects.create(
            tenant=tenant,
            customer=customer,
            direction=Direction.INBOUND,
            body=body,
            status=MessageStatus.RECEIVED,
            provider_message_id=message_sid,
            from_number=from_number,
            to_number=to_number,
            media_urls='\n'.join(media_urls) if media_urls else '',
        )

        # No audit log on inbound creates — `_dispatch` is async; the
        # operator's UI is what triggers the audit-loggable read.

        # Twilio docs: empty <Response/> means "no auto-reply." We
        # rely on the operator's UI for replies, so empty TwiML.
        return Response('', content_type='application/xml')


def _verify_twilio_signature(request) -> bool:
    """Same signature-verification approach as the marketing status-
    callback endpoint. See its docstring for the rationale + the
    test-mode bypass."""
    token = getattr(settings, 'TWILIO_AUTH_TOKEN', '')
    if getattr(settings, 'TWILIO_TEST_MODE', False) or not token:
        return True

    from twilio.request_validator import RequestValidator

    signature = request.META.get('HTTP_X_TWILIO_SIGNATURE', '')
    if not signature:
        return False

    # Twilio signs the URL it called. We don't have a configured
    # public URL setting for the inbound webhook the way we do for
    # the status callback, so fall back to request.build_absolute_uri.
    # Behind ALB+CloudFront, `request.build_absolute_uri()` resolves
    # to the public-facing URL via SECURE_PROXY_SSL_HEADER.
    url = request.build_absolute_uri()
    validator = RequestValidator(token)
    return validator.validate(url, dict(request.data.items()), signature)


# ── Saved replies (canned templates) ─────────────────────────────────


class SavedReplyViewSet(viewsets.ModelViewSet):
    """`/api/messaging/saved-replies/` — full CRUD for the operator's
    canned inbox templates.

    Tenant-shared by design: anyone on staff can read, create, edit,
    or delete any reply. This mirrors how Front / Boulevard / Slack
    quick-replies work — they're a shared brand-voice resource, not a
    per-user notebook. If individual-scoped templates ever become a
    real ask, we add an `owner` FK + a `visibility` choice.

    Body content is **not** PHI in v1: operators paste canned answers
    to common questions ("our address is …"); the PHI substitution
    only happens at send-time when the operator types the customer-
    specific personalisation into the composer. So we skip the per-
    read audit log (which would just clutter the trail with template
    reads). Mutations are audit-logged so the trail can answer "who
    changed the address reply?"
    """

    permission_classes = [IsTenantStaff, _SMS_INBOX_GATE]
    serializer_class = SavedReplySerializer
    http_method_names = ['get', 'post', 'put', 'patch', 'delete', 'head', 'options']

    def get_queryset(self):
        tenant = get_current_tenant()
        if tenant is None:
            return SavedReply.objects.none()
        return SavedReply.objects.filter(tenant=tenant).select_related('created_by')

    def perform_create(self, serializer):
        tenant = get_current_tenant()
        if tenant is None:
            raise PermissionDenied('No tenant context.')
        instance = serializer.save(
            tenant=tenant,
            created_by=self.request.user if self.request.user.is_authenticated else None,
        )
        record(
            action=AuditLog.Action.CREATE,
            resource_type='messaging_saved_reply',
            resource_id=instance.id,
            request=self.request,
            metadata={'name': instance.name},
        )

    def perform_update(self, serializer):
        instance = serializer.save()
        record(
            action=AuditLog.Action.UPDATE,
            resource_type='messaging_saved_reply',
            resource_id=instance.id,
            request=self.request,
            metadata={'name': instance.name},
        )

    def perform_destroy(self, instance):
        record(
            action=AuditLog.Action.DELETE,
            resource_type='messaging_saved_reply',
            resource_id=instance.id,
            request=self.request,
            metadata={'name': instance.name},
        )
        instance.delete()


# ── Automated SMS templates (tenant settings) ────────────────────────


class AutomatedTemplatesView(APIView):
    """`/api/messaging/automated-templates/` — GET + PATCH the
    tenant's three automated-SMS bodies + review-request settings.

    Singleton resource per tenant (the rows live as fields on Tenant
    itself, not in a separate table). PATCH semantics: omit a field
    to leave it untouched. GET always returns the full shape +
    platform default bodies so the UI can render the "reset to
    default" affordance.
    """

    permission_classes = [IsTenantStaff, _SMS_INBOX_GATE]

    def get(self, request):
        tenant = get_current_tenant()
        if tenant is None:
            raise PermissionDenied('No tenant context.')
        ser = AutomatedTemplatesSerializer(instance=tenant)
        return Response(ser.data)

    def patch(self, request):
        tenant = get_current_tenant()
        if tenant is None:
            raise PermissionDenied('No tenant context.')

        ser = AutomatedTemplatesSerializer(instance=tenant, data=request.data, partial=True)
        ser.is_valid(raise_exception=True)

        update_fields: list[str] = []
        for field in (
            'confirmation_sms_template',
            'reminder_sms_template',
            'review_request_sms_template',
            'review_request_enabled',
            'review_request_hours_after',
            'google_review_url',
        ):
            if field in ser.validated_data:
                setattr(tenant, field, ser.validated_data[field])
                update_fields.append(field)
        if update_fields:
            tenant.save(update_fields=[*update_fields, 'updated_at'])

        record(
            action=AuditLog.Action.UPDATE,
            resource_type='tenant_automated_templates',
            resource_id=tenant.id,
            request=request,
            metadata={'fields': update_fields},
        )

        # Return the fresh resource so the frontend reconciles state.
        return Response(AutomatedTemplatesSerializer(instance=tenant).data)
