/**
 * Forms pending panel.
 *
 * Reads from the forms-outstanding report and surfaces the clients
 * with the most pending consent forms. This is the front desk's
 * pre-arrival paperwork chase list — clients arriving today who
 * still need to sign before checkout.
 *
 * Front-desk's most useful dashboard feature on a busy morning.
 */

'use client';

import Link from 'next/link';

import {
  formatNumber,
  useFormsOutstanding,
  type FormsOutstandingRow,
} from '@/lib/reports';

const MAX_ROWS = 5;

export function FormsPendingPanel() {
  const { data, isLoading } = useFormsOutstanding();

  const rows = (data?.rows ?? []).slice(0, MAX_ROWS);
  const hiddenCount = Math.max((data?.rows.length ?? 0) - rows.length, 0);
  const totalPending = data?.summary.total_pending_forms ?? 0;
  const customerCount = data?.summary.customer_count ?? 0;

  return (
    <section className="rounded-lg border bg-card">
      <header className="flex items-center justify-between gap-4 border-b px-5 py-4">
        <div>
          <p className="text-[11px] uppercase tracking-wide text-muted-foreground/80 font-medium">
            Pending consent forms
          </p>
          <p className="mt-1 font-serif text-base font-medium text-foreground">
            {isLoading
              ? 'Loading…'
              : customerCount === 0
                ? 'All signed'
                : `${formatNumber(totalPending)} form${totalPending === 1 ? '' : 's'} · ${formatNumber(customerCount)} client${customerCount === 1 ? '' : 's'}`}
          </p>
        </div>
        <Link
          href="/reports/guests/forms-outstanding"
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
            <Row key={row.customer_id} row={row} />
          ))}
        </ul>
      )}

      {hiddenCount > 0 ? (
        <Link
          href="/reports/guests/forms-outstanding"
          className="block border-t px-5 py-3 text-xs font-medium text-muted-foreground hover:bg-muted/30 hover:text-foreground transition-colors"
        >
          + {hiddenCount} more in the report
        </Link>
      ) : null}
    </section>
  );
}

function Row({ row }: { row: FormsOutstandingRow }) {
  return (
    <li>
      <Link
        href={`/clients/${row.customer_id}`}
        className="grid grid-cols-[1fr_auto] items-baseline gap-3 px-5 py-3 transition-colors hover:bg-muted/30"
      >
        <div className="min-w-0">
          <p className="truncate text-sm font-medium text-foreground">{row.customer_name}</p>
          <p className="truncate text-xs text-muted-foreground">
            {row.customer_phone || row.customer_email || '—'}
          </p>
        </div>
        <span className="shrink-0 inline-flex items-center gap-1 rounded-full bg-amber-100 dark:bg-amber-950 px-2.5 py-0.5 text-[11px] font-medium tabular-nums text-amber-900 dark:text-amber-100">
          {formatNumber(row.pending_form_count)} pending
        </span>
      </Link>
    </li>
  );
}

function SkeletonRows() {
  return (
    <ul className="divide-y">
      {[...Array(3)].map((_, i) => (
        <li key={i} className="grid grid-cols-[1fr_auto] items-baseline gap-3 px-5 py-3">
          <div className="space-y-2">
            <div className="h-3 w-32 animate-pulse rounded bg-muted/60" />
            <div className="h-2.5 w-24 animate-pulse rounded bg-muted/40" />
          </div>
          <div className="h-5 w-16 animate-pulse rounded-full bg-muted/40" />
        </li>
      ))}
    </ul>
  );
}

function Empty() {
  return (
    <div className="px-5 py-10 text-center">
      <p className="text-sm text-muted-foreground">No pending consent forms.</p>
      <p className="mt-1 text-xs text-muted-foreground/75 italic">
        Every client has signed what they need.
      </p>
    </div>
  );
}
