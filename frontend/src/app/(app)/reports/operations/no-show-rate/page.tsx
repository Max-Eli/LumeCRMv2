'use client';

import { useState } from 'react';

import {
  type NoShowRateRow,
  formatNumber,
  formatPct,
  useNoShowRate,
} from '@/lib/reports';

import { defaultDateRange, type DateRange } from '../../_components/date-range-picker';
import {
  ReportSection,
  ReportShell,
  SummaryTile,
  SummaryTileRow,
} from '../../_components/report-shell';
import { ReportTable, type Column } from '../../_components/report-table';

export default function NoShowRatePage() {
  const [range, setRange] = useState<DateRange>(defaultDateRange);
  const { data, isLoading, error } = useNoShowRate(range);

  return (
    <ReportShell
      title="No-show rate"
      description="Share of appointments where the client didn't show up. The reminder-cadence health check."
      phiTier="none"
      dateRange={range}
      onDateRangeChange={setRange}
      isLoading={isLoading}
      error={error}
      exportPath="/api/reports/operations/no-show-rate/"
    >
      {data ? (
        <>
          <SummaryTileRow>
            <SummaryTile label="Overall rate" value={formatPct(data.summary.overall_no_show_rate_pct)} />
            <SummaryTile label="Total appointments" value={formatNumber(data.summary.total_appointments)} />
            <SummaryTile label="Total no-shows" value={formatNumber(data.summary.total_no_shows)} />
          </SummaryTileRow>
          <ReportSection title="Daily no-show rate" description="One row per day.">
            <Table rows={data.rows} />
          </ReportSection>
        </>
      ) : null}
    </ReportShell>
  );
}

function Table({ rows }: { rows: NoShowRateRow[] }) {
  const columns: Column<NoShowRateRow>[] = [
    { key: 'date', label: 'Date', align: 'left', render: (r) => r.date },
    { key: 'total', label: 'Appointments', align: 'right', render: (r) => formatNumber(r.total_appointments) },
    { key: 'no_show', label: 'No-shows', align: 'right', render: (r) => formatNumber(r.no_show_count) },
    {
      key: 'rate',
      label: 'Rate',
      align: 'right',
      className: 'font-medium',
      render: (r) => formatPct(r.no_show_rate_pct),
    },
  ];
  return <ReportTable columns={columns} rows={rows} rowKey={(r) => r.date} />;
}
