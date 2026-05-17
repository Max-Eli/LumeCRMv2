"""Refresh IG profile (name + username + profile pic) on existing threads.

When the IG profile feature shipped, every existing SocialThread had
empty profile fields (no display name, no profile pic). Webhook
deliveries on new messages refresh those threads naturally — but
quiet threads (no recent inbound) stay empty until a customer messages
again.

This command populates them in one pass. Also useful when:

  - Meta's profile-pic signing keys rotate (URLs ~weekly) and a
    handful of threads have stale URLs the operator wants refreshed
    immediately.
  - Operator-triggered "refresh this customer's IG identity" via a
    future per-row UI button.

Idempotent — re-running is a no-op for fresh threads (the
IG_PROFILE_REFRESH_AFTER_DAYS cooldown skips them).

Usage:

    # Refresh every CONNECTED IG thread (the common case after a
    # one-time backfill).
    python manage.py refresh_ig_profiles

    # Single tenant.
    python manage.py refresh_ig_profiles --tenant=acmespa

    # Force refresh even if the cached profile is still fresh.
    python manage.py refresh_ig_profiles --force

    # See what would happen.
    python manage.py refresh_ig_profiles --dry-run
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.integrations.meta import (
    IG_PROFILE_REFRESH_AFTER_DAYS,
    _fetch_ig_profile_best_effort,
)
from apps.integrations.models import Connection, SocialThread


class Command(BaseCommand):
    help = 'Refresh IG name + @handle + profile picture on existing social threads.'

    def add_arguments(self, parser):
        parser.add_argument('--tenant', type=str, default=None)
        parser.add_argument('--force', action='store_true', help='Refresh even if not stale.')
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **opts):
        threads = SocialThread.objects.filter(
            provider=SocialThread.Provider.INSTAGRAM,
            connection__status=Connection.Status.CONNECTED,
        ).select_related('connection')
        if opts.get('tenant'):
            threads = threads.filter(tenant__slug=opts['tenant'])

        total = threads.count()
        self.stdout.write(self.style.NOTICE(
            f'Found {total} candidate thread(s). '
            f'force={opts["force"]} dry_run={opts["dry_run"]}'
        ))

        skipped_fresh = 0
        skipped_empty = 0
        refreshed = 0
        for thread in threads:
            # Honour the cooldown unless --force.
            if not opts['force']:
                if (
                    thread.external_profile_fetched_at is not None
                    and (timezone.now() - thread.external_profile_fetched_at).days
                    < IG_PROFILE_REFRESH_AFTER_DAYS
                ):
                    skipped_fresh += 1
                    continue

            if opts['dry_run']:
                self.stdout.write(
                    f'  thread #{thread.pk} would refresh '
                    f'(currently: name={thread.external_display_name!r} '
                    f'@={thread.external_username!r} '
                    f'pic={"yes" if thread.external_profile_pic_url else "no"})'
                )
                continue

            profile = _fetch_ig_profile_best_effort(
                connection=thread.connection,
                external_thread_id=thread.external_thread_id,
            )
            if not (profile.get('username') or profile.get('name') or profile.get('profile_pic')):
                skipped_empty += 1
                continue

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
            refreshed += 1

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            f'Done. refreshed={refreshed} '
            f'skipped_fresh={skipped_fresh} '
            f'skipped_empty={skipped_empty}'
        ))
