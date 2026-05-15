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


# ── Twilio status callback ──────────────────────────────────────────


class TwilioStatusCallbackView(APIView):
    """`POST /api/marketing/twilio/status-callback/` — Twilio delivery
    webhook.

    Twilio POSTs here when an SMS we sent changes state:
    queued → sent → delivered, or queued → failed / undelivered.
    We update the matching MarketingSendLog row (correlated by the
    Twilio Message SID we stored as provider_message_id) so the
    operator's campaign-detail send-log reflects real delivery, not
    just "we handed it off to Twilio."

    Auth: Twilio signs every request via X-Twilio-Signature
    (HMAC-SHA1 over the full URL + sorted body params, using our
    TWILIO_AUTH_TOKEN as the key). We verify with the SDK's
    RequestValidator. Spoofed callbacks return 403.

    Body shape (form-encoded by Twilio):
      - MessageSid: SM...
      - MessageStatus: queued / sent / delivered / failed / undelivered
      - ErrorCode, ErrorMessage: present on failure
    """

    permission_classes = [AllowAny]
    authentication_classes = []
    # Twilio sends form-encoded data; CSRF is bypassed via the
    # signature check below (X-Twilio-Signature is the auth, not the
    # CSRF cookie).

    def post(self, request):
        from django.conf import settings

        from .models import MarketingSendLog

        if not _verify_twilio_signature(request):
            return Response({'detail': 'Bad signature.'}, status=status.HTTP_403_FORBIDDEN)

        message_sid = request.data.get('MessageSid', '').strip()
        message_status = request.data.get('MessageStatus', '').strip()
        error_code = request.data.get('ErrorCode', '').strip()
        error_message = request.data.get('ErrorMessage', '').strip()

        if not message_sid:
            return Response({'detail': 'MessageSid required.'}, status=status.HTTP_400_BAD_REQUEST)

        # Map Twilio's status vocabulary to ours. Twilio also emits
        # "queued" and "sending" on the way up; we treat those as
        # SENT (our model doesn't track sub-states between handoff
        # and final delivery).
        update_fields: dict = {}
        if message_status in ('queued', 'sending', 'sent'):
            update_fields['status'] = MarketingSendLog.Status.SENT
            update_fields['sent_at'] = timezone.now()
        elif message_status == 'delivered':
            update_fields['status'] = MarketingSendLog.Status.DELIVERED
            update_fields['delivered_at'] = timezone.now()
        elif message_status in ('failed', 'undelivered'):
            update_fields['status'] = MarketingSendLog.Status.FAILED
            update_fields['failed_at'] = timezone.now()
            update_fields['failure_reason'] = (
                f'twilio:{error_code} {error_message}'.strip()[:500]
            )

        if not update_fields:
            # Status we don't care about (e.g. "accepted") — 200 OK
            # so Twilio doesn't retry, but no row update.
            return Response({'ok': True, 'noop': True})

        updated = MarketingSendLog.objects.filter(
            provider_message_id=message_sid,
        ).update(**update_fields)

        if updated == 0:
            # Unknown SID — could be a callback for a send we don't
            # know about (replay, test from Twilio console, race with
            # row insert). 200 OK so Twilio doesn't retry; the audit
            # log captures the orphan callback for inspection.
            return Response({'ok': True, 'unmatched': True})

        return Response({'ok': True})


def _verify_twilio_signature(request) -> bool:
    """Verify the X-Twilio-Signature header on an inbound webhook.

    Twilio docs:
    https://www.twilio.com/docs/usage/webhooks/webhooks-security

    The signature is HMAC-SHA1(url + sorted_body_params,
    auth_token). The SDK's RequestValidator does the math; we just
    need to supply the full URL we received the call at (including
    the proxy-aware scheme) + the body params.

    In test mode (TWILIO_TEST_MODE=True) we skip verification so
    unit tests can POST without signing — they're using fake data
    anyway. Same with completely-empty TWILIO_AUTH_TOKEN (would-
    be-an-IF-but-we-don't-have-Twilio-configured-at-all).
    """
    from django.conf import settings

    token = getattr(settings, 'TWILIO_AUTH_TOKEN', '')
    if getattr(settings, 'TWILIO_TEST_MODE', False) or not token:
        return True

    from twilio.request_validator import RequestValidator

    signature = request.META.get('HTTP_X_TWILIO_SIGNATURE', '')
    if not signature:
        return False

    # Twilio signs the URL Twilio thinks it called. Use our public
    # callback URL (configured in settings) so a proxy that rewrites
    # Host doesn't break verification. Fallback to request.build_
    # absolute_uri() when the setting isn't pinned (dev only).
    url = (
        getattr(settings, 'TWILIO_STATUS_CALLBACK_URL', '')
        or request.build_absolute_uri()
    )

    validator = RequestValidator(token)
    return validator.validate(url, dict(request.data.items()), signature)
