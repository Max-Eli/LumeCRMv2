"""Base view + helpers for every report.

Every concrete report subclasses `BaseReportView`, sets the metadata
class attributes (`report_id`, `category`, `permission`, `title`,
`description`, `phi_tier`), and implements `run(...)`. The base class
handles parameter parsing, permission gating (via
`ReportPermission`), audit logging, and response shaping.

Why one class per report (not a generic dispatcher): each report has
its own param + response shape. A generic `ReportViewSet` that
dispatches on `report_id` would re-implement DRF routing badly and
defeat drf-spectacular's per-endpoint OpenAPI generation. See ADR
0013 for the full rationale.

Response envelope (consistent across all reports):

    {
      "report_id": "financial.sales_by_date_range",
      "params":    {...},        # what the report ran with
      "summary":   {...},        # scalar aggregates (top-of-page tiles)
      "rows":      [...],        # tabular data (table body)
    }

Same endpoint serves CSV when called with `?download=csv`. CSV streams
the `rows` table flattened to scalars; subclasses can override
`csv_columns()` if their default-flattened shape isn't right (e.g.
the daily-close-out per-method dict). See `_export_csv()` and ADR
0013 for the PHI-confirmation gate that fires for `per_customer`
reports.

We use `?download=csv` (not `?format=csv`) deliberately — DRF
reserves `?format=` for its own content negotiation, which would
404 a `format=csv` query param when no CSV renderer is registered
on the view.

The audit log entry on every successful run names the report ID, the
category, the params, and the row count. PHI never appears in the
audit metadata — even per-customer reports record only counts there.
CSV exports write `action=EXPORT` instead of `READ` and include
`phi_confirmed: True` when the report carries per-customer PHI.
"""

from __future__ import annotations

import csv
import datetime as dt
from io import StringIO
from typing import Any

from django.http import StreamingHttpResponse
from django.utils.dateparse import parse_date
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.models import AuditLog
from apps.audit.services import record

from .permissions import ReportPermission

DEFAULT_DATE_RANGE_DAYS = 30
MAX_DATE_RANGE_DAYS = 366

# Truthy values the frontend may send for ?phi_confirmed=. Lowercased.
TRUTHY_QUERY_VALUES = frozenset({'1', 'true', 'yes', 'on'})


class BaseReportView(APIView):
    """Base class for every report.

    Subclasses set the class attributes below and implement `run()`.
    """

    permission_classes = [ReportPermission]

    # Stable identifier — '<category>.<snake_case_name>'. Used as
    # `AuditLog.resource_id` and as the catalog key.
    report_id: str = ''

    # One of: 'financial' | 'staff' | 'guests' | 'operations' | 'marketing'.
    category: str = ''

    # Permission constant from `apps.tenants.permissions.P`.
    permission: str = ''

    # Human-readable label + one-line description for the catalog.
    title: str = ''
    description: str = ''

    # PHI sensitivity (drives the export-confirmation gate):
    #   'none'         — counts and money only, no per-customer rows
    #   'aggregated'   — names staff but not customers
    #   'per_customer' — names individual customers; CSV export requires
    #                    `?phi_confirmed=true` (operator attestation)
    phi_tier: str = 'none'

    # ── Request lifecycle ─────────────────────────────────────────

    def get(self, request, *args, **kwargs):
        params = self.parse_params(request)
        result = self.run(request, **params)
        envelope = {
            'report_id': self.report_id,
            'params': self._params_for_response(params),
            'summary': result.get('summary', {}),
            'rows': result.get('rows', []),
        }
        if self._is_csv_request(request):
            return self._export_csv(request, envelope)
        self._audit_read(request, envelope)
        return Response(envelope)

    # ── Subclass extension points ────────────────────────────────

    def run(self, request, **params) -> dict:
        """Compute the report. Returns a dict with optional 'summary' + 'rows' keys."""
        raise NotImplementedError

    def parse_params(self, request) -> dict:
        """Parse query params into a kwargs dict for `run()`.

        Default implementation: parses `date_from` + `date_to` with a
        last-30-days fallback. Override for reports with different
        params, calling helpers below as needed.
        """
        return self.parse_date_range(request)

    def csv_columns(self, envelope: dict) -> list[tuple[str, str]] | None:
        """Optional override: return [(header, row_key), ...] for the CSV.

        If `None` (default), the export auto-detects columns from the
        first row's keys, in their dict order. Override when the
        default order is awkward (e.g. you want money columns on
        the right, not after the date).
        """
        return None

    def csv_rows(self, envelope: dict) -> list[dict]:
        """Optional override: produce the row dicts to feed into the CSV.

        Defaults to `envelope['rows']`. Override when rows contain
        nested data that needs to be flattened into per-column scalars
        (e.g. daily close-out's `by_method` dict expanded into one
        column per payment method).

        Must remain pure — don't mutate `envelope`.
        """
        return list(envelope.get('rows') or [])

    # ── Helpers ──────────────────────────────────────────────────

    def parse_date_range(self, request) -> dict:
        """Parse `?date_from=YYYY-MM-DD&date_to=YYYY-MM-DD` from query params.

        Defaults: last 30 days ending today (UTC).
        Validates: dates parse, range non-inverted, span ≤ MAX_DATE_RANGE_DAYS.
        """
        today = dt.date.today()
        date_to_raw = (request.query_params.get('date_to') or '').strip()
        date_from_raw = (request.query_params.get('date_from') or '').strip()

        date_to = parse_date(date_to_raw) if date_to_raw else today
        if date_to_raw and date_to is None:
            raise ValidationError({'date_to': 'Invalid date format; expected YYYY-MM-DD.'})

        date_from = parse_date(date_from_raw) if date_from_raw else (date_to - dt.timedelta(days=DEFAULT_DATE_RANGE_DAYS - 1))
        if date_from_raw and date_from is None:
            raise ValidationError({'date_from': 'Invalid date format; expected YYYY-MM-DD.'})

        if date_from > date_to:
            raise ValidationError({'date_from': 'date_from must be on or before date_to.'})

        span = (date_to - date_from).days + 1
        if span > MAX_DATE_RANGE_DAYS:
            raise ValidationError({
                'date_to': f'Date range too wide ({span} days); max is {MAX_DATE_RANGE_DAYS}.'
            })

        return {'date_from': date_from, 'date_to': date_to}

    @staticmethod
    def _params_for_response(params: dict) -> dict:
        """Coerce params (dates, etc.) into JSON-serializable shape for the response + audit log."""
        return {
            k: (v.isoformat() if isinstance(v, (dt.date, dt.datetime)) else v)
            for k, v in params.items()
        }

    # ── CSV export ───────────────────────────────────────────────

    def _is_csv_request(self, request) -> bool:
        # NOTE: not `?format=csv` — that name is reserved by DRF
        # content negotiation and would 404 when no CSV renderer is
        # registered. `?download=csv` keeps the intent clear and
        # sidesteps the conflict.
        return (request.query_params.get('download') or '').strip().lower() == 'csv'

    def _phi_confirmed(self, request) -> bool:
        raw = (request.query_params.get('phi_confirmed') or '').strip().lower()
        return raw in TRUTHY_QUERY_VALUES

    def _export_csv(self, request, envelope: dict) -> StreamingHttpResponse:
        """Stream the report's `rows` as CSV.

        Per-customer reports require `?phi_confirmed=true` — that's the
        operator's attestation that the export is necessary for spa
        operations (HIPAA §164.502(b) minimum-necessary). Without it
        we 403 with a `phi_confirmation_required` detail so the
        frontend can show the confirmation modal.
        """
        if self.phi_tier == 'per_customer' and not self._phi_confirmed(request):
            raise PermissionDenied({
                'detail': (
                    'This report contains per-customer PHI. Export requires '
                    'explicit confirmation via the export-confirmation prompt.'
                ),
                'code': 'phi_confirmation_required',
                'phi_tier': self.phi_tier,
            })

        rows = self.csv_rows(envelope)
        columns = self.csv_columns(envelope) or self._auto_columns(rows)
        filename = self._csv_filename(envelope)

        response = StreamingHttpResponse(
            self._stream_csv(rows, columns),
            content_type='text/csv; charset=utf-8',
        )
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        # Audit AFTER stream construction but BEFORE returning so the
        # entry is recorded even if the client aborts the download
        # mid-stream. Better to over-record than under-record on PHI.
        self._audit_export(request, envelope, row_count=len(rows))
        return response

    def _csv_filename(self, envelope: dict) -> str:
        """e.g. 'financial.sales_by_date_range_2026-04-01_2026-05-01.csv'."""
        params = envelope.get('params') or {}
        suffix_parts = []
        if 'date_from' in params and 'date_to' in params:
            suffix_parts = [str(params['date_from']), str(params['date_to'])]
        else:
            suffix_parts = [dt.date.today().isoformat()]
        suffix = '_'.join(suffix_parts)
        return f'{self.report_id}_{suffix}.csv'

    @staticmethod
    def _auto_columns(rows: list[dict]) -> list[tuple[str, str]]:
        """Default column extraction: keys of the first row, in dict order.
        Header label = key with underscores → spaces, title-cased."""
        if not rows:
            return []
        out = []
        for k in rows[0].keys():
            label = k.replace('_', ' ').title()
            out.append((label, k))
        return out

    @staticmethod
    def _stream_csv(rows: list[dict], columns: list[tuple[str, str]]):
        """Generator yielding CSV bytes — one chunk per row, plus header."""
        buf = StringIO()
        writer = csv.writer(buf)
        writer.writerow([label for label, _key in columns])
        yield buf.getvalue()
        for row in rows:
            buf.seek(0)
            buf.truncate(0)
            writer.writerow([
                _csv_value(row.get(key))
                for _label, key in columns
            ])
            yield buf.getvalue()

    # ── Audit ────────────────────────────────────────────────────

    def _audit_read(self, request, envelope: dict) -> None:
        """Write an AuditLog entry for a JSON report read.

        SOC 2 CC 6.1 + HIPAA §164.312(b): "who ran what when." The
        entry captures the report ID, category, params, and row count
        — never PHI from the response itself.
        """
        record(
            action=AuditLog.Action.READ,
            resource_type='report',
            resource_id=self.report_id,
            request=request,
            metadata={
                'category': self.category,
                'params': envelope['params'],
                'row_count': len(envelope.get('rows') or []),
            },
        )

    def _audit_export(self, request, envelope: dict, *, row_count: int) -> None:
        """Write an AuditLog entry for a CSV export.

        Uses `action=EXPORT` to distinguish from on-screen reads
        (different SOC 2 control). Adds `phi_confirmed` to metadata
        so a reviewer can answer "did the operator click through the
        PHI gate" without re-deriving from the URL params.
        """
        record(
            action=AuditLog.Action.EXPORT,
            resource_type='report',
            resource_id=self.report_id,
            request=request,
            metadata={
                'category': self.category,
                'params': envelope['params'],
                'row_count': row_count,
                'phi_tier': self.phi_tier,
                'phi_confirmed': self.phi_tier == 'per_customer' and self._phi_confirmed(request),
            },
        )

    # ── Catalog metadata ─────────────────────────────────────────

    @classmethod
    def catalog_entry(cls, *, url: str) -> dict:
        """Return the catalog metadata block for this report.

        Used by the catalog endpoint to render the frontend library
        page. `url` is supplied by the caller because URL resolution
        depends on the route registration, not the class itself.
        """
        return {
            'id': cls.report_id,
            'category': cls.category,
            'title': cls.title,
            'description': cls.description,
            'phi_tier': cls.phi_tier,
            'url': url,
        }


def cents_to_int(value: Any) -> int:
    """Coerce a Sum() aggregate result to int (Django returns None for empty sets)."""
    return int(value or 0)


def _csv_value(v: Any) -> str:
    """Coerce a row value to a CSV cell. Lists/dicts become JSON, None → empty."""
    if v is None:
        return ''
    if isinstance(v, bool):
        return 'true' if v else 'false'
    if isinstance(v, (dict, list)):
        import json
        return json.dumps(v, separators=(',', ':'))
    return str(v)
