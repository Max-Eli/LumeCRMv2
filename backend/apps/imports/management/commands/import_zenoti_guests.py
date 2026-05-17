"""Import Zenoti customers into a Lumè tenant.

Two-pass: validate everything first (dry-run), then write only after
the operator approves. See ADR 0030 for the rationale and the
permanent-once-imported audit log shape.

Usage:

    # Dry-run against the sandbox tenant. ALWAYS do this first.
    python manage.py import_zenoti_guests \\
      --tenant demo \\
      --file ZenotiActiveGuest.csv \\
      --dry-run

    # Real import to Manhattan once dry-run looks clean.
    python manage.py import_zenoti_guests \\
      --tenant manhattan-laser-spa \\
      --file ZenotiActiveGuest.csv

    # Write the per-row error log to a file for triage.
    python manage.py import_zenoti_guests \\
      --tenant demo --file Zenoti...csv --dry-run \\
      --error-log /tmp/zenoti-errors.csv
"""

from __future__ import annotations

import csv

from django.core.management.base import BaseCommand, CommandError

from apps.imports.zenoti.importer import import_zenoti_guests
from apps.tenants.models import Tenant


class Command(BaseCommand):
    help = 'Import Zenoti customers into a Lumè tenant. Always dry-run first.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--tenant', type=str, required=True,
            help='Target tenant slug (e.g. `demo` or `manhattan-laser-spa`).',
        )
        parser.add_argument(
            '--file', type=str, default=None,
            help='Local path to the Zenoti guest CSV export. Mutually exclusive with --s3-uri.',
        )
        parser.add_argument(
            '--s3-uri', type=str, default=None,
            help='S3 URI to the CSV (e.g. `s3://lume-prod-media-xxx/imports/zenoti.csv`). '
                 'Streamed into memory; never touched on local disk. Mutually exclusive with --file.',
        )
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Validate + report only. No DB writes. Use this first.',
        )
        parser.add_argument(
            '--error-log', type=str, default=None,
            help='Optional path to write a CSV of per-row mapping errors.',
        )

    def handle(self, *args, **opts):
        try:
            tenant = Tenant.objects.get(slug=opts['tenant'])
        except Tenant.DoesNotExist:
            raise CommandError(f'No tenant with slug {opts["tenant"]!r}.')

        self.stdout.write(self.style.NOTICE(
            f'Importing Zenoti guests into tenant={tenant.slug} '
            f'(id={tenant.pk}) dry_run={opts["dry_run"]}'
        ))

        if bool(opts.get('file')) == bool(opts.get('s3_uri')):
            raise CommandError('Provide exactly one of --file or --s3-uri.')

        if opts.get('s3_uri'):
            file_obj = _open_s3_uri(opts['s3_uri'])
        else:
            try:
                file_obj = open(opts['file'], encoding='utf-8-sig')
            except OSError as e:
                raise CommandError(f'Cannot open file: {e}')

        try:
            report = import_zenoti_guests(
                tenant=tenant, file_obj=file_obj, dry_run=opts['dry_run'],
            )
        finally:
            file_obj.close()

        # ── Print the reconciliation report ────────────────────────
        self.stdout.write('')
        self.stdout.write(self.style.NOTICE('=== Reconciliation report ==='))
        for key, value in report.to_summary_dict().items():
            self.stdout.write(f'  {key:40s} = {value}')

        if report.header_errors:
            self.stdout.write('')
            self.stdout.write(self.style.ERROR('HEADER ERRORS (import aborted):'))
            for err in report.header_errors:
                self.stdout.write(f'  - {err}')

        if report.duplicate_external_ids:
            self.stdout.write('')
            self.stdout.write(self.style.WARNING(
                f'DUPLICATE external_ids in export (first 20): '
                f'{report.duplicate_external_ids[:20]}'
            ))

        if report.mapping_errors:
            self.stdout.write('')
            self.stdout.write(self.style.WARNING(
                f'MAPPING ERRORS: {len(report.mapping_errors)} rows '
                f'(first 5 shown; pass --error-log to dump all):'
            ))
            for err in report.mapping_errors[:5]:
                self.stdout.write(
                    f'  line {err.line_number}: '
                    f'{err.raw_first_name!r}/{err.raw_last_name!r} '
                    f'code={err.raw_code!r} → {err.reason}'
                )

        if report.db_errors:
            self.stdout.write('')
            self.stdout.write(self.style.ERROR(
                f'DB ERRORS: {len(report.db_errors)} rows (first 5):'
            ))
            for err in report.db_errors[:5]:
                self.stdout.write(f'  - {err}')

        # Optional: write the full per-row error log.
        if opts.get('error_log') and report.mapping_errors:
            self._write_error_log(opts['error_log'], report.mapping_errors)
            self.stdout.write('')
            self.stdout.write(self.style.NOTICE(
                f'Per-row error log written to {opts["error_log"]}'
            ))

        self.stdout.write('')
        if opts['dry_run']:
            self.stdout.write(self.style.SUCCESS('DRY-RUN complete. No DB writes performed.'))
            if not report.header_errors and report.rows_mapped > 0:
                self.stdout.write(
                    f'Ready to import {report.rows_mapped} guests. '
                    f'Re-run without --dry-run when approved.'
                )
        else:
            self.stdout.write(self.style.SUCCESS(
                f'IMPORT complete. Created={report.rows_created} '
                f'Updated={report.rows_updated} '
                f'Skipped={report.rows_skipped_duplicate_in_export + report.rows_skipped_db_error}'
            ))

    def _write_error_log(self, path, errors):
        with open(path, 'w', newline='', encoding='utf-8') as f:
            w = csv.writer(f)
            w.writerow(['line_number', 'first_name', 'last_name', 'code', 'reason'])
            for err in errors:
                w.writerow([
                    err.line_number, err.raw_first_name, err.raw_last_name,
                    err.raw_code, err.reason,
                ])


def _open_s3_uri(uri: str):
    """Download an S3 object into an in-memory StringIO and return it.

    The backend container has IAM access to the media bucket via the
    ECS task role (no creds in env). Stream to memory rather than
    disk so we don't leave PHI on the container filesystem after
    the task exits.
    """
    import io
    import boto3

    if not uri.startswith('s3://'):
        raise CommandError('--s3-uri must start with s3://')
    rest = uri[len('s3://'):]
    if '/' not in rest:
        raise CommandError('--s3-uri must include both bucket and key.')
    bucket, _, key = rest.partition('/')
    s3 = boto3.client('s3')
    body = s3.get_object(Bucket=bucket, Key=key)['Body'].read()
    # utf-8-sig handles a BOM if Zenoti's export was saved from Excel.
    return io.StringIO(body.decode('utf-8-sig'))
