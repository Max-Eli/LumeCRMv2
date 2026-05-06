'use client';

import { useState } from 'react';

import {
  type RevenueByServiceRow,
  formatCents,
  formatNumber,
  useRevenueByService,
} from '@/lib/reports';

import { defaultDateRange, type DateRange } from '../../_components/date-range-picker';
import {
  ReportSection,
  ReportShell,
  SummaryTile,
  SummaryTileRow,
} from '../../_components/report-shell';
import { ReportTable, type Column } from '../../_components/report-table';

export default function RevenueByServicePage() {
  const [range, setRange] = useState<DateRange>(defaultDateRange);
  const { data, isLoading, error } = useRevenueByService(range);

  return (
    <ReportShell
      title="Revenue by service"
      description="Which services bring in the most money. Sums PAID invoice line items by service over the window."
      phiTier="none"
      dateRange={range}
      onDateRangeChange={setRange}
      isLoading={isLoading}
      error={error}
      exportPath="/api/reports/financial/revenue-by-service/"
    >
      {data ? (
        <>
          <SummaryTileRow>
            <SummaryTile label="Total revenue" value={formatCents(data.summary.total_gross_cents)} />
            <SummaryTile label="Units sold" value={formatNumber(data.summary.total_units)} />
            <SummaryTile label="Distinct services" value={formatNumber(data.summary.service_count)} />
            <SummaryTile label="Avg per service" value={formatCents(data.summary.avg_revenue_per_service_cents)} />
          </SummaryTileRow>
          <ReportSection title="Per-service breakdown" description="Ranked by gross. Standalone retail / fees aren't service-attributed and are omitted.">
            <Table rows={data.rows} />
          </ReportSection>
        </>
      ) : null}
    </ReportShell>
  );
}

function Table({ rows }: { rows: RevenueByServiceRow[] }) {
  const columns: Column<RevenueByServiceRow>[] = [
    { key: 'service', label: 'Service', align: 'left', render: (r) => r.service_name },
    { key: 'units', label: 'Units', align: 'right', render: (r) => formatNumber(r.unit_count) },
    { key: 'tax', label: 'Tax', align: 'right', render: (r) => formatCents(r.tax_cents) },
    {
      key: 'gross',
      label: 'Gross',
      align: 'right',
      className: 'font-medium',
      render: (r) => formatCents(r.gross_cents),
    },
  ];
  return <ReportTable columns={columns} rows={rows} rowKey={(r) => r.service_id} />;
}
