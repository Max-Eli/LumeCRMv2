"""Operations reports — appointment flow and front-desk-y metrics.

Source of truth: `apps.appointments.Appointment`. No PHI rows in this
category — every report is an aggregate count or rate, never per-
customer detail.

Reports in this module:

  - AppointmentsByStatusReport     (Session 2)
  - NoShowRateReport               (Session 2)
  - CancellationRateReport         (Session 2)
  - BookingLeadTimeReport          (Session 2)
  - ServiceMixReport               (Session 2)
  - BusiestHoursReport             (Session 2)
"""

import datetime as dt
from collections import OrderedDict

from django.db.models import Count, F, Q
from drf_spectacular.utils import OpenApiParameter, extend_schema

from apps.appointments.models import Appointment
from apps.tenants.permissions import P

from ..base import BaseReportView

DATE_FROM_PARAM = OpenApiParameter('date_from', str, description='Start date (inclusive, YYYY-MM-DD). Defaults to 30 days before date_to.')
DATE_TO_PARAM = OpenApiParameter('date_to', str, description='End date (inclusive, YYYY-MM-DD). Defaults to today.')


def _status_label(value: str) -> str:
    return dict(Appointment.Status.choices).get(value, value)


# ── Appointments by status ─────────────────────────────────────────


@extend_schema(
    tags=['Reports — Operations'],
    parameters=[DATE_FROM_PARAM, DATE_TO_PARAM],
    description=(
        'Counts of appointments grouped by their final status (booked / '
        'confirmed / checked_in / completed / no_show / cancelled). '
        'Filter window is on Appointment.start_time (the calendar day, '
        'not the booking-creation day).'
    ),
)
class AppointmentsByStatusReport(BaseReportView):
    """Counts of appointments grouped by status over the window."""

    report_id = 'operations.appointments_by_status'
    category = 'operations'
    permission = P.VIEW_OPERATIONS_REPORTS
    title = 'Appointments by status'
    description = "Booked, confirmed, checked-in, completed, no-show, cancelled — counts over the window."
    phi_tier = 'none'

    def run(self, request, *, date_from, date_to):
        per_status = (
            Appointment.objects
            .for_current_tenant()
            .filter(
                start_time__date__gte=date_from,
                start_time__date__lte=date_to,
            )
            .values('status')
            .annotate(c=Count('id'))
        )
        counts = {row['status']: int(row['c']) for row in per_status}

        # Initialize every status so the UI can render a stable bar
        # chart with zero-bars rather than gaps.
        rows = []
        for value, label in Appointment.Status.choices:
            rows.append({
                'status': value,
                'status_label': label,
                'appointment_count': counts.get(value, 0),
            })
        total = sum(r['appointment_count'] for r in rows)

        return {
            'summary': {
                'total_appointments': total,
                'status_count': sum(1 for r in rows if r['appointment_count'] > 0),
            },
            'rows': rows,
        }


# ── No-show rate (overall) ─────────────────────────────────────────


@extend_schema(
    tags=['Reports — Operations'],
    parameters=[DATE_FROM_PARAM, DATE_TO_PARAM],
    description=(
        'Overall no-show rate over the window: count(status=no_show) / '
        'count(all). For a per-provider breakdown, use the Staff report.'
    ),
)
class NoShowRateReport(BaseReportView):
    """Overall no-show rate + count over the window."""

    report_id = 'operations.no_show_rate'
    category = 'operations'
    permission = P.VIEW_OPERATIONS_REPORTS
    title = 'No-show rate'
    description = "Share of appointments where the client didn't show up. The reminder-cadence health check."
    phi_tier = 'none'

    def run(self, request, *, date_from, date_to):
        qs = (
            Appointment.objects
            .for_current_tenant()
            .filter(
                start_time__date__gte=date_from,
                start_time__date__lte=date_to,
            )
        )
        total = qs.count()
        no_show = qs.filter(status=Appointment.Status.NO_SHOW).count()
        rate = (no_show / total * 100) if total else 0

        # Per-day breakdown for the chart.
        per_day = (
            qs.values('start_time__date')
            .annotate(
                total=Count('id'),
                no_show=Count('id', filter=Q(status=Appointment.Status.NO_SHOW)),
            )
        )
        per_day_map = {r['start_time__date']: r for r in per_day}

        rows = []
        cursor = date_from
        while cursor <= date_to:
            r = per_day_map.get(cursor)
            day_total = int(r['total']) if r else 0
            day_ns = int(r['no_show']) if r else 0
            day_rate = (day_ns / day_total * 100) if day_total else 0
            rows.append({
                'date': cursor.isoformat(),
                'total_appointments': day_total,
                'no_show_count': day_ns,
                'no_show_rate_pct': round(day_rate, 1),
            })
            cursor += dt.timedelta(days=1)

        return {
            'summary': {
                'total_appointments': total,
                'total_no_shows': no_show,
                'overall_no_show_rate_pct': round(rate, 1),
            },
            'rows': rows,
        }


# ── Cancellation rate (overall) ────────────────────────────────────


@extend_schema(
    tags=['Reports — Operations'],
    parameters=[DATE_FROM_PARAM, DATE_TO_PARAM],
    description=(
        'Overall cancellation rate over the window: count(status='
        'cancelled) / count(all). Useful for spotting cadence issues '
        '(too-aggressive booking, too-strict policy, etc).'
    ),
)
class CancellationRateReport(BaseReportView):
    """Overall cancellation rate + count over the window."""

    report_id = 'operations.cancellation_rate'
    category = 'operations'
    permission = P.VIEW_OPERATIONS_REPORTS
    title = 'Cancellation rate'
    description = "Share of appointments that got cancelled (separate from no-shows). Trend it to spot policy issues."
    phi_tier = 'none'

    def run(self, request, *, date_from, date_to):
        qs = (
            Appointment.objects
            .for_current_tenant()
            .filter(
                start_time__date__gte=date_from,
                start_time__date__lte=date_to,
            )
        )
        total = qs.count()
        cancelled = qs.filter(status=Appointment.Status.CANCELLED).count()
        rate = (cancelled / total * 100) if total else 0

        per_day = (
            qs.values('start_time__date')
            .annotate(
                total=Count('id'),
                cancelled=Count('id', filter=Q(status=Appointment.Status.CANCELLED)),
            )
        )
        per_day_map = {r['start_time__date']: r for r in per_day}

        rows = []
        cursor = date_from
        while cursor <= date_to:
            r = per_day_map.get(cursor)
            day_total = int(r['total']) if r else 0
            day_c = int(r['cancelled']) if r else 0
            day_rate = (day_c / day_total * 100) if day_total else 0
            rows.append({
                'date': cursor.isoformat(),
                'total_appointments': day_total,
                'cancelled_count': day_c,
                'cancellation_rate_pct': round(day_rate, 1),
            })
            cursor += dt.timedelta(days=1)

        return {
            'summary': {
                'total_appointments': total,
                'total_cancellations': cancelled,
                'overall_cancellation_rate_pct': round(rate, 1),
            },
            'rows': rows,
        }


# ── Booking lead time ──────────────────────────────────────────────


# Pre-built buckets — the question is "how far ahead do clients book?"
# so a histogram of (start_time - created_at) is more useful than a
# raw average alone (which gets dominated by a few far-out bookings).
LEAD_TIME_BUCKETS = [
    ('same_day', 'Same day', 0, 0),
    ('1_to_3', '1–3 days out', 1, 3),
    ('4_to_7', '4–7 days out', 4, 7),
    ('1_to_2_weeks', '8–14 days out', 8, 14),
    ('2_to_4_weeks', '15–30 days out', 15, 30),
    ('over_30', '31+ days out', 31, None),
]


@extend_schema(
    tags=['Reports — Operations'],
    parameters=[DATE_FROM_PARAM, DATE_TO_PARAM],
    description=(
        'Booking lead time = days between booking creation and appointment '
        'start. Histogram + average over appointments CREATED within the '
        'date range. Useful for online-booking sizing decisions and '
        'understanding how far out the spa\'s book actually fills.'
    ),
)
class BookingLeadTimeReport(BaseReportView):
    """Lead-time histogram + average for appointments created in the window."""

    report_id = 'operations.booking_lead_time'
    category = 'operations'
    permission = P.VIEW_OPERATIONS_REPORTS
    title = 'Booking lead time'
    description = "How far ahead clients are booking — histogram of days between booking and appointment, plus average."
    phi_tier = 'none'

    def run(self, request, *, date_from, date_to):
        qs = (
            Appointment.objects
            .for_current_tenant()
            .filter(
                created_at__date__gte=date_from,
                created_at__date__lte=date_to,
            )
            .values('created_at', 'start_time')
        )

        bucket_counts = {b[0]: 0 for b in LEAD_TIME_BUCKETS}
        total_appointments = 0
        total_lead_days = 0
        for appt in qs:
            lead = (appt['start_time'].date() - appt['created_at'].date()).days
            if lead < 0:
                # Backfilled / historical appointments where created_at
                # post-dates start_time. Skip — they distort the metric.
                continue
            total_appointments += 1
            total_lead_days += lead
            for bucket_id, _label, lo, hi in LEAD_TIME_BUCKETS:
                if hi is None and lead >= lo:
                    bucket_counts[bucket_id] += 1
                    break
                if hi is not None and lo <= lead <= hi:
                    bucket_counts[bucket_id] += 1
                    break

        rows = [
            {
                'bucket_id': b[0],
                'label': b[1],
                'min_days': b[2],
                'max_days': b[3],
                'appointment_count': bucket_counts[b[0]],
                'share_pct': round((bucket_counts[b[0]] / total_appointments * 100), 1) if total_appointments else 0.0,
            }
            for b in LEAD_TIME_BUCKETS
        ]

        avg_lead = (total_lead_days / total_appointments) if total_appointments else 0

        return {
            'summary': {
                'total_appointments': total_appointments,
                'avg_lead_days': round(avg_lead, 1),
            },
            'rows': rows,
        }


# ── Service mix ────────────────────────────────────────────────────


@extend_schema(
    tags=['Reports — Operations'],
    parameters=[DATE_FROM_PARAM, DATE_TO_PARAM],
    description=(
        'Counts of appointments grouped by service. Includes ALL '
        'statuses (booked + completed + cancelled + no-show) — this is '
        '"what clients try to book," not "what gets delivered." For '
        'delivered-only mix, filter the response client-side or use the '
        'Revenue by service report.'
    ),
)
class ServiceMixReport(BaseReportView):
    """Appointment count per service in the window, ranked highest-first."""

    report_id = 'operations.service_mix'
    category = 'operations'
    permission = P.VIEW_OPERATIONS_REPORTS
    title = 'Service mix'
    description = "Which services are booked the most. All statuses included — this is demand, not delivery."
    phi_tier = 'none'

    def run(self, request, *, date_from, date_to):
        qs = (
            Appointment.objects
            .for_current_tenant()
            .filter(
                start_time__date__gte=date_from,
                start_time__date__lte=date_to,
            )
            .values('service_id', 'service__name')
            .annotate(appointment_count=Count('id'))
            .order_by('-appointment_count')
        )

        rows = [
            {
                'service_id': r['service_id'],
                'service_name': r['service__name'] or f"Service #{r['service_id']}",
                'appointment_count': int(r['appointment_count']),
            }
            for r in qs
        ]
        total = sum(r['appointment_count'] for r in rows)
        for r in rows:
            r['share_pct'] = round((r['appointment_count'] / total * 100), 1) if total else 0.0

        return {
            'summary': {
                'total_appointments': total,
                'service_count': len(rows),
            },
            'rows': rows,
        }


# ── Busiest hours / days ───────────────────────────────────────────


WEEKDAY_LABELS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']


@extend_schema(
    tags=['Reports — Operations'],
    parameters=[DATE_FROM_PARAM, DATE_TO_PARAM],
    description=(
        'A heatmap of when the spa is busiest: counts of appointments '
        'grouped by hour-of-day × weekday. Useful for staff scheduling '
        'decisions ("we need a second front desk on Saturday afternoons") '
        'and for online-booking slot promotion ("show empty Tuesday mornings").'
    ),
)
class BusiestHoursReport(BaseReportView):
    """Heatmap of appointment counts by hour-of-day × weekday."""

    report_id = 'operations.busiest_hours'
    category = 'operations'
    permission = P.VIEW_OPERATIONS_REPORTS
    title = 'Busiest hours / days'
    description = "Heatmap of when the spa is busiest — hour of day × weekday. Use it to staff up at the right times."
    phi_tier = 'none'

    def run(self, request, *, date_from, date_to):
        qs = (
            Appointment.objects
            .for_current_tenant()
            .filter(
                start_time__date__gte=date_from,
                start_time__date__lte=date_to,
            )
            .values('start_time')
        )

        # 7 days × 24 hours grid initialized to zero so the frontend
        # can render a full heatmap without sparse-cell handling.
        grid = [[0 for _ in range(24)] for _ in range(7)]
        per_hour = [0 for _ in range(24)]
        per_weekday = [0 for _ in range(7)]
        total = 0
        for appt in qs:
            t = appt['start_time']
            # Use UTC components — per-tenant TZ bucketing is in the
            # production-lift list (same caveat as financial reports).
            wd = t.weekday()  # 0=Monday
            hr = t.hour
            grid[wd][hr] += 1
            per_hour[hr] += 1
            per_weekday[wd] += 1
            total += 1

        rows = []
        for wd in range(7):
            for hr in range(24):
                if grid[wd][hr] == 0:
                    continue
                rows.append({
                    'weekday': wd,
                    'weekday_label': WEEKDAY_LABELS[wd],
                    'hour': hr,
                    'appointment_count': grid[wd][hr],
                })
        rows.sort(key=lambda r: -r['appointment_count'])

        peak_hour = max(range(24), key=lambda h: per_hour[h]) if total else None
        peak_weekday = max(range(7), key=lambda w: per_weekday[w]) if total else None

        return {
            'summary': {
                'total_appointments': total,
                'peak_hour': peak_hour,
                'peak_hour_label': f'{peak_hour:02d}:00' if peak_hour is not None else None,
                'peak_weekday': peak_weekday,
                'peak_weekday_label': WEEKDAY_LABELS[peak_weekday] if peak_weekday is not None else None,
                'grid': grid,
                'per_hour': per_hour,
                'per_weekday': per_weekday,
            },
            'rows': rows,
        }
