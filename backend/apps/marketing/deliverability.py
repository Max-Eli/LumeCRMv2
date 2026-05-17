"""Email deliverability primitives.

Three responsibilities consolidated into one module so the policy
boundary is easy to find:

  1. `is_suppressed(email)` — the single source of truth that every
     send path consults before letting a message reach AWS.

  2. `SuppressionCheckingSESBackend` — Django email backend that
     wraps `django_ses.SESBackend`, filtering suppressed recipients
     out of every outbound message transparently. Set as
     `EMAIL_BACKEND` in `lume_crm/settings/prod.py` so all 7 existing
     `EmailMultiAlternatives` callsites are policy-gated with zero
     callsite refactor (and future ones get the same protection for
     free).

  3. `verify_sns_signature(payload)` — X.509 verification of inbound
     AWS SNS notifications. Used by the `/api/aws/ses-events/`
     webhook receiver; rejects everything that didn't come from AWS.

See [ADR 0029] for the full design rationale (platform-wide vs
per-tenant suppression, backend-wrapper choice, complaint
permanence policy, alarm thresholds).
"""

from __future__ import annotations

import base64
import logging
import re

import requests
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.x509 import load_pem_x509_certificate

# django-ses is a prod-only dependency (requirements-prod.txt). In
# dev + CI the import is unavailable; fall back to `object` so the
# class definition still succeeds. The dev EMAIL_BACKEND never
# points at this wrapper, so the fallback is never actually used.
try:
    from django_ses import SESBackend  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover — dev/test environment only
    SESBackend = object  # type: ignore[assignment, misc]

from .models import EmailSuppression

logger = logging.getLogger(__name__)


# ── Suppression check (hot path) ────────────────────────────────────


def is_suppressed(email: str) -> bool:
    """Return True if `email` is on the platform-wide suppression list.

    Hot-path safe — single indexed point-lookup on
    `EmailSuppression.email`, ~100µs. Called by:

      - `SuppressionCheckingSESBackend` (every outbound message).
      - `apps.marketing.sender` (so it can write a SUPPRESSED
        SendLog row with the right reason — the backend would
        otherwise silently drop with only an info log).

    Normalisation: addresses are lowercased + stripped before
    comparison. We don't honour the +tag part (`user+x@gmail.com`
    and `user@gmail.com` are normalised to the latter for the
    Gmail edge case) — Gmail aliases really do reach the same
    inbox, and continuing to send to the +tag after a complaint
    on the bare address would defeat the suppression intent.
    """
    if not email:
        return False
    normalised = _normalise_email(email)
    if not normalised:
        return False
    return EmailSuppression.objects.filter(email=normalised).exists()


def _normalise_email(email: str) -> str:
    """Lowercase, strip, and collapse Gmail-style +tags. See `is_suppressed`."""
    addr = (email or '').strip().lower()
    if '@' not in addr:
        return ''
    local, _, domain = addr.partition('@')
    if domain in ('gmail.com', 'googlemail.com') and '+' in local:
        local = local.split('+', 1)[0]
    return f'{local}@{domain}'


# ── Django email backend wrapper ────────────────────────────────────


def filter_suppressed_recipients(email_messages):
    """Prune suppressed addresses from every message; return the sendable list.

    Pure function — easy to test in isolation against the real
    EmailSuppression table without needing to construct an SES
    backend. The `SuppressionCheckingSESBackend.send_messages`
    method below delegates here so production + tests exercise
    identical code.

      - For each `EmailMessage`, `to` / `cc` / `bcc` are pruned of
        suppressed addresses in place.
      - If a message has no remaining recipients, it is dropped
        from the returned list (with an info log carrying
        domain-only audit metadata — never full addresses).
      - Partial drops (some recipients suppressed, others not) log
        + leave the message in the sendable list with the kept
        recipients.

    Returns the list of messages that should actually be forwarded
    to SES.
    """
    sendable = []
    for msg in email_messages:
        original_to = list(msg.to or [])
        original_cc = list(msg.cc or [])
        original_bcc = list(msg.bcc or [])

        msg.to = [a for a in original_to if not is_suppressed(a)]
        msg.cc = [a for a in original_cc if not is_suppressed(a)]
        msg.bcc = [a for a in original_bcc if not is_suppressed(a)]

        dropped = (
            (len(original_to) - len(msg.to))
            + (len(original_cc) - len(msg.cc))
            + (len(original_bcc) - len(msg.bcc))
        )

        if not (msg.to or msg.cc or msg.bcc):
            logger.info(
                'email.suppressed.all_recipients',
                extra={
                    'subject_length': len(msg.subject or ''),
                    'dropped_count': dropped,
                    # Domain-only audit metadata — never full addresses.
                    'recipient_domains': sorted({
                        a.split('@')[-1].lower()
                        for a in (original_to + original_cc + original_bcc)
                        if '@' in a
                    }),
                },
            )
            continue

        if dropped:
            logger.info(
                'email.suppressed.partial',
                extra={
                    'dropped_count': dropped,
                    'remaining_count': len(msg.to) + len(msg.cc) + len(msg.bcc),
                },
            )

        sendable.append(msg)
    return sendable


class SuppressionCheckingSESBackend(SESBackend):
    """Drop suppressed recipients before forwarding to SES.

    A transparent layer over `django_ses.SESBackend` — every send
    via Django's mail subsystem is filtered. Three motivations to
    layer it here vs. forcing every callsite to use a helper:

      1. There are already 7 `EmailMultiAlternatives` callsites
         across portal, forms, invoices, booking, tenants,
         marketing. Refactoring each is invasive and easy to
         forget on the next feature.
      2. Any future callsite that uses Django's mail subsystem is
         policy-gated for free.
      3. Defense in depth: the marketing sender ALSO checks
         `is_suppressed()` up-front so it can write a
         `MarketingSendLog.SUPPRESSED` audit row.

    The filtering itself lives in `filter_suppressed_recipients`
    so tests can exercise it without instantiating an SES backend
    (django-ses is a prod-only dependency).
    """

    def send_messages(self, email_messages):
        sendable = filter_suppressed_recipients(email_messages)
        if not sendable:
            return 0
        return super().send_messages(sendable)


# ── AWS SNS signature verification ──────────────────────────────────


# AWS-owned cert host pattern — SNS message claims include a
# `SigningCertURL`; we reject anything not under this regex BEFORE
# fetching, to prevent attacker-hosted-cert spoofing.
_AWS_SNS_CERT_URL_RE = re.compile(
    r'^https://sns\.[a-z0-9-]+\.amazonaws\.com/[A-Za-z0-9_/.-]+\.pem$'
)

# In-process cache of the AWS signing cert (it rotates ~yearly).
# Bounded by cert URL — different regions get separate entries.
_CERT_CACHE: dict[str, object] = {}


def verify_sns_signature(payload: dict) -> bool:
    """Verify the X.509 signature on an SNS message claim.

    Implements the algorithm from AWS docs:
    https://docs.aws.amazon.com/sns/latest/dg/sns-verify-signature-of-message.html

    1. Reject if `SigningCertURL` isn't on the AWS cert host pattern.
    2. Fetch + cache the cert.
    3. Build the canonical string-to-sign for the message Type.
    4. RSA verify with the cert's public key against base64-decoded
       `Signature`.

    Returns True on a valid signature, False otherwise. Never raises
    — webhook handlers turn False into a 200-with-rejection response
    (same posture as ADR 0027 §3 for Meta webhooks: never 4xx the
    provider, even for bad data).
    """
    try:
        cert_url = payload.get('SigningCertURL', '') or ''
        if not _AWS_SNS_CERT_URL_RE.match(cert_url):
            logger.warning(
                'sns.sig.bad_cert_url',
                extra={'cert_url_length': len(cert_url)},
            )
            return False

        sig_b64 = payload.get('Signature', '') or ''
        if not sig_b64:
            return False

        cert = _fetch_signing_cert(cert_url)
        if cert is None:
            return False

        canonical = _canonical_string(payload)
        if canonical is None:
            return False

        signature = base64.b64decode(sig_b64)

        # SNS uses RSA-SHA1 for SignatureVersion=1 and RSA-SHA256 for
        # SignatureVersion=2. Honour the claim.
        sig_version = (payload.get('SignatureVersion') or '1').strip()
        hash_alg = hashes.SHA256() if sig_version == '2' else hashes.SHA1()

        cert.public_key().verify(
            signature,
            canonical.encode('utf-8'),
            padding.PKCS1v15(),
            hash_alg,
        )
        return True
    except InvalidSignature:
        logger.warning('sns.sig.invalid')
        return False
    except Exception:  # noqa: BLE001 — webhook MUST stay 200
        logger.exception('sns.sig.verify_unexpected_error')
        return False


def _fetch_signing_cert(cert_url: str):
    """Fetch + cache the AWS PEM cert at `cert_url`.

    Returns None on any fetch / parse failure (caller treats as
    "signature unverifiable" → reject).
    """
    cached = _CERT_CACHE.get(cert_url)
    if cached is not None:
        return cached
    try:
        resp = requests.get(cert_url, timeout=5)
        resp.raise_for_status()
        cert = load_pem_x509_certificate(resp.content)
        _CERT_CACHE[cert_url] = cert
        return cert
    except Exception:  # noqa: BLE001 — failure → return None, caller rejects
        logger.exception('sns.sig.cert_fetch_failed')
        return None


def _canonical_string(payload: dict) -> str | None:
    """Build the canonical string-to-sign per SNS docs.

    Field set depends on `Type`:

      - `Notification`:
            Message\\n<msg>\\n
            MessageId\\n<id>\\n
            [Subject\\n<subj>\\n]      # only when Subject is present
            Timestamp\\n<ts>\\n
            TopicArn\\n<arn>\\n
            Type\\n<type>\\n

      - `SubscriptionConfirmation` / `UnsubscribeConfirmation`:
            Message\\n<msg>\\n
            MessageId\\n<id>\\n
            SubscribeURL\\n<url>\\n
            Timestamp\\n<ts>\\n
            Token\\n<token>\\n
            TopicArn\\n<arn>\\n
            Type\\n<type>\\n

    Returns None on unknown `Type` (caller rejects).
    """
    msg_type = payload.get('Type', '') or ''
    if msg_type == 'Notification':
        keys = ['Message', 'MessageId']
        if 'Subject' in payload and payload.get('Subject') is not None:
            keys.append('Subject')
        keys += ['Timestamp', 'TopicArn', 'Type']
    elif msg_type in ('SubscriptionConfirmation', 'UnsubscribeConfirmation'):
        keys = [
            'Message', 'MessageId', 'SubscribeURL',
            'Timestamp', 'Token', 'TopicArn', 'Type',
        ]
    else:
        logger.warning('sns.sig.unknown_type', extra={'msg_type': msg_type})
        return None

    parts = []
    for key in keys:
        value = payload.get(key)
        if value is None:
            return None
        parts.append(f'{key}\n{value}\n')
    return ''.join(parts)


# ── Suppression upsert helpers (called by the webhook receiver) ─────


def record_bounce(*, email: str, bounce_subtype: str, message_id: str, raw: dict) -> EmailSuppression | None:
    """Upsert an EmailSuppression row for a permanent SES bounce.

    Returns the row (created or updated). Returns None when `email`
    is empty / malformed — caller logs + continues.

    Idempotency: a second bounce on the same address bumps
    `last_seen_at` + `event_count`, never duplicates.
    """
    normalised = _normalise_email(email)
    if not normalised:
        return None
    row, created = EmailSuppression.objects.get_or_create(
        email=normalised,
        defaults={
            'reason': EmailSuppression.Reason.BOUNCE_PERMANENT,
            'bounce_subtype': bounce_subtype or '',
            'ses_message_id': message_id or '',
            'raw_event': raw,
            'notes': f'auto: permanent bounce ({bounce_subtype or "unknown subtype"})',
        },
    )
    if not created:
        row.event_count = (row.event_count or 0) + 1
        row.save(update_fields=['event_count', 'last_seen_at'])
    return row


def record_complaint(*, email: str, complaint_subtype: str, message_id: str, raw: dict) -> EmailSuppression | None:
    """Upsert an EmailSuppression row for an SES complaint."""
    normalised = _normalise_email(email)
    if not normalised:
        return None
    row, created = EmailSuppression.objects.get_or_create(
        email=normalised,
        defaults={
            'reason': EmailSuppression.Reason.COMPLAINT,
            'complaint_subtype': complaint_subtype or '',
            'ses_message_id': message_id or '',
            'raw_event': raw,
            'notes': f'auto: complaint ({complaint_subtype or "unknown subtype"})',
        },
    )
    if not created:
        row.event_count = (row.event_count or 0) + 1
        # Promote bounce → complaint on overlap; complaint is stronger
        # (ISP-cooperative: a user explicitly marked us as spam).
        if row.reason != EmailSuppression.Reason.COMPLAINT:
            row.reason = EmailSuppression.Reason.COMPLAINT
            row.complaint_subtype = complaint_subtype or ''
            row.save(update_fields=[
                'event_count', 'reason', 'complaint_subtype', 'last_seen_at',
            ])
        else:
            row.save(update_fields=['event_count', 'last_seen_at'])
    return row
