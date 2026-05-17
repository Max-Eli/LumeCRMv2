"""Import Zenoti packages into a Lumè tenant.

Multi-file CLI — Zenoti caps the Package Status report at 11
months per export, so 2024+2025+2026 ships as 3-4 files. Pass
them all in one invocation; the importer dedupes overlap by
Invoice No (later file wins for the most-recent balance).

Usage:

    # Local files, dry-run.
    python manage.py import_zenoti_packages \\
      --tenant demo \\
      --file "Packages01:01:24-11:30:24.csv" \\
      --file "Packages12:01:24-12:31:24.csv" \\
      --file "Packages01:01:25-11:30:25.csv" \\
      --file "Packages12:01:25-05:16:26.csv" \\
      --dry-run

    # Same files from S3 (production via ECS one-shot).
    python manage.py import_zenoti_packages \\
      --tenant demo \\
      --s3-uri s3://lume-prod-media-xxx/imports/packages-2024.csv \\
      --s3-uri s3://lume-prod-media-xxx/imports/packages-2024-dec.csv \\
      --s3-uri s3://lume-prod-media-xxx/imports/packages-2025.csv \\
      --s3-uri s3://lume-prod-media-xxx/imports/packages-2026-partial.csv \\
      --dry-run

You can mix --file and --s3-uri in one invocation; both stream
into memory.
"""

from __future__ import annotations

import csv
import io

from django.core.management.base import BaseCommand, CommandError

from apps.imports.zenoti.packages_importer import import_zenoti_packages
from apps.tenants.models import Tenant


class Command(BaseCommand):
    help = (
        'Import Zenoti packages into a Lumè tenant. Accepts multiple '
        '--file / --s3-uri inputs. Always dry-run first.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--tenant', type=str, required=True)
        parser.add_argument(
            '--file', action='append', default=[],
            help='Local path to a Zenoti Package Status CSV. Repeat for multiple files.',
        )
        parser.add_argument(
            '--s3-uri', action='append', default=[],
            help='S3 URI to a Zenoti Package Status CSV. Repeat for multiple files.',
        )
        parser.add_argument('--dry-run', action='store_true')
        parser.add_argument(
            '--error-log', type=str, default=None,
            help='Optional path to write a CSV of per-row mapping errors.',
        )
        parser.add_argument(
            '--customer-miss-log', type=str, default=None,
            help='Optional path to write a list of customer-match misses.',
        )

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
            f'Importing Zenoti packages into tenant={tenant.slug} '
            f'files={len(sources)} dry_run={opts["dry_run"]}'
        ))
        for label, _ in sources:
            self.stdout.write(f'  source: {label}')

        try:
            report = import_zenoti_packages(
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

        if report.mapping_errors:
            self.stdout.write('')
            self.stdout.write(self.style.WARNING(
                f'MAPPING ERRORS: {len(report.mapping_errors)} rows (first 5):'
            ))
            for err in report.mapping_errors[:5]:
                self.stdout.write(
                    f'  line {err.line_number}: invoice={err.raw_invoice_no!r} '
                    f'guest={err.raw_guest_name!r} → {err.reason}'
                )

        if report.customer_misses:
            self.stdout.write('')
            self.stdout.write(self.style.WARNING(
                f'CUSTOMER-MATCH MISSES: {len(report.customer_misses)} packages '
                f'(first 10 shown):'
            ))
            for miss in report.customer_misses[:10]:
                self.stdout.write(f'  - {miss}')

        if report.unmatched_service_names:
            self.stdout.write('')
            self.stdout.write(self.style.WARNING(
                f'UNMATCHED service names (kept as text snapshot): '
                f'{len(report.unmatched_service_names)} distinct '
                f'(first 10 shown):'
            ))
            for n in sorted(report.unmatched_service_names)[:10]:
                self.stdout.write(f'  - {n!r}')

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
        if opts.get('customer_miss_log') and report.customer_misses:
            with open(opts['customer_miss_log'], 'w') as f:
                for miss in report.customer_misses:
                    f.write(miss + '\n')
            self.stdout.write(self.style.NOTICE(
                f'Customer-miss log written to {opts["customer_miss_log"]}'
            ))

        self.stdout.write('')
        if opts['dry_run']:
            self.stdout.write(self.style.SUCCESS('DRY-RUN complete. No DB writes performed.'))
        else:
            self.stdout.write(self.style.SUCCESS(
                f'IMPORT complete. Created={report.rows_created} '
                f'Updated={report.rows_updated} '
                f'NoCustomer={report.rows_skipped_no_customer} '
                f'DBErr={report.rows_skipped_db_error} '
                f'Items={report.items_created} '
                f'(matched={report.items_matched_service} '
                f'unmatched={report.items_unmatched_service})'
            ))

    def _write_error_log(self, path, errors):
        with open(path, 'w', newline='', encoding='utf-8') as f:
            w = csv.writer(f)
            w.writerow(['line_number', 'invoice_no', 'guest_name', 'package_name', 'reason'])
            for err in errors:
                w.writerow([
                    err.line_number, err.raw_invoice_no, err.raw_guest_name,
                    err.raw_package_name, err.reason,
                ])


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
