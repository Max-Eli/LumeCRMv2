"""Public marketing endpoints — no auth required.

Today: the one-click unsubscribe surface. Mounted at
`/api/marketing/unsubscribe/<token>/`.

Pattern mirrors the booking + form-fill public flows: token IS the
security boundary (256-bit, not enumerable), no session, no CSRF.
Idempotent — visiting an already-used token still returns the
"you're unsubscribed" state without churning state.
"""

from __future__ import annotations

from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.models import AuditLog
from apps.audit.services import record

from .models import Channel, UnsubscribeToken


class PublicUnsubscribeView(APIView):
    """`GET / POST /api/marketing/unsubscribe/<token>/` — flip the
    customer's marketing-suppressed state for the channel this token
    targets.

    GET returns the current state so the frontend can render
    "you're unsubscribed" or "click to confirm" without a server
    round-trip per click. POST is the one-click commit per
    CAN-SPAM (RFC 8058 list-unsubscribe) — flips suppression and
    records the action.

    Audit: every access writes an `AuditLog` entry with the IP +
    user-agent. PHI is the customer's marketing status; the entry
    captures who unsubscribed (no PHI in metadata; just IDs +
    domain).
    """

    permission_classes = [AllowAny]
    authentication_classes = []  # No session, no CSRF.

    @extend_schema(
        responses={
            200: OpenApiResponse(description='Unsubscribe state'),
            404: OpenApiResponse(description='Unknown or invalid token'),
        },
    )
    def get(self, request, token: str):
        record_obj = self._resolve(token)
        return Response(self._payload(record_obj, request))

    @extend_schema(
        responses={
            200: OpenApiResponse(description='Unsubscribed (idempotent)'),
            404: OpenApiResponse(description='Unknown or invalid token'),
        },
    )
    def post(self, request, token: str):
        unsub = self._resolve(token)
        customer = unsub.customer
        already = unsub.used_at is not None

        if not already:
            now = timezone.now()
            unsub.used_at = now
            unsub.used_ip = _client_ip(request)
            unsub.used_user_agent = (request.META.get('HTTP_USER_AGENT') or '')[:500]
            unsub.save(update_fields=[
                'used_at', 'used_ip', 'used_user_agent',
            ])

            # Flip the customer's marketing-suppressed flag for the
            # channel this token targets. Suppression source is the
            # link click (per ADR 0016 enum).
            if unsub.channel == Channel.EMAIL:
                customer.email_marketing_suppressed_at = now
                customer.email_marketing_suppression_source = 'unsubscribe_link'
                customer.save(update_fields=[
                    'email_marketing_suppressed_at',
                    'email_marketing_suppression_source',
                    'updated_at',
                ])
            elif unsub.channel == Channel.SMS:
                customer.sms_marketing_suppressed_at = now
                customer.sms_marketing_suppression_source = 'unsubscribe_link'
                customer.save(update_fields=[
                    'sms_marketing_suppressed_at',
                    'sms_marketing_suppression_source',
                    'updated_at',
                ])

        record(
            action=AuditLog.Action.UPDATE,
            resource_type='customer',
            resource_id=customer.pk,
            tenant=unsub.tenant,
            user=None,
            request=request,
            metadata={
                'event': 'unsubscribed_via_link',
                'channel': unsub.channel,
                'token_id': unsub.pk,
                'idempotent_repeat': already,
            },
        )

        return Response(self._payload(unsub, request))

    # ── Helpers ────────────────────────────────────────────────────

    def _resolve(self, token: str) -> UnsubscribeToken:
        if not token:
            from django.http import Http404
            raise Http404('Unknown unsubscribe link.')
        return get_object_or_404(
            UnsubscribeToken.objects.select_related('customer', 'tenant'),
            token=token,
        )

    def _payload(self, unsub: UnsubscribeToken, request) -> dict:
        # Minimum-necessary disclosure on the public surface — first
        # name only (so the page can say "Hi Pat, you're unsubscribed")
        # plus the spa name + channel. We intentionally do NOT echo
        # back email or phone (no PHI on the public payload).
        return {
            'tenant_name': unsub.tenant.name,
            'channel': unsub.channel,
            'channel_label': dict(Channel.choices).get(unsub.channel, unsub.channel),
            'customer_first_name': unsub.customer.first_name or '',
            'is_unsubscribed': unsub.used_at is not None,
            'unsubscribed_at': unsub.used_at.isoformat() if unsub.used_at else None,
        }


def _client_ip(request) -> str | None:
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')
