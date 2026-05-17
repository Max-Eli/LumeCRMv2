'use client';

import { useState } from 'react';

import {
  type RevenueByAcquisitionSourceRow,
  formatCents,
  formatNumber,
  useRevenueByAcquisitionSource,
} from '@/lib/reports';

import { defaultDateRange, type DateRange } from '../../_components/date-range-picker';
import {
  ReportSection,
  ReportShell,
  SummaryTile,
  SummaryTileRow,
} from '../../_components/report-shell';
import { ReportTable, type Column } from '../../_components/report-table';

export default function RevenueByAcquisitionSourcePage() {
  const [range, setRange] = useState<DateRange>(defaultDateRange);
  const { data, isLoading, error } = useRevenueByAcquisitionSource(range);

  return (
    <ReportShell
      title="Revenue by acquisition source"
      description="Per-channel gross + average ticket + customer count. Use it alongside Bookings by acquisition source to see which channels actually convert to spend, not just bookings."
      phiTier="aggregated"
      dateRange={range}
      onDateRangeChange={setRange}
      isLoading={isLoading}
      error={error}
      exportPath="/api/reports/financial/revenue-by-acquisition-source/"
    >
      {data ? (
        <>
          <SummaryTileRow>
            <SummaryTile
              label="Total revenue"
              value={formatCents(data.summary.total_gross_cents)}
            />
            <SummaryTile
              label="Paid invoices"
              value={formatNumber(data.summary.total_invoices)}
            />
            <SummaryTile
              label="Distinct channels"
              value={formatNumber(data.summary.distinct_sources)}
            />
          </SummaryTileRow>
          <ReportSection
            title="Per-channel breakdown"
            description="Acquisition source is captured at customer-create time and immutable thereafter — historical changes don't affect this report."
          >
            <Table rows={data.rows} />
          </ReportSection>
        </>
      ) : null}
    </ReportShell>
  );
}

function Table({ rows }: { rows: RevenueByAcquisitionSourceRow[] }) {
  const columns: Column<RevenueByAcquisitionSourceRow>[] = [
    {
      key: 'source',
      label: 'Channel',
      align: 'left',
      render: (r) => r.acquisition_source_label,
    },
    {
      key: 'gross',
      label: 'Gross revenue',
      align: 'right',
      className: 'font-medium',
      render: (r) => formatCents(r.gross_cents),
    },
    {
      key: 'invoices',
      label: 'Invoices',
      align: 'right',
      render: (r) => formatNumber(r.invoice_count),
    },
    {
      key: 'customers',
      label: 'Customers',
      align: 'right',
      render: (r) => formatNumber(r.customer_count),
    },
    {
      key: 'avg',
      label: 'Avg ticket',
      align: 'right',
      render: (r) => formatCents(r.avg_ticket_cents),
    },
  ];
  return <ReportTable columns={columns} rows={rows} rowKey={(r) => r.acquisition_source} />;
}
