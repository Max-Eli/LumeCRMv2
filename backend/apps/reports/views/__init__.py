"""Concrete report views, grouped by category.

When adding a new report:
1. Add the view class to the appropriate `views/<category>.py`
2. Re-export from this module
3. Wire the URL in `urls.py`
4. Add to `catalog.REPORT_CATALOG` so it appears in the library page
"""

from .financial import (
    ARAgingReport,
    DailyCloseOutReport,
    RevenueByLocationReport,
    RevenueByServiceReport,
    SalesByDateRangeReport,
    TaxCollectedReport,
)
from .guests import (
    BirthdayListReport,
    FormsOutstandingReport,
    InactiveClientsReport,
    NewVsReturningReport,
    TopSpendersReport,
    VisitFrequencyReport,
)
from .operations import (
    AppointmentsByStatusReport,
    BookingLeadTimeReport,
    BusiestHoursReport,
    CancellationRateReport,
    NoShowRateReport,
    ServiceMixReport,
)
from .staff import (
    NewClientsByProviderReport,
    NoShowRateByProviderReport,
    RepeatRateByProviderReport,
    RevenueByProviderReport,
    ScheduleUtilizationReport,
)

__all__ = [
    # Financial
    'SalesByDateRangeReport',
    'DailyCloseOutReport',
    'ARAgingReport',
    'RevenueByServiceReport',
    'RevenueByLocationReport',
    'TaxCollectedReport',
    # Staff
    'RevenueByProviderReport',
    'ScheduleUtilizationReport',
    'NoShowRateByProviderReport',
    'NewClientsByProviderReport',
    'RepeatRateByProviderReport',
    # Guests
    'NewVsReturningReport',
    'TopSpendersReport',
    'InactiveClientsReport',
    'BirthdayListReport',
    'VisitFrequencyReport',
    'FormsOutstandingReport',
    # Operations
    'AppointmentsByStatusReport',
    'NoShowRateReport',
    'CancellationRateReport',
    'BookingLeadTimeReport',
    'ServiceMixReport',
    'BusiestHoursReport',
]
