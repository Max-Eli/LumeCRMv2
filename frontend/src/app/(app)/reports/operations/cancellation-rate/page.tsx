'use client';

import { useState } from 'react';

import {
  type CancellationRateRow,
  formatNumber,
  formatPct,
  useCancellationRate,
} from '@/lib/reports';

import { defaultDateRange, type DateRange } from '../../_components/date-range-picker';
import {
  ReportSection,
  ReportShell,
  SummaryTile,
  SummaryTileRow,
} from '../../_components/report-shell';
import { ReportTable, type Column } from '../../_components/report-table';

export default function CancellationRatePage() {
  const [range, setRange] = useState<DateRange>(defaultDateRange);
  const { data, isLoading, error } = useCancellationRate(range);

  return (
    <ReportShell
      title="Cancellation rate"
      description="Share of appointments that got cancelled (separate from no-shows). Trend it to spot policy issues."
      phiTier="none"
      dateRange={range}
      onDateRangeChange={setRange}
      isLoading={isLoading}
      error={error}
      exportPath="/api/reports/operations/cancellation-rate/"
    >
      {data ? (
        <>
          <SummaryTileRow>
            <SummaryTile label="Overall rate" value={formatPct(data.summary.overall_cancellation_rate_pct)} />
            <SummaryTile label="Total appointments" value={formatNumber(data.summary.total_appointments)} />
            <SummaryTile label="Total cancellations" value={formatNumber(data.summary.total_cancellations)} />
          </SummaryTileRow>
          <ReportSection title="Daily cancellation rate" description="One row per day.">
            <Table rows={data.rows} />
          </ReportSection>
        </>
      ) : null}
    </ReportShell>
  );
}

function Table({ rows }: { rows: CancellationRateRow[] }) {
  const columns: Column<CancellationRateRow>[] = [
    { key: 'date', label: 'Date', align: 'left', render: (r) => r.date },
    { key: 'total', label: 'Appointments', align: 'right', render: (r) => formatNumber(r.total_appointments) },
    { key: 'cancelled', label: 'Cancelled', align: 'right', render: (r) => formatNumber(r.cancelled_count) },
    {
      key: 'rate',
      label: 'Rate',
      align: 'right',
      className: 'font-medium',
      render: (r) => formatPct(r.cancellation_rate_pct),
    },
  ];
  return <ReportTable columns={columns} rows={rows} rowKey={(r) => r.date} />;
}
