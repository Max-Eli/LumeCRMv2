"""Financial reports — money in, money out.

Source of truth: `apps.invoices.Invoice` (status=PAID, closed_at in
range). All money is in cents per ADR 0007. Aggregations use Postgres
SUM/COUNT — at our scale this stays well under 100ms.

Reports in this module:

  - SalesByDateRangeReport     (Session 1)
  - DailyCloseOutReport        (Session 2)
  - ARAgingReport              (Session 2)
  - RevenueByServiceReport     (Session 2)
  - RevenueByLocationReport    (Session 2)
  - TaxCollectedReport         (Session 2)
  - RevenueByAcquisitionSourceReport  (Session 2B — ADR 0027 §8c)
"""

from collections import OrderedDict

from django.db.models import Count, F, Sum
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.exceptions import ValidationError

from apps.invoices.models import Invoice, InvoiceLineItem
from apps.tenants.permissions import P

from ..base import BaseReportView, cents_to_int

DATE_FROM_PARAM = OpenApiParameter('date_from', str, description='Start date (inclusive, YYYY-MM-DD). Defaults to 30 days before date_to.')
DATE_TO_PARAM = OpenApiParameter('date_to', str, description='End date (inclusive, YYYY-MM-DD). Defaults to today.')


# ── Sales by date range ────────────────────────────────────────────


@extend_schema(
    tags=['Reports — Financial'],
    parameters=[DATE_FROM_PARAM, DATE_TO_PARAM],
    description=(
        'Daily sales totals (gross / tax / subtotal / invoice count) plus a '
        'payment-method breakdown summary. Counts only PAID invoices closed '
        'within the date range. Money is in cents.'
    ),
)
class SalesByDateRangeReport(BaseReportView):
    """Daily sales over a date range, plus a payment-method summary."""

    report_id = 'financial.sales_by_date_range'
    category = 'financial'
    permission = P.VIEW_FINANCIAL_REPORTS
    title = 'Sales by date range'
    description = "Daily gross, tax, and net totals — plus a payment-method breakdown. Excludes voids and unpaid invoices."
    phi_tier = 'none'

    def run(self, request, *, date_from, date_to):
        qs = (
            Invoice.objects
            .for_current_tenant()
            .filter(
                status=Invoice.Status.PAID,
                closed_at__date__gte=date_from,
                closed_at__date__lte=date_to,
            )
        )

        per_day_qs = (
            qs.values('closed_at__date')
            .annotate(
                gross_cents=Sum('total_cents'),
                tax_cents=Sum('tax_cents'),
                subtotal_cents=Sum('subtotal_cents'),
                invoice_count=Count('id'),
            )
        )
        per_day_map = {row['closed_at__date']: row for row in per_day_qs}

        rows = []
        cursor = date_from
        while cursor <= date_to:
            row = per_day_map.get(cursor)
            rows.append({
                'date': cursor.isoformat(),
                'gross_cents': cents_to_int(row['gross_cents']) if row else 0,
                'tax_cents': cents_to_int(row['tax_cents']) if row else 0,
                'subtotal_cents': cents_to_int(row['subtotal_cents']) if row else 0,
                'invoice_count': int(row['invoice_count']) if row else 0,
            })
            cursor = self._next_day(cursor)

        method_labels = OrderedDict(Invoice.PaymentMethod.choices)
        per_method_qs = (
            qs.values('payment_method')
            .annotate(
                gross_cents=Sum('total_cents'),
                invoice_count=Count('id'),
            )
            .order_by('-gross_cents')
        )
        by_payment_method = [
            {
                'method': r['payment_method'],
                'method_label': method_labels.get(r['payment_method'], r['payment_method']),
                'gross_cents': cents_to_int(r['gross_cents']),
                'invoice_count': int(r['invoice_count']),
            }
            for r in per_method_qs
        ]

        totals = qs.aggregate(
            gross=Sum('total_cents'),
            tax=Sum('tax_cents'),
            subtotal=Sum('subtotal_cents'),
            count=Count('id'),
        )
        gross_total = cents_to_int(totals['gross'])
        invoice_count = int(totals['count'] or 0)
        avg_invoice_cents = (gross_total // invoice_count) if invoice_count else 0

        return {
            'summary': {
                'total_gross_cents': gross_total,
                'total_tax_cents': cents_to_int(totals['tax']),
                'total_subtotal_cents': cents_to_int(totals['subtotal']),
                'paid_invoice_count': invoice_count,
                'avg_invoice_cents': avg_invoice_cents,
                'by_payment_method': by_payment_method,
            },
            'rows': rows,
        }

    @staticmethod
    def _next_day(d):
        import datetime as dt
        return d + dt.timedelta(days=1)


# ── Daily close-out ────────────────────────────────────────────────


@extend_schema(
    tags=['Reports — Financial'],
    parameters=[DATE_FROM_PARAM, DATE_TO_PARAM],
    description=(
        'One row per day with gross, tax, net, and a per-payment-method '
        "breakdown. Front-desk's end-of-day reconciliation report — counts "
        'cash drawer separately from check / card / other so the totals can '
        'be matched against physical receipts. Refunds will appear as a '
        'separate column when Phase 2A POS lands the refund ledger.'
    ),
)
class DailyCloseOutReport(BaseReportView):
    """End-of-day reconciliation — daily gross broken down by payment method."""

    report_id = 'financial.daily_close_out'
    category = 'financial'
    permission = P.VIEW_FINANCIAL_REPORTS
    title = 'Daily close-out'
    description = "End-of-day reconciliation — gross + per-payment-method totals per day. Use it to match the cash drawer + card terminal."
    phi_tier = 'none'

    def run(self, request, *, date_from, date_to):
        qs = (
            Invoice.objects
            .for_current_tenant()
            .filter(
                status=Invoice.Status.PAID,
                closed_at__date__gte=date_from,
                closed_at__date__lte=date_to,
            )
        )

        # Aggregate per (date, payment_method) — pivot client-side into
        # one row per day with a column per method.
        per_day_method_qs = (
            qs.values('closed_at__date', 'payment_method')
            .annotate(
                gross_cents=Sum('total_cents'),
                invoice_count=Count('id'),
            )
        )

        method_labels = OrderedDict(Invoice.PaymentMethod.choices)
        method_keys = list(method_labels.keys())

        # Initialize every day in the range with zero columns so the
        # operator's reconciliation form has a row for the day they're
        # closing even if zero PAID invoices.
        per_day = {}
        cursor = date_from
        while cursor <= date_to:
            per_day[cursor] = {
                'date': cursor.isoformat(),
                'gross_cents': 0,
                'tax_cents': 0,
                'invoice_count': 0,
                'by_method': {m: 0 for m in method_keys},
            }
            cursor = self._next_day(cursor)

        per_day_total_qs = (
            qs.values('closed_at__date')
            .annotate(
                gross=Sum('total_cents'),
                tax=Sum('tax_cents'),
                count=Count('id'),
            )
        )
        for row in per_day_total_qs:
            d = row['closed_at__date']
            if d in per_day:
                per_day[d]['gross_cents'] = cents_to_int(row['gross'])
                per_day[d]['tax_cents'] = cents_to_int(row['tax'])
                per_day[d]['invoice_count'] = int(row['count'])

        for row in per_day_method_qs:
            d = row['closed_at__date']
            if d in per_day:
                per_day[d]['by_method'][row['payment_method']] = cents_to_int(row['gross_cents'])

        rows = list(per_day.values())

        totals = qs.aggregate(
            gross=Sum('total_cents'),
            tax=Sum('tax_cents'),
            count=Count('id'),
        )

        return {
            'summary': {
                'total_gross_cents': cents_to_int(totals['gross']),
                'total_tax_cents': cents_to_int(totals['tax']),
                'paid_invoice_count': int(totals['count'] or 0),
                'method_keys': method_keys,
                'method_labels': method_labels,
            },
            'rows': rows,
        }

    @staticmethod
    def _next_day(d):
        import datetime as dt
        return d + dt.timedelta(days=1)

    def csv_rows(self, envelope):
        """Flatten the per-row `by_method` dict into one column per
        payment method (the auto-flattener would JSON-stringify it,
        which doesn't paste cleanly into Excel)."""
        method_keys = (envelope.get('summary') or {}).get('method_keys') or []
        out = []
        for row in envelope.get('rows') or []:
            flat = {k: v for k, v in row.items() if k != 'by_method'}
            for mk in method_keys:
                flat[f'method_{mk}_cents'] = (row.get('by_method') or {}).get(mk, 0)
            out.append(flat)
        return out

    def csv_columns(self, envelope):
        method_keys = (envelope.get('summary') or {}).get('method_keys') or []
        method_labels = (envelope.get('summary') or {}).get('method_labels') or {}
        cols = [
            ('Date',     'date'),
            ('Invoices', 'invoice_count'),
        ]
        for mk in method_keys:
            cols.append((f"{method_labels.get(mk, mk)} (cents)", f'method_{mk}_cents'))
        cols.extend([
            ('Tax (cents)',   'tax_cents'),
            ('Gross (cents)', 'gross_cents'),
        ])
        return cols


# ── AR aging ───────────────────────────────────────────────────────


AGING_BUCKETS = [
    ('current', 'Current (≤30 days)', 0, 30),
    ('30_60', '31–60 days', 31, 60),
    ('60_90', '61–90 days', 61, 90),
    ('over_90', 'Over 90 days', 91, None),
]


@extend_schema(
    tags=['Reports — Financial'],
    description=(
        'Open (unpaid) invoices grouped by age. Shows total outstanding and '
        'a per-customer drill-down so the front desk knows who to chase. '
        'Snapshot of "right now" — no date-range params; uses today as the '
        'aging anchor.'
    ),
)
class ARAgingReport(BaseReportView):
    """Outstanding (OPEN) invoices, grouped into 30 / 60 / 90 / 90+ buckets.

    PHI tier: per_customer (rows include customer names + email).
    """

    report_id = 'financial.ar_aging'
    category = 'financial'
    permission = P.VIEW_FINANCIAL_REPORTS
    title = 'Accounts receivable aging'
    description = "Open invoices ranked by how old they are. Find out who hasn't paid and how long ago they were billed."
    phi_tier = 'per_customer'

    def parse_params(self, request):
        # No params — snapshot of "right now."
        return {}

    def run(self, request, *_):
        today = timezone.now().date()
        qs = (
            Invoice.objects
            .for_current_tenant()
            .filter(status=Invoice.Status.OPEN)
            .select_related('customer', 'appointment')
            .order_by('created_at')
        )

        bucket_totals = {b[0]: {'gross_cents': 0, 'invoice_count': 0} for b in AGING_BUCKETS}
        rows = []
        for invoice in qs:
            age_days = (today - invoice.created_at.date()).days
            bucket_id = self._bucket_for(age_days)
            bucket_totals[bucket_id]['gross_cents'] += invoice.total_cents
            bucket_totals[bucket_id]['invoice_count'] += 1
            rows.append({
                'invoice_id': invoice.pk,
                'customer_id': invoice.customer_id,
                'customer_name': invoice.customer.full_name,
                'customer_email': invoice.customer.email or '',
                'age_days': age_days,
                'bucket': bucket_id,
                'gross_cents': invoice.total_cents,
                'created_date': invoice.created_at.date().isoformat(),
            })

        rows.sort(key=lambda r: (-r['age_days'], r['customer_name'].lower()))

        total_open_cents = sum(r['gross_cents'] for r in rows)

        return {
            'summary': {
                'total_open_cents': total_open_cents,
                'open_invoice_count': len(rows),
                'buckets': [
                    {
                        'id': b[0],
                        'label': b[1],
                        'gross_cents': bucket_totals[b[0]]['gross_cents'],
                        'invoice_count': bucket_totals[b[0]]['invoice_count'],
                    }
                    for b in AGING_BUCKETS
                ],
            },
            'rows': rows,
        }

    @staticmethod
    def _bucket_for(age_days: int) -> str:
        for bucket_id, _label, lo, hi in AGING_BUCKETS:
            if hi is None and age_days >= lo:
                return bucket_id
            if hi is not None and lo <= age_days <= hi:
                return bucket_id
        return AGING_BUCKETS[0][0]


# ── Revenue by service ─────────────────────────────────────────────


@extend_schema(
    tags=['Reports — Financial'],
    parameters=[DATE_FROM_PARAM, DATE_TO_PARAM],
    description=(
        'Gross revenue per service over the date range. Sums line items '
        'on PAID invoices; standalone retail / fees (no service FK) are '
        'omitted. Useful for menu pricing decisions and identifying the '
        'service mix that actually pays the bills.'
    ),
)
class RevenueByServiceReport(BaseReportView):
    """Gross revenue and unit count per service, ranked highest-first."""

    report_id = 'financial.revenue_by_service'
    category = 'financial'
    permission = P.VIEW_FINANCIAL_REPORTS
    title = 'Revenue by service'
    description = "Which services bring in the most money. Sums PAID invoice line items by service over the window."
    phi_tier = 'none'

    def run(self, request, *, date_from, date_to):
        qs = (
            InvoiceLineItem.objects
            .filter(
                invoice__tenant=self._current_tenant(),
                invoice__status=Invoice.Status.PAID,
                invoice__closed_at__date__gte=date_from,
                invoice__closed_at__date__lte=date_to,
                service__isnull=False,
            )
            .values('service_id', 'service__name')
            .annotate(
                gross_cents=Sum('line_subtotal_cents'),
                tax_cents=Sum('line_tax_cents'),
                unit_count=Sum('quantity'),
            )
            .order_by('-gross_cents')
        )

        rows = [
            {
                'service_id': r['service_id'],
                'service_name': r['service__name'] or '(unnamed service)',
                'gross_cents': cents_to_int(r['gross_cents']),
                'tax_cents': cents_to_int(r['tax_cents']),
                'unit_count': int(r['unit_count'] or 0),
            }
            for r in qs
        ]

        gross_total = sum(r['gross_cents'] for r in rows)
        unit_total = sum(r['unit_count'] for r in rows)

        return {
            'summary': {
                'total_gross_cents': gross_total,
                'total_units': unit_total,
                'service_count': len(rows),
                'avg_revenue_per_service_cents': (gross_total // len(rows)) if rows else 0,
            },
            'rows': rows,
        }

    @staticmethod
    def _current_tenant():
        from apps.tenants.context import get_current_tenant
        return get_current_tenant()


# ── Revenue by location ────────────────────────────────────────────


@extend_schema(
    tags=['Reports — Financial'],
    parameters=[DATE_FROM_PARAM, DATE_TO_PARAM],
    description=(
        'PAID invoice totals grouped by the appointment\'s location. Useful '
        'for multi-location tenants to see which sites earned what. '
        'Standalone (no-appointment) invoices are omitted — they have no '
        'location to attribute to.'
    ),
)
class RevenueByLocationReport(BaseReportView):
    """Revenue + paid-appointment count per location, ranked highest-first."""

    report_id = 'financial.revenue_by_location'
    category = 'financial'
    permission = P.VIEW_FINANCIAL_REPORTS
    title = 'Revenue by location'
    description = "Per-location gross + paid-appointment count. Useful when a tenant has more than one site."
    phi_tier = 'none'

    def run(self, request, *, date_from, date_to):
        qs = (
            Invoice.objects
            .for_current_tenant()
            .filter(
                status=Invoice.Status.PAID,
                closed_at__date__gte=date_from,
                closed_at__date__lte=date_to,
                appointment__isnull=False,
            )
            .values('appointment__location_id', 'appointment__location__name')
            .annotate(
                gross_cents=Sum('total_cents'),
                appointment_count=Count('id'),
            )
            .order_by('-gross_cents')
        )

        rows = [
            {
                'location_id': r['appointment__location_id'],
                'location_name': r['appointment__location__name'] or f"Location #{r['appointment__location_id']}",
                'gross_cents': cents_to_int(r['gross_cents']),
                'appointment_count': int(r['appointment_count']),
            }
            for r in qs
        ]

        gross_total = sum(r['gross_cents'] for r in rows)
        appointments_total = sum(r['appointment_count'] for r in rows)

        return {
            'summary': {
                'total_gross_cents': gross_total,
                'total_appointments': appointments_total,
                'location_count': len(rows),
            },
            'rows': rows,
        }


# ── Tax collected ──────────────────────────────────────────────────


@extend_schema(
    tags=['Reports — Financial'],
    parameters=[DATE_FROM_PARAM, DATE_TO_PARAM],
    description=(
        'Sales-tax-equivalent total collected on PAID invoices in the window. '
        'Per-line tax-rate breakdown helps reconcile against the tax-rate '
        'configuration on services. Excludes voids and unpaid invoices.'
    ),
)
class TaxCollectedReport(BaseReportView):
    """Tax collected over the window, with a per-rate breakdown."""

    report_id = 'financial.tax_collected'
    category = 'financial'
    permission = P.VIEW_FINANCIAL_REPORTS
    title = 'Tax collected'
    description = "Tax dollars collected over the window, with a breakdown by tax rate. Use it for sales-tax filing prep."
    phi_tier = 'none'

    def run(self, request, *, date_from, date_to):
        # Aggregate at the line-item level so we can group by tax rate.
        line_qs = (
            InvoiceLineItem.objects
            .filter(
                invoice__tenant=self._current_tenant(),
                invoice__status=Invoice.Status.PAID,
                invoice__closed_at__date__gte=date_from,
                invoice__closed_at__date__lte=date_to,
            )
            .values('tax_rate_percent')
            .annotate(
                tax_cents=Sum('line_tax_cents'),
                taxable_subtotal_cents=Sum('line_subtotal_cents'),
                line_count=Count('id'),
            )
            .order_by('-tax_rate_percent')
        )

        rows = [
            {
                'tax_rate_percent': str(r['tax_rate_percent']),
                'taxable_subtotal_cents': cents_to_int(r['taxable_subtotal_cents']),
                'tax_cents': cents_to_int(r['tax_cents']),
                'line_count': int(r['line_count']),
            }
            for r in line_qs
        ]

        total_tax_cents = sum(r['tax_cents'] for r in rows)
        total_subtotal_cents = sum(r['taxable_subtotal_cents'] for r in rows)

        # Effective combined rate, just for summary glanceability.
        effective_rate = (
            float(total_tax_cents) / float(total_subtotal_cents) * 100
            if total_subtotal_cents
            else 0.0
        )

        return {
            'summary': {
                'total_tax_cents': total_tax_cents,
                'total_taxable_subtotal_cents': total_subtotal_cents,
                'rate_count': len(rows),
                'effective_rate_percent': round(effective_rate, 4),
            },
            'rows': rows,
        }

    @staticmethod
    def _current_tenant():
        from apps.tenants.context import get_current_tenant
        return get_current_tenant()


# ── Revenue by acquisition source (ADR 0027 §8c) ───────────────────


@extend_schema(
    tags=['Reports — Financial'],
    parameters=[DATE_FROM_PARAM, DATE_TO_PARAM],
    description=(
        'PAID invoice totals grouped by customer.acquisition_source — '
        'which channel originally brought each customer in. Answers '
        '"is the Instagram ad budget producing actual revenue?" by '
        'showing gross + average ticket + customer counts per channel.'
    ),
)
class RevenueByAcquisitionSourceReport(BaseReportView):
    """Revenue per acquisition channel, ranked highest-first."""

    report_id = 'financial.revenue_by_acquisition_source'
    category = 'financial'
    permission = P.VIEW_FINANCIAL_REPORTS
    title = 'Revenue by acquisition source'
    description = (
        'Per-channel gross + average ticket + customer count. Pair with '
        'the Operations version to see whether each channel converts to '
        'revenue, not just bookings.'
    )
    # PHI tier: aggregated. Per-channel totals never expose any
    # individual customer — pure aggregate rollup.
    phi_tier = 'aggregated'

    def run(self, request, *, date_from, date_to):
        from apps.customers.models import Customer

        per_source = (
            Invoice.objects
            .for_current_tenant()
            .filter(
                status=Invoice.Status.PAID,
                closed_at__date__gte=date_from,
                closed_at__date__lte=date_to,
            )
            .values('customer__acquisition_source')
            .annotate(
                gross_cents=Sum('total_cents'),
                invoice_count=Count('id'),
                customer_count=Count('customer', distinct=True),
            )
            .order_by('-gross_cents')
        )

        source_labels = dict(Customer.AcquisitionSource.choices)
        rows = []
        for r in per_source:
            src = r['customer__acquisition_source'] or 'manual'
            gross = cents_to_int(r['gross_cents'])
            invoice_count = int(r['invoice_count'])
            customer_count = int(r['customer_count'])
            avg_ticket = gross // invoice_count if invoice_count else 0
            rows.append({
                'acquisition_source': src,
                'acquisition_source_label': source_labels.get(src, src),
                'gross_cents': gross,
                'invoice_count': invoice_count,
                'customer_count': customer_count,
                'avg_ticket_cents': avg_ticket,
            })

        gross_total = sum(r['gross_cents'] for r in rows)
        invoice_total = sum(r['invoice_count'] for r in rows)
        return {
            'summary': {
                'total_gross_cents': gross_total,
                'total_invoices': invoice_total,
                'distinct_sources': len(rows),
            },
            'rows': rows,
        }
