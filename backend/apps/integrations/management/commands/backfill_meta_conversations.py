"""Backfill recent Instagram DM history into already-connected tenants.

ADR 0027 §10. Fresh connects auto-backfill in the OAuth callback;
this command is for tenants that connected BEFORE the backfill code
shipped, or who want to re-run after a Meta hiccup.

Idempotent — safe to invoke against the same connection repeatedly.

Usage:

    # Backfill every CONNECTED meta_instagram row
    python manage.py backfill_meta_conversations

    # Single tenant
    python manage.py backfill_meta_conversations --tenant=acmespa

    # Single connection (when you know its ID)
    python manage.py backfill_meta_conversations --connection-id=42

    # See what would happen without writing rows
    python manage.py backfill_meta_conversations --dry-run
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.audit.models import AuditLog
from apps.audit.services import record
from apps.integrations import backfill as _backfill
from apps.integrations.models import Connection


class Command(BaseCommand):
    help = 'Seed the social inbox with recent IG DM history for connected tenants.'

    def add_arguments(self, parser):
        parser.add_argument('--tenant', type=str, default=None)
        parser.add_argument('--connection-id', type=int, default=None)
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **opts):
        candidates = Connection.objects.filter(
            provider=Connection.Provider.META_INSTAGRAM,
            status=Connection.Status.CONNECTED,
        )
        if opts.get('tenant'):
            candidates = candidates.filter(tenant__slug=opts['tenant'])
        if opts.get('connection_id'):
            candidates = candidates.filter(pk=opts['connection_id'])

        total = candidates.count()
        if total == 0:
            raise CommandError(
                'No matching connected Instagram connections found.'
            )

        self.stdout.write(self.style.NOTICE(
            f'Backfilling {total} connection(s). dry_run={opts["dry_run"]}'
        ))

        grand = _Grand()
        for conn in candidates:
            self.stdout.write(
                f'#{conn.pk} {conn.tenant.slug} ({conn.external_name or conn.external_id})'
            )
            if opts['dry_run']:
                # Read-only path: just exercise the API + count without
                # creating rows. Implemented inline rather than gating
                # in the module so the audit/idempotency story stays
                # straightforward.
                from apps.integrations import meta as meta_oauth
                try:
                    payload = conn.auth_data_dict
                except Exception:
                    self.stdout.write(self.style.ERROR(
                        '  decrypt failed'
                    ))
                    continue
                if not (payload.get('ig_user_id') and payload.get('access_token')):
                    self.stdout.write(self.style.WARNING(
                        '  missing credentials, skipping'
                    ))
                    continue
                try:
                    convs = meta_oauth.list_recent_conversations(
                        ig_user_id=payload['ig_user_id'],
                        access_token=payload['access_token'],
                    )
                    self.stdout.write(
                        f'  would examine {len(convs)} conversation(s)'
                    )
                    grand.conversations += len(convs)
                except meta_oauth.MetaOAuthError as e:
                    self.stdout.write(self.style.ERROR(f'  Meta error: {e}'))
                    grand.errors += 1
                continue

            result = _backfill.backfill_connection(conn)
            self.stdout.write(
                f'  examined={result.conversations_examined} '
                f'msgs_created={result.messages_created} '
                f'msgs_dup={result.messages_duplicate} '
                f'errors={result.api_errors}'
            )
            record(
                action=AuditLog.Action.UPDATE,
                resource_type='integration_connection',
                resource_id=conn.pk,
                request=None,
                metadata={
                    'event': 'backfill_completed_manual',
                    **result.to_audit_metadata(),
                },
            )
            grand.conversations += result.conversations_examined
            grand.created += result.messages_created
            grand.dup += result.messages_duplicate
            grand.errors += result.api_errors

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            f'Done. conversations={grand.conversations} '
            f'msgs_created={grand.created} '
            f'msgs_dup={grand.dup} '
            f'errors={grand.errors}'
        ))


class _Grand:
    """Cheap mutable accumulator for cross-connection totals."""
    def __init__(self):
        self.conversations = 0
        self.created = 0
        self.dup = 0
        self.errors = 0
