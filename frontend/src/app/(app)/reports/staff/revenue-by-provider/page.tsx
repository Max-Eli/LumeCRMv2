/**
 * `/reports/staff/revenue-by-provider` — provider productivity.
 * Gross revenue + paid-appointment count per provider over the
 * window, ranked highest-first.
 *
 * Source: PAID invoices joined to their appointment's provider.
 * Standalone (POS / package) invoices have no provider attribution
 * and are omitted — they'll get their own report when Phase 2A POS
 * lands.
 */

'use client';

import { useState } from 'react';

import { InitialsAvatar } from '@/components/initials-avatar';
import { formatCents, formatNumber, useRevenueByProvider } from '@/lib/reports';

import { defaultDateRange, type DateRange } from '../../_components/date-range-picker';
import {
  EmptyRow,
  ReportSection,
  ReportShell,
  SummaryTile,
  SummaryTileRow,
} from '../../_components/report-shell';

export default function RevenueByProviderPage() {
  const [range, setRange] = useState<DateRange>(defaultDateRange);
  const { data, isLoading, error } = useRevenueByProvider(range);

  return (
    <ReportShell
      title="Revenue by provider"
      description="Which providers brought in the most revenue, and from how many appointments. Counts only PAID invoices in the window."
      phiTier="aggregated"
      dateRange={range}
      onDateRangeChange={setRange}
      isLoading={isLoading}
      error={error}
      exportPath="/api/reports/staff/revenue-by-provider/"
    >
      {data ? (
        <>
          <SummaryTileRow>
            <SummaryTile
              label="Total revenue"
              value={formatCents(data.summary.total_gross_cents)}
              hint={`across ${formatNumber(data.summary.provider_count)} provider${data.summary.provider_count === 1 ? '' : 's'}`}
            />
            <SummaryTile
              label="Paid appointments"
              value={formatNumber(data.summary.total_appointments)}
            />
            <SummaryTile
              label="Avg per provider"
              value={formatCents(data.summary.avg_revenue_per_provider_cents)}
            />
            <SummaryTile
              label="Top provider"
              value={data.rows[0] ? formatCents(data.rows[0].gross_cents) : '—'}
              hint={data.rows[0]?.provider_name}
            />
          </SummaryTileRow>

          <ReportSection
            title="Per-provider breakdown"
            description="Ranked by gross revenue. Providers with no paid invoices in the window are omitted."
          >
            {data.rows.length === 0 ? (
              <EmptyRow>No provider revenue in this window.</EmptyRow>
            ) : (
              <div className="border rounded-lg bg-card overflow-hidden">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-[11px] uppercase tracking-wide text-muted-foreground border-b bg-muted/20">
                      <th className="px-4 py-2 font-medium">Provider</th>
                      <th className="px-4 py-2 font-medium text-right">Appointments</th>
                      <th className="px-4 py-2 font-medium text-right">Avg ticket</th>
                      <th className="px-4 py-2 font-medium text-right">Gross</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y">
                    {data.rows.map((row) => {
                      const avgTicket = row.appointment_count
                        ? row.gross_cents / row.appointment_count
                        : 0;
                      return (
                        <tr key={row.provider_id} className="hover:bg-muted/30 transition-colors">
                          <td className="px-4 py-2">
                            <div className="flex items-center gap-2.5">
                              <InitialsAvatar name={row.provider_name} size="sm" />
                              <span className="text-foreground">{row.provider_name}</span>
                            </div>
                          </td>
                          <td className="px-4 py-2 tabular-nums text-right text-muted-foreground">
                            {formatNumber(row.appointment_count)}
                          </td>
                          <td className="px-4 py-2 tabular-nums text-right text-muted-foreground">
                            {formatCents(Math.round(avgTicket))}
                          </td>
                          <td className="px-4 py-2 tabular-nums text-right font-medium">
                            {formatCents(row.gross_cents)}
                          </td>
                        </tr>
                      );
                    })}
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
