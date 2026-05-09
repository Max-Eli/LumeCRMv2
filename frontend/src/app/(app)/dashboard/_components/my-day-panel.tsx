/**
 * Provider-only "My day" panel — replaces the generic schedule panel
 * when the dashboard is rendered for someone with role=provider.
 *
 * Mobile-first because providers walk between rooms with their phone.
 * Combines three things they actually look at:
 *   1. Are they on the clock right now? (with one-tap clock-in/out)
 *   2. Their appointments today, filtered to themselves only
 *   3. A footer link to their MTD commissions
 *
 * Filters today's appointments by matching the session user's email
 * against `Appointment.provider.user_email` — the provider summary
 * embedded in every appointment payload. Keeps this panel
 * self-contained without a new API endpoint.
 */

'use client';

import {
  ArrowRight,
  Clock,
  Loader2,
  LogIn,
  LogOut,
} from 'lucide-react';
import Link from 'next/link';
import { useEffect, useState } from 'react';
import { toast } from 'sonner';

import { ApiError } from '@/lib/api';
import { useUser } from '@/lib/auth';
import { type Appointment, useAppointmentsForDate } from '@/lib/appointments';
import { toIsoDate } from '@/lib/reports';
import {
  elapsedSeconds,
  formatDuration,
  useClockIn,
  useClockOut,
  useMyTimeState,
} from '@/lib/timetracking';
import { cn } from '@/lib/utils';

const STATUS_TONE: Record<string, string> = {
  booked: 'text-foreground/70',
  confirmed: 'text-emerald-700',
  checked_in: 'text-amber-700',
  completed: 'text-muted-foreground',
  no_show: 'text-rose-700',
  cancelled: 'text-muted-foreground line-through',
};

const STATUS_LABEL: Record<string, string> = {
  booked: 'Booked',
  confirmed: 'Confirmed',
  checked_in: 'Checked in',
  completed: 'Done',
  no_show: 'No-show',
  cancelled: 'Cancelled',
};

export function MyDayPanel() {
  const { data: user } = useUser();
  const myState = useMyTimeState();
  const clockIn = useClockIn();
  const clockOut = useClockOut();

  // Today as ISO. Lazy useState init keeps `new Date()` out of render
  // (React Compiler purity rule) without a setState-in-effect dance.
  // The `useAppointmentsForDate` query only fires client-side anyway,
  // so any hydration-time date drift is invisible to the user.
  const [today] = useState<string>(() => toIsoDate(new Date()));
  const { data: appts, isLoading: apptsLoading } = useAppointmentsForDate(today);

  // Live elapsed counter ticks once a second when clocked in. Pure
  // cosmetic; data layer doesn't refetch.
  const [now, setNow] = useState<number>(() => Date.now());
  useEffect(() => {
    if (!myState.data?.open_entry) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [myState.data?.open_entry]);

  const myAppts = (appts ?? []).filter(
    (a) => a.provider.user_email === user?.email,
  );

  const onClockIn = () => {
    clockIn.mutate(
      {},
      {
        onSuccess: () => toast.success("You're clocked in"),
        onError: (err) => toastApiError(err, "Couldn't clock in."),
      },
    );
  };
  const onClockOut = () => {
    clockOut.mutate(
      {},
      {
        onSuccess: () => toast.success("You're clocked out"),
        onError: (err) => toastApiError(err, "Couldn't clock out."),
      },
    );
  };

  const openEntry = myState.data?.open_entry ?? null;
  const isLoadingState = myState.isLoading;

  return (
    <section className="rounded-2xl border bg-card overflow-hidden">
      {/* Clock-in hero */}
      {isLoadingState ? (
        <div className="px-5 py-8 sm:py-10 text-center text-sm text-muted-foreground">
          <Loader2 className="size-5 animate-spin mx-auto mb-2" />
          Loading…
        </div>
      ) : openEntry ? (
        <div className="bg-emerald-50/60 px-5 py-6 sm:px-7 sm:py-7">
          <div className="flex items-center justify-between gap-4 flex-wrap">
            <div>
              <p className="inline-flex items-center gap-2 text-emerald-800 text-[11px] uppercase tracking-[0.18em] font-medium">
                <span className="size-2 rounded-full bg-emerald-500 animate-pulse" />
                On the clock
              </p>
              <p className="font-mono text-3xl sm:text-4xl font-semibold tabular-nums tracking-tight text-emerald-900 mt-1.5">
                {formatDuration(elapsedSeconds(openEntry, now))}
              </p>
              <p className="text-xs text-emerald-800/80 mt-1">
                since{' '}
                {new Date(openEntry.clock_in_at).toLocaleTimeString(undefined, {
                  hour: 'numeric',
                  minute: '2-digit',
                })}
              </p>
            </div>
            <button
              type="button"
              onClick={onClockOut}
              disabled={clockOut.isPending}
              className={cn(
                'inline-flex items-center justify-center gap-1.5',
                'h-12 px-5 rounded-xl bg-foreground text-background',
                'text-sm font-medium hover:bg-foreground/90',
                'transition-colors disabled:opacity-60',
              )}
            >
              {clockOut.isPending ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <LogOut className="size-4" />
              )}
              Clock out
            </button>
          </div>
        </div>
      ) : (
        <div className="bg-muted/30 px-5 py-6 sm:px-7 sm:py-7">
          <div className="flex items-center justify-between gap-4 flex-wrap">
            <div>
              <p className="inline-flex items-center gap-2 text-muted-foreground text-[11px] uppercase tracking-[0.18em] font-medium">
                <Clock className="size-3.5" />
                Off the clock
              </p>
              <p className="font-serif text-2xl sm:text-3xl font-medium tracking-tight mt-1.5">
                Ready when you are.
              </p>
            </div>
            <button
              type="button"
              onClick={onClockIn}
              disabled={clockIn.isPending}
              className={cn(
                'inline-flex items-center justify-center gap-1.5',
                'h-12 px-5 rounded-xl bg-emerald-600 text-white',
                'text-sm font-medium hover:bg-emerald-700',
                'transition-colors disabled:opacity-60',
              )}
            >
              {clockIn.isPending ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <LogIn className="size-4" />
              )}
              Clock in
            </button>
          </div>
        </div>
      )}

      {/* Today's appointments */}
      <header className="flex items-center justify-between gap-4 border-t px-5 py-4">
        <div>
          <p className="text-[11px] uppercase tracking-wide text-muted-foreground/80 font-medium">
            Your appointments today
          </p>
          <p className="mt-1 font-serif text-base font-medium">
            {apptsLoading
              ? 'Loading…'
              : `${myAppts.length} appointment${myAppts.length === 1 ? '' : 's'}`}
          </p>
        </div>
        <Link
          href="/calendar"
          className="text-xs font-medium uppercase tracking-[0.16em] text-foreground/70 hover:text-accent transition-colors"
        >
          Calendar →
        </Link>
      </header>

      {apptsLoading ? (
        <SkeletonRows />
      ) : myAppts.length === 0 ? (
        <div className="px-5 py-8 text-center text-sm text-muted-foreground">
          Nothing on your books today.
        </div>
      ) : (
        <ul className="divide-y">
          {sortForProvider(myAppts).slice(0, 6).map((appt) => (
            <ApptRow key={appt.id} appt={appt} />
          ))}
        </ul>
      )}

      {/* Footer: peek at commissions */}
      <Link
        href="/staff/commissions"
        className="border-t px-5 py-3 flex items-center justify-between text-sm hover:bg-muted/30 transition-colors"
      >
        <span className="text-muted-foreground">Your commissions</span>
        <span className="inline-flex items-center gap-1 text-foreground/70">
          View earnings
          <ArrowRight className="size-3.5" />
        </span>
      </Link>
    </section>
  );
}

function ApptRow({ appt }: { appt: Appointment }) {
  const start = new Date(appt.start_time);
  const time = start.toLocaleTimeString('en-US', {
    hour: 'numeric',
    minute: '2-digit',
  });
  const tone = STATUS_TONE[appt.status] ?? 'text-foreground';
  const label = STATUS_LABEL[appt.status] ?? appt.status;

  return (
    <li>
      <Link
        href={`/clients/${appt.customer.id}`}
        className="grid grid-cols-[60px_1fr_auto] items-baseline gap-3 px-5 py-3 transition-colors hover:bg-muted/30"
      >
        <span className="font-mono text-xs tabular-nums text-foreground/60">
          {time}
        </span>
        <div className="min-w-0">
          <p
            className={cn(
              'truncate text-sm font-medium',
              appt.status === 'cancelled'
                ? 'line-through text-muted-foreground'
                : 'text-foreground',
            )}
          >
            {appt.customer.full_name}
          </p>
          <p className="truncate text-xs text-muted-foreground">
            {appt.service.name}
          </p>
        </div>
        <span
          className={cn(
            'shrink-0 text-[11px] uppercase tracking-[0.14em]',
            tone,
          )}
        >
          {label}
        </span>
      </Link>
    </li>
  );
}

function SkeletonRows() {
  return (
    <ul className="divide-y">
      {[...Array(3)].map((_, i) => (
        <li
          key={i}
          className="grid grid-cols-[60px_1fr_auto] items-baseline gap-3 px-5 py-3"
        >
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

function sortForProvider(appts: Appointment[]): Appointment[] {
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

function toastApiError(err: Error, fallback: string) {
  if (err instanceof ApiError && err.body && typeof err.body === 'object') {
    const body = err.body as { detail?: string };
    if (body.detail) {
      toast.error(body.detail);
      return;
    }
  }
  toast.error(fallback);
}
