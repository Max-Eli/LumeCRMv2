/**
 * Hero revenue chart panel for the dashboard.
 *
 * Shows last-30-days gross revenue as an SVG sparkline with weekend
 * bands. The headline above the chart is the total + delta vs. the
 * previous 30-day window — so the operator gets the bottom-line at
 * a glance and the trend underneath.
 *
 * Hits the existing financial.sales-by-date-range report (no new
 * endpoint). Tanstack-query caches it for 5 minutes.
 */

'use client';

import Link from 'next/link';

import { formatCents, formatNumber, useSalesByDateRange } from '@/lib/reports';

import { last30DaysWindow, deltaPct } from './date-windows';
import { DeltaArrow } from './delta-arrow';
import { Sparkline } from './sparkline';

// Helpers — keep date math out of the component body.
function previous30DaysWindow() {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const startThis = new Date(today);
  startThis.setDate(startThis.getDate() - 29);
  const endPrev = new Date(startThis);
  endPrev.setDate(endPrev.getDate() - 1);
  const startPrev = new Date(endPrev);
  startPrev.setDate(startPrev.getDate() - 29);
  const fmt = (d: Date) =>
    `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  return { date_from: fmt(startPrev), date_to: fmt(endPrev) };
}

export function RevenueChartPanel() {
  const last30 = useSalesByDateRange(last30DaysWindow());
  const prev30 = useSalesByDateRange(previous30DaysWindow());

  const loading = last30.isLoading || prev30.isLoading;
  const total = last30.data?.summary.total_gross_cents ?? 0;
  const prevTotal = prev30.data?.summary.total_gross_cents ?? 0;
  const pct = last30.data && prev30.data ? deltaPct(total, prevTotal) : null;
  const invoiceCount = last30.data?.summary.paid_invoice_count ?? 0;

  const points = (last30.data?.rows ?? []).map((r) => ({
    date: r.date,
    value: r.gross_cents,
  }));

  return (
    <section className="rounded-lg border bg-card">
      <header className="flex flex-wrap items-end justify-between gap-4 border-b px-5 py-4">
        <div>
          <p className="text-[11px] uppercase tracking-wide text-muted-foreground/80 font-medium">
            Revenue · Last 30 days
          </p>
          {loading ? (
            <div className="mt-2 h-9 w-40 animate-pulse rounded bg-muted/60" />
          ) : (
            <div className="mt-1 flex items-baseline gap-3">
              <p className="font-serif text-3xl font-medium tracking-tight tabular-nums text-foreground sm:text-4xl">
                {formatCents(total)}
              </p>
              <DeltaArrow
                pct={pct}
                tone={pct !== null && pct >= 0 ? 'positive' : 'negative'}
                hint="vs. previous 30 days"
              />
            </div>
          )}
          <p className="mt-1 text-xs text-muted-foreground">
            {loading
              ? 'Loading…'
              : invoiceCount === 0
                ? 'No paid invoices in this window'
                : `${formatNumber(invoiceCount)} paid invoice${invoiceCount === 1 ? '' : 's'} · weekend days subtly shaded`}
          </p>
        </div>
        <Link
          href="/reports/financial/sales-by-date-range"
          className="text-xs font-medium uppercase tracking-[0.16em] text-foreground/70 hover:text-accent transition-colors"
        >
          Open report →
        </Link>
      </header>
      <div className="px-5 py-5">
        <Sparkline
          data={points}
          height={200}
          formatTitle={(p) =>
            `${p.date}: ${formatCents(p.value)}`
          }
        />
      </div>
    </section>
  );
}
