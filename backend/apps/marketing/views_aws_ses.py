"""AWS SNS receiver for SES bounce + complaint events.

Public endpoint at `/api/aws/ses-events/`. AllowAny + CSRF-exempt:
the security boundary is AWS's X.509 signature on every SNS
message (`apps.marketing.deliverability.verify_sns_signature`).

Two message types handled:

  - `SubscriptionConfirmation` — when SNS first attaches to our
    endpoint, it sends this with a `SubscribeURL`. We GET the URL
    to confirm. Idempotent — repeat confirmations are harmless.

  - `Notification` — wraps an SES event in the `Message` field
    (a nested JSON string per AWS conventions). We parse it and
    dispatch on `eventType`:

      - `Bounce` with `bounceType == 'Permanent'` → suppress every
        bounced address. Transient bounces are logged but never
        suppressed (they may recover).
      - `Complaint` → suppress every complained address regardless
        of subtype. A complaint is a binding "stop sending to me."
      - `Delivery` / `Send` / `Open` / `Click` → logged at info
        level for ops visibility; no DB writes.
      - Unknown `eventType` → logged + 200 OK.

Per ADR 0027 §3 (Meta webhooks) and ADR 0029, we NEVER 4xx the
provider. A signature failure, bad JSON, or unknown shape returns
200 with `{received: false, reason: ...}` so AWS doesn't enter a
retry storm against us.
"""

from __future__ import annotations

import json
import logging

import requests
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .deliverability import (
    record_bounce,
    record_complaint,
    verify_sns_signature,
)

logger = logging.getLogger(__name__)


class SnsEventReceiverView(APIView):
    """AWS SNS → SES event ingestion endpoint."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        raw = request.body
        try:
            payload = json.loads(raw.decode('utf-8') or '{}')
        except (ValueError, UnicodeDecodeError):
            logger.warning('aws.ses.webhook.bad_json', extra={'body_length': len(raw)})
            return Response(
                {'received': False, 'reason': 'bad_json'},
                status=status.HTTP_200_OK,
            )

        if not verify_sns_signature(payload):
            logger.warning('aws.ses.webhook.bad_signature')
            return Response(
                {'received': False, 'reason': 'invalid_signature'},
                status=status.HTTP_200_OK,
            )

        msg_type = payload.get('Type', '') or ''

        if msg_type == 'SubscriptionConfirmation':
            return self._handle_subscription_confirmation(payload)
        if msg_type == 'UnsubscribeConfirmation':
            # SNS sends this when the topic is unsubscribed; benign log.
            logger.info('aws.ses.webhook.unsubscribe_confirmation')
            return Response({'received': True}, status=status.HTTP_200_OK)
        if msg_type == 'Notification':
            return self._handle_notification(payload)

        logger.warning('aws.ses.webhook.unknown_type', extra={'msg_type': msg_type})
        return Response(
            {'received': False, 'reason': 'unknown_type'},
            status=status.HTTP_200_OK,
        )

    # ── Subscription confirm ────────────────────────────────────────

    def _handle_subscription_confirmation(self, payload: dict) -> Response:
        """GET the SubscribeURL to confirm the SNS topic attachment.

        SNS retries the confirmation message until the URL is hit,
        so a transient failure here is recoverable on the next attempt.
        """
        subscribe_url = payload.get('SubscribeURL', '') or ''
        if not subscribe_url:
            return Response(
                {'received': False, 'reason': 'missing_subscribe_url'},
                status=status.HTTP_200_OK,
            )
        try:
            resp = requests.get(subscribe_url, timeout=5)
            resp.raise_for_status()
        except Exception as e:  # noqa: BLE001
            logger.exception(
                'aws.ses.webhook.subscribe_failed',
                extra={'error': str(e)[:200]},
            )
            return Response(
                {'received': True, 'subscribed': False},
                status=status.HTTP_200_OK,
            )
        logger.info('aws.ses.webhook.subscribed', extra={
            'topic_arn': payload.get('TopicArn', ''),
        })
        return Response(
            {'received': True, 'subscribed': True},
            status=status.HTTP_200_OK,
        )

    # ── Notification dispatch ───────────────────────────────────────

    def _handle_notification(self, payload: dict) -> Response:
        # The SES event lives in `Message` as a nested JSON string.
        try:
            inner = json.loads(payload.get('Message', '') or '{}')
        except (ValueError, TypeError):
            logger.warning('aws.ses.webhook.inner_bad_json')
            return Response(
                {'received': False, 'reason': 'inner_bad_json'},
                status=status.HTTP_200_OK,
            )

        event_type = (inner.get('eventType') or inner.get('notificationType') or '').strip()
        mail = inner.get('mail', {}) or {}
        message_id = mail.get('messageId', '') or ''

        if event_type == 'Bounce':
            return self._handle_bounce(inner, message_id)
        if event_type == 'Complaint':
            return self._handle_complaint(inner, message_id)
        if event_type in ('Delivery', 'Send', 'Open', 'Click', 'Rendering Failure'):
            logger.info(
                'aws.ses.webhook.event',
                extra={'event_type': event_type, 'message_id': message_id},
            )
            return Response({'received': True}, status=status.HTTP_200_OK)

        logger.warning(
            'aws.ses.webhook.unknown_event_type',
            extra={'event_type': event_type},
        )
        return Response(
            {'received': False, 'reason': 'unknown_event_type'},
            status=status.HTTP_200_OK,
        )

    def _handle_bounce(self, inner: dict, message_id: str) -> Response:
        bounce = inner.get('bounce', {}) or {}
        bounce_type = (bounce.get('bounceType') or '').strip()
        bounce_subtype = (bounce.get('bounceSubType') or '').strip()
        recipients = bounce.get('bouncedRecipients', []) or []

        if bounce_type != 'Permanent':
            # Transient → logged, not suppressed.
            logger.info(
                'aws.ses.webhook.bounce_transient',
                extra={
                    'message_id': message_id,
                    'recipient_count': len(recipients),
                    'bounce_subtype': bounce_subtype,
                },
            )
            return Response(
                {'received': True, 'suppressed_count': 0},
                status=status.HTTP_200_OK,
            )

        suppressed = 0
        for rcpt in recipients:
            email = (rcpt.get('emailAddress') or '').strip()
            row = record_bounce(
                email=email,
                bounce_subtype=bounce_subtype,
                message_id=message_id,
                raw=inner,
            )
            if row is not None:
                suppressed += 1

        logger.info(
            'aws.ses.webhook.bounce_permanent',
            extra={
                'message_id': message_id,
                'suppressed_count': suppressed,
                'bounce_subtype': bounce_subtype,
            },
        )
        return Response(
            {'received': True, 'suppressed_count': suppressed},
            status=status.HTTP_200_OK,
        )

    def _handle_complaint(self, inner: dict, message_id: str) -> Response:
        complaint = inner.get('complaint', {}) or {}
        complaint_subtype = (complaint.get('complaintSubType') or '').strip()
        # AWS spec uses `complaintFeedbackType` for the ISP-categorised
        # feedback ("abuse" / "fraud" / etc.); fall back to subtype.
        if not complaint_subtype:
            complaint_subtype = (complaint.get('complaintFeedbackType') or '').strip()
        recipients = complaint.get('complainedRecipients', []) or []

        suppressed = 0
        for rcpt in recipients:
            email = (rcpt.get('emailAddress') or '').strip()
            row = record_complaint(
                email=email,
                complaint_subtype=complaint_subtype,
                message_id=message_id,
                raw=inner,
            )
            if row is not None:
                suppressed += 1

        logger.info(
            'aws.ses.webhook.complaint',
            extra={
                'message_id': message_id,
                'suppressed_count': suppressed,
                'complaint_subtype': complaint_subtype,
            },
        )
        return Response(
            {'received': True, 'suppressed_count': suppressed},
            status=status.HTTP_200_OK,
        )
