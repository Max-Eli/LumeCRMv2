'use client';

import { useState } from 'react';

import {
  type TaxCollectedRow,
  formatCents,
  formatNumber,
  formatPct,
  useTaxCollected,
} from '@/lib/reports';

import { defaultDateRange, type DateRange } from '../../_components/date-range-picker';
import {
  ReportSection,
  ReportShell,
  SummaryTile,
  SummaryTileRow,
} from '../../_components/report-shell';
import { ReportTable, type Column } from '../../_components/report-table';

export default function TaxCollectedPage() {
  const [range, setRange] = useState<DateRange>(defaultDateRange);
  const { data, isLoading, error } = useTaxCollected(range);

  return (
    <ReportShell
      title="Tax collected"
      description="Sales tax collected on PAID invoices in the window, with a per-rate breakdown for filing prep."
      phiTier="none"
      dateRange={range}
      onDateRangeChange={setRange}
      isLoading={isLoading}
      error={error}
      exportPath="/api/reports/financial/tax-collected/"
    >
      {data ? (
        <>
          <SummaryTileRow>
            <SummaryTile label="Total tax" value={formatCents(data.summary.total_tax_cents)} />
            <SummaryTile label="Taxable subtotal" value={formatCents(data.summary.total_taxable_subtotal_cents)} />
            <SummaryTile label="Effective rate" value={formatPct(data.summary.effective_rate_percent, 3)} />
            <SummaryTile label="Distinct rates" value={formatNumber(data.summary.rate_count)} />
          </SummaryTileRow>
          <ReportSection title="Per-rate breakdown" description="Each row is the line items at that rate, summed across the window.">
            <Table rows={data.rows} />
          </ReportSection>
        </>
      ) : null}
    </ReportShell>
  );
}

function Table({ rows }: { rows: TaxCollectedRow[] }) {
  const columns: Column<TaxCollectedRow>[] = [
    { key: 'rate', label: 'Rate', align: 'left', render: (r) => `${r.tax_rate_percent}%` },
    { key: 'lines', label: 'Lines', align: 'right', render: (r) => formatNumber(r.line_count) },
    { key: 'subtotal', label: 'Taxable subtotal', align: 'right', render: (r) => formatCents(r.taxable_subtotal_cents) },
    {
      key: 'tax',
      label: 'Tax collected',
      align: 'right',
      className: 'font-medium',
      render: (r) => formatCents(r.tax_cents),
    },
  ];
  return <ReportTable columns={columns} rows={rows} rowKey={(r) => r.tax_rate_percent} />;
}
