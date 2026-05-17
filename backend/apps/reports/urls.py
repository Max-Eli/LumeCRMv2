"""URL routes for the reports module.

URL shape: `/api/reports/<category>/<report-slug>/`. Each report
gets its own path (one APIView per report — see ADR 0013).

The catalog at `/api/reports/` is the single discovery endpoint
the frontend uses to render the library page. When adding a new
report:

  1. Add the route here.
  2. Add the entry to `catalog.REPORT_CATALOG`.
  3. The frontend library auto-renders the new card on next load.
"""

from django.urls import path

from .catalog import ReportCatalogView
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

urlpatterns = [
    path('reports/', ReportCatalogView.as_view(), name='reports-catalog'),

    # Financial
    path('reports/financial/sales-by-date-range/', SalesByDateRangeReport.as_view(),
         name='reports-financial-sales-by-date-range'),
    path('reports/financial/daily-close-out/', DailyCloseOutReport.as_view(),
         name='reports-financial-daily-close-out'),
    path('reports/financial/ar-aging/', ARAgingReport.as_view(),
         name='reports-financial-ar-aging'),
    path('reports/financial/revenue-by-service/', RevenueByServiceReport.as_view(),
         name='reports-financial-revenue-by-service'),
    path('reports/financial/revenue-by-location/', RevenueByLocationReport.as_view(),
         name='reports-financial-revenue-by-location'),
    path('reports/financial/tax-collected/', TaxCollectedReport.as_view(),
         name='reports-financial-tax-collected'),
    path('reports/financial/revenue-by-acquisition-source/',
         RevenueByAcquisitionSourceReport.as_view(),
         name='reports-financial-revenue-by-acquisition-source'),

    # Staff
    path('reports/staff/revenue-by-provider/', RevenueByProviderReport.as_view(),
         name='reports-staff-revenue-by-provider'),
    path('reports/staff/schedule-utilization/', ScheduleUtilizationReport.as_view(),
         name='reports-staff-schedule-utilization'),
    path('reports/staff/no-show-rate-by-provider/', NoShowRateByProviderReport.as_view(),
         name='reports-staff-no-show-rate-by-provider'),
    path('reports/staff/new-clients-by-provider/', NewClientsByProviderReport.as_view(),
         name='reports-staff-new-clients-by-provider'),
    path('reports/staff/repeat-rate-by-provider/', RepeatRateByProviderReport.as_view(),
         name='reports-staff-repeat-rate-by-provider'),

    # Guests
    path('reports/guests/new-vs-returning/', NewVsReturningReport.as_view(),
         name='reports-guests-new-vs-returning'),
    path('reports/guests/top-spenders/', TopSpendersReport.as_view(),
         name='reports-guests-top-spenders'),
    path('reports/guests/inactive-clients/', InactiveClientsReport.as_view(),
         name='reports-guests-inactive-clients'),
    path('reports/guests/birthday-list/', BirthdayListReport.as_view(),
         name='reports-guests-birthday-list'),
    path('reports/guests/visit-frequency/', VisitFrequencyReport.as_view(),
         name='reports-guests-visit-frequency'),
    path('reports/guests/forms-outstanding/', FormsOutstandingReport.as_view(),
         name='reports-guests-forms-outstanding'),

    # Operations
    path('reports/operations/appointments-by-status/', AppointmentsByStatusReport.as_view(),
         name='reports-operations-appointments-by-status'),
    path('reports/operations/no-show-rate/', NoShowRateReport.as_view(),
         name='reports-operations-no-show-rate'),
    path('reports/operations/cancellation-rate/', CancellationRateReport.as_view(),
         name='reports-operations-cancellation-rate'),
    path('reports/operations/booking-lead-time/', BookingLeadTimeReport.as_view(),
         name='reports-operations-booking-lead-time'),
    path('reports/operations/service-mix/', ServiceMixReport.as_view(),
         name='reports-operations-service-mix'),
    path('reports/operations/busiest-hours/', BusiestHoursReport.as_view(),
         name='reports-operations-busiest-hours'),
    path('reports/operations/bookings-by-acquisition-source/',
         BookingsByAcquisitionSourceReport.as_view(),
         name='reports-operations-bookings-by-acquisition-source'),
]
