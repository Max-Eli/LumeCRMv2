/**
 * `/reports/financial/sales-by-date-range` — the workhorse Financial
 * report. Daily gross / tax / subtotal / invoice count over any
 * window, plus a payment-method breakdown.
 *
 * Source data: PAID invoices closed within the date range. Excludes
 * VOID and OPEN invoices (operator hasn't actually collected the
 * money on those yet). Money in cents on the wire; formatted as USD
 * for display.
 */

'use client';

import { useState } from 'react';

import { formatCents, formatNumber, useSalesByDateRange } from '@/lib/reports';

import { defaultDateRange, type DateRange } from '../../_components/date-range-picker';
import {
  EmptyRow,
  ReportSection,
  ReportShell,
  SummaryTile,
  SummaryTileRow,
} from '../../_components/report-shell';

export default function SalesByDateRangePage() {
  const [range, setRange] = useState<DateRange>(defaultDateRange);
  const { data, isLoading, error } = useSalesByDateRange(range);

  return (
    <ReportShell
      title="Sales by date range"
      description="Daily gross, tax, and net totals across PAID invoices. Voids and unpaid invoices are excluded."
      phiTier="none"
      dateRange={range}
      onDateRangeChange={setRange}
      isLoading={isLoading}
      error={error}
      exportPath="/api/reports/financial/sales-by-date-range/"
    >
      {data ? (
        <>
          <SummaryTileRow>
            <SummaryTile
              label="Gross sales"
              value={formatCents(data.summary.total_gross_cents)}
              hint={`${formatNumber(data.summary.paid_invoice_count)} paid invoice${data.summary.paid_invoice_count === 1 ? '' : 's'}`}
            />
            <SummaryTile
              label="Subtotal"
              value={formatCents(data.summary.total_subtotal_cents)}
              hint="before tax"
            />
            <SummaryTile
              label="Tax collected"
              value={formatCents(data.summary.total_tax_cents)}
            />
            <SummaryTile
              label="Avg invoice"
              value={formatCents(data.summary.avg_invoice_cents)}
            />
          </SummaryTileRow>

          <ReportSection
            title="Daily breakdown"
            description="One row per day in the range. Days with no sales appear as zeros."
          >
            {data.rows.length === 0 ? (
              <EmptyRow>No sales in this window.</EmptyRow>
            ) : (
              <div className="border rounded-lg bg-card overflow-hidden">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-[11px] uppercase tracking-wide text-muted-foreground border-b bg-muted/20">
                      <th className="px-4 py-2 font-medium">Date</th>
                      <th className="px-4 py-2 font-medium text-right">Invoices</th>
                      <th className="px-4 py-2 font-medium text-right">Subtotal</th>
                      <th className="px-4 py-2 font-medium text-right">Tax</th>
                      <th className="px-4 py-2 font-medium text-right">Gross</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y">
                    {data.rows.map((row) => (
                      <tr key={row.date} className="hover:bg-muted/30 transition-colors">
                        <td className="px-4 py-2 tabular-nums text-foreground">
                          {formatDateLabel(row.date)}
                        </td>
                        <td className="px-4 py-2 tabular-nums text-right text-muted-foreground">
                          {formatNumber(row.invoice_count)}
                        </td>
                        <td className="px-4 py-2 tabular-nums text-right text-muted-foreground">
                          {formatCents(row.subtotal_cents)}
                        </td>
                        <td className="px-4 py-2 tabular-nums text-right text-muted-foreground">
                          {formatCents(row.tax_cents)}
                        </td>
                        <td className="px-4 py-2 tabular-nums text-right font-medium">
                          {formatCents(row.gross_cents)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </ReportSection>

          <ReportSection
            title="By payment method"
            description="How customers paid across this window. Useful for cash-handling reconciliation."
          >
            {data.summary.by_payment_method.length === 0 ? (
              <EmptyRow>No payments in this window.</EmptyRow>
            ) : (
              <div className="border rounded-lg bg-card overflow-hidden">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-[11px] uppercase tracking-wide text-muted-foreground border-b bg-muted/20">
                      <th className="px-4 py-2 font-medium">Method</th>
                      <th className="px-4 py-2 font-medium text-right">Invoices</th>
                      <th className="px-4 py-2 font-medium text-right">Gross</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y">
                    {data.summary.by_payment_method.map((m) => (
                      <tr key={m.method} className="hover:bg-muted/30 transition-colors">
                        <td className="px-4 py-2 text-foreground">{m.method_label}</td>
                        <td className="px-4 py-2 tabular-nums text-right text-muted-foreground">
                          {formatNumber(m.invoice_count)}
                        </td>
                        <td className="px-4 py-2 tabular-nums text-right font-medium">
                          {formatCents(m.gross_cents)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </ReportSection>
        </>
      ) : null}
    </ReportShell>
  );
}

function formatDateLabel(iso: string): string {
  const [y, m, d] = iso.split('-').map(Number);
  const date = new Date(y, m - 1, d);
  return date.toLocaleDateString('en-US', {
    weekday: 'short',
    month: 'short',
    day: 'numeric',
  });
}
