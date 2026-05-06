"""Guest reports — client acquisition, retention, lifecycle.

PHI tier matters here: all reports in this category surface customer
names. Session 3 will add the export-confirmation modal before CSV
download. In-app display is unchanged at v1.

Reports in this module:

  - NewVsReturningReport            (Session 1)
  - TopSpendersReport               (Session 2)
  - InactiveClientsReport           (Session 2)
  - BirthdayListReport              (Session 2)
  - VisitFrequencyReport            (Session 2)
  - FormsOutstandingReport          (Session 2)
"""

import datetime as dt
from collections import OrderedDict

from django.db.models import Count, F, Max, Min, Q, Sum
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.exceptions import ValidationError

from apps.appointments.models import Appointment
from apps.customers.models import Customer
from apps.forms.models import FormSubmission
from apps.invoices.models import Invoice
from apps.tenants.permissions import P

from ..base import BaseReportView, cents_to_int

DATE_FROM_PARAM = OpenApiParameter('date_from', str, description='Start date (inclusive, YYYY-MM-DD). Defaults to 30 days before date_to.')
DATE_TO_PARAM = OpenApiParameter('date_to', str, description='End date (inclusive, YYYY-MM-DD). Defaults to today.')
DAYS_PARAM = OpenApiParameter('days', int, description='Day-window size. Validation per report.')


# ── New vs returning (Session 1) ───────────────────────────────────


@extend_schema(
    tags=['Reports — Guests'],
    parameters=[DATE_FROM_PARAM, DATE_TO_PARAM],
    description=(
        'Per-customer breakdown of new vs returning clients within the '
        'window. "New" = first-ever appointment falls inside the range. '
        '"Returning" = had at least one appointment before the range AND '
        'at least one inside it.'
    ),
)
class NewVsReturningReport(BaseReportView):
    """New vs returning clients in a date range, per-customer detail."""

    report_id = 'guests.new_vs_returning'
    category = 'guests'
    permission = P.VIEW_GUEST_REPORTS
    title = 'New vs returning clients'
    description = "How many first-time visits vs return visits in the window — and which customers were which."
    phi_tier = 'per_customer'

    def run(self, request, *, date_from, date_to):
        in_range_customer_ids = list(
            Appointment.objects
            .for_current_tenant()
            .filter(
                start_time__date__gte=date_from,
                start_time__date__lte=date_to,
            )
            .values_list('customer_id', flat=True)
            .distinct()
        )
        if not in_range_customer_ids:
            return {
                'summary': {
                    'new_count': 0,
                    'returning_count': 0,
                    'total_unique_customers': 0,
                },
                'rows': [],
            }

        first_appt_qs = (
            Appointment.objects
            .for_current_tenant()
            .filter(customer_id__in=in_range_customer_ids)
            .values('customer_id')
            .annotate(first_at=Min('start_time'))
        )
        first_appt_by_customer = {row['customer_id']: row['first_at'].date() for row in first_appt_qs}

        customers = (
            Customer.objects
            .for_current_tenant()
            .filter(id__in=in_range_customer_ids)
            .only('id', 'first_name', 'last_name', 'preferred_name', 'email', 'phone', 'created_at')
        )

        in_range_counts = dict(
            Appointment.objects
            .for_current_tenant()
            .filter(
                customer_id__in=in_range_customer_ids,
                start_time__date__gte=date_from,
                start_time__date__lte=date_to,
            )
            .values('customer_id')
            .annotate(c=Count('id'))
            .values_list('customer_id', 'c')
        )

        rows = []
        new_count = 0
        returning_count = 0
        for c in customers:
            first_at = first_appt_by_customer.get(c.id)
            if first_at is None:
                continue
            classification = 'new' if (date_from <= first_at <= date_to) else 'returning'
            if classification == 'new':
                new_count += 1
            else:
                returning_count += 1
            rows.append({
                'customer_id': c.id,
                'customer_name': c.full_name,
                'classification': classification,
                'first_appointment_date': first_at.isoformat(),
                'appointments_in_range': int(in_range_counts.get(c.id, 0)),
            })

        rows.sort(key=lambda r: (0 if r['classification'] == 'new' else 1, r['customer_name'].lower()))

        return {
            'summary': {
                'new_count': new_count,
                'returning_count': returning_count,
                'total_unique_customers': new_count + returning_count,
            },
            'rows': rows,
        }


# ── Top spenders (LTV) ─────────────────────────────────────────────


@extend_schema(
    tags=['Reports — Guests'],
    parameters=[
        OpenApiParameter('limit', int, description='Top-N to return. Default 50, max 500.'),
    ],
    description=(
        'Lifetime revenue per client, ranked highest-first. Sums PAID '
        'invoice totals across all time (no date range — LTV is the '
        'point). Use it for VIP outreach, win-back campaigns, or to '
        'understand the revenue concentration in the book.'
    ),
)
class TopSpendersReport(BaseReportView):
    """Top-N clients by lifetime PAID invoice total."""

    report_id = 'guests.top_spenders'
    category = 'guests'
    permission = P.VIEW_GUEST_REPORTS
    title = 'Top spenders (lifetime)'
    description = "Lifetime revenue per client, ranked highest-first. The book's revenue concentration in one place."
    phi_tier = 'per_customer'

    DEFAULT_LIMIT = 50
    MAX_LIMIT = 500

    def parse_params(self, request):
        raw = (request.query_params.get('limit') or '').strip()
        if not raw:
            limit = self.DEFAULT_LIMIT
        else:
            try:
                limit = int(raw)
            except ValueError:
                raise ValidationError({'limit': 'Must be an integer.'})
            if limit < 1 or limit > self.MAX_LIMIT:
                raise ValidationError({'limit': f'Must be between 1 and {self.MAX_LIMIT}.'})
        return {'limit': limit}

    def run(self, request, *, limit):
        qs = (
            Invoice.objects
            .for_current_tenant()
            .filter(status=Invoice.Status.PAID)
            .values('customer_id')
            .annotate(
                lifetime_cents=Sum('total_cents'),
                paid_invoice_count=Count('id'),
                last_paid_at=Max('closed_at'),
            )
            .order_by('-lifetime_cents')[:limit]
        )

        customer_ids = [r['customer_id'] for r in qs]
        customers = {
            c.id: c
            for c in Customer.objects.for_current_tenant().filter(id__in=customer_ids)
        }

        rows = []
        for r in qs:
            c = customers.get(r['customer_id'])
            if c is None:
                continue
            rows.append({
                'customer_id': c.id,
                'customer_name': c.full_name,
                'customer_email': c.email or '',
                'lifetime_cents': cents_to_int(r['lifetime_cents']),
                'paid_invoice_count': int(r['paid_invoice_count']),
                'last_paid_date': r['last_paid_at'].date().isoformat() if r['last_paid_at'] else None,
            })

        total_lifetime = sum(r['lifetime_cents'] for r in rows)

        return {
            'summary': {
                'returned_count': len(rows),
                'total_lifetime_cents': total_lifetime,
                'avg_lifetime_cents': (total_lifetime // len(rows)) if rows else 0,
                'limit': limit,
            },
            'rows': rows,
        }


# ── Inactive clients ───────────────────────────────────────────────


@extend_schema(
    tags=['Reports — Guests'],
    parameters=[
        OpenApiParameter('days', int, description='Inactivity threshold in days. Defaults to 90.'),
    ],
    description=(
        'Clients whose most recent appointment is older than N days (or '
        'who have never had an appointment). Re-engagement / win-back '
        'starting list. Excludes inactive customer records soft-deleted '
        'via the customer admin.'
    ),
)
class InactiveClientsReport(BaseReportView):
    """Clients with no appointment in the last N days."""

    report_id = 'guests.inactive_clients'
    category = 'guests'
    permission = P.VIEW_GUEST_REPORTS
    title = 'Inactive clients'
    description = "Clients whose last visit was more than N days ago. Pull this for win-back campaigns."
    phi_tier = 'per_customer'

    DEFAULT_DAYS = 90
    MAX_DAYS = 1825  # ~5 years

    def parse_params(self, request):
        raw = (request.query_params.get('days') or '').strip()
        if not raw:
            days = self.DEFAULT_DAYS
        else:
            try:
                days = int(raw)
            except ValueError:
                raise ValidationError({'days': 'Must be an integer.'})
            if days < 1 or days > self.MAX_DAYS:
                raise ValidationError({'days': f'Must be between 1 and {self.MAX_DAYS}.'})
        return {'days': days}

    def run(self, request, *, days):
        cutoff = (timezone.now() - dt.timedelta(days=days)).date()

        # All active customers with their last-appointment date.
        last_appt = (
            Appointment.objects
            .for_current_tenant()
            .values('customer_id')
            .annotate(last_at=Max('start_time'))
        )
        last_at_by_customer = {r['customer_id']: r['last_at'].date() for r in last_appt}

        customers = (
            Customer.objects
            .for_current_tenant()
            .only('id', 'first_name', 'last_name', 'preferred_name', 'email', 'phone', 'created_at')
        )

        rows = []
        for c in customers:
            last_seen = last_at_by_customer.get(c.id)
            if last_seen is None:
                # Never had an appointment — still counts as inactive,
                # but anchor the "days since" to the customer record's
                # creation date so they aren't marked decades-stale on
                # day 1.
                anchor = c.created_at.date()
                days_since = (timezone.now().date() - anchor).days
                if days_since < days:
                    continue
                rows.append({
                    'customer_id': c.id,
                    'customer_name': c.full_name,
                    'customer_email': c.email or '',
                    'customer_phone': c.phone or '',
                    'last_appointment_date': None,
                    'days_since_last_visit': days_since,
                    'never_visited': True,
                })
            else:
                if last_seen >= cutoff:
                    continue
                days_since = (timezone.now().date() - last_seen).days
                rows.append({
                    'customer_id': c.id,
                    'customer_name': c.full_name,
                    'customer_email': c.email or '',
                    'customer_phone': c.phone or '',
                    'last_appointment_date': last_seen.isoformat(),
                    'days_since_last_visit': days_since,
                    'never_visited': False,
                })

        # Most-stale first; never-visited bubble to the top of the
        # respective bucket.
        rows.sort(key=lambda r: -r['days_since_last_visit'])

        return {
            'summary': {
                'inactive_client_count': len(rows),
                'never_visited_count': sum(1 for r in rows if r['never_visited']),
                'days_threshold': days,
            },
            'rows': rows,
        }


# ── Birthday list ──────────────────────────────────────────────────


@extend_schema(
    tags=['Reports — Guests'],
    parameters=[
        OpenApiParameter('window_days', int, description='Days ahead from today. Defaults to 30, max 90.'),
    ],
    description=(
        'Customers whose birthday falls within the next N days (year-'
        'agnostic). Marketing pull for "happy birthday — here\'s 15% off" '
        'sends. Customers without a birthday on file are omitted.'
    ),
)
class BirthdayListReport(BaseReportView):
    """Customers with birthdays in the next N days."""

    report_id = 'guests.birthday_list'
    category = 'guests'
    permission = P.VIEW_GUEST_REPORTS
    title = 'Birthday list'
    description = "Clients whose birthday falls in the next N days. Pull this for birthday outreach."
    phi_tier = 'per_customer'

    DEFAULT_WINDOW = 30
    MAX_WINDOW = 90

    def parse_params(self, request):
        raw = (request.query_params.get('window_days') or '').strip()
        if not raw:
            window = self.DEFAULT_WINDOW
        else:
            try:
                window = int(raw)
            except ValueError:
                raise ValidationError({'window_days': 'Must be an integer.'})
            if window < 1 or window > self.MAX_WINDOW:
                raise ValidationError({'window_days': f'Must be between 1 and {self.MAX_WINDOW}.'})
        return {'window_days': window}

    def run(self, request, *, window_days):
        today = timezone.now().date()
        end = today + dt.timedelta(days=window_days)

        customers = (
            Customer.objects
            .for_current_tenant()
            .filter(date_of_birth__isnull=False)
            .only(
                'id', 'first_name', 'last_name', 'preferred_name', 'email',
                'phone', 'date_of_birth', 'email_opt_in',
            )
        )

        rows = []
        for c in customers:
            next_bday = self._next_birthday_after(c.date_of_birth, today)
            if next_bday > end:
                continue
            age_turning = next_bday.year - c.date_of_birth.year
            rows.append({
                'customer_id': c.id,
                'customer_name': c.full_name,
                'customer_email': c.email or '',
                'customer_phone': c.phone or '',
                'birthday': c.date_of_birth.strftime('%m-%d'),
                'next_birthday_date': next_bday.isoformat(),
                'days_until_birthday': (next_bday - today).days,
                'age_turning': age_turning,
                'email_opt_in': c.email_opt_in,
            })
        rows.sort(key=lambda r: (r['days_until_birthday'], r['customer_name'].lower()))

        return {
            'summary': {
                'upcoming_birthday_count': len(rows),
                'window_days': window_days,
                'opted_in_count': sum(1 for r in rows if r['email_opt_in']),
            },
            'rows': rows,
        }

    @staticmethod
    def _next_birthday_after(dob: dt.date, anchor: dt.date) -> dt.date:
        """The next occurrence of DOB's month/day on or after `anchor`.
        Handles Feb 29 by falling back to Feb 28 in non-leap years."""
        month, day = dob.month, dob.day
        try:
            this_year = dt.date(anchor.year, month, day)
        except ValueError:
            # Feb 29 in a non-leap year → use Feb 28
            this_year = dt.date(anchor.year, month, 28)
        if this_year >= anchor:
            return this_year
        try:
            return dt.date(anchor.year + 1, month, day)
        except ValueError:
            return dt.date(anchor.year + 1, month, 28)


# ── Visit frequency distribution ───────────────────────────────────


# Buckets for the lifetime visit-count histogram. Tuned to highlight
# the long tail (1-shot trials vs. 6+ regulars) without exploding the
# row count for spas with thousands of customers.
VISIT_FREQ_BUCKETS = [
    ('one_visit', 'One visit', 1, 1),
    ('two_to_five', '2–5 visits', 2, 5),
    ('six_to_ten', '6–10 visits', 6, 10),
    ('eleven_plus', '11+ visits', 11, None),
]


@extend_schema(
    tags=['Reports — Guests'],
    description=(
        'Histogram of lifetime visit counts per client. "Visit" here '
        'means appointments with status COMPLETED or CHECKED_IN — '
        'cancellations and no-shows are excluded so the distribution '
        'reflects who actually showed up. No date params: the question is '
        'lifetime book composition.'
    ),
)
class VisitFrequencyReport(BaseReportView):
    """Lifetime visit-count distribution. No PHI rows — pure aggregate."""

    report_id = 'guests.visit_frequency'
    category = 'guests'
    permission = P.VIEW_GUEST_REPORTS
    title = 'Visit frequency distribution'
    description = "Histogram of how many lifetime visits each client has. Surfaces the regulars vs the one-and-done crowd."
    phi_tier = 'none'

    DELIVERED_STATUSES = (
        Appointment.Status.CHECKED_IN,
        Appointment.Status.COMPLETED,
    )

    def parse_params(self, request):
        return {}

    def run(self, request, *_):
        per_customer = (
            Appointment.objects
            .for_current_tenant()
            .filter(status__in=self.DELIVERED_STATUSES)
            .values('customer_id')
            .annotate(c=Count('id'))
        )
        bucket_counts = {b[0]: 0 for b in VISIT_FREQ_BUCKETS}
        total_unique = 0
        for r in per_customer:
            total_unique += 1
            count = int(r['c'])
            for bucket_id, _label, lo, hi in VISIT_FREQ_BUCKETS:
                if hi is None and count >= lo:
                    bucket_counts[bucket_id] += 1
                    break
                if hi is not None and lo <= count <= hi:
                    bucket_counts[bucket_id] += 1
                    break

        rows = [
            {
                'bucket_id': b[0],
                'label': b[1],
                'min_visits': b[2],
                'max_visits': b[3],
                'customer_count': bucket_counts[b[0]],
                'share_pct': round((bucket_counts[b[0]] / total_unique * 100), 1) if total_unique else 0.0,
            }
            for b in VISIT_FREQ_BUCKETS
        ]

        return {
            'summary': {
                'total_unique_clients_with_visits': total_unique,
                'bucket_count': len(rows),
            },
            'rows': rows,
        }


# ── Forms outstanding per customer ─────────────────────────────────


@extend_schema(
    tags=['Reports — Guests'],
    description=(
        'Per-customer count of pending FormSubmission rows — i.e. forms '
        'assigned to the customer but not yet signed. Useful for the '
        'front desk pre-checkin sweep ("who do I need to chase about '
        'paperwork before their appointment").'
    ),
)
class FormsOutstandingReport(BaseReportView):
    """Customers with one or more pending (unsigned) form submissions."""

    report_id = 'guests.forms_outstanding'
    category = 'guests'
    permission = P.VIEW_GUEST_REPORTS
    title = 'Forms outstanding'
    description = "Clients with unsigned forms waiting on them. Front-desk's pre-arrival paperwork chase list."
    phi_tier = 'per_customer'

    def parse_params(self, request):
        return {}

    def run(self, request, *_):
        per_customer = (
            FormSubmission.objects
            .for_current_tenant()
            .filter(status='pending')
            .values('customer_id')
            .annotate(pending_count=Count('id'))
            .order_by('-pending_count')
        )
        customer_ids = [r['customer_id'] for r in per_customer]
        customers = {
            c.id: c
            for c in Customer.objects.for_current_tenant().filter(id__in=customer_ids)
        }
        rows = []
        for r in per_customer:
            c = customers.get(r['customer_id'])
            if c is None:
                continue
            rows.append({
                'customer_id': c.id,
                'customer_name': c.full_name,
                'customer_email': c.email or '',
                'customer_phone': c.phone or '',
                'pending_form_count': int(r['pending_count']),
            })
        rows.sort(key=lambda r: (-r['pending_form_count'], r['customer_name'].lower()))

        return {
            'summary': {
                'customer_count': len(rows),
                'total_pending_forms': sum(r['pending_form_count'] for r in rows),
            },
            'rows': rows,
        }
