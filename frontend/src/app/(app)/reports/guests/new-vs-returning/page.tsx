/**
 * `/reports/guests/new-vs-returning` — client acquisition + retention.
 *
 * For each customer with an appointment in the window, classifies as:
 *   - new       — first-ever appointment falls inside the window
 *   - returning — had an appointment before the window AND in it
 *
 * Cancellations + no-shows still count as visits for classification —
 * the question is whether the customer ever crossed the door, not
 * whether they showed up. (No-show rate is its own report — Session 2.)
 *
 * PHI tier: per_customer. The rows include client names. Today the
 * page renders them inline — the export-confirmation modal lands
 * Session 3 with CSV download.
 */

'use client';

import { ShieldCheck } from 'lucide-react';
import Link from 'next/link';
import { useState } from 'react';

import { formatNumber, useNewVsReturning } from '@/lib/reports';
import { cn } from '@/lib/utils';

import { defaultDateRange, type DateRange } from '../../_components/date-range-picker';
import {
  EmptyRow,
  ReportSection,
  ReportShell,
  SummaryTile,
  SummaryTileRow,
} from '../../_components/report-shell';

export default function NewVsReturningPage() {
  const [range, setRange] = useState<DateRange>(defaultDateRange);
  const { data, isLoading, error } = useNewVsReturning(range);

  return (
    <ReportShell
      title="New vs returning clients"
      description="Who walked in for the first time vs who came back. Appointment cancellations and no-shows still count as visits."
      phiTier="per_customer"
      dateRange={range}
      onDateRangeChange={setRange}
      isLoading={isLoading}
      error={error}
      exportPath="/api/reports/guests/new-vs-returning/"
    >
      {data ? (
        <>
          <SummaryTileRow>
            <SummaryTile
              label="New clients"
              value={formatNumber(data.summary.new_count)}
              hint="first-ever visit in the window"
            />
            <SummaryTile
              label="Returning clients"
              value={formatNumber(data.summary.returning_count)}
              hint="had visited before the window"
            />
            <SummaryTile
              label="Total unique"
              value={formatNumber(data.summary.total_unique_customers)}
            />
            <SummaryTile
              label="New share"
              value={
                data.summary.total_unique_customers
                  ? `${Math.round((data.summary.new_count / data.summary.total_unique_customers) * 100)}%`
                  : '—'
              }
            />
          </SummaryTileRow>

          <PhiNotice />

          <ReportSection
            title="Per-customer detail"
            description="New clients first, then returning. Click a name to open their profile."
          >
            {data.rows.length === 0 ? (
              <EmptyRow>No appointments in this window.</EmptyRow>
            ) : (
              <div className="border rounded-lg bg-card overflow-hidden">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-[11px] uppercase tracking-wide text-muted-foreground border-b bg-muted/20">
                      <th className="px-4 py-2 font-medium">Client</th>
                      <th className="px-4 py-2 font-medium">Type</th>
                      <th className="px-4 py-2 font-medium">First visit ever</th>
                      <th className="px-4 py-2 font-medium text-right">Visits in window</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y">
                    {data.rows.map((row) => (
                      <tr key={row.customer_id} className="hover:bg-muted/30 transition-colors">
                        <td className="px-4 py-2">
                          <Link
                            href={`/clients/${row.customer_id}`}
                            className="text-foreground hover:underline underline-offset-2"
                          >
                            {row.customer_name}
                          </Link>
                        </td>
                        <td className="px-4 py-2">
                          <ClassificationPill classification={row.classification} />
                        </td>
                        <td className="px-4 py-2 tabular-nums text-muted-foreground">
                          {formatDateLabel(row.first_appointment_date)}
                        </td>
                        <td className="px-4 py-2 tabular-nums text-right font-medium">
                          {formatNumber(row.appointments_in_range)}
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

function ClassificationPill({ classification }: { classification: 'new' | 'returning' }) {
  return (
    <span
      className={cn(
        'inline-flex items-center h-5 px-2 rounded text-[10px] uppercase tracking-wide font-medium',
        classification === 'new'
          ? 'bg-emerald-50 text-emerald-900 dark:bg-emerald-950 dark:text-emerald-100'
          : 'bg-muted text-muted-foreground',
      )}
    >
      {classification}
    </span>
  );
}

function PhiNotice() {
  return (
    <div className="flex items-start gap-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-100">
      <ShieldCheck className="size-4 shrink-0 mt-0.5" aria-hidden />
      <p>
        This report names individual clients (PHI). Treat the screen + any
        export accordingly. CSV export with explicit confirmation lands in a
        future session.
      </p>
    </div>
  );
}

function formatDateLabel(iso: string): string {
  const [y, m, d] = iso.split('-').map(Number);
  const date = new Date(y, m - 1, d);
  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}
