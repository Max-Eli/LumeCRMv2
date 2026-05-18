"""Import Zenoti appointments into a Lumè tenant.

Multi-file CLI (Zenoti caps reports at 11 months). Customers,
Services, Employees must be imported first — appointments need
all three FK targets to land.

Usage:

    # Local files, dry-run first.
    python manage.py import_zenoti_appointments \\
      --tenant demo \\
      --file appointments2026.csv \\
      --file appointments2025.csv \\
      --dry-run

    # S3 (production via ECS one-shot).
    python manage.py import_zenoti_appointments \\
      --tenant demo \\
      --s3-uri s3://bucket/imports/appointments-2026.csv \\
      --s3-uri s3://bucket/imports/appointments-2025.csv
"""

from __future__ import annotations

import csv
import io

from django.core.management.base import BaseCommand, CommandError

from apps.imports.zenoti.appointments_importer import import_zenoti_appointments
from apps.tenants.models import Tenant


class Command(BaseCommand):
    help = (
        'Import Zenoti appointments into a Lumè tenant. Accepts '
        'multiple --file / --s3-uri inputs. Always dry-run first.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--tenant', type=str, required=True)
        parser.add_argument('--file', action='append', default=[])
        parser.add_argument('--s3-uri', action='append', default=[])
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **opts):
        try:
            tenant = Tenant.objects.get(slug=opts['tenant'])
        except Tenant.DoesNotExist:
            raise CommandError(f'No tenant with slug {opts["tenant"]!r}.')

        sources: list[tuple[str, object]] = []
        for path in opts['file']:
            sources.append((path, _open_local(path)))
        for uri in opts['s3_uri']:
            sources.append((uri, _open_s3_uri(uri)))
        if not sources:
            raise CommandError('Provide at least one --file or --s3-uri.')

        self.stdout.write(self.style.NOTICE(
            f'Importing Zenoti appointments into tenant={tenant.slug} '
            f'files={len(sources)} dry_run={opts["dry_run"]}'
        ))
        for label, _ in sources:
            self.stdout.write(f'  source: {label}')

        try:
            report = import_zenoti_appointments(
                tenant=tenant,
                file_objs=[obj for _, obj in sources],
                dry_run=opts['dry_run'],
            )
        finally:
            for _, obj in sources:
                try:
                    obj.close()
                except Exception:
                    pass

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
                    f'  line {err.line_number}: invoice={err.raw_invoice_no!r} '
                    f'status={err.raw_status!r} → {err.reason}'
                )

        if report.customer_misses:
            self.stdout.write('')
            self.stdout.write(self.style.WARNING(
                f'CUSTOMER MISSES: {len(report.customer_misses)} (first 10):'
            ))
            for miss in report.customer_misses[:10]:
                self.stdout.write(f'  - {miss}')

        if report.service_misses:
            self.stdout.write('')
            self.stdout.write(self.style.WARNING(
                f'UNMATCHED SERVICE NAMES: {len(report.service_misses)} distinct (first 10):'
            ))
            for n in report.service_misses[:10]:
                self.stdout.write(f'  - {n!r}')

        if report.provider_misses:
            self.stdout.write('')
            self.stdout.write(self.style.WARNING(
                f'UNMATCHED PROVIDER NAMES: {len(report.provider_misses)} distinct:'
            ))
            for n in report.provider_misses[:10]:
                self.stdout.write(f'  - {n!r}')

        if report.db_errors:
            self.stdout.write('')
            self.stdout.write(self.style.ERROR(
                f'DB ERRORS: {len(report.db_errors)} (first 5):'
            ))
            for err in report.db_errors[:5]:
                self.stdout.write(f'  - {err}')

        self.stdout.write('')
        if opts['dry_run']:
            self.stdout.write(self.style.SUCCESS('DRY-RUN complete. No DB writes performed.'))
        else:
            self.stdout.write(self.style.SUCCESS(
                f'IMPORT complete. '
                f'Created={report.rows_created} '
                f'Updated={report.rows_updated} '
                f'InvoicesClosed={report.invoices_closed} '
                f'InvoicesVoided={report.invoices_voided} '
                f'SchedulesSet={report.schedules_set} '
                f'NoCust={report.rows_skipped_no_customer} '
                f'NoSvc={report.rows_skipped_no_service} '
                f'NoProv={report.rows_skipped_no_provider}'
            ))


def _open_local(path: str):
    try:
        return open(path, encoding='utf-8-sig')
    except OSError as e:
        raise CommandError(f'Cannot open file {path}: {e}')


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
