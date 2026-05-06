"""Staff reports — provider productivity + revenue attribution.

Source of truth: `apps.invoices.Invoice` joined to
`apps.appointments.Appointment` joined to `provider`
(`apps.tenants.TenantMembership`). Schedule data comes from
`apps.tenants.ProviderSchedule` (1:1 with MembershipLocation).

Reports in this module:

  - RevenueByProviderReport            (Session 1)
  - ScheduleUtilizationReport          (Session 2)
  - NoShowRateByProviderReport         (Session 2)
  - NewClientsByProviderReport         (Session 2)
  - RepeatRateByProviderReport         (Session 2)
"""

from collections import defaultdict
from datetime import time as dt_time

from django.db.models import Count, F, Q, Sum
from drf_spectacular.utils import OpenApiParameter, extend_schema

from apps.appointments.models import Appointment
from apps.invoices.models import Invoice
from apps.tenants.models import ProviderSchedule, TenantMembership
from apps.tenants.permissions import P

from ..base import BaseReportView, cents_to_int

DATE_FROM_PARAM = OpenApiParameter('date_from', str, description='Start date (inclusive, YYYY-MM-DD). Defaults to 30 days before date_to.')
DATE_TO_PARAM = OpenApiParameter('date_to', str, description='End date (inclusive, YYYY-MM-DD). Defaults to today.')

WEEKDAY_NAMES = ('monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday')


def _compose_provider_name(first: str | None, last: str | None, email: str | None, pk: int) -> str:
    full = f"{first or ''} {last or ''}".strip()
    return full or (email or f'Provider #{pk}')


# ── Revenue by provider (Session 1) ────────────────────────────────


@extend_schema(
    tags=['Reports — Staff'],
    parameters=[DATE_FROM_PARAM, DATE_TO_PARAM],
    description=(
        'Revenue and appointment counts per provider, derived from PAID '
        'invoices closed within the date range. Providers with zero '
        'revenue in the window are omitted (they appear in operations '
        'reports instead).'
    ),
)
class RevenueByProviderReport(BaseReportView):
    """Revenue + paid appointment count per provider, ranked highest-first."""

    report_id = 'staff.revenue_by_provider'
    category = 'staff'
    permission = P.VIEW_STAFF_REPORTS
    title = 'Revenue by provider'
    description = "Gross revenue and paid-appointment counts per provider, ranked highest-first."
    phi_tier = 'aggregated'

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
            .values(
                provider_id=F('appointment__provider_id'),
                first_name=F('appointment__provider__user__first_name'),
                last_name=F('appointment__provider__user__last_name'),
                email=F('appointment__provider__user__email'),
            )
            .annotate(
                gross_cents=Sum('total_cents'),
                appointment_count=Count('id'),
            )
            .order_by('-gross_cents')
        )

        rows = [
            {
                'provider_id': r['provider_id'],
                'provider_name': _compose_provider_name(
                    r['first_name'], r['last_name'], r['email'], r['provider_id'],
                ),
                'gross_cents': cents_to_int(r['gross_cents']),
                'appointment_count': int(r['appointment_count']),
            }
            for r in qs
        ]

        gross_total = sum(r['gross_cents'] for r in rows)
        appointments_total = sum(r['appointment_count'] for r in rows)
        provider_count = len(rows)

        return {
            'summary': {
                'total_gross_cents': gross_total,
                'total_appointments': appointments_total,
                'provider_count': provider_count,
                'avg_revenue_per_provider_cents': (gross_total // provider_count) if provider_count else 0,
            },
            'rows': rows,
        }


# ── Schedule utilization ───────────────────────────────────────────


@extend_schema(
    tags=['Reports — Staff'],
    parameters=[DATE_FROM_PARAM, DATE_TO_PARAM],
    description=(
        'For each provider with a saved weekly schedule, compares booked '
        'appointment hours to scheduled work hours over the date range. '
        'Cancellations and no-shows are EXCLUDED from "booked" — the point '
        'is "did the provider perform the service," not "did we put '
        'something on their calendar." Utilization = booked ÷ scheduled.'
    ),
)
class ScheduleUtilizationReport(BaseReportView):
    """Booked-hour utilization vs scheduled hours, per provider."""

    report_id = 'staff.schedule_utilization'
    category = 'staff'
    permission = P.VIEW_STAFF_REPORTS
    title = 'Schedule utilization'
    description = "What share of each provider's scheduled hours actually got delivered. Cancellations and no-shows don't count as utilized."
    phi_tier = 'aggregated'

    # Statuses that count as "the provider actually performed work."
    DELIVERED_STATUSES = (
        Appointment.Status.CHECKED_IN,
        Appointment.Status.COMPLETED,
    )

    def run(self, request, *, date_from, date_to):
        # Build scheduled minutes per provider over the window. Walk
        # day-by-day and look up the provider's weekly_hours for that
        # weekday across ALL their MembershipLocation rows in this tenant.
        from apps.tenants.context import get_current_tenant
        tenant = get_current_tenant()

        # Pull every schedule for this tenant in a single query, keyed by
        # membership_id (a provider can have multiple schedules — one per
        # location they work at).
        schedules = (
            ProviderSchedule.objects
            .filter(membership_location__membership__tenant=tenant)
            .select_related('membership_location__membership__user')
        )
        per_membership_schedules: dict[int, list[dict]] = defaultdict(list)
        provider_meta: dict[int, dict] = {}
        for s in schedules:
            membership = s.membership_location.membership
            per_membership_schedules[membership.pk].append(s.weekly_hours or {})
            if membership.pk not in provider_meta:
                provider_meta[membership.pk] = {
                    'first_name': membership.user.first_name,
                    'last_name': membership.user.last_name,
                    'email': membership.user.email,
                }

        # Sum scheduled minutes per provider for the date range.
        scheduled_per_provider: dict[int, int] = defaultdict(int)
        import datetime as dt
        cursor = date_from
        while cursor <= date_to:
            weekday = WEEKDAY_NAMES[cursor.weekday()]
            for membership_id, schedule_dicts in per_membership_schedules.items():
                for sched in schedule_dicts:
                    blocks = sched.get(weekday, []) or []
                    for block in blocks:
                        scheduled_per_provider[membership_id] += _block_minutes(
                            block.get('start'), block.get('end'),
                        )
            cursor += dt.timedelta(days=1)

        # Sum delivered minutes per provider in the range.
        delivered_qs = (
            Appointment.objects
            .for_current_tenant()
            .filter(
                start_time__date__gte=date_from,
                start_time__date__lte=date_to,
                status__in=self.DELIVERED_STATUSES,
            )
            .values('provider_id', 'start_time', 'end_time')
        )
        delivered_per_provider: dict[int, int] = defaultdict(int)
        for appt in delivered_qs:
            delta = (appt['end_time'] - appt['start_time']).total_seconds() / 60
            delivered_per_provider[appt['provider_id']] += int(delta)

        # Hydrate provider metadata for any provider that has delivered
        # appointments but no schedule (so the row appears with 0%
        # scheduled rather than getting silently dropped).
        missing_meta = [pid for pid in delivered_per_provider if pid not in provider_meta]
        if missing_meta:
            for m in (
                TenantMembership.objects
                .filter(tenant=tenant, pk__in=missing_meta)
                .select_related('user')
            ):
                provider_meta[m.pk] = {
                    'first_name': m.user.first_name,
                    'last_name': m.user.last_name,
                    'email': m.user.email,
                }

        all_provider_ids = set(scheduled_per_provider) | set(delivered_per_provider)
        rows = []
        for pid in all_provider_ids:
            scheduled = scheduled_per_provider.get(pid, 0)
            delivered = delivered_per_provider.get(pid, 0)
            meta = provider_meta.get(pid, {})
            utilization_pct = (delivered / scheduled * 100) if scheduled else 0
            rows.append({
                'provider_id': pid,
                'provider_name': _compose_provider_name(
                    meta.get('first_name'), meta.get('last_name'), meta.get('email'), pid,
                ),
                'scheduled_minutes': scheduled,
                'delivered_minutes': delivered,
                'utilization_pct': round(utilization_pct, 1),
            })
        # Highest utilization first; tie-break by name.
        rows.sort(key=lambda r: (-r['utilization_pct'], r['provider_name'].lower()))

        total_scheduled = sum(r['scheduled_minutes'] for r in rows)
        total_delivered = sum(r['delivered_minutes'] for r in rows)
        overall_pct = (total_delivered / total_scheduled * 100) if total_scheduled else 0

        return {
            'summary': {
                'total_scheduled_minutes': total_scheduled,
                'total_delivered_minutes': total_delivered,
                'overall_utilization_pct': round(overall_pct, 1),
                'provider_count': len(rows),
            },
            'rows': rows,
        }


def _block_minutes(start: str | None, end: str | None) -> int:
    """Minutes between two HH:MM strings. 0 on bad input — schedule
    validation lives in the serializer; reports stay tolerant."""
    if not start or not end:
        return 0
    try:
        s_h, s_m = (int(x) for x in start.split(':'))
        e_h, e_m = (int(x) for x in end.split(':'))
    except (ValueError, AttributeError):
        return 0
    s_total = s_h * 60 + s_m
    e_total = e_h * 60 + e_m
    delta = e_total - s_total
    return max(delta, 0)


# ── No-show rate per provider ──────────────────────────────────────


@extend_schema(
    tags=['Reports — Staff'],
    parameters=[DATE_FROM_PARAM, DATE_TO_PARAM],
    description=(
        'No-show count + rate per provider over the date range. Useful for '
        'spotting providers whose clients consistently flake (often a '
        'reminder-cadence problem rather than a provider problem — but the '
        'data is the starting point). Computed on appointments whose '
        'start_time falls in the window.'
    ),
)
class NoShowRateByProviderReport(BaseReportView):
    """No-show count + rate per provider."""

    report_id = 'staff.no_show_rate_by_provider'
    category = 'staff'
    permission = P.VIEW_STAFF_REPORTS
    title = 'No-show rate by provider'
    description = "Per-provider no-show count and rate over the window. Often a reminder-cadence signal rather than a provider one."
    phi_tier = 'aggregated'

    def run(self, request, *, date_from, date_to):
        qs = (
            Appointment.objects
            .for_current_tenant()
            .filter(
                start_time__date__gte=date_from,
                start_time__date__lte=date_to,
            )
            .values(
                'provider_id',
                'provider__user__first_name',
                'provider__user__last_name',
                'provider__user__email',
            )
            .annotate(
                total=Count('id'),
                no_show_count=Count('id', filter=Q(status=Appointment.Status.NO_SHOW)),
            )
            .order_by('-no_show_count')
        )

        rows = []
        for r in qs:
            total = int(r['total'])
            no_show = int(r['no_show_count'])
            rate = (no_show / total * 100) if total else 0
            rows.append({
                'provider_id': r['provider_id'],
                'provider_name': _compose_provider_name(
                    r['provider__user__first_name'],
                    r['provider__user__last_name'],
                    r['provider__user__email'],
                    r['provider_id'],
                ),
                'total_appointments': total,
                'no_show_count': no_show,
                'no_show_rate_pct': round(rate, 1),
            })

        total_appts = sum(r['total_appointments'] for r in rows)
        total_no_shows = sum(r['no_show_count'] for r in rows)
        overall_rate = (total_no_shows / total_appts * 100) if total_appts else 0

        return {
            'summary': {
                'total_appointments': total_appts,
                'total_no_shows': total_no_shows,
                'overall_no_show_rate_pct': round(overall_rate, 1),
                'provider_count': len(rows),
            },
            'rows': rows,
        }


# ── New clients by provider ────────────────────────────────────────


@extend_schema(
    tags=['Reports — Staff'],
    parameters=[DATE_FROM_PARAM, DATE_TO_PARAM],
    description=(
        'For each provider, the count of clients whose VERY FIRST '
        'appointment ever was with this provider AND fell inside the date '
        'range. Marketing + commission attribution: "who is bringing in '
        'new business." Cancellations + no-shows still count.'
    ),
)
class NewClientsByProviderReport(BaseReportView):
    """Count of net-new clients each provider acquired in the window."""

    report_id = 'staff.new_clients_by_provider'
    category = 'staff'
    permission = P.VIEW_STAFF_REPORTS
    title = 'New clients acquired by provider'
    description = "Who's bringing in new business: clients whose first-ever appointment was with this provider in the window."
    phi_tier = 'aggregated'

    def run(self, request, *, date_from, date_to):
        # 1. For every customer, find their first-ever appointment in
        #    this tenant. We only care about customers whose first appt
        #    falls inside the window.
        from django.db.models import Min
        first_appt_qs = (
            Appointment.objects
            .for_current_tenant()
            .values('customer_id')
            .annotate(first_at=Min('start_time'))
        )
        new_customer_ids = [
            row['customer_id'] for row in first_appt_qs
            if date_from <= row['first_at'].date() <= date_to
        ]
        if not new_customer_ids:
            return {
                'summary': {
                    'total_new_clients': 0,
                    'provider_count': 0,
                },
                'rows': [],
            }

        # 2. For each new customer, find the provider on their FIRST
        #    appointment and credit that provider.
        new_with_provider = (
            Appointment.objects
            .for_current_tenant()
            .filter(customer_id__in=new_customer_ids)
            .values('customer_id')
            .annotate(first_at=Min('start_time'))
        )
        first_at_by_customer = {row['customer_id']: row['first_at'] for row in new_with_provider}

        # Join back to find the provider on each first appointment.
        first_appts = (
            Appointment.objects
            .for_current_tenant()
            .filter(customer_id__in=new_customer_ids)
            .select_related('provider', 'provider__user')
        )
        per_provider: dict[int, dict] = {}
        for appt in first_appts:
            if appt.start_time != first_at_by_customer.get(appt.customer_id):
                continue
            pid = appt.provider_id
            entry = per_provider.setdefault(pid, {
                'provider_id': pid,
                'first_name': appt.provider.user.first_name,
                'last_name': appt.provider.user.last_name,
                'email': appt.provider.user.email,
                'new_client_count': 0,
            })
            entry['new_client_count'] += 1

        rows = [
            {
                'provider_id': p['provider_id'],
                'provider_name': _compose_provider_name(
                    p['first_name'], p['last_name'], p['email'], p['provider_id'],
                ),
                'new_client_count': p['new_client_count'],
            }
            for p in per_provider.values()
        ]
        rows.sort(key=lambda r: (-r['new_client_count'], r['provider_name'].lower()))

        return {
            'summary': {
                'total_new_clients': sum(r['new_client_count'] for r in rows),
                'provider_count': len(rows),
            },
            'rows': rows,
        }


# ── Repeat rate by provider ────────────────────────────────────────


@extend_schema(
    tags=['Reports — Staff'],
    description=(
        'For each provider, the share of unique clients (across all time) '
        'who came back for a second visit. No date params — this is a '
        'lifetime-loyalty metric. Computed across ALL appointment statuses '
        '(cancellations + no-shows still count as visits — the question is '
        'how many distinct clients chose this provider more than once).'
    ),
)
class RepeatRateByProviderReport(BaseReportView):
    """Share of each provider's unique clients who returned for a 2nd+ visit."""

    report_id = 'staff.repeat_rate_by_provider'
    category = 'staff'
    permission = P.VIEW_STAFF_REPORTS
    title = 'Repeat rate by provider'
    description = "Lifetime metric: of every unique client a provider saw, what share came back. Higher = stickier book."
    phi_tier = 'aggregated'

    def parse_params(self, request):
        # No params — lifetime metric.
        return {}

    def run(self, request, *_):
        # For each (provider, customer) pair, count appointments. A
        # customer with 2+ appointments with the same provider is a
        # "returner" for that provider.
        per_pair_qs = (
            Appointment.objects
            .for_current_tenant()
            .values('provider_id', 'customer_id')
            .annotate(c=Count('id'))
        )

        per_provider: dict[int, dict] = defaultdict(lambda: {'unique_clients': 0, 'returners': 0})
        for row in per_pair_qs:
            entry = per_provider[row['provider_id']]
            entry['unique_clients'] += 1
            if row['c'] >= 2:
                entry['returners'] += 1

        # Hydrate provider names.
        from apps.tenants.context import get_current_tenant
        tenant = get_current_tenant()
        provider_meta = {
            m.pk: m
            for m in TenantMembership.objects
                .filter(tenant=tenant, pk__in=list(per_provider.keys()))
                .select_related('user')
        }

        rows = []
        for pid, stats in per_provider.items():
            unique = stats['unique_clients']
            returners = stats['returners']
            rate = (returners / unique * 100) if unique else 0
            m = provider_meta.get(pid)
            name = (
                _compose_provider_name(m.user.first_name, m.user.last_name, m.user.email, pid)
                if m else f'Provider #{pid}'
            )
            rows.append({
                'provider_id': pid,
                'provider_name': name,
                'unique_client_count': unique,
                'repeat_client_count': returners,
                'repeat_rate_pct': round(rate, 1),
            })
        rows.sort(key=lambda r: (-r['repeat_rate_pct'], -r['unique_client_count'], r['provider_name'].lower()))

        total_unique = sum(r['unique_client_count'] for r in rows)
        total_returners = sum(r['repeat_client_count'] for r in rows)
        overall_rate = (total_returners / total_unique * 100) if total_unique else 0

        return {
            'summary': {
                'total_unique_clients': total_unique,
                'total_repeat_clients': total_returners,
                'overall_repeat_rate_pct': round(overall_rate, 1),
                'provider_count': len(rows),
            },
            'rows': rows,
        }
