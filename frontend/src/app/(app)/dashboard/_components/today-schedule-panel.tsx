/**
 * Today's schedule panel.
 *
 * Lists the next several appointments in chronological order. Each
 * row shows time, client name, service, provider, and the current
 * status (booked / confirmed / checked_in / completed / etc.).
 * Future appointments rank higher than already-completed ones —
 * the operator's eye is looking for "what's coming up next."
 *
 * Reads from /api/appointments/?date=today via the existing
 * `useAppointmentsForDate` hook, so the data is the same the
 * calendar shows. No duplicate query layer.
 */

'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';

import { type Appointment, useAppointmentsForDate } from '@/lib/appointments';
import { toIsoDate } from '@/lib/reports';
import { cn } from '@/lib/utils';

const MAX_ROWS = 6;

const STATUS_TONE: Record<string, string> = {
  booked: 'text-foreground/70',
  confirmed: 'text-emerald-700 dark:text-emerald-400',
  checked_in: 'text-amber-700 dark:text-amber-400',
  completed: 'text-muted-foreground',
  no_show: 'text-rose-700 dark:text-rose-400',
  cancelled: 'text-muted-foreground line-through',
};

const STATUS_LABEL: Record<string, string> = {
  booked: 'Booked',
  confirmed: 'Confirmed',
  checked_in: 'Checked in',
  completed: 'Completed',
  no_show: 'No-show',
  cancelled: 'Cancelled',
};

export function TodaySchedulePanel() {
  // Stable today-string (initialized client-side so SSR hydration matches).
  const [today, setToday] = useState<string | undefined>(undefined);
  useEffect(() => {
    setToday(toIsoDate(new Date()));
  }, []);
  const { data, isLoading } = useAppointmentsForDate(today);

  const sorted = sortForDashboard(data ?? []);
  const rows = sorted.slice(0, MAX_ROWS);
  const hiddenCount = Math.max(sorted.length - rows.length, 0);

  return (
    <section className="rounded-lg border bg-card">
      <header className="flex items-center justify-between gap-4 border-b px-5 py-4">
        <div>
          <p className="text-[11px] uppercase tracking-wide text-muted-foreground/80 font-medium">
            Today's schedule
          </p>
          <p className="mt-1 font-serif text-base font-medium text-foreground">
            {isLoading ? 'Loading…' : `${data?.length ?? 0} appointment${data?.length === 1 ? '' : 's'}`}
          </p>
        </div>
        <Link
          href="/calendar"
          className="text-xs font-medium uppercase tracking-[0.16em] text-foreground/70 hover:text-accent transition-colors"
        >
          Open calendar →
        </Link>
      </header>

      {isLoading ? (
        <SkeletonRows />
      ) : rows.length === 0 ? (
        <Empty />
      ) : (
        <ul className="divide-y">
          {rows.map((appt) => (
            <Row key={appt.id} appt={appt} />
          ))}
        </ul>
      )}

      {hiddenCount > 0 ? (
        <Link
          href="/calendar"
          className="block border-t px-5 py-3 text-xs font-medium text-muted-foreground hover:bg-muted/30 hover:text-foreground transition-colors"
        >
          + {hiddenCount} more on the calendar
        </Link>
      ) : null}
    </section>
  );
}

function Row({ appt }: { appt: Appointment }) {
  const start = new Date(appt.start_time);
  const time = start.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
  const tone = STATUS_TONE[appt.status] ?? 'text-foreground';
  const label = STATUS_LABEL[appt.status] ?? appt.status;

  return (
    <li>
      <Link
        href={`/clients/${appt.customer.id}`}
        className="grid grid-cols-[60px_1fr_auto] items-baseline gap-3 px-5 py-3 transition-colors hover:bg-muted/30"
      >
        <span className="font-mono text-xs tabular-nums text-foreground/60">{time}</span>
        <div className="min-w-0">
          <p className={cn('truncate text-sm font-medium', appt.status === 'cancelled' ? 'line-through text-muted-foreground' : 'text-foreground')}>
            {appt.customer.full_name}
          </p>
          <p className="truncate text-xs text-muted-foreground">
            {appt.service.name} · {composeProviderName(appt.provider)}
          </p>
        </div>
        <span className={cn('shrink-0 text-[11px] uppercase tracking-[0.14em]', tone)}>
          {label}
        </span>
      </Link>
    </li>
  );
}

function SkeletonRows() {
  return (
    <ul className="divide-y">
      {[...Array(4)].map((_, i) => (
        <li key={i} className="grid grid-cols-[60px_1fr_auto] items-baseline gap-3 px-5 py-3">
          <div className="h-3 w-12 animate-pulse rounded bg-muted/60" />
          <div className="space-y-2">
            <div className="h-3 w-32 animate-pulse rounded bg-muted/60" />
            <div className="h-2.5 w-24 animate-pulse rounded bg-muted/40" />
          </div>
          <div className="h-2.5 w-16 animate-pulse rounded bg-muted/40" />
        </li>
      ))}
    </ul>
  );
}

function Empty() {
  return (
    <div className="px-5 py-10 text-center">
      <p className="text-sm text-muted-foreground">No appointments today.</p>
    </div>
  );
}

// Sort: future / in-progress first, then completed at the end.
function sortForDashboard(appts: Appointment[]): Appointment[] {
  const order: Record<string, number> = {
    checked_in: 0,
    confirmed: 1,
    booked: 1,
    completed: 2,
    no_show: 3,
    cancelled: 4,
  };
  return [...appts].sort((a, b) => {
    const oa = order[a.status] ?? 99;
    const ob = order[b.status] ?? 99;
    if (oa !== ob) return oa - ob;
    return new Date(a.start_time).getTime() - new Date(b.start_time).getTime();
  });
}

function composeProviderName(p: Appointment['provider']): string {
  const full = `${p.user_first_name || ''} ${p.user_last_name || ''}`.trim();
  return full || p.user_email;
}
