"""Import Zenoti employees into a Lumè tenant.

Always dry-run first; only commit to a real tenant once the
reconciliation report looks right.

Usage:

    # Dry-run against demo.
    python manage.py import_zenoti_employees \\
      --tenant demo --file Employees.csv --dry-run

    # Live to demo.
    python manage.py import_zenoti_employees \\
      --tenant demo --file Employees.csv

    # Via S3 (production via ECS one-shot).
    python manage.py import_zenoti_employees \\
      --tenant demo \\
      --s3-uri s3://lume-prod-media-xxx/imports/employees.csv
"""

from __future__ import annotations

import csv
import io

from django.core.management.base import BaseCommand, CommandError

from apps.imports.zenoti.employees_importer import import_zenoti_employees
from apps.tenants.models import Tenant


class Command(BaseCommand):
    help = 'Import Zenoti employees (bookable staff) into a Lumè tenant.'

    def add_arguments(self, parser):
        parser.add_argument('--tenant', type=str, required=True)
        parser.add_argument('--file', type=str, default=None)
        parser.add_argument('--s3-uri', type=str, default=None)
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

        file_obj = _open_s3_uri(opts['s3_uri']) if opts.get('s3_uri') else _open_local(opts['file'])

        self.stdout.write(self.style.NOTICE(
            f'Importing Zenoti employees into tenant={tenant.slug} dry_run={opts["dry_run"]}'
        ))

        try:
            report = import_zenoti_employees(
                tenant=tenant, file_obj=file_obj, dry_run=opts['dry_run'],
            )
        finally:
            try:
                file_obj.close()
            except Exception:
                pass

        # ── Reconciliation report ────────────────────────────────
        self.stdout.write('')
        self.stdout.write(self.style.NOTICE('=== Reconciliation report ==='))
        for key, value in report.to_summary_dict().items():
            self.stdout.write(f'  {key:40s} = {value}')

        if report.header_errors:
            self.stdout.write('')
            self.stdout.write(self.style.ERROR('HEADER ERRORS (import aborted):'))
            for err in report.header_errors:
                self.stdout.write(f'  - {err}')

        if report.mapping_errors:
            self.stdout.write('')
            self.stdout.write(self.style.WARNING(
                f'MAPPING ERRORS: {len(report.mapping_errors)} rows (first 5):'
            ))
            for err in report.mapping_errors[:5]:
                self.stdout.write(
                    f'  line {err.line_number}: code={err.raw_code!r} '
                    f'{err.raw_first_name!r}/{err.raw_last_name!r} '
                    f'job={err.raw_job!r} → {err.reason}'
                )

        if report.duplicate_emails:
            self.stdout.write('')
            self.stdout.write(self.style.WARNING(
                f'DUPLICATE emails inside export: {report.duplicate_emails[:10]}'
            ))

        if report.db_errors:
            self.stdout.write('')
            self.stdout.write(self.style.ERROR(
                f'DB ERRORS: {len(report.db_errors)} rows (first 5):'
            ))
            for err in report.db_errors[:5]:
                self.stdout.write(f'  - {err}')

        if opts.get('error_log') and report.mapping_errors:
            with open(opts['error_log'], 'w', newline='', encoding='utf-8') as f:
                w = csv.writer(f)
                w.writerow(['line_number', 'code', 'first_name', 'last_name', 'job', 'reason'])
                for err in report.mapping_errors:
                    w.writerow([err.line_number, err.raw_code, err.raw_first_name,
                                err.raw_last_name, err.raw_job, err.reason])
            self.stdout.write('')
            self.stdout.write(self.style.NOTICE(
                f'Per-row error log written to {opts["error_log"]}'
            ))

        self.stdout.write('')
        if opts['dry_run']:
            self.stdout.write(self.style.SUCCESS('DRY-RUN complete. No DB writes performed.'))
        else:
            self.stdout.write(self.style.SUCCESS(
                f'IMPORT complete. '
                f'Users created/reused={report.users_created}/{report.users_reused} '
                f'Memberships created/reused={report.memberships_created}/{report.memberships_reused} '
                f'JobTitles created={report.job_titles_created} '
                f'LocationsAssigned={report.locations_assigned}'
            ))


def _open_local(path: str):
    try:
        return open(path, encoding='utf-8-sig')
    except OSError as e:
        raise CommandError(f'Cannot open file: {e}')


def _open_s3_uri(uri: str):
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
