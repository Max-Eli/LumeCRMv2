'use client';

import { useState } from 'react';

import { type DailyCloseOutRow, formatCents, formatNumber, useDailyCloseOut } from '@/lib/reports';

import { defaultDateRange, type DateRange } from '../../_components/date-range-picker';
import {
  ReportSection,
  ReportShell,
  SummaryTile,
  SummaryTileRow,
} from '../../_components/report-shell';
import { ReportTable, type Column } from '../../_components/report-table';

export default function DailyCloseOutPage() {
  const [range, setRange] = useState<DateRange>(defaultDateRange);
  const { data, isLoading, error } = useDailyCloseOut(range);

  return (
    <ReportShell
      title="Daily close-out"
      description="End-of-day reconciliation: gross + per-payment-method totals per day. Match against the cash drawer + card terminal."
      phiTier="none"
      dateRange={range}
      onDateRangeChange={setRange}
      isLoading={isLoading}
      error={error}
      exportPath="/api/reports/financial/daily-close-out/"
    >
      {data ? (
        <>
          <SummaryTileRow>
            <SummaryTile label="Gross sales" value={formatCents(data.summary.total_gross_cents)} />
            <SummaryTile label="Tax collected" value={formatCents(data.summary.total_tax_cents)} />
            <SummaryTile label="Paid invoices" value={formatNumber(data.summary.paid_invoice_count)} />
          </SummaryTileRow>
          <ReportSection title="Per-day reconciliation" description="Gross + per-payment-method breakdown for each day in the range.">
            <DailyTable
              rows={data.rows}
              methodKeys={data.summary.method_keys}
              methodLabels={data.summary.method_labels}
            />
          </ReportSection>
        </>
      ) : null}
    </ReportShell>
  );
}

function DailyTable({
  rows,
  methodKeys,
  methodLabels,
}: {
  rows: DailyCloseOutRow[];
  methodKeys: string[];
  methodLabels: Record<string, string>;
}) {
  const dynamicColumns: Column<DailyCloseOutRow>[] = methodKeys.map((m) => ({
    key: `method_${m}`,
    label: methodLabels[m] ?? m,
    align: 'right',
    render: (r) => formatCents(r.by_method[m] ?? 0),
  }));
  const columns: Column<DailyCloseOutRow>[] = [
    { key: 'date', label: 'Date', align: 'left', render: (r) => formatDateLabel(r.date) },
    { key: 'count', label: 'Invoices', align: 'right', render: (r) => formatNumber(r.invoice_count) },
    ...dynamicColumns,
    { key: 'tax', label: 'Tax', align: 'right', render: (r) => formatCents(r.tax_cents) },
    {
      key: 'gross',
      label: 'Gross',
      align: 'right',
      className: 'font-medium',
      render: (r) => formatCents(r.gross_cents),
    },
  ];
  return <ReportTable columns={columns} rows={rows} rowKey={(r) => r.date} />;
}

function formatDateLabel(iso: string): string {
  const [y, m, d] = iso.split('-').map(Number);
  return new Date(y, m - 1, d).toLocaleDateString('en-US', {
    weekday: 'short',
    month: 'short',
    day: 'numeric',
  });
}
