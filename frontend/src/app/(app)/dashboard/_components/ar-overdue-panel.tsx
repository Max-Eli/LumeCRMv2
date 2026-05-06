/**
 * AR overdue panel.
 *
 * Pulls from the AR aging report and shows the oldest open invoices
 * — the front desk's chase list. Filtered to invoices over thirty
 * days old; "current" buckets (≤ 30 days) are normal billing flow
 * and don't need dashboard attention.
 *
 * The full AR aging report is one click away — this is a "what's
 * urgent" surface, not a complete view.
 */

'use client';

import Link from 'next/link';

import { formatCents, formatNumber, useARAging, type ARAgingRow } from '@/lib/reports';
import { cn } from '@/lib/utils';

const MAX_ROWS = 5;

const BUCKET_TONE: Record<string, string> = {
  '30_60': 'text-amber-700 dark:text-amber-400',
  '60_90': 'text-orange-700 dark:text-orange-400',
  over_90: 'text-rose-700 dark:text-rose-400',
};

const BUCKET_LABEL: Record<string, string> = {
  '30_60': '30-60d',
  '60_90': '60-90d',
  over_90: '90+d',
};

export function AROverduePanel() {
  const { data, isLoading } = useARAging();

  // Filter to "actually overdue" — drop the current bucket. Current
  // invoices haven't crossed the 30-day chase line yet.
  const overdueRows = (data?.rows ?? []).filter((r) => r.bucket !== 'current');
  const overdueTotal = overdueRows.reduce((s, r) => s + r.gross_cents, 0);
  const rows = overdueRows.slice(0, MAX_ROWS);
  const hiddenCount = Math.max(overdueRows.length - rows.length, 0);

  return (
    <section className="rounded-lg border bg-card">
      <header className="flex items-center justify-between gap-4 border-b px-5 py-4">
        <div>
          <p className="text-[11px] uppercase tracking-wide text-muted-foreground/80 font-medium">
            Overdue invoices
          </p>
          <p className="mt-1 font-serif text-base font-medium text-foreground">
            {isLoading
              ? 'Loading…'
              : overdueRows.length === 0
                ? 'All clear'
                : `${formatCents(overdueTotal)} across ${formatNumber(overdueRows.length)}`}
          </p>
        </div>
        <Link
          href="/reports/financial/ar-aging"
          className="text-xs font-medium uppercase tracking-[0.16em] text-foreground/70 hover:text-accent transition-colors"
        >
          Open report →
        </Link>
      </header>

      {isLoading ? (
        <SkeletonRows />
      ) : rows.length === 0 ? (
        <Empty />
      ) : (
        <ul className="divide-y">
          {rows.map((row) => (
            <Row key={row.invoice_id} row={row} />
          ))}
        </ul>
      )}

      {hiddenCount > 0 ? (
        <Link
          href="/reports/financial/ar-aging"
          className="block border-t px-5 py-3 text-xs font-medium text-muted-foreground hover:bg-muted/30 hover:text-foreground transition-colors"
        >
          + {hiddenCount} more in the report
        </Link>
      ) : null}
    </section>
  );
}

function Row({ row }: { row: ARAgingRow }) {
  const tone = BUCKET_TONE[row.bucket] ?? 'text-foreground/70';
  const label = BUCKET_LABEL[row.bucket] ?? `${row.age_days}d`;
  return (
    <li>
      <Link
        href={`/clients/${row.customer_id}`}
        className="grid grid-cols-[1fr_auto_auto] items-baseline gap-3 px-5 py-3 transition-colors hover:bg-muted/30"
      >
        <div className="min-w-0">
          <p className="truncate text-sm font-medium text-foreground">{row.customer_name}</p>
          <p className="truncate text-xs text-muted-foreground">
            Billed {row.created_date}
          </p>
        </div>
        <span className={cn('shrink-0 text-[11px] uppercase tracking-[0.14em]', tone)}>
          {label}
        </span>
        <span className="shrink-0 font-medium tabular-nums text-foreground">
          {formatCents(row.gross_cents)}
        </span>
      </Link>
    </li>
  );
}

function SkeletonRows() {
  return (
    <ul className="divide-y">
      {[...Array(3)].map((_, i) => (
        <li key={i} className="grid grid-cols-[1fr_auto_auto] items-baseline gap-3 px-5 py-3">
          <div className="space-y-2">
            <div className="h-3 w-32 animate-pulse rounded bg-muted/60" />
            <div className="h-2.5 w-24 animate-pulse rounded bg-muted/40" />
          </div>
          <div className="h-2.5 w-12 animate-pulse rounded bg-muted/40" />
          <div className="h-3 w-16 animate-pulse rounded bg-muted/60" />
        </li>
      ))}
    </ul>
  );
}

function Empty() {
  return (
    <div className="px-5 py-10 text-center">
      <p className="text-sm text-muted-foreground">No overdue invoices.</p>
      <p className="mt-1 text-xs text-muted-foreground/75 italic">
        Anything older than 30 days appears here.
      </p>
    </div>
  );
}
