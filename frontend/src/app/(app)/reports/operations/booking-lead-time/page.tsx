'use client';

import { useState } from 'react';

import {
  type BookingLeadTimeRow,
  formatNumber,
  formatPct,
  useBookingLeadTime,
} from '@/lib/reports';

import { defaultDateRange, type DateRange } from '../../_components/date-range-picker';
import {
  ReportSection,
  ReportShell,
  SummaryTile,
  SummaryTileRow,
} from '../../_components/report-shell';
import { ReportTable, type Column } from '../../_components/report-table';

export default function BookingLeadTimePage() {
  const [range, setRange] = useState<DateRange>(defaultDateRange);
  const { data, isLoading, error } = useBookingLeadTime(range);

  return (
    <ReportShell
      title="Booking lead time"
      description="How far ahead clients book — histogram of days between booking creation and appointment, plus average."
      phiTier="none"
      dateRange={range}
      onDateRangeChange={setRange}
      isLoading={isLoading}
      error={error}
      exportPath="/api/reports/operations/booking-lead-time/"
    >
      {data ? (
        <>
          <SummaryTileRow>
            <SummaryTile label="Avg lead time" value={`${data.summary.avg_lead_days.toFixed(1)} days`} />
            <SummaryTile label="Appointments" value={formatNumber(data.summary.total_appointments)} hint="created in window" />
          </SummaryTileRow>
          <ReportSection title="Distribution" description="Backfilled appointments (created after start time) are excluded.">
            <Table rows={data.rows} />
          </ReportSection>
        </>
      ) : null}
    </ReportShell>
  );
}

function Table({ rows }: { rows: BookingLeadTimeRow[] }) {
  const columns: Column<BookingLeadTimeRow>[] = [
    { key: 'bucket', label: 'Lead', align: 'left', render: (r) => r.label },
    { key: 'count', label: 'Appointments', align: 'right', render: (r) => formatNumber(r.appointment_count) },
    {
      key: 'share',
      label: 'Share',
      align: 'right',
      className: 'font-medium',
      render: (r) => formatPct(r.share_pct),
    },
  ];
  return <ReportTable columns={columns} rows={rows} rowKey={(r) => r.bucket_id} />;
}
