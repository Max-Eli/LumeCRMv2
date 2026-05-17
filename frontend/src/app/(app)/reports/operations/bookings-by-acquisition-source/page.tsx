'use client';

import { useState } from 'react';

import {
  type BookingsByAcquisitionSourceRow,
  formatNumber,
  useBookingsByAcquisitionSource,
} from '@/lib/reports';

import { defaultDateRange, type DateRange } from '../../_components/date-range-picker';
import {
  ReportSection,
  ReportShell,
  SummaryTile,
  SummaryTileRow,
} from '../../_components/report-shell';
import { ReportTable, type Column } from '../../_components/report-table';

export default function BookingsByAcquisitionSourcePage() {
  const [range, setRange] = useState<DateRange>(defaultDateRange);
  const { data, isLoading, error } = useBookingsByAcquisitionSource(range);

  return (
    <ReportShell
      title="Bookings by acquisition source"
      description="Which channels (IG DMs, online booking, referrals, walk-ins) are producing actual appointments. Pair with the Revenue version to see whether each channel converts to spend."
      phiTier="none"
      dateRange={range}
      onDateRangeChange={setRange}
      isLoading={isLoading}
      error={error}
      exportPath="/api/reports/operations/bookings-by-acquisition-source/"
    >
      {data ? (
        <>
          <SummaryTileRow>
            <SummaryTile
              label="Total appointments"
              value={formatNumber(data.summary.total_appointments)}
            />
            <SummaryTile
              label="Distinct channels"
              value={formatNumber(data.summary.distinct_sources)}
            />
          </SummaryTileRow>
          <ReportSection
            title="Per-channel breakdown"
            description="Cancellation + no-show rates per channel help identify low-quality acquisition (e.g. flaky social-DM leads vs reliable referrals)."
          >
            <Table rows={data.rows} />
          </ReportSection>
        </>
      ) : null}
    </ReportShell>
  );
}

function Table({ rows }: { rows: BookingsByAcquisitionSourceRow[] }) {
  const columns: Column<BookingsByAcquisitionSourceRow>[] = [
    {
      key: 'source',
      label: 'Channel',
      align: 'left',
      render: (r) => r.acquisition_source_label,
    },
    {
      key: 'total',
      label: 'Bookings',
      align: 'right',
      className: 'font-medium',
      render: (r) => formatNumber(r.appointment_count),
    },
    {
      key: 'completed',
      label: 'Completed',
      align: 'right',
      render: (r) => formatNumber(r.completed_count),
    },
    {
      key: 'cancelled',
      label: 'Cancelled',
      align: 'right',
      render: (r) =>
        `${formatNumber(r.cancelled_count)} (${r.cancellation_rate_pct}%)`,
    },
    {
      key: 'noshow',
      label: 'No-show',
      align: 'right',
      render: (r) =>
        `${formatNumber(r.no_show_count)} (${r.no_show_rate_pct}%)`,
    },
  ];
  return <ReportTable columns={columns} rows={rows} rowKey={(r) => r.acquisition_source} />;
}
