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

        # Capture profile data from the message's `from` expansion when
        # it's a customer-sent message. Meta's per-user profile endpoint
        # requires the 24-hour messaging window AND Advanced Access;
        # the message-context expansion (`from{username,name,profile_pic}`)
        # is more permissive (works in Standard Access for any message
        # in any conversation the business has had). For threads that
        # existed before the IG profile feature shipped, this is the
        # only working path to populate name + handle until the user
        # sends a fresh message.
        if not is_outbound:
            from_obj = msg.get('from') or {}
            _apply_message_context_profile(thread=thread, customer=customer, from_obj=from_obj)

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


def _apply_message_context_profile(*, thread, customer, from_obj: dict) -> None:
    """Populate thread + customer profile fields from message-context data.

    Meta's `from{id,username,name,profile_pic}` expansion on a message
    works in Standard Access — unlike the per-user profile endpoint
    which requires Advanced Access + the 24h messaging window. This
    is the only working path to populate IG identity for historical
    threads until App Review approval lands.

    Idempotent + non-destructive:
      - Thread fields are only set when Meta returned non-empty values.
      - Customer first/last name + instagram_handle are only updated
        when the customer still carries the "Instagram visitor XXXXXX"
        placeholder (i.e. the row was auto-created from a webhook
        before profile data was available). Operator-edited customers
        are left alone.
    """
    from_username = (from_obj.get('username') or '').strip()
    from_name = (from_obj.get('name') or '').strip()
    from_pic = (from_obj.get('profile_pic') or '').strip()

    if not (from_username or from_name or from_pic):
        return

    thread_update_fields = []
    if from_username and from_username != thread.external_username:
        thread.external_username = from_username[:128]
        thread_update_fields.append('external_username')
    if from_name and from_name != thread.external_display_name:
        thread.external_display_name = from_name[:200]
        thread_update_fields.append('external_display_name')
    if from_pic and from_pic != thread.external_profile_pic_url:
        thread.external_profile_pic_url = from_pic[:2048]
        thread_update_fields.append('external_profile_pic_url')

    if thread_update_fields:
        thread.external_profile_fetched_at = timezone.now()
        thread_update_fields += ['external_profile_fetched_at', 'updated_at']
        thread.save(update_fields=thread_update_fields)

    # Promote the customer name when it's still the placeholder.
    customer_update_fields = []
    if from_name and customer.first_name.startswith('Instagram visitor '):
        first, _, last = from_name.partition(' ')
        customer.first_name = first[:60] or 'Instagram'
        customer.last_name = last[:60]
        customer_update_fields += ['first_name', 'last_name']
    if from_username and not customer.instagram_handle:
        customer.instagram_handle = from_username[:60]
        customer_update_fields.append('instagram_handle')
    if customer_update_fields:
        customer_update_fields.append('updated_at')
        customer.save(update_fields=customer_update_fields)


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
