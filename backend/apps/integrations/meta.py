"""Meta (Facebook + Instagram + WhatsApp) OAuth + Graph API client.

ADR 0027 is the canonical spec. This module owns:

  - The OAuth flow primitives (state token, authorize URL builder,
    code exchange, page selection, webhook subscription).
  - Graph API HTTP helpers (no per-call retry; the OAuth flow runs
    interactively and a 5xx surfaces as an error the operator can
    retry by clicking Connect again).
  - The webhook payload parser that lifts incoming IG / FB / WA
    messages into our SocialThread + SocialMessage rows.

Why one module: the OAuth dance, the Graph calls, and the webhook
payload shapes are all coupled to Meta's data model. Splitting them
spreads the "I need to think about Meta's quirks" surface across
three files for no benefit. Tests inject by patching `requests.get`
/ `requests.post`.

Module-level constants pin the Graph API version. Bumping it is a
one-line change here.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import hmac
import logging
import secrets
import time
import urllib.parse as _urlparse
from dataclasses import dataclass
from typing import Any

import requests
from django.conf import settings
from django.utils import timezone

from .models import Connection

logger = logging.getLogger(__name__)


# ── Constants ───────────────────────────────────────────────────────


GRAPH_API_VERSION = 'v22.0'
GRAPH_BASE = f'https://graph.facebook.com/{GRAPH_API_VERSION}'
OAUTH_DIALOG_URL = f'https://www.facebook.com/{GRAPH_API_VERSION}/dialog/oauth'

# Per ADR 0027 §2 — state tokens older than this are rejected as
# replays. 10 min is comfortable for a real human consent flow
# without leaving the door open for long-window replays.
STATE_TTL_SECONDS = 600

# Per-provider scope sets. Source of truth lives here AND in
# `providers.py` — the duplication is intentional so the Meta App
# Review submission and the runtime requested scopes can diverge
# during a transitional period. If they drift, audit + reconcile.
# Scope names below are the ones tied to the **Facebook Login for
# Business** flow (the one we use — IG Business account linked to a
# FB Page, page access token drives outbound). Meta also offers a
# newer "Instagram Login with Business" flow whose scopes are prefixed
# `instagram_business_*`; those are NOT valid with FB Login and Meta
# rejects the OAuth request with "Invalid Scopes" if mixed in.
#
# Reference: developers.facebook.com/docs/permissions
SCOPES_INSTAGRAM = (
    'instagram_basic',              # read the IG Business account metadata
    'instagram_manage_messages',    # send + receive DMs
    'pages_show_list',              # list the FB Pages the user manages
    'pages_messaging',              # required to subscribe to the messages webhook
    'pages_manage_metadata',        # subscribe the Page to webhook events
    'business_management',          # required when the Page is owned by a Business Manager
)

# Webhook fields we subscribe a Page to. `messages` covers inbound DMs;
# `messaging_postbacks` covers button clicks (we don't ship Quick
# Replies in v1 but enabling the field now avoids a re-subscribe
# round-trip later). `message_reads` is delivery-receipt data, useful
# for read-status display.
PAGE_SUBSCRIBED_FIELDS = (
    'messages',
    'messaging_postbacks',
    'message_reads',
)


# ── Exceptions ──────────────────────────────────────────────────────


class MetaOAuthError(Exception):
    """Any failure during the OAuth flow that's worth surfacing to
    the operator with a specific message ('We could not find a Page
    with an Instagram Business account', 'Token exchange failed', etc).
    """


class MetaSignatureError(Exception):
    """Webhook payload signature did not match. Callers should log +
    return 200 with `{received: false}` per ADR 0027 §3 — Meta retries
    4xx storms."""


# ── State token (CSRF defence + OAuth code binding) ─────────────────


def generate_state_token() -> str:
    """Cryptographically random 256-bit token, URL-safe base64.

    Each Connect click gets a fresh token; it's stored on the user's
    server-side session and echoed back via the OAuth redirect. The
    callback verifies it matches + isn't expired before doing
    anything with the `code` parameter.
    """
    return secrets.token_urlsafe(32)


def store_state_in_session(request, state: str, *, tenant_id: int, provider: str) -> None:
    """Save the state token + binding context in the user's session.
    The binding (tenant_id, provider, timestamp) lets us reject a
    callback that arrives at the wrong tenant or that was issued
    against a different provider than what's being completed."""
    request.session['meta_oauth_state'] = state
    request.session['meta_oauth_tenant_id'] = tenant_id
    request.session['meta_oauth_provider'] = provider
    request.session['meta_oauth_issued_at'] = int(time.time())
    request.session.modified = True


def consume_state_from_session(request, state_received: str) -> dict[str, Any]:
    """Validate the callback `state` against the session.

    Returns the stored binding dict on success. Raises
    `MetaOAuthError` with a specific message for each failure mode so
    the operator-facing error UX can be precise.
    """
    expected = request.session.get('meta_oauth_state')
    if not expected:
        raise MetaOAuthError(
            'No OAuth flow is in progress. Click Connect again to start over.'
        )
    if not _consteq(state_received, expected):
        raise MetaOAuthError(
            'OAuth state mismatch. This usually means the connect link '
            'was reused or a different browser tab interfered. Click '
            'Connect again to retry.'
        )
    issued_at = request.session.get('meta_oauth_issued_at', 0)
    age = int(time.time()) - int(issued_at)
    if age > STATE_TTL_SECONDS:
        raise MetaOAuthError(
            f'OAuth flow timed out after {STATE_TTL_SECONDS // 60} minutes. '
            'Click Connect again to start over.'
        )

    binding = {
        'tenant_id': request.session.get('meta_oauth_tenant_id'),
        'provider': request.session.get('meta_oauth_provider'),
        'issued_at': issued_at,
    }

    # One-time-use: clear the state immediately so the same callback
    # link can't be replayed (e.g. by browser back button).
    for key in (
        'meta_oauth_state', 'meta_oauth_tenant_id',
        'meta_oauth_provider', 'meta_oauth_issued_at',
    ):
        request.session.pop(key, None)
    request.session.modified = True

    return binding


def _consteq(a: str, b: str) -> bool:
    """Constant-time string comparison for security tokens."""
    return hmac.compare_digest(
        (a or '').encode('utf-8'),
        (b or '').encode('utf-8'),
    )


# ── OAuth dialog URL ────────────────────────────────────────────────


def build_authorize_url(*, provider: str, state: str) -> str:
    """Construct the Facebook OAuth dialog URL for the given provider."""
    if provider == 'meta_instagram':
        scopes = SCOPES_INSTAGRAM
    else:
        # FB Messenger + WhatsApp wire up in future sessions.
        raise MetaOAuthError(
            f'OAuth flow for provider {provider!r} is not implemented yet.'
        )

    params = {
        'client_id': settings.META_APP_ID,
        'redirect_uri': settings.META_OAUTH_REDIRECT_URI,
        'state': state,
        'scope': ','.join(scopes),
        'response_type': 'code',
    }
    return f'{OAUTH_DIALOG_URL}?{_urlparse.urlencode(params)}'


# ── Token exchange ──────────────────────────────────────────────────


@dataclass
class TokenExchangeResult:
    """What we keep after the short-lived → long-lived → page-token chain."""
    page_id: str
    page_name: str
    page_access_token: str
    instagram_business_account_id: str
    instagram_username: str
    granted_scopes: list[str]
    expires_at: int | None  # Unix timestamp; None for non-expiring tokens
    # FB user ID of the person who authorised the connection. Captured
    # so the Meta data-deletion callback can find this Connection when
    # that user later removes the app from their FB settings.
    fb_user_id: str


def exchange_code_for_connection(code: str) -> TokenExchangeResult:
    """Full code → page-token chain for an Instagram connection.

    Steps (per ADR 0027 §2):
      1. Exchange `code` for a short-lived user token.
      2. Exchange short-lived user token for a long-lived (60d) user token.
      3. Call `/me/accounts` to list Pages the user manages.
      4. Pick the first Page that has an `instagram_business_account` link.
      5. The /me/accounts response already includes a Page access token
         derived from the long-lived user token — use it.
      6. Fetch the IG Business Account's username for display.

    Any step that fails raises MetaOAuthError with operator-readable copy.
    """
    short_token = _exchange_code_for_short_token(code)
    long_token = _exchange_short_for_long_token(short_token)
    fb_user_id = _fetch_me_id(long_token)
    pages = _list_pages_with_ig(long_token)

    if not pages:
        raise MetaOAuthError(
            "No Facebook Page with a linked Instagram Business account was "
            "found on this Meta account. Make sure your Instagram is "
            "converted to a Business account and linked to a Facebook Page."
        )

    page = pages[0]  # Session 3 will add a picker for multi-page tenants
    page_id = page['id']
    page_name = page.get('name', '')
    page_access_token = page['access_token']
    ig_business = page.get('instagram_business_account', {}) or {}
    ig_id = ig_business.get('id', '')
    if not ig_id:
        raise MetaOAuthError(
            f'Page {page_name!r} reported an IG link but no Business '
            'Account ID. Reconnect and retry.'
        )

    ig_username = _fetch_ig_username(ig_id, page_access_token)
    granted = _fetch_granted_scopes(long_token)

    # Page access tokens derived from a long-lived user token inherit
    # ~60d expiry. We don't store the precise expiry from this endpoint
    # — Session 2's refresh job re-issues against /me/accounts which
    # always returns a fresh token.
    expires_at = int(time.time()) + 60 * 24 * 3600

    return TokenExchangeResult(
        page_id=page_id,
        page_name=page_name,
        page_access_token=page_access_token,
        instagram_business_account_id=ig_id,
        instagram_username=ig_username,
        granted_scopes=granted,
        expires_at=expires_at,
        fb_user_id=fb_user_id,
    )


def _fetch_me_id(user_access_token: str) -> str:
    """GET /me?fields=id — the FB user ID of the consenting user."""
    response = requests.get(
        f'{GRAPH_BASE}/me',
        params={'access_token': user_access_token, 'fields': 'id'},
        timeout=15,
    )
    payload = _expect_json(response, step='fb user id fetch')
    return payload.get('id', '')


def _exchange_code_for_short_token(code: str) -> str:
    """POST /oauth/access_token — code → short-lived user token."""
    response = requests.get(
        f'{GRAPH_BASE}/oauth/access_token',
        params={
            'client_id': settings.META_APP_ID,
            'client_secret': settings.META_APP_SECRET,
            'redirect_uri': settings.META_OAUTH_REDIRECT_URI,
            'code': code,
        },
        timeout=15,
    )
    return _extract_access_token(response, step='short-token exchange')


def _exchange_short_for_long_token(short_token: str) -> str:
    """Upgrade the short-lived user token to a 60-day long-lived one."""
    response = requests.get(
        f'{GRAPH_BASE}/oauth/access_token',
        params={
            'grant_type': 'fb_exchange_token',
            'client_id': settings.META_APP_ID,
            'client_secret': settings.META_APP_SECRET,
            'fb_exchange_token': short_token,
        },
        timeout=15,
    )
    return _extract_access_token(response, step='long-token exchange')


def _list_pages_with_ig(user_access_token: str) -> list[dict]:
    """GET /me/accounts — returns pages with IG business account info."""
    response = requests.get(
        f'{GRAPH_BASE}/me/accounts',
        params={
            'access_token': user_access_token,
            'fields': 'id,name,access_token,instagram_business_account{id}',
        },
        timeout=15,
    )
    payload = _expect_json(response, step='page listing')
    return [p for p in payload.get('data', []) if p.get('instagram_business_account')]


def _fetch_ig_username(ig_business_account_id: str, page_access_token: str) -> str:
    """GET /{ig-id}?fields=username — display name for the IG account."""
    response = requests.get(
        f'{GRAPH_BASE}/{ig_business_account_id}',
        params={
            'access_token': page_access_token,
            'fields': 'username',
        },
        timeout=15,
    )
    payload = _expect_json(response, step='IG username fetch')
    return payload.get('username', '')


def _fetch_granted_scopes(user_access_token: str) -> list[str]:
    """GET /me/permissions — list of granted permission names."""
    response = requests.get(
        f'{GRAPH_BASE}/me/permissions',
        params={'access_token': user_access_token},
        timeout=15,
    )
    payload = _expect_json(response, step='scope listing')
    return [
        p['permission'] for p in payload.get('data', [])
        if p.get('status') == 'granted'
    ]


def subscribe_page_to_webhooks(*, page_id: str, page_access_token: str) -> None:
    """POST /{page-id}/subscribed_apps — enable webhook delivery."""
    response = requests.post(
        f'{GRAPH_BASE}/{page_id}/subscribed_apps',
        data={
            'access_token': page_access_token,
            'subscribed_fields': ','.join(PAGE_SUBSCRIBED_FIELDS),
        },
        timeout=15,
    )
    payload = _expect_json(response, step='webhook subscription')
    if not payload.get('success', False):
        raise MetaOAuthError(
            f'Meta reported webhook subscription failed: {payload!r}'
        )


def _extract_access_token(response: requests.Response, *, step: str) -> str:
    payload = _expect_json(response, step=step)
    token = payload.get('access_token')
    if not token:
        raise MetaOAuthError(
            f'Meta did not return an access token during {step}: {payload!r}'
        )
    return token


def _expect_json(response: requests.Response, *, step: str) -> dict:
    """Parse + 200-check + surface Meta's error format if non-2xx.

    Meta returns error details in the body even on 4xx, which is the
    most useful diagnostic ("(#190) The access token could not be
    decrypted" tells you exactly what's wrong).
    """
    try:
        body = response.json()
    except ValueError:
        body = {'raw': response.text[:500]}

    if response.status_code >= 400:
        meta_err = body.get('error', body)
        raise MetaOAuthError(
            f'{step} failed ({response.status_code}): '
            f'{meta_err.get("message", meta_err)}'
        )
    return body


# ── Webhook signature verification ──────────────────────────────────


def verify_webhook_signature(
    *, raw_body: bytes, header_value: str,
) -> bool:
    """Verify the `X-Hub-Signature-256` header on an inbound webhook.

    Meta signs the raw request body with HMAC-SHA256 keyed on the
    App Secret. The header is `sha256=<hex digest>`. Constant-time
    compare prevents timing oracles.

    `META_TEST_MODE=True` bypasses for unit tests (mirrors the
    `TWILIO_TEST_MODE` pattern from ADR 0021).
    """
    if getattr(settings, 'META_TEST_MODE', False):
        return True

    if not header_value or not header_value.startswith('sha256='):
        return False

    received = header_value.split('=', 1)[1]
    expected = hmac.new(
        key=settings.META_APP_SECRET.encode('utf-8'),
        msg=raw_body,
        digestmod=hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(received, expected)


# ── Data deletion callback (signed_request) ─────────────────────────


def parse_signed_request(signed_request: str) -> dict[str, Any]:
    """Decode + verify Meta's `signed_request` format.

    The string is `<base64url_signature>.<base64url_payload>`. The
    signature is HMAC-SHA256 over the raw payload string, keyed on
    the App Secret. Returns the decoded payload dict on success;
    raises MetaSignatureError otherwise.

    `META_TEST_MODE=True` skips signature verification (mirrors the
    webhook test toggle) so unit tests don't need to compute HMACs.
    """
    if not signed_request or '.' not in signed_request:
        raise MetaSignatureError('Malformed signed_request — missing separator.')

    sig_b64, payload_b64 = signed_request.split('.', 1)

    try:
        payload_json = _b64url_decode(payload_b64)
    except Exception as e:
        raise MetaSignatureError(f'Could not decode payload: {e}') from e

    try:
        import json as _json
        payload = _json.loads(payload_json.decode('utf-8'))
    except (ValueError, UnicodeDecodeError) as e:
        raise MetaSignatureError(f'Payload is not valid JSON: {e}') from e

    if not getattr(settings, 'META_TEST_MODE', False):
        try:
            received_sig = _b64url_decode(sig_b64)
        except Exception as e:
            raise MetaSignatureError(f'Could not decode signature: {e}') from e

        expected_sig = hmac.new(
            key=settings.META_APP_SECRET.encode('utf-8'),
            msg=payload_b64.encode('utf-8'),  # sign the RAW b64 payload, not the decoded JSON
            digestmod=hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(received_sig, expected_sig):
            raise MetaSignatureError('signed_request signature mismatch.')

        algorithm = payload.get('algorithm', '')
        if algorithm.upper().replace('-', '') != 'HMACSHA256':
            raise MetaSignatureError(
                f'Unexpected signed_request algorithm: {algorithm!r}'
            )

    return payload


def _b64url_decode(value: str) -> bytes:
    """URL-safe base64 decode with padding restored. Meta's
    signed_request strips trailing `=` per RFC 4648 § 5."""
    import base64
    padding = '=' * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def verify_webhook_subscription_challenge(
    *, mode: str, token: str, challenge: str,
) -> str | None:
    """Handle the GET subscription handshake.

    Returns the challenge string to echo back on success, None to
    indicate the view should respond 403.
    """
    if mode != 'subscribe':
        return None
    if not _consteq(token, settings.META_WEBHOOK_VERIFY_TOKEN):
        return None
    return challenge


# ── Webhook payload routing → SocialThread + SocialMessage rows ─────


@dataclass
class IngestionResult:
    """What an inbound webhook produced. Used by tests + audit log."""
    threads_touched: int = 0
    messages_created: int = 0
    messages_duplicate: int = 0
    pages_unmatched: int = 0


def ingest_webhook_payload(payload: dict) -> IngestionResult:
    """Top-level entry: parse a Meta webhook POST body and persist
    everything we can match to a connected tenant.

    Per ADR 0027 §4, payloads carry `entry[]` keyed by Page ID. We
    look up the Page in the Connection table (provider=instagram,
    external_id=page_id, status=connected). Unknown pages are
    swallowed (logged + counted) — they're either disconnected or
    were never ours.
    """
    result = IngestionResult()
    for entry in payload.get('entry', []):
        page_id = entry.get('id', '')
        if not page_id:
            continue

        connection = Connection.objects.filter(
            provider=Connection.Provider.META_INSTAGRAM,
            status=Connection.Status.CONNECTED,
            external_id=page_id,
        ).first()

        if connection is None:
            result.pages_unmatched += 1
            logger.info(
                'integrations.meta.webhook_unmatched_page',
                extra={'page_id': page_id},
            )
            continue

        # IG DM payloads use the Messenger Platform shape:
        # entry['messaging'] is a list of message events.
        for event in entry.get('messaging', []):
            _process_messaging_event(connection, event, result)

    return result


def _process_messaging_event(
    connection: Connection, event: dict, result: IngestionResult,
) -> None:
    """Handle one entry.messaging[i] item.

    The Messenger Platform schema:
      {
        "sender":    {"id": "<PSID>"},
        "recipient": {"id": "<PAGE_ID>"},
        "timestamp": 1700000000000,
        "message":   {
          "mid":  "...",
          "text": "..." OR "attachments": [...]
        }
      }

    Outbound echoes ("we sent a message via Meta and they're telling
    us about it") are skipped — those will be tracked by the
    outbound send path in Session 2.
    """
    sender = event.get('sender', {}) or {}
    sender_id = sender.get('id')
    if not sender_id or sender_id == connection.external_id:
        # Either no sender (shouldn't happen) or it's our own page
        # echoing back an outbound send.
        return

    msg = event.get('message', {}) or {}
    mid = msg.get('mid')
    if not mid:
        return

    # Skip our own echoes — Meta sets `is_echo: True` on those.
    if msg.get('is_echo'):
        return

    text = msg.get('text', '') or ''
    attachments = msg.get('attachments', []) or []
    media_urls = '\n'.join(
        a.get('payload', {}).get('url', '')
        for a in attachments
        if a.get('payload', {}).get('url')
    )

    ts_ms = event.get('timestamp')
    received_at = (
        _dt.datetime.fromtimestamp(ts_ms / 1000, tz=_dt.timezone.utc)
        if ts_ms else timezone.now()
    )

    # Find or create the thread + its customer.
    thread, customer = _resolve_thread_and_customer(
        connection=connection,
        external_thread_id=sender_id,
    )

    # Idempotent insert — duplicate `mid` raises IntegrityError which
    # we treat as "already ingested, no-op."
    from django.db import IntegrityError, transaction
    from .models import SocialMessage

    try:
        with transaction.atomic():
            SocialMessage.objects.create(
                tenant=connection.tenant,
                thread=thread,
                direction=SocialMessage.Direction.INBOUND,
                body=text,
                media_urls=media_urls,
                external_message_id=mid,
                status=SocialMessage.Status.RECEIVED,
                received_at=received_at,
            )
    except IntegrityError:
        result.messages_duplicate += 1
        return

    # Bump thread aggregates.
    thread.last_message_at = received_at
    thread.last_inbound_at = received_at
    thread.read_at = None  # new inbound resets unread state
    thread.save(update_fields=['last_message_at', 'last_inbound_at', 'read_at', 'updated_at'])

    result.threads_touched += 1
    result.messages_created += 1


def _resolve_thread_and_customer(
    *, connection: Connection, external_thread_id: str,
) -> tuple[Any, Any]:
    """Return (SocialThread, Customer) for an inbound message.

    - If a SocialThread already exists for this (tenant, provider, sender),
      reuse it (and its customer).
    - Else find a Customer whose `instagram_handle` matches the
      sender's username (Session 2 enriches this lookup; Session 1
      stays with what the webhook gives us).
    - Else create a new social-guest Customer + SocialThread together.
    """
    from apps.customers.models import Customer
    from .models import SocialThread

    thread = SocialThread.objects.filter(
        tenant=connection.tenant,
        provider=SocialThread.Provider.INSTAGRAM,
        external_thread_id=external_thread_id,
    ).select_related('customer').first()

    if thread is not None:
        return thread, thread.customer

    # No prior thread → create a social-guest customer + thread.
    # We do NOT call out to Meta for the username here; that's a
    # Session 2 enrichment so the webhook path stays synchronous +
    # cheap. The thread carries `external_username=''` until then.
    customer = Customer.objects.create(
        tenant=connection.tenant,
        first_name=f'Instagram visitor {external_thread_id[-6:]}',
        last_name='',
        acquisition_source=Customer.AcquisitionSource.INSTAGRAM,
        external_id=external_thread_id,
        external_source='instagram',
        imported_at=timezone.now(),
        is_social_guest=True,
        # Conservative defaults: social-DM-derived customers are NOT
        # opted in to anything until the operator confirms identity.
        email_opt_in=False,
        sms_opt_in=False,
        email_marketing_opt_in=False,
        sms_marketing_opt_in=False,
    )

    thread = SocialThread.objects.create(
        tenant=connection.tenant,
        provider=SocialThread.Provider.INSTAGRAM,
        connection=connection,
        customer=customer,
        external_thread_id=external_thread_id,
        external_username='',
        last_message_at=timezone.now(),
    )
    return thread, customer


# ── Data deletion processing ────────────────────────────────────────


def revoke_connections_for_user(fb_user_id: str) -> list[tuple[int, str]]:
    """Force-disconnect every Connection authorised by this FB user.

    Returns `[(connection_id, page_id), ...]` for the rows that were
    revoked — page_id captured BEFORE the field is wiped so the
    caller can persist it for the deletion audit trail. Tokens are
    cleared atomically; the rows stay in the database so the tenant
    sees "disconnected — reauthorisation needed" in their
    integrations UI.

    SocialMessages + SocialThreads are NOT deleted — they belong to
    the spa's business records, not the IG user's personal data
    (the spa is the data controller). The user-facing instructions
    URL explains this explicitly per Meta's data-deletion guidance.
    """
    from django.db import transaction

    affected: list[tuple[int, str]] = []
    if not fb_user_id:
        return affected

    # We stored fb_user_id inside the encrypted auth_data blob, so we
    # can't filter on it at the SQL layer. Iterate every CONNECTED
    # row and check after decryption. This is a small-N table in
    # practice (one row per (tenant, provider) and most tenants have
    # at most a few). If it ever grows, lift fb_user_id to a column.
    candidates = Connection.objects.filter(
        provider__startswith='meta_',
        status=Connection.Status.CONNECTED,
    )
    for conn in candidates:
        try:
            payload = conn.auth_data_dict
        except Exception:
            # Corrupt ciphertext shouldn't break the deletion flow;
            # log + move on.
            logger.exception(
                'integrations.meta.deletion_decrypt_failed',
                extra={'connection_id': conn.pk},
            )
            continue
        if payload.get('fb_user_id') != fb_user_id:
            continue

        # Capture page_id BEFORE we wipe the field — the caller
        # persists it for the audit trail.
        page_id_at_revoke = conn.external_id

        with transaction.atomic():
            conn.status = Connection.Status.DISCONNECTED
            conn.clear_auth_data()
            conn.external_id = ''
            conn.external_name = ''
            conn.disconnected_at = timezone.now()
            conn.last_error_at = timezone.now()
            conn.last_error_message = (
                'Disconnected via Meta data-deletion callback — '
                'user removed the app from Facebook.'
            )
            conn.save(update_fields=[
                'status', 'auth_data', 'external_id', 'external_name',
                'disconnected_at', 'last_error_at', 'last_error_message',
                'updated_at',
            ])
            affected.append((conn.pk, page_id_at_revoke))

    return affected
