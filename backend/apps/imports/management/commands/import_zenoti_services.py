"""Import Zenoti services into a Lumè tenant.

Mirrors `import_zenoti_guests` for shape + safety. Two-pass; ALWAYS
dry-run first. See [ADR 0030] for the migration design.

Usage:

    # Dry-run against demo first.
    python manage.py import_zenoti_services \\
      --tenant demo \\
      --file serviceswithprices.csv \\
      --dry-run

    # Live import once dry-run is clean.
    python manage.py import_zenoti_services \\
      --tenant demo \\
      --file serviceswithprices.csv

    # S3 input (for production via ECS one-shot).
    python manage.py import_zenoti_services \\
      --tenant manhattan-laser-spa \\
      --s3-uri s3://lume-prod-media-xxx/imports/services.csv
"""

from __future__ import annotations

import csv

from django.core.management.base import BaseCommand, CommandError

from apps.imports.zenoti.services_importer import import_zenoti_services
from apps.tenants.models import Tenant


class Command(BaseCommand):
    help = 'Import Zenoti services into a Lumè tenant. Always dry-run first.'

    def add_arguments(self, parser):
        parser.add_argument('--tenant', type=str, required=True)
        parser.add_argument(
            '--file', type=str, default=None,
            help='Local path to the Zenoti services-with-prices CSV.',
        )
        parser.add_argument(
            '--s3-uri', type=str, default=None,
            help='S3 URI (s3://bucket/key) — streamed into memory; never touches disk.',
        )
        parser.add_argument('--dry-run', action='store_true')
        parser.add_argument(
            '--error-log', type=str, default=None,
            help='Optional path to write a CSV of per-row mapping errors.',
        )

    def handle(self, *args, **opts):
        try:
            tenant = Tenant.objects.get(slug=opts['tenant'])
        except Tenant.DoesNotExist:
            raise CommandError(f'No tenant with slug {opts["tenant"]!r}.')

        if bool(opts.get('file')) == bool(opts.get('s3_uri')):
            raise CommandError('Provide exactly one of --file or --s3-uri.')

        self.stdout.write(self.style.NOTICE(
            f'Importing Zenoti services into tenant={tenant.slug} dry_run={opts["dry_run"]}'
        ))

        if opts.get('s3_uri'):
            file_obj = _open_s3_uri(opts['s3_uri'])
        else:
            try:
                file_obj = open(opts['file'], encoding='utf-8-sig')
            except OSError as e:
                raise CommandError(f'Cannot open file: {e}')

        try:
            report = import_zenoti_services(
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
                f'(first 5 shown):'
            ))
            for err in report.mapping_errors[:5]:
                self.stdout.write(
                    f'  line {err.line_number}: name={err.raw_name!r} '
                    f'code={err.raw_code!r} → {err.reason}'
                )

        if report.db_errors:
            self.stdout.write('')
            self.stdout.write(self.style.ERROR(
                f'DB ERRORS: {len(report.db_errors)} rows (first 5):'
            ))
            for err in report.db_errors[:5]:
                self.stdout.write(f'  - {err}')

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
                    f'Ready to import {report.rows_mapped} services + '
                    f'create {len(set(m.category_name for m in [] if m))} categories. '
                    f'Re-run without --dry-run when approved.'
                )
        else:
            self.stdout.write(self.style.SUCCESS(
                f'IMPORT complete. Created={report.rows_created} '
                f'Updated={report.rows_updated} '
                f'Skipped(filter)={report.rows_skipped_filtered} '
                f'Skipped(dupe)={report.rows_skipped_duplicate_in_export} '
                f'Skipped(db)={report.rows_skipped_db_error} '
                f'Categories+={report.categories_created}'
            ))

    def _write_error_log(self, path, errors):
        with open(path, 'w', newline='', encoding='utf-8') as f:
            w = csv.writer(f)
            w.writerow(['line_number', 'name', 'code', 'category', 'reason'])
            for err in errors:
                w.writerow([
                    err.line_number, err.raw_name, err.raw_code,
                    err.raw_category, err.reason,
                ])


def _open_s3_uri(uri: str):
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
    return io.StringIO(body.decode('utf-8-sig'))
