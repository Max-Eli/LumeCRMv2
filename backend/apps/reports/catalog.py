"""Report catalog — single source of truth for which reports exist.

The catalog endpoint (`GET /api/reports/`) returns the set of reports
the current membership has permission to run. Frontend renders the
library page from this — no hardcoded list, no permission logic
duplicated client-side. When a new report ships, append it to
`REPORT_CATALOG` and add its URL in `urls.py`; it auto-appears in
the library for users with the right role.

Categories carry `label` (human-readable) + `description` (one-line
sub-header for the library card grid). Reports inside each category
are ordered as listed.
"""

from __future__ import annotations

from rest_framework.response import Response
from rest_framework.views import APIView

from apps.tenants.permissions import P, has_permission

from .permissions import ReportCatalogPermission
from .views import (
    AppointmentsByStatusReport,
    ARAgingReport,
    BirthdayListReport,
    BookingLeadTimeReport,
    BookingsByAcquisitionSourceReport,
    BusiestHoursReport,
    CancellationRateReport,
    DailyCloseOutReport,
    FormsOutstandingReport,
    InactiveClientsReport,
    NewClientsByProviderReport,
    NewVsReturningReport,
    NoShowRateByProviderReport,
    NoShowRateReport,
    RepeatRateByProviderReport,
    RevenueByAcquisitionSourceReport,
    RevenueByLocationReport,
    RevenueByProviderReport,
    RevenueByServiceReport,
    SalesByDateRangeReport,
    ScheduleUtilizationReport,
    ServiceMixReport,
    TaxCollectedReport,
    TopSpendersReport,
    VisitFrequencyReport,
)

# (category_id, label, description, [(view_class, url_path), ...])
REPORT_CATALOG: list[tuple[str, str, str, list[tuple[type, str]]]] = [
    (
        'financial',
        'Financial',
        'Sales, payment methods, taxes, accounts receivable.',
        [
            (SalesByDateRangeReport,    '/api/reports/financial/sales-by-date-range/'),
            (DailyCloseOutReport,       '/api/reports/financial/daily-close-out/'),
            (RevenueByServiceReport,    '/api/reports/financial/revenue-by-service/'),
            (RevenueByLocationReport,   '/api/reports/financial/revenue-by-location/'),
            (TaxCollectedReport,        '/api/reports/financial/tax-collected/'),
            (ARAgingReport,             '/api/reports/financial/ar-aging/'),
            (RevenueByAcquisitionSourceReport,
                '/api/reports/financial/revenue-by-acquisition-source/'),
        ],
    ),
    (
        'staff',
        'Staff',
        'Provider productivity, revenue attribution, utilization.',
        [
            (RevenueByProviderReport,        '/api/reports/staff/revenue-by-provider/'),
            (ScheduleUtilizationReport,      '/api/reports/staff/schedule-utilization/'),
            (NoShowRateByProviderReport,     '/api/reports/staff/no-show-rate-by-provider/'),
            (NewClientsByProviderReport,     '/api/reports/staff/new-clients-by-provider/'),
            (RepeatRateByProviderReport,     '/api/reports/staff/repeat-rate-by-provider/'),
        ],
    ),
    (
        'guests',
        'Guests',
        'Client acquisition, retention, lifecycle.',
        [
            (NewVsReturningReport,      '/api/reports/guests/new-vs-returning/'),
            (TopSpendersReport,         '/api/reports/guests/top-spenders/'),
            (InactiveClientsReport,     '/api/reports/guests/inactive-clients/'),
            (VisitFrequencyReport,      '/api/reports/guests/visit-frequency/'),
            (BirthdayListReport,        '/api/reports/guests/birthday-list/'),
            (FormsOutstandingReport,    '/api/reports/guests/forms-outstanding/'),
        ],
    ),
    (
        'operations',
        'Operations',
        'Appointment flow, no-show + cancellation rates, service mix.',
        [
            (AppointmentsByStatusReport, '/api/reports/operations/appointments-by-status/'),
            (NoShowRateReport,           '/api/reports/operations/no-show-rate/'),
            (CancellationRateReport,     '/api/reports/operations/cancellation-rate/'),
            (BookingLeadTimeReport,      '/api/reports/operations/booking-lead-time/'),
            (ServiceMixReport,           '/api/reports/operations/service-mix/'),
            (BusiestHoursReport,         '/api/reports/operations/busiest-hours/'),
            (BookingsByAcquisitionSourceReport,
                '/api/reports/operations/bookings-by-acquisition-source/'),
        ],
    ),
    (
        'marketing',
        'Marketing',
        'Campaign performance and referral source attribution.',
        [
            # Phase 3 territory — referral tracking + email/SMS campaigns
            # need to land before these reports have data to draw from.
        ],
    ),
]


# Category-level "can the user see this category at all?" gate. Used
# to omit empty/inaccessible categories from the catalog response.
CATEGORY_PERMISSION = {
    'financial': P.VIEW_FINANCIAL_REPORTS,
    'staff': P.VIEW_STAFF_REPORTS,
    'guests': P.VIEW_GUEST_REPORTS,
    'operations': P.VIEW_OPERATIONS_REPORTS,
    'marketing': P.VIEW_MARKETING_REPORTS,
}


class ReportCatalogView(APIView):
    """List the reports the current user is allowed to run.

    Filters by the current membership's effective permissions:
      - A report whose `permission` the user lacks is omitted.
      - A category with zero accessible reports is omitted entirely
        (cleaner UX than rendering "Marketing — 0 reports").

    Superusers see everything. Anyone authenticated in a tenant can
    hit this endpoint; the response shape is the same.
    """

    permission_classes = [ReportCatalogPermission]

    def get(self, request, *args, **kwargs):
        membership = getattr(request, 'tenant_membership', None)
        is_superuser = bool(request.user and request.user.is_superuser)

        def can_see(perm: str) -> bool:
            if is_superuser:
                return True
            if not membership:
                return False
            return has_permission(membership, perm)

        out_categories = []
        for category_id, label, description, reports in REPORT_CATALOG:
            visible_reports = [
                view_cls.catalog_entry(url=url)
                for view_cls, url in reports
                if can_see(view_cls.permission)
            ]
            if not visible_reports:
                continue
            out_categories.append({
                'id': category_id,
                'label': label,
                'description': description,
                'reports': visible_reports,
            })

        return Response({'categories': out_categories})
