"""Backfill recent Instagram DM history into the social inbox.

ADR 0027 §10. Meta's webhook system only forwards messages received
AFTER a webhook subscription is registered — there is no history
push on connect. Without backfill, a spa connecting their existing
Instagram presence sees an empty inbox even when they have years of
DMs in the IG app.

This module bridges the gap: on every successful OAuth connect, we
call Meta's `/conversations` + `/{conversation-id}/messages` endpoints
to seed the inbox with the most recent conversations. Caveats:

- Meta only returns recent activity (last ~30-50 conversations, and
  ~20-25 messages per conversation by default). Older threads + older
  messages within a thread are NOT available via this endpoint.
- Rate-limited (~200 calls/hour/account). One backfill = one /conversations
  call + up to BACKFILL_MAX_CONVERSATIONS message-fetch calls.
- The IG-scoped PSIDs we see here are the SAME format webhooks
  deliver, so re-using `_resolve_thread_and_customer` from meta.py
  gives us identical customer matching semantics.

Idempotency: the `SocialMessage` model's `(tenant, external_message_id)`
unique constraint plus `SocialThread`'s `(tenant, provider,
external_thread_id)` unique constraint mean re-running the backfill
is a no-op for already-imported rows. Safe to call repeatedly.

PHI posture: backfilled messages persist encrypted-at-rest the same
way live-ingested ones do (RDS KMS). Audit log records counts only,
never message bodies.
"""

from __future__ import annotations

import datetime as _dt
import logging
from dataclasses import dataclass

from django.db import IntegrityError, transaction
from django.utils import timezone

from . import meta as meta_oauth
from .meta import _resolve_thread_and_customer
from .models import Connection, SocialMessage, SocialThread

logger = logging.getLogger(__name__)


@dataclass
class BackfillResult:
    """Per-connection summary written to the audit log.

    Counts are intentionally minimal — `conversations_examined`,
    `messages_created`, and `messages_duplicate` together give a
    complete picture of what changed. We don't track threads_created
    because the existing `_resolve_thread_and_customer` helper
    doesn't surface a was-created flag; adding that would touch the
    live-ingest hot path for marginal benefit. Inspect SocialThread
    rows directly if you need that detail.
    """
    conversations_examined: int = 0
    messages_created: int = 0
    messages_duplicate: int = 0
    api_errors: int = 0

    def to_audit_metadata(self) -> dict:
        return {
            'conversations_examined': self.conversations_examined,
            'messages_created': self.messages_created,
            'messages_duplicate': self.messages_duplicate,
            'api_errors': self.api_errors,
        }


def backfill_connection(connection: Connection) -> BackfillResult:
    """Pull recent conversations + messages from Meta into our DB.

    Returns a BackfillResult summarising what happened (used by the
    OAuth callback to audit-log the backfill and by the management
    command to print human-readable output).

    Idempotent: re-running on the same connection adds nothing new.
    """
    result = BackfillResult()

    try:
        payload = connection.auth_data_dict
    except Exception:
        logger.warning(
            'integrations.backfill.decrypt_failed',
            extra={'connection_id': connection.pk},
        )
        return result

    ig_user_id = payload.get('ig_user_id', '')
    access_token = payload.get('access_token', '')
    if not (ig_user_id and access_token):
        logger.info(
            'integrations.backfill.skipped_missing_credentials',
            extra={'connection_id': connection.pk},
        )
        return result

    try:
        conversations = meta_oauth.list_recent_conversations(
            ig_user_id=ig_user_id,
            access_token=access_token,
        )
    except meta_oauth.MetaOAuthError as e:
        logger.warning(
            'integrations.backfill.list_conversations_failed',
            extra={'connection_id': connection.pk, 'error': str(e)[:300]},
        )
        result.api_errors += 1
        return result

    result.conversations_examined = len(conversations)

    for conv in conversations:
        conv_id = conv.get('id', '')
        if not conv_id:
            continue
        try:
            messages = meta_oauth.fetch_conversation_messages(
                conversation_id=conv_id,
                access_token=access_token,
            )
        except meta_oauth.MetaOAuthError as e:
            logger.warning(
                'integrations.backfill.fetch_messages_failed',
                extra={
                    'connection_id': connection.pk,
                    'conversation_id': conv_id,
                    'error': str(e)[:300],
                },
            )
            result.api_errors += 1
            continue
        _ingest_conversation_messages(
            connection=connection,
            ig_user_id=ig_user_id,
            messages=messages,
            result=result,
        )

    return result


def _ingest_conversation_messages(
    *,
    connection: Connection,
    ig_user_id: str,
    messages: list[dict],
    result: BackfillResult,
) -> None:
    """Convert Meta's message format into SocialThread + SocialMessage rows.

    Meta returns messages newest-first. We process oldest-first so
    `last_message_at` ends up reflecting the most recent message
    after all rows are written.

    A "thread" in Meta's `/conversations` is between two parties (the
    Business account + one customer). The customer is whoever appears
    on the OPPOSITE side of `from`/`to` from our `ig_user_id`. We use
    THEIR PSID as the SocialThread.external_thread_id so future
    webhook deliveries match the same thread.
    """
    if not messages:
        return

    for msg in reversed(messages):
        meta_message_id = msg.get('id', '')
        if not meta_message_id:
            continue
        body = msg.get('message', '') or ''
        created_time = _parse_iso(msg.get('created_time'))
        from_id = (msg.get('from') or {}).get('id', '')
        to_data = (msg.get('to') or {}).get('data', []) or []
        to_id = to_data[0].get('id', '') if to_data else ''

        is_outbound = from_id == ig_user_id
        # The OTHER party — whichever side isn't our business account.
        other_party = to_id if is_outbound else from_id
        if not other_party:
            continue

        thread, customer = _resolve_thread_and_customer(
            connection=connection,
            external_thread_id=other_party,
        )

        try:
            with transaction.atomic():
                SocialMessage.objects.create(
                    tenant=connection.tenant,
                    thread=thread,
                    direction=(
                        SocialMessage.Direction.OUTBOUND if is_outbound
                        else SocialMessage.Direction.INBOUND
                    ),
                    body=body,
                    external_message_id=meta_message_id,
                    status=(
                        SocialMessage.Status.SENT if is_outbound
                        else SocialMessage.Status.RECEIVED
                    ),
                    received_at=created_time if not is_outbound else None,
                    sent_at=created_time if is_outbound else None,
                )
        except IntegrityError:
            # Already backfilled — re-running is a no-op.
            result.messages_duplicate += 1
            continue

        result.messages_created += 1

        # Bump thread aggregates — only ADVANCE forward, never rewind.
        # Why: backfill runs on every reconnect, and historical messages
        # are older than any live-webhook state we already have. Without
        # this guard, a reconnect overwrites a fresh `last_inbound_at`
        # (e.g. from a DM that arrived 2 minutes ago) with a timestamp
        # from days ago — and the operator suddenly can't reply because
        # the UI thinks Meta's 24-hour window has closed.
        update_fields = ['updated_at']
        if thread.last_message_at is None or created_time > thread.last_message_at:
            thread.last_message_at = created_time
            update_fields.append('last_message_at')
        if not is_outbound:
            if (
                thread.last_inbound_at is None
                or created_time > thread.last_inbound_at
            ):
                thread.last_inbound_at = created_time
                # Only flip back to unread if this is the most recent
                # inbound. Backfilling 6-month-old history shouldn't
                # re-flag a thread the operator already triaged.
                thread.read_at = None
                update_fields += ['last_inbound_at', 'read_at']
        thread.save(update_fields=update_fields)


def _parse_iso(s: str | None) -> _dt.datetime:
    """Parse Meta's ISO timestamps (e.g. '2026-05-17T12:34:56+0000').

    Falls back to now() so we always have a usable datetime even if
    Meta's format ever changes.
    """
    if not s:
        return timezone.now()
    try:
        # Meta omits the colon in TZ offsets; Python 3.12 handles
        # both. Strip 'Z' for older versions just in case.
        if s.endswith('Z'):
            s = s[:-1] + '+0000'
        return _dt.datetime.fromisoformat(s).astimezone(_dt.timezone.utc)
    except (ValueError, TypeError):
        return timezone.now()
