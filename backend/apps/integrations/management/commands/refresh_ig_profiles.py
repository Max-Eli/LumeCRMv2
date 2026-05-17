"""Refresh IG name + @handle (+ profile pic when available) on existing threads.

Three paths, ordered by what works in Meta's permission model:

  - **Via messages (default, --via-messages)** — re-runs the backfill
    against the connection, which now extracts `from{username,name,
    profile_pic}` from each message's expansion. This works in
    Standard Access for any conversation the business has had, so
    it's the only reliable path until App Review approval lands.

  - **Bulk via /conversations participants (--bulk)** — works
    regardless of messaging-window state but REQUIRES Advanced Access
    on `instagram_business_manage_messages`. Returns 403 "Insufficient
    permissions" otherwise. Use post-App-Review for a faster single-
    call refresh.

  - **Per-thread via /{psid} profile endpoint (--per-thread)** —
    catches profile_pic for threads INSIDE the 24-hour messaging
    window. Returns "user not found" / "consent required" outside
    the window. Webhook path runs this on every new inbound so
    in-window threads stay current naturally.

When the customer carries the placeholder "Instagram visitor XXXXXX"
first_name (i.e. the row was created before the IG profile fetch
shipped), the command also updates the Customer row with the IG
display name + handle. Otherwise it leaves the customer alone so an
operator's manual edits aren't overwritten.

Usage:

    # Default: via messages — the path that works pre-App-Review.
    python manage.py refresh_ig_profiles

    # Bulk via participants (requires Advanced Access).
    python manage.py refresh_ig_profiles --bulk

    # Per-thread profile fetch (gets profile pic for in-window threads).
    python manage.py refresh_ig_profiles --per-thread

    # Single tenant.
    python manage.py refresh_ig_profiles --tenant=acmespa

    # See what would happen.
    python manage.py refresh_ig_profiles --dry-run
"""

from __future__ import annotations

import logging

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.integrations.meta import (
    IG_PROFILE_REFRESH_AFTER_DAYS,
    MetaOAuthError,
    _fetch_ig_profile_best_effort,
    list_conversations_with_participants,
)
from apps.integrations.models import Connection, SocialThread

logger = logging.getLogger(__name__)

# When the customer's first_name starts with this prefix, the row
# was auto-created from a webhook before we had IG profile data.
# Safe to overwrite with the real IG display name.
_PLACEHOLDER_FIRST_NAME_PREFIX = 'Instagram visitor '


class Command(BaseCommand):
    help = 'Refresh IG name + @handle (+ profile pic via --per-thread) on existing social threads.'

    def add_arguments(self, parser):
        parser.add_argument('--tenant', type=str, default=None)
        # Mode selection. Mutually-exclusive in spirit; the dispatch
        # below picks the most-specific flag (per-thread > bulk > messages).
        parser.add_argument(
            '--bulk', action='store_true',
            help='Use /conversations?fields=participants (requires Advanced Access).',
        )
        parser.add_argument(
            '--per-thread', action='store_true',
            help='Use the per-user profile endpoint (gets profile_pic, in-window threads only).',
        )
        parser.add_argument(
            '--via-messages', action='store_true',
            help='[default] Re-run backfill to extract profile data from message context. Works in Standard Access.',
        )
        parser.add_argument(
            '--force', action='store_true',
            help='Refresh even when the cached profile is still inside the cooldown.',
        )
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **opts):
        connections = Connection.objects.filter(
            provider=Connection.Provider.META_INSTAGRAM,
            status=Connection.Status.CONNECTED,
        )
        if opts.get('tenant'):
            connections = connections.filter(tenant__slug=opts['tenant'])

        # Default mode is via-messages — it's the only path that works
        # in Standard Access (pre-App-Review). --bulk and --per-thread
        # are explicit opt-ins for post-App-Review use.
        mode = (
            'per-thread' if opts['per_thread']
            else 'bulk' if opts['bulk']
            else 'via-messages'
        )

        total = connections.count()
        self.stdout.write(self.style.NOTICE(
            f'Found {total} connected IG connection(s). '
            f'mode={mode} force={opts["force"]} dry_run={opts["dry_run"]}'
        ))

        grand_refreshed = 0
        grand_skipped = 0
        grand_errors = 0

        for conn in connections:
            try:
                payload = conn.auth_data_dict
            except Exception:
                self.stdout.write(self.style.ERROR(
                    f'  conn #{conn.pk}: decrypt failed, skipping'
                ))
                grand_errors += 1
                continue

            access_token = payload.get('access_token', '')
            ig_user_id = payload.get('ig_user_id', '')
            if not (access_token and ig_user_id):
                self.stdout.write(self.style.WARNING(
                    f'  conn #{conn.pk}: missing credentials, skipping'
                ))
                continue

            self.stdout.write(
                f'  conn #{conn.pk} {conn.tenant.slug} '
                f'({conn.external_name or conn.external_id})'
            )

            if opts['per_thread']:
                r, s, e = self._refresh_per_thread(conn, opts)
            elif opts['bulk']:
                r, s, e = self._refresh_bulk(
                    conn=conn, ig_user_id=ig_user_id,
                    access_token=access_token, opts=opts,
                )
            else:
                r, s, e = self._refresh_via_messages(
                    conn=conn, opts=opts,
                )
            grand_refreshed += r
            grand_skipped += s
            grand_errors += e

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            f'Done. refreshed={grand_refreshed} '
            f'skipped={grand_skipped} errors={grand_errors}'
        ))

    # ── Via-messages path (works in Standard Access) ────────────────

    def _refresh_via_messages(self, *, conn, opts):
        """Re-run backfill — its per-message processing now extracts
        profile data from `from{username,name,profile_pic}` and applies
        it to the thread + customer. Counts are derived from the diff
        in threads with populated profiles before vs after."""
        from apps.integrations import backfill as _backfill

        with_profile_before = SocialThread.objects.filter(
            connection=conn,
            provider=SocialThread.Provider.INSTAGRAM,
        ).exclude(external_username='').count()

        if opts['dry_run']:
            self.stdout.write(
                f'    [dry-run] would invoke backfill_connection to '
                f'extract from{{...}} expansions on each message'
            )
            return 0, 0, 0

        result = _backfill.backfill_connection(conn)
        self.stdout.write(
            f'    backfill: examined={result.conversations_examined} '
            f'created={result.messages_created} '
            f'dup={result.messages_duplicate} '
            f'api_errors={result.api_errors}'
        )

        with_profile_after = SocialThread.objects.filter(
            connection=conn,
            provider=SocialThread.Provider.INSTAGRAM,
        ).exclude(external_username='').count()

        refreshed = max(0, with_profile_after - with_profile_before)
        return refreshed, 0, result.api_errors

    # ── Bulk path (requires Advanced Access) ────────────────────────

    def _refresh_bulk(self, *, conn, ig_user_id, access_token, opts):
        """Use /conversations?fields=participants to populate every thread."""
        try:
            conversations = list_conversations_with_participants(
                ig_user_id=ig_user_id,
                access_token=access_token,
            )
        except MetaOAuthError as e:
            self.stdout.write(self.style.ERROR(
                f'    Meta error listing conversations: {e}'
            ))
            return 0, 0, 1

        # Build a {participant_psid: {name, username}} map. Skip our own
        # business PSID; the rest are customers (one per conversation).
        psid_to_profile = {}
        for conv in conversations:
            participants = (conv.get('participants') or {}).get('data') or []
            for p in participants:
                p_id = p.get('id', '')
                if not p_id or p_id == ig_user_id:
                    continue
                psid_to_profile[p_id] = {
                    'name': p.get('name', '') or '',
                    'username': p.get('username', '') or '',
                }

        self.stdout.write(
            f'    Meta returned {len(psid_to_profile)} customer participant(s) '
            f'across {len(conversations)} conversation(s).'
        )

        # Match against existing threads on this connection.
        threads = SocialThread.objects.filter(
            connection=conn,
            provider=SocialThread.Provider.INSTAGRAM,
        ).select_related('customer')

        refreshed = 0
        skipped = 0
        for thread in threads:
            profile = psid_to_profile.get(thread.external_thread_id)
            if not profile:
                # Meta didn't return this PSID in the conversations
                # call — probably stale (test PSID, deleted user).
                skipped += 1
                continue

            # Cooldown — unless --force, don't re-fetch fresh rows.
            if not opts['force']:
                if (
                    thread.external_profile_fetched_at is not None
                    and (timezone.now() - thread.external_profile_fetched_at).days
                    < IG_PROFILE_REFRESH_AFTER_DAYS
                ):
                    skipped += 1
                    continue

            if opts['dry_run']:
                self.stdout.write(
                    f'    would set thread #{thread.pk}: '
                    f'name={profile["name"]!r} '
                    f'username={profile["username"]!r}'
                )
                continue

            self._apply_profile_to_thread(thread, profile, has_profile_pic=False)
            self._maybe_update_customer_name(thread.customer, profile)
            refreshed += 1

        return refreshed, skipped, 0

    # ── Per-thread fallback (catches profile_pic) ───────────────────

    def _refresh_per_thread(self, conn, opts):
        threads = SocialThread.objects.filter(
            connection=conn,
            provider=SocialThread.Provider.INSTAGRAM,
        ).select_related('customer')

        refreshed = 0
        skipped = 0
        errors = 0
        for thread in threads:
            if not opts['force']:
                if (
                    thread.external_profile_fetched_at is not None
                    and (timezone.now() - thread.external_profile_fetched_at).days
                    < IG_PROFILE_REFRESH_AFTER_DAYS
                ):
                    skipped += 1
                    continue

            profile = _fetch_ig_profile_best_effort(
                connection=conn,
                external_thread_id=thread.external_thread_id,
            )
            if not (profile.get('username') or profile.get('name') or profile.get('profile_pic')):
                # Outside messaging window or other Meta rejection.
                errors += 1
                continue

            if opts['dry_run']:
                self.stdout.write(
                    f'    would set thread #{thread.pk}: {profile!r}'
                )
                continue

            self._apply_profile_to_thread(
                thread, profile,
                has_profile_pic=bool(profile.get('profile_pic')),
            )
            self._maybe_update_customer_name(thread.customer, profile)
            refreshed += 1
        return refreshed, skipped, errors

    # ── Shared writers ──────────────────────────────────────────────

    def _apply_profile_to_thread(self, thread, profile, *, has_profile_pic):
        thread.external_username = profile.get('username', '') or thread.external_username
        thread.external_display_name = profile.get('name', '') or thread.external_display_name
        if has_profile_pic:
            thread.external_profile_pic_url = profile.get('profile_pic', '') or thread.external_profile_pic_url
        thread.external_profile_fetched_at = timezone.now()
        thread.save(update_fields=[
            'external_username',
            'external_display_name',
            'external_profile_pic_url',
            'external_profile_fetched_at',
            'updated_at',
        ])

    def _maybe_update_customer_name(self, customer, profile):
        """Update Customer.first_name / last_name / instagram_handle when
        the row still carries the auto-created placeholder.

        Detection: first_name starts with "Instagram visitor ". This
        means the Customer was created by the webhook before IG profile
        data was available; safe to overwrite. If the operator has
        renamed the customer (or merged into a real client record), the
        prefix won't match and we leave the row alone.
        """
        ig_name = (profile.get('name') or '').strip()
        ig_username = (profile.get('username') or '').strip()

        update_fields = []
        if (
            ig_name
            and customer.first_name.startswith(_PLACEHOLDER_FIRST_NAME_PREFIX)
        ):
            first, _, last = ig_name.partition(' ')
            customer.first_name = first[:60] or 'Instagram'
            customer.last_name = last[:60]
            update_fields += ['first_name', 'last_name']

        if ig_username and not customer.instagram_handle:
            customer.instagram_handle = ig_username[:60]
            update_fields.append('instagram_handle')

        if update_fields:
            update_fields.append('updated_at')
            customer.save(update_fields=update_fields)
