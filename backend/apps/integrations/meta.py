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
from django.core import signing
from django.utils import timezone

from .models import Connection

logger = logging.getLogger(__name__)


# ── Constants ───────────────────────────────────────────────────────


GRAPH_API_VERSION = 'v22.0'
GRAPH_BASE = f'https://graph.facebook.com/{GRAPH_API_VERSION}'
OAUTH_DIALOG_URL = f'https://www.facebook.com/{GRAPH_API_VERSION}/dialog/oauth'

# ── Instagram Login (Business) endpoints ───────────────────────────
#
# Distinct from the Facebook Login endpoints above. Instagram Login
# is a Meta-supported OAuth flow released in 2024 that authenticates
# the spa directly via instagram.com — no Facebook account or Page
# required. Uses the Instagram product's separate App ID / Secret
# (see INSTAGRAM_APP_ID / INSTAGRAM_APP_SECRET in settings/base.py).
#
# IMPORTANT: graph.instagram.com does NOT accept a version prefix
# in the URL path (unlike graph.facebook.com which requires
# `/v22.0/...`). Meta's IG API returns a misleading "Unsupported
# request - method type: get/post" (IGApiException code 100) when
# you include `/v22.0/`. Confirmed empirically 2026-05.
#
# Reference: developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login
IG_OAUTH_AUTHORIZE_URL = 'https://www.instagram.com/oauth/authorize'
IG_OAUTH_TOKEN_URL = 'https://api.instagram.com/oauth/access_token'
IG_GRAPH_BASE = 'https://graph.instagram.com'   # NO version prefix
IG_GRAPH_EXCHANGE_TOKEN_URL = 'https://graph.instagram.com/access_token'

# Per ADR 0027 §2 — state tokens older than this are rejected as
# replays. 10 min is comfortable for a real human consent flow
# without leaving the door open for long-window replays.
STATE_TTL_SECONDS = 600

# Per-provider scope sets. Source of truth lives here AND in
# `providers.py` — the duplication is intentional so the Meta App
# Review submission and the runtime requested scopes can diverge
# during a transitional period. If they drift, audit + reconcile.
# Instagram Login scopes — the `instagram_business_*` family
# released with the 2024 IG Business Login flow. Different from the
# Facebook Login scopes (which use bare `instagram_*` + `pages_*`)
# and ONLY valid for the IG Login OAuth endpoint above. Mixing them
# with the FB Login OAuth gets rejected with "Invalid Scopes".
#
# Reference: developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/business-login
SCOPES_INSTAGRAM = (
    'instagram_business_basic',           # read account profile + media
    'instagram_business_manage_messages', # send + receive DMs
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
#
# The state token is a Django-signed payload carrying its own
# binding (tenant_id, provider, nonce). It does NOT depend on the
# user's session cookie surviving the round-trip from Instagram —
# which Lax cookies usually do for cross-site top-level GETs, but
# in practice gets blocked by stale cookie domains, tracking-
# prevention modes, and incognito quirks (which produced the
# "No OAuth flow is in progress" misfires).
#
# Signed-state matches RFC 6749 §10.12: an opaque, integrity-
# protected value the auth server echoes back. Replay isn't a
# meaningful concern here — Instagram's `code` is single-use, so
# completing the callback twice with the same state would still
# need a fresh `code` for a second token-exchange call.
STATE_TOKEN_SALT = 'meta-oauth-state.v1'


def issue_state_token(*, tenant_id: int, provider: str) -> str:
    """Mint a signed state token that round-trips through Instagram.

    Encodes the binding (tenant_id, provider) and a nonce, signs
    with SECRET_KEY + a salted timestamp, and returns the URL-safe
    string. `verify_state_token` is the only legitimate consumer.
    """
    payload = {
        'tenant_id': tenant_id,
        'provider': provider,
        'nonce': secrets.token_urlsafe(16),
    }
    return signing.dumps(payload, salt=STATE_TOKEN_SALT, compress=False)


def verify_state_token(state: str) -> dict[str, Any]:
    """Validate a callback `state` and return its embedded binding.

    Raises `MetaOAuthError` with a specific message for each failure
    mode so the operator-facing error UX stays precise.
    """
    if not state:
        raise MetaOAuthError(
            'No OAuth flow is in progress. Click Connect again to start over.'
        )
    try:
        payload = signing.loads(
            state,
            salt=STATE_TOKEN_SALT,
            max_age=STATE_TTL_SECONDS,
        )
    except signing.SignatureExpired:
        raise MetaOAuthError(
            f'OAuth flow timed out after {STATE_TTL_SECONDS // 60} minutes. '
            'Click Connect again to start over.'
        )
    except signing.BadSignature:
        raise MetaOAuthError(
            'OAuth state could not be verified. This usually means the '
            'connect link was tampered with or a different browser tab '
            'interfered. Click Connect again to retry.'
        )
    return {
        'tenant_id': payload.get('tenant_id'),
        'provider': payload.get('provider'),
    }


def _consteq(a: str, b: str) -> bool:
    """Constant-time string comparison for security tokens. Used by
    `verify_webhook_subscription_challenge` to compare the
    incoming `hub.verify_token` to the configured secret without a
    timing oracle."""
    return hmac.compare_digest(
        (a or '').encode('utf-8'),
        (b or '').encode('utf-8'),
    )


# ── OAuth dialog URL ────────────────────────────────────────────────


def build_authorize_url(*, provider: str, state: str) -> str:
    """Construct the OAuth authorize URL for the given provider.

    For `meta_instagram` this is the Instagram Login authorize URL —
    the spa logs in directly with their IG credentials, no Facebook
    account needed. For future `meta_facebook` (FB Messenger) this
    will return the Facebook OAuth dialog URL using the FB App ID.
    """
    if provider == 'meta_instagram':
        params = {
            'client_id': settings.INSTAGRAM_APP_ID,
            'redirect_uri': settings.META_OAUTH_REDIRECT_URI,
            'state': state,
            'scope': ','.join(SCOPES_INSTAGRAM),
            'response_type': 'code',
        }
        return f'{IG_OAUTH_AUTHORIZE_URL}?{_urlparse.urlencode(params)}'

    # FB Messenger + WhatsApp wire up in future sessions.
    raise MetaOAuthError(
        f'OAuth flow for provider {provider!r} is not implemented yet.'
    )


# ── Token exchange ──────────────────────────────────────────────────


@dataclass
class TokenExchangeResult:
    """Result of the Instagram Login token-exchange chain.

    `ig_user_id` is the IG-scoped user identifier — also what Meta
    puts in `entry[].id` on every webhook delivery, so we store it
    as `Connection.external_id` for fast payload routing.
    """
    ig_user_id: str
    ig_username: str
    access_token: str           # long-lived (~60 day) IG access token
    granted_scopes: list[str]
    expires_at: int | None      # Unix timestamp; None if non-expiring


def exchange_code_for_connection(code: str) -> TokenExchangeResult:
    """Full code → IG token chain (Instagram Login flow).

    Steps:
      1. POST code → short-lived (1-hour) IG user token at
         api.instagram.com/oauth/access_token. Response carries
         {access_token, user_id, permissions}.
      2. Best-effort: exchange short → long-lived (~60d) token via
         graph.instagram.com/access_token?grant_type=ig_exchange_token.
         Meta's docs say GET on this endpoint, but the live API has
         been rejecting both GET and POST with "Unsupported method"
         errors as of 2026-05. When the exchange fails we fall back
         to the short token — the connection works for ~1 hour and
         the operator must reconnect. TODO(session-2B): resolve the
         right endpoint and remove the fallback.
      3. GET /me to confirm the user_id + fetch the username for the
         integrations UI.
      4. Webhook subscription is registered after the Connection row
         is saved (callback view calls `subscribe_ig_user_to_webhooks`).

    Step 1 / 3 failures raise MetaOAuthError. Step 2 failures only log.
    """
    short_token, ig_user_id = _ig_exchange_code_for_short_token(code)

    # Long-token exchange is best-effort right now (see TODO above).
    try:
        access_token, expires_in = _ig_exchange_short_for_long_token(short_token)
        token_kind = 'long-lived'
    except MetaOAuthError as e:
        logger.warning(
            'integrations.meta.long_token_exchange_failed_using_short',
            extra={'error': str(e)[:300]},
        )
        access_token = short_token
        expires_in = 3600  # 1 hour — the documented short-token TTL
        token_kind = 'short-lived (fallback)'

    # Profile fetch is best-effort. The short-token response already
    # gave us the user_id; the username is purely display polish. If
    # the profile call fails, we proceed with a placeholder name and
    # log so we can debug Meta's response shape.
    ig_username = ''
    try:
        profile = _ig_fetch_me(access_token, ig_user_id=ig_user_id)
        ig_username = profile.get('username', '')
        # Belt-and-braces: prefer profile's user_id if present.
        ig_user_id = str(
            profile.get('user_id')
            or profile.get('id')
            or ig_user_id
        )
    except MetaOAuthError as e:
        logger.warning(
            'integrations.meta.profile_fetch_failed_proceeding',
            extra={'error': str(e)[:300], 'ig_user_id': ig_user_id},
        )

    granted = _ig_fetch_granted_permissions(access_token)
    expires_at = int(time.time()) + (expires_in or 60 * 24 * 3600)
    logger.info(
        'integrations.meta.connection_tokens_ready',
        extra={
            'ig_user_id': ig_user_id,
            'ig_username': ig_username,
            'token_kind': token_kind,
            'expires_at': expires_at,
        },
    )

    return TokenExchangeResult(
        ig_user_id=ig_user_id,
        ig_username=ig_username,
        access_token=access_token,
        granted_scopes=granted,
        expires_at=expires_at,
    )


def _ig_exchange_code_for_short_token(code: str) -> tuple[str, str]:
    """POST api.instagram.com/oauth/access_token. Returns (short_token, user_id).

    Form-encoded body, NOT query params — IG's OAuth token endpoint
    enforces this. Sending as query params returns a 400 with a
    cryptic 'missing grant_type' error even though the field is set.
    """
    response = requests.post(
        IG_OAUTH_TOKEN_URL,
        data={
            'client_id': settings.INSTAGRAM_APP_ID,
            'client_secret': settings.INSTAGRAM_APP_SECRET,
            'grant_type': 'authorization_code',
            'redirect_uri': settings.META_OAUTH_REDIRECT_URI,
            'code': code,
        },
        timeout=15,
    )
    payload = _expect_json(response, step='ig short-lived token')
    token = payload.get('access_token', '')
    user_id = str(payload.get('user_id', ''))
    if not token:
        raise MetaOAuthError(
            f'Instagram returned no access_token in the code exchange: {payload}'
        )
    return token, user_id


def _ig_exchange_short_for_long_token(short_token: str) -> tuple[str, int | None]:
    """Exchange short-lived IG token for a long-lived (~60 day) one.

    Meta's docs say `GET https://graph.instagram.com/access_token` but
    the live API returns 400 IGApiException code 100 "Unsupported
    method" regardless of HTTP verb. Known issue (in2code-de/instagram#41
    opened Dec 2024, unresolved). Until Meta fixes their API or docs,
    we try several plausible endpoint variants in order and return
    the first one that succeeds.

    Returns (long_token, expires_in_seconds). Long-lived IG tokens
    typically expire in 5184000 seconds (60 days). Raises
    MetaOAuthError with details of each attempt if all fail.
    """
    attempts = [
        # 1. The officially-documented endpoint + method.
        {
            'label': 'docs-default GET graph.instagram.com/access_token',
            'method': 'GET',
            'url': 'https://graph.instagram.com/access_token',
            'params': {
                'grant_type': 'ig_exchange_token',
                'client_secret': settings.INSTAGRAM_APP_SECRET,
                'access_token': short_token,
            },
        },
        # 2. Same endpoint, POST with form body (some Meta endpoints
        #    accept either method despite docs saying one).
        {
            'label': 'POST graph.instagram.com/access_token',
            'method': 'POST',
            'url': 'https://graph.instagram.com/access_token',
            'data': {
                'grant_type': 'ig_exchange_token',
                'client_secret': settings.INSTAGRAM_APP_SECRET,
                'access_token': short_token,
            },
        },
        # 3. The same `api.instagram.com/oauth/access_token` endpoint
        #    that issued the short token, with the exchange grant type.
        #    Mirrors how Facebook Login reuses one endpoint for both
        #    code-exchange and token-exchange.
        {
            'label': 'POST api.instagram.com/oauth/access_token (reuse-endpoint pattern)',
            'method': 'POST',
            'url': IG_OAUTH_TOKEN_URL,
            'data': {
                'grant_type': 'ig_exchange_token',
                'client_id': settings.INSTAGRAM_APP_ID,
                'client_secret': settings.INSTAGRAM_APP_SECRET,
                'access_token': short_token,
            },
        },
        # 4. Facebook Graph API path with fb_exchange_token grant —
        #    some 3rd-party docs (Meta's own ig-mcp sample) use this
        #    for IG tokens despite it being an FB-Login path.
        {
            'label': 'GET graph.facebook.com/v22.0/oauth/access_token fb_exchange_token',
            'method': 'GET',
            'url': f'{GRAPH_BASE}/oauth/access_token',
            'params': {
                'grant_type': 'fb_exchange_token',
                'client_id': settings.INSTAGRAM_APP_ID,
                'client_secret': settings.INSTAGRAM_APP_SECRET,
                'fb_exchange_token': short_token,
            },
        },
    ]

    last_error: str = ''
    for attempt in attempts:
        try:
            if attempt['method'] == 'GET':
                response = requests.get(
                    attempt['url'],
                    params=attempt['params'],
                    timeout=15,
                )
            else:
                response = requests.post(
                    attempt['url'],
                    data=attempt['data'],
                    timeout=15,
                )
        except requests.RequestException as e:
            last_error = f'{attempt["label"]} → network error: {e}'
            logger.warning(
                'integrations.meta.long_token_attempt_failed',
                extra={'label': attempt['label'], 'error': str(e)[:200]},
            )
            continue

        if response.status_code == 200:
            try:
                payload = response.json()
            except ValueError:
                payload = {}
            token = payload.get('access_token', '')
            expires_in = payload.get('expires_in')
            if token:
                logger.info(
                    'integrations.meta.long_token_attempt_succeeded',
                    extra={
                        'label': attempt['label'],
                        'expires_in': expires_in,
                    },
                )
                return token, expires_in

        # 4xx / 5xx — log the body shape for the next round of debugging
        try:
            body = response.json()
            meta_err = body.get('error', body)
        except ValueError:
            meta_err = {'raw': response.text[:200]}
        last_error = (
            f'{attempt["label"]} → {response.status_code}: '
            f'{meta_err.get("message", meta_err)}'
        )
        logger.warning(
            'integrations.meta.long_token_attempt_failed',
            extra={
                'label': attempt['label'],
                'status': response.status_code,
                'meta_error': meta_err,
            },
        )

    raise MetaOAuthError(
        f'All long-lived token exchange attempts failed. Last: {last_error}'
    )


def _ig_fetch_me(access_token: str, *, ig_user_id: str = '') -> dict:
    """Fetch the IG profile (id, username, name).

    Tries `/me` first; if Meta rejects it (the IG Login flow has been
    returning "Unsupported method: get" on /me as of 2026-05), falls
    back to `/{ig_user_id}` which is the explicit-ID form documented
    for Instagram API with Instagram Login. Caller passes the
    user_id from the short-token exchange.
    """
    response = requests.get(
        f'{IG_GRAPH_BASE}/me',
        params={
            'access_token': access_token,
            'fields': 'user_id,username,name',
        },
        timeout=15,
    )
    if response.status_code == 200:
        return _expect_json(response, step='ig profile fetch (me)')

    # /me failed — fall back to /{user_id} explicit-ID form
    if ig_user_id:
        logger.info(
            'integrations.meta.profile_me_failed_trying_explicit_id',
            extra={
                'me_status': response.status_code,
                'me_body': response.text[:300],
            },
        )
        response = requests.get(
            f'{IG_GRAPH_BASE}/{ig_user_id}',
            params={
                'access_token': access_token,
                'fields': 'user_id,username,name',
            },
            timeout=15,
        )
    return _expect_json(response, step='ig profile fetch')


def _ig_fetch_granted_permissions(access_token: str) -> list[str]:
    """Best-effort: list permissions granted on the long-lived token.

    Unlike Facebook Login (where /me/permissions is documented), the
    Instagram Login flow doesn't expose a runtime permissions endpoint
    — scopes are pinned at token-issue time. We return the requested
    scope list as a stand-in; any one missing would have failed the
    OAuth grant outright.
    """
    return list(SCOPES_INSTAGRAM)


def subscribe_ig_user_to_webhooks(*, ig_user_id: str, access_token: str) -> None:
    """POST /{ig-user-id}/subscribed_apps — enable webhook delivery.

    Without this, Meta won't deliver inbound DMs even with valid
    OAuth + tokens. Subscription persists until the operator
    disconnects or revokes access via Instagram.

    `subscribed_fields` is REQUIRED — earlier code assumed Meta
    defaulted to "all enabled fields"; the live API rejects with
    "The parameter subscribed_fields is required" (2026-05).

    URL variants — empirically Meta accepts different shapes for
    different IG account types/states, even within the same Meta
    Business Portfolio. One account connects fine with the `/v22.0/`
    prefixed form; the next gets "Unsupported method: post" on the
    same URL and only works against the bare (unversioned) host. So
    we try them in order and return on first success. Same pattern
    as `_ig_exchange_short_for_long_token`.

    We subscribe to `messages` (inbound DMs) and `messaging_postbacks`
    (button clicks for any future quick-reply UI). Adding fields
    later only requires the operator to disconnect + reconnect.
    """
    _ig_subscribed_apps_call(
        method='POST',
        ig_user_id=ig_user_id,
        access_token=access_token,
        extra_params={'subscribed_fields': 'messages,messaging_postbacks'},
        action='subscribe',
    )


def _ig_subscribed_apps_call(
    *,
    method: str,
    ig_user_id: str,
    access_token: str,
    extra_params: dict[str, str],
    action: str,
) -> None:
    """Shared multi-variant caller for /{ig-user-id}/subscribed_apps.

    Tries the versioned host first (`graph.instagram.com/v22.0/...`),
    falls back to the unversioned host (`graph.instagram.com/...`).
    Raises MetaOAuthError only when every variant fails — and the
    raised message names every attempted URL + Meta's response so
    operators have something concrete to debug from.
    """
    variants = [
        f'https://graph.instagram.com/{GRAPH_API_VERSION}/{ig_user_id}/subscribed_apps',
        f'https://graph.instagram.com/{ig_user_id}/subscribed_apps',
    ]
    # Dispatch on `requests.post` / `requests.delete` directly (not
    # `requests.request`) because the test suite + most mocking
    # patterns in this codebase patch the verb-specific functions.
    verb = {'POST': requests.post, 'DELETE': requests.delete}[method]
    last_error: str = ''
    for url in variants:
        try:
            response = verb(
                url,
                params={'access_token': access_token, **extra_params},
                timeout=15,
            )
        except requests.RequestException as e:
            last_error = f'{url} → network error: {e}'
            logger.warning(
                'integrations.meta.subscribed_apps_attempt_failed',
                extra={'url': url, 'action': action, 'error': str(e)[:200]},
            )
            continue

        try:
            payload = response.json()
        except ValueError:
            payload = {'raw': response.text[:300]}

        if response.status_code == 200 and payload.get('success'):
            logger.info(
                'integrations.meta.subscribed_apps_attempt_succeeded',
                extra={'url': url, 'action': action},
            )
            return

        meta_err = payload.get('error', payload)
        last_error = (
            f'{url} → {response.status_code}: '
            f'{meta_err.get("message", meta_err) if isinstance(meta_err, dict) else meta_err}'
        )
        logger.warning(
            'integrations.meta.subscribed_apps_attempt_failed',
            extra={
                'url': url,
                'action': action,
                'status': response.status_code,
                'meta_error': meta_err,
            },
        )

    raise MetaOAuthError(
        f'webhook {action} failed for IG user {ig_user_id} across all '
        f'endpoint variants. Last: {last_error}'
    )


# ── Conversation backfill (ADR 0027 §10) ──────────────────────────


# Per Meta's docs the /conversations endpoint paginates with `next`
# cursors. We cap at MAX_CONVERSATIONS to avoid an unbounded sweep
# for a spa with thousands of historical threads — first connect
# should be reasonably fast, polish later if anyone asks for full
# history.
BACKFILL_MAX_CONVERSATIONS = 50
BACKFILL_MAX_MESSAGES_PER_CONVERSATION = 25


def list_recent_conversations(
    *, ig_user_id: str, access_token: str,
) -> list[dict]:
    """GET /{ig-user-id}/conversations — list recent conversations.

    Returns a list of conversation summaries with their IDs. Each
    looks like `{'id': 'aWdfZA...', 'updated_time': '2026-...'}`.
    """
    response = requests.get(
        f'{IG_GRAPH_BASE}/{ig_user_id}/conversations',
        params={
            'access_token': access_token,
            'fields': 'id,updated_time',
            'limit': BACKFILL_MAX_CONVERSATIONS,
        },
        timeout=20,
    )
    payload = _expect_json(response, step='ig list conversations')
    return payload.get('data', [])


def fetch_conversation_messages(
    *, conversation_id: str, access_token: str,
) -> list[dict]:
    """GET /{conversation-id}?fields=messages{...} — fetch a conversation's messages.

    Returns the message list — sender + recipient IDs + body + created_time
    + (when Meta allows) sender username/name/profile_pic via message-
    context expansion.

    Meta paginates inside the messages field; we take the first page
    only (most recent N messages) to keep backfill bounded.

    Profile-expansion strategy: the `from` field expansion `{id,
    username,name,profile_pic}` is more permissive than the standalone
    profile endpoint (the latter requires the 24-hour messaging window
    AND Advanced Access; the former works in Standard Access for
    messages in any conversation the business has). Callers can rely
    on `from.username` being populated whenever Meta has it; `name` +
    `profile_pic` are populated when Meta has them and our app has the
    relevant scope.
    """
    response = requests.get(
        f'{IG_GRAPH_BASE}/{conversation_id}',
        params={
            'access_token': access_token,
            'fields': (
                'messages.limit('
                + str(BACKFILL_MAX_MESSAGES_PER_CONVERSATION)
                + '){id,created_time,from{id,username,name,profile_pic},to,message}'
            ),
        },
        timeout=20,
    )
    payload = _expect_json(response, step='ig fetch messages')
    msgs_envelope = payload.get('messages') or {}
    return msgs_envelope.get('data', [])


def list_conversations_with_participants(
    *, ig_user_id: str, access_token: str,
) -> list[dict]:
    """GET /{ig-user-id}/conversations?fields=participants — bulk profile data.

    The per-user profile endpoint (`fetch_ig_user_profile`) fails with
    "user not found" or "user consent required" for any conversation
    OUTSIDE the 24-hour messaging window — which is most of an inbox's
    backlog. The `/conversations` endpoint with `participants` expansion
    works regardless of window state and returns `{id, name, username}`
    for every participant in every conversation in ONE call (vs one per
    thread), so it's both more permissive and cheaper.

    Returns the raw conversations list. Each entry:

        {
          "id": "<CONVERSATION_ID>",
          "participants": {"data": [
            {"id": "<BUSINESS_PSID>", "name": "...", "username": "..."},
            {"id": "<CUSTOMER_PSID>", "name": "Maria", "username": "maria.beauty"}
          ]}
        }

    Caller iterates participants, filters out our own business PSID
    (== ig_user_id), and uses the remainder to populate SocialThread
    rows keyed by `external_thread_id == participant.id`.

    Profile pic URLs are NOT available via this endpoint — Meta only
    surfaces those from the per-user `?fields=profile_pic` call which
    requires the messaging window. The avatar component falls back to
    initials when the URL is empty; once a user sends a fresh DM the
    webhook path picks up the fresh profile pic.
    """
    response = requests.get(
        f'{IG_GRAPH_BASE}/{ig_user_id}/conversations',
        params={
            'access_token': access_token,
            'platform': 'instagram',
            'fields': 'participants',
            'limit': BACKFILL_MAX_CONVERSATIONS,
        },
        timeout=20,
    )
    payload = _expect_json(response, step='ig list conversations w/ participants')
    return payload.get('data', [])


def fetch_ig_user_profile(
    *, ig_scoped_id: str, page_access_token: str,
) -> dict:
    """GET /{ig-scoped-id}?fields=name,username,profile_pic — fetch IG profile.

    Returns `{name, username, profile_pic}` for the IG user identified
    by the PSID (page-scoped user ID) Meta delivers in webhook payloads.
    Available fields per Meta's Instagram Messaging API:

      - `name`        — the user's display name as it appears in IG
      - `username`    — the @handle
      - `profile_pic` — signed CloudFront URL, expires in ~weeks

    Authorisation: the page access token must be the one tied to a
    business account that has been in a conversation with this user
    (which is exactly what we hold). The Instagram Messaging API
    explicitly grants profile access only when a DM relationship
    exists — privacy-preserving by design.

    Raises MetaOAuthError on Meta-side rejection. Callers should
    treat profile fetch as best-effort: a failure shouldn't block
    thread creation or message ingestion. Empty / missing fields
    are returned as empty strings, never None — the SocialThread
    fields are CharFields with default=''.

    Notes:
      - The endpoint path is /{psid} directly, NO version prefix
        (matches the /me + /{user_id} pattern; unversioned).
      - Meta sometimes returns 400 for users who blocked the
        business — caller logs + leaves the existing values intact.
    """
    response = requests.get(
        f'{IG_GRAPH_BASE}/{ig_scoped_id}',
        params={
            'access_token': page_access_token,
            'fields': 'name,username,profile_pic',
        },
        timeout=10,
    )
    payload = _expect_json(response, step='ig fetch user profile')
    return {
        'name': payload.get('name', '') or '',
        'username': payload.get('username', '') or '',
        'profile_pic': payload.get('profile_pic', '') or '',
    }


def unsubscribe_ig_user_from_webhooks(*, ig_user_id: str, access_token: str) -> None:
    """DELETE /{ig-user-id}/subscribed_apps — stop webhook delivery.

    Mirrors `subscribe_ig_user_to_webhooks` (same multi-variant URL
    fallback) but for the disconnect path. Without this call, Meta
    keeps delivering webhook events to our endpoint forever (or
    until the user revokes via Instagram). Each delivery 200s but
    logs "no matching connection" — wasteful + makes the logs
    harder to read.

    Raises MetaOAuthError on non-success. Caller should treat as
    best-effort: a dangling Meta subscription is annoying but not
    safety-critical, so a disconnect should still proceed locally
    even if this call fails.
    """
    _ig_subscribed_apps_call(
        method='DELETE',
        ig_user_id=ig_user_id,
        access_token=access_token,
        extra_params={},
        action='unsubscribe',
    )


# ── Outbound DM send (ADR 0027 §7) ─────────────────────────────────


# Meta's 24-hour reply window for the standard messaging API. Outbound
# messages sent more than 24h after the last inbound message are
# rejected with error code 10 unless tagged. We don't support tags
# in v1, so we gate at the application layer with a clearer error
# than what Meta would return.
META_REPLY_WINDOW_HOURS = 24


# ── Long-lived token refresh (60-day cycle) ────────────────────────


def refresh_long_lived_token(*, access_token: str) -> tuple[str, int | None]:
    """Refresh a long-lived IG token before it expires.

    Per Meta docs: GET graph.instagram.com/refresh_access_token with
    grant_type=ig_refresh_token. Token must be at least 24h old +
    not yet expired. Refreshed token is valid for 60 days from the
    refresh time.

    Returns (new_token, expires_in_seconds). Raises MetaOAuthError
    if Meta rejects (the refresh job catches + logs so one bad row
    doesn't block the whole sweep).
    """
    response = requests.get(
        'https://graph.instagram.com/refresh_access_token',
        params={
            'grant_type': 'ig_refresh_token',
            'access_token': access_token,
        },
        timeout=15,
    )
    payload = _expect_json(response, step='ig token refresh')
    token = payload.get('access_token', '')
    expires_in = payload.get('expires_in')
    if not token:
        raise MetaOAuthError(
            f'Token refresh returned no access_token: {payload}'
        )
    return token, expires_in


def send_instagram_dm(
    *,
    ig_user_id: str,
    access_token: str,
    recipient_psid: str,
    body: str,
) -> dict:
    """POST /{ig-user-id}/messages — send a DM.

    `recipient_psid` is the Page-Scoped User ID Meta sends in webhook
    payloads as `sender.id`. It's the only identifier valid for
    outbound — we never receive or use the customer's real IG user
    ID, by Meta's design.

    Returns Meta's response payload `{recipient_id, message_id}` on
    success. Raises MetaOAuthError on rejection so the caller can
    surface the error message to the operator.
    """
    # `/messages` is an "action" endpoint like `/subscribed_apps` —
    # the version prefix is required here (Meta rejects un-versioned
    # POSTs to this path with "Unsupported method"). Profile-fetch
    # GETs on /me + /{user_id} stay unversioned per the verified-
    # empirically pattern.
    response = requests.post(
        f'https://graph.instagram.com/{GRAPH_API_VERSION}/{ig_user_id}/messages',
        params={'access_token': access_token},
        json={
            'recipient': {'id': recipient_psid},
            'message': {'text': body},
        },
        timeout=15,
    )
    return _expect_json(response, step='ig outbound send')


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
        # Log the FULL Meta error response (incl. type / code /
        # fbtrace_id) so we can debug "Unsupported method" and
        # similar generic-sounding errors. Tokens are NOT in the
        # response so this is safe to log.
        logger.warning(
            'integrations.meta.api_error',
            extra={
                'step': step,
                'status': response.status_code,
                'meta_error': meta_err,
                'request_url': response.url,
            },
        )
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
            msg_row = SocialMessage.objects.create(
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

    # Archive Meta-hosted media to our S3 before it expires (~24h).
    # Best-effort: a download/upload failure logs + leaves media_urls
    # as the fallback. ADR 0027 §6. Synchronous for now — moves to
    # async worker if media volume becomes a problem.
    if media_urls:
        from .media_archive import archive_message_media
        try:
            archive_message_media(msg_row)
        except Exception as e:
            logger.warning(
                'integrations.meta.media_archive_failed',
                extra={
                    'message_id': msg_row.pk,
                    'error': str(e)[:300],
                },
            )

    # Bump thread aggregates — only ADVANCE forward. Webhooks can
    # arrive out-of-order (network re-deliveries, Meta retry), and an
    # older event mustn't rewind a fresher state set by a later one.
    # The matching backfill path uses the same guard.
    update_fields = ['updated_at']
    if thread.last_message_at is None or received_at > thread.last_message_at:
        thread.last_message_at = received_at
        update_fields.append('last_message_at')
    if thread.last_inbound_at is None or received_at > thread.last_inbound_at:
        thread.last_inbound_at = received_at
        thread.read_at = None  # new inbound resets unread state
        update_fields += ['last_inbound_at', 'read_at']
    thread.save(update_fields=update_fields)

    result.threads_touched += 1
    result.messages_created += 1

    # AI inbox dispatch — guardrail-gated, never raises. For tenants
    # without the Instagram agent enabled this is a cheap no-op that
    # returns before any meaningful work. Idempotent per inbound
    # SocialMessage, so Meta webhook retries can't double-reply.
    from apps.ai_inbox.services.dispatch import maybe_dispatch_to_ai_instagram
    maybe_dispatch_to_ai_instagram(message=msg_row, thread=thread, connection=connection)


def _resolve_thread_and_customer(
    *, connection: Connection, external_thread_id: str,
) -> tuple[Any, Any]:
    """Return (SocialThread, Customer) for an inbound message.

    - If a SocialThread already exists for this (tenant, provider, sender),
      reuse it (and refresh its IG profile if stale).
    - Else create a new social-guest Customer + SocialThread, fetching
      the IG profile (name + @username + profile pic) so the inbox
      shows the customer's identity instead of an opaque PSID.

    Profile fetching is best-effort: a Meta-side failure logs + leaves
    the thread on its current profile values. The operator still sees
    the conversation; they just see initials instead of an avatar.
    """
    from apps.customers.models import Customer
    from .models import SocialThread

    thread = SocialThread.objects.filter(
        tenant=connection.tenant,
        provider=SocialThread.Provider.INSTAGRAM,
        external_thread_id=external_thread_id,
    ).select_related('customer').first()

    if thread is not None:
        _maybe_refresh_ig_profile(connection=connection, thread=thread)
        return thread, thread.customer

    # No prior thread → fetch the IG profile up front so the new
    # social-guest customer can carry a real name (and the inbox UI
    # has an avatar to show). The Graph call is synchronous and
    # adds ~200ms to webhook processing; that's acceptable because
    # new threads are infrequent (a webhook firing on a NEW sender,
    # not on every subsequent message in an established thread).
    profile = _fetch_ig_profile_best_effort(
        connection=connection,
        external_thread_id=external_thread_id,
    )

    # Use the IG display name when we got one; fall back to the
    # "Instagram visitor <last6>" placeholder so the customer list
    # still looks coherent if Meta returned nothing.
    if profile.get('name'):
        first_name, _, last_name = profile['name'].partition(' ')
        first_name = first_name[:60] or 'Instagram'
        last_name = last_name[:60]
    else:
        first_name = f'Instagram visitor {external_thread_id[-6:]}'
        last_name = ''

    customer = Customer.objects.create(
        tenant=connection.tenant,
        first_name=first_name,
        last_name=last_name,
        acquisition_source=Customer.AcquisitionSource.INSTAGRAM,
        external_id=external_thread_id,
        external_source='instagram',
        imported_at=timezone.now(),
        is_social_guest=True,
        instagram_handle=profile.get('username', '')[:60],
        # Conservative defaults: social-DM-derived customers are NOT
        # opted in to anything until the operator confirms identity.
        email_opt_in=False,
        sms_opt_in=False,
        email_marketing_opt_in=False,
        sms_marketing_opt_in=False,
    )

    fetched_at = timezone.now() if profile.get('username') or profile.get('profile_pic') else None
    thread = SocialThread.objects.create(
        tenant=connection.tenant,
        provider=SocialThread.Provider.INSTAGRAM,
        connection=connection,
        customer=customer,
        external_thread_id=external_thread_id,
        external_username=profile.get('username', ''),
        external_display_name=profile.get('name', ''),
        external_profile_pic_url=profile.get('profile_pic', ''),
        external_profile_fetched_at=fetched_at,
        last_message_at=timezone.now(),
    )
    return thread, customer


# Profile pictures from Meta are signed CloudFront URLs that rotate
# every few weeks. Refreshing inline on every webhook would burn
# Meta's 200-calls/hour ceiling for no benefit. Refresh only when
# the cached profile is older than this threshold.
IG_PROFILE_REFRESH_AFTER_DAYS = 6


def _maybe_refresh_ig_profile(*, connection: Connection, thread) -> None:
    """If the thread's IG profile data is stale, fetch fresh + save.

    Stale = never fetched OR fetched > IG_PROFILE_REFRESH_AFTER_DAYS
    ago. Refresh failure is silent (logged at INFO); the operator
    sees the old data until the next successful refresh.
    """
    if (
        thread.external_profile_fetched_at is not None
        and (timezone.now() - thread.external_profile_fetched_at).days < IG_PROFILE_REFRESH_AFTER_DAYS
    ):
        return  # still fresh

    profile = _fetch_ig_profile_best_effort(
        connection=connection,
        external_thread_id=thread.external_thread_id,
    )
    # Empty profile (Meta returned nothing) — don't blank out what
    # we already have. Leave the row alone.
    if not (profile.get('username') or profile.get('name') or profile.get('profile_pic')):
        return

    thread.external_username = profile.get('username', '') or thread.external_username
    thread.external_display_name = profile.get('name', '') or thread.external_display_name
    thread.external_profile_pic_url = profile.get('profile_pic', '') or thread.external_profile_pic_url
    thread.external_profile_fetched_at = timezone.now()
    thread.save(update_fields=[
        'external_username',
        'external_display_name',
        'external_profile_pic_url',
        'external_profile_fetched_at',
        'updated_at',
    ])


def _fetch_ig_profile_best_effort(
    *, connection: Connection, external_thread_id: str,
) -> dict:
    """Wrapper around fetch_ig_user_profile that swallows errors.

    Returns the profile dict on success; an empty dict on any failure.
    Callers can safely use `.get(...)` against the result without
    needing to handle exceptions in the webhook hot path.
    """
    try:
        payload = connection.auth_data_dict
    except Exception:
        return {}
    access_token = payload.get('access_token', '')
    if not access_token:
        return {}
    try:
        return fetch_ig_user_profile(
            ig_scoped_id=external_thread_id,
            page_access_token=access_token,
        )
    except MetaOAuthError as e:
        logger.info(
            'integrations.meta.profile_fetch_failed',
            extra={
                'connection_id': connection.pk,
                'psid_tail': external_thread_id[-6:],
                'error': str(e)[:200],
            },
        )
        return {}
    except Exception as e:  # noqa: BLE001
        logger.warning(
            'integrations.meta.profile_fetch_unexpected_error',
            extra={
                'connection_id': connection.pk,
                'psid_tail': external_thread_id[-6:],
                'error': str(e)[:200],
            },
        )
        return {}


# ── Data deletion processing ────────────────────────────────────────


def revoke_connections_for_user(user_id: str) -> list[tuple[int, str]]:
    """Force-disconnect every Connection authorised by this user.

    `user_id` is the identifier Meta sends in the signed_request
    payload on the data-deletion callback. For the Instagram Login
    flow that's the IG user_id (also stored on Connection as
    external_id); for legacy FB Login Connection rows it'd be the
    fb_user_id buried in auth_data_dict.

    Returns `[(connection_id, external_id), ...]` for the rows that
    were revoked — external_id captured BEFORE the field is wiped so
    the caller can persist it in the deletion audit trail. Tokens
    are cleared atomically; the rows stay in the database so the
    tenant sees "disconnected — reauthorisation needed" in their
    integrations UI.

    SocialMessages + SocialThreads are NOT deleted — they belong to
    the spa's business records, not the IG user's personal data
    (the spa is the data controller). The user-facing instructions
    URL explains this explicitly per Meta's data-deletion guidance.
    """
    from django.db import transaction

    affected: list[tuple[int, str]] = []
    if not user_id:
        return affected

    # Fast path: Instagram Login stores ig_user_id directly as
    # external_id on the Connection row, so we can filter at the SQL
    # layer for those. For legacy FB Login rows (if any), fall back
    # to the post-decrypt match below.
    candidates = list(
        Connection.objects.filter(
            provider__startswith='meta_',
            status=Connection.Status.CONNECTED,
        )
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
        # Match either form:
        #   - IG Login: external_id (== ig_user_id) directly
        #   - Legacy FB Login: auth_data['fb_user_id']
        matches_ig = conn.external_id == user_id
        matches_fb = payload.get('fb_user_id') == user_id
        if not (matches_ig or matches_fb):
            continue

        # Capture external_id BEFORE we wipe the field — the caller
        # persists it for the audit trail.
        external_id_at_revoke = conn.external_id

        with transaction.atomic():
            conn.status = Connection.Status.DISCONNECTED
            conn.clear_auth_data()
            conn.external_id = ''
            conn.external_name = ''
            conn.disconnected_at = timezone.now()
            conn.last_error_at = timezone.now()
            conn.last_error_message = (
                'Disconnected via Meta data-deletion callback — '
                'user removed the app from Meta.'
            )
            conn.save(update_fields=[
                'status', 'auth_data', 'external_id', 'external_name',
                'disconnected_at', 'last_error_at', 'last_error_message',
                'updated_at',
            ])
            affected.append((conn.pk, external_id_at_revoke))

    return affected
