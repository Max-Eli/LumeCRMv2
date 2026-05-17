"""Refresh long-lived Instagram tokens before they expire.

Instagram-Login long-lived tokens expire after 60 days. Meta's
`/refresh_access_token` endpoint extends them for another 60 days
as long as the token is at least 24h old + not yet expired. Without
this job, every connection silently dies on day 60 and the spa has
to reconnect from scratch.

Designed to run daily (EventBridge → ECS RunTask scheduled rule;
Terraform follow-up). Idempotent — safe to invoke twice in a row.

Behavior:
  - Selects connections where `expires_at` is set AND falls inside
    the refresh window (default: between 24h-old and 14 days from
    expiry — wide enough to recover from a few days of missed runs).
  - For each: attempt the refresh via Meta, update auth_data with
    the new token + extended expires_at on success, log + skip on
    failure (one bad row doesn't block the rest).
  - Flips Connection.status to ERROR when a refresh fails with a
    permanent-looking Meta error (expired, revoked) so the operator
    sees "reconnect needed" in the integrations UI.

Usage:

    python manage.py refresh_meta_tokens
    python manage.py refresh_meta_tokens --window-days=30
    python manage.py refresh_meta_tokens --tenant=acmespa --dry-run
"""

from __future__ import annotations

import time
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.integrations import meta as meta_oauth
from apps.integrations.models import Connection


# Permanent Meta error substrings — when we see these, we mark the
# connection ERROR (operator must reconnect). Anything else, we log
# but keep the connection alive for the next sweep to retry.
_PERMANENT_ERROR_HINTS = (
    'token has expired',
    'session has expired',
    'oauth access token',
    'permissions error',
    'access token could not be decrypted',
)


class Command(BaseCommand):
    help = 'Refresh long-lived Instagram access tokens before they expire.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--window-days', type=int, default=14,
            help='Refresh connections expiring within this many days (default: 14).',
        )
        parser.add_argument(
            '--tenant', type=str, default=None,
            help='Limit to a single tenant slug (debugging).',
        )
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Report what would refresh; do not call Meta.',
        )

    def handle(self, *args, **opts):
        window_days = opts['window_days']
        tenant_slug = opts['tenant']
        dry_run = opts['dry_run']

        now = timezone.now()
        # `expires_at` on Connection.auth_data is a Unix timestamp.
        # Refresh when (now + window_days) >= expires_at.
        # Also enforce Meta's minimum (token must be ≥24h old).
        threshold = int((now + timedelta(days=window_days)).timestamp())
        min_age = int((now - timedelta(hours=24)).timestamp())

        candidates = Connection.objects.filter(
            provider=Connection.Provider.META_INSTAGRAM,
            status=Connection.Status.CONNECTED,
        )
        if tenant_slug:
            candidates = candidates.filter(tenant__slug=tenant_slug)

        total = candidates.count()
        self.stdout.write(self.style.NOTICE(
            f'Inspecting {total} connected IG connection(s); '
            f'window={window_days}d; dry_run={dry_run}'
        ))

        refreshed = 0
        skipped = 0
        failed = 0
        errored_out = 0

        for conn in candidates.iterator():
            try:
                payload = conn.auth_data_dict
            except Exception as e:
                self._log_warn(
                    f'#{conn.pk} {conn.tenant.slug}: decrypt failed ({e}); skipping'
                )
                skipped += 1
                continue

            expires_at = payload.get('expires_at')
            access_token = payload.get('access_token', '')

            if not expires_at or not access_token:
                self._log_warn(
                    f'#{conn.pk} {conn.tenant.slug}: missing expires_at/access_token; skipping'
                )
                skipped += 1
                continue
            if expires_at > threshold:
                # Plenty of life left.
                skipped += 1
                continue
            if expires_at < min_age:
                # Token too old to refresh per Meta's 24h rule —
                # operator must reconnect.
                self._log_warn(
                    f'#{conn.pk} {conn.tenant.slug}: token >24h old; '
                    'reconnect required'
                )
                continue

            self.stdout.write(
                f'#{conn.pk} {conn.tenant.slug} expires at '
                f'{_fmt(expires_at)} (within window) → refresh'
            )
            if dry_run:
                refreshed += 1
                continue

            try:
                new_token, expires_in = meta_oauth.refresh_long_lived_token(
                    access_token=access_token,
                )
            except meta_oauth.MetaOAuthError as e:
                msg = str(e).lower()
                if any(hint in msg for hint in _PERMANENT_ERROR_HINTS):
                    conn.status = Connection.Status.ERROR
                    conn.last_error_at = now
                    conn.last_error_message = (
                        'Token refresh failed permanently — please '
                        'reconnect Instagram. Original error: '
                        + str(e)[:300]
                    )
                    conn.save(update_fields=[
                        'status', 'last_error_at', 'last_error_message',
                        'updated_at',
                    ])
                    errored_out += 1
                    self._log_err(
                        f'#{conn.pk} {conn.tenant.slug}: permanent refresh '
                        f'error, flagged ERROR ({e})'
                    )
                else:
                    failed += 1
                    self._log_err(
                        f'#{conn.pk} {conn.tenant.slug}: refresh failed '
                        f'(transient, will retry next sweep): {e}'
                    )
                continue

            # Success — update the encrypted payload + bump expires_at.
            payload['access_token'] = new_token
            payload['expires_at'] = int(time.time()) + (expires_in or 60 * 24 * 3600)
            conn.set_auth_data(payload)
            conn.last_synced_at = now
            conn.save(update_fields=['auth_data', 'last_synced_at', 'updated_at'])
            refreshed += 1

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            f'Done. Refreshed={refreshed} Skipped={skipped} '
            f'TransientFailed={failed} PermanentErrored={errored_out}'
        ))

    def _log_warn(self, msg: str) -> None:
        self.stdout.write(self.style.WARNING(msg))

    def _log_err(self, msg: str) -> None:
        self.stdout.write(self.style.ERROR(msg))


def _fmt(unix_ts: int) -> str:
    from datetime import datetime
    return datetime.fromtimestamp(unix_ts).strftime('%Y-%m-%d %H:%M')
