'use client';

import { useState } from 'react';

import {
  type RevenueByLocationRow,
  formatCents,
  formatNumber,
  useRevenueByLocation,
} from '@/lib/reports';

import { defaultDateRange, type DateRange } from '../../_components/date-range-picker';
import {
  ReportSection,
  ReportShell,
  SummaryTile,
  SummaryTileRow,
} from '../../_components/report-shell';
import { ReportTable, type Column } from '../../_components/report-table';

export default function RevenueByLocationPage() {
  const [range, setRange] = useState<DateRange>(defaultDateRange);
  const { data, isLoading, error } = useRevenueByLocation(range);

  return (
    <ReportShell
      title="Revenue by location"
      description="Per-location gross + paid-appointment count. Useful when a tenant runs more than one site."
      phiTier="none"
      dateRange={range}
      onDateRangeChange={setRange}
      isLoading={isLoading}
      error={error}
      exportPath="/api/reports/financial/revenue-by-location/"
    >
      {data ? (
        <>
          <SummaryTileRow>
            <SummaryTile label="Total revenue" value={formatCents(data.summary.total_gross_cents)} />
            <SummaryTile label="Paid appointments" value={formatNumber(data.summary.total_appointments)} />
            <SummaryTile label="Locations" value={formatNumber(data.summary.location_count)} />
          </SummaryTileRow>
          <ReportSection title="Per-location breakdown" description="Standalone (no-appointment) invoices have no location and are omitted.">
            <Table rows={data.rows} />
          </ReportSection>
        </>
      ) : null}
    </ReportShell>
  );
}

function Table({ rows }: { rows: RevenueByLocationRow[] }) {
  const columns: Column<RevenueByLocationRow>[] = [
    { key: 'name', label: 'Location', align: 'left', render: (r) => r.location_name },
    { key: 'appts', label: 'Appointments', align: 'right', render: (r) => formatNumber(r.appointment_count) },
    {
      key: 'gross',
      label: 'Gross',
      align: 'right',
      className: 'font-medium',
      render: (r) => formatCents(r.gross_cents),
    },
  ];
  return <ReportTable columns={columns} rows={rows} rowKey={(r) => r.location_id} />;
}
