/**
 * `/clock-in` — mobile-first employee clock-in/out panel.
 *
 * Every employee opens this on their phone (or tablet at the front
 * desk) to start/end their shift. Designed for one-handed use:
 * giant touch target, live elapsed time when clocked in, recent
 * shifts below for quick "did I forget yesterday?" glance.
 *
 * Touch targets are ≥56px (well above the 44px iOS minimum).
 * Inputs are size:16px+ to avoid iOS auto-zoom on focus.
 */

'use client';

import {
  AlertCircle,
  CheckCircle2,
  Clock,
  Loader2,
  LogIn,
  LogOut,
  Users as UsersIcon,
} from 'lucide-react';
import Link from 'next/link';
import { useEffect, useState } from 'react';
import { toast } from 'sonner';

import { ApiError } from '@/lib/api';
import { useCurrentMembership, useUser } from '@/lib/auth';
import {
  type TimeEntry,
  elapsedSeconds,
  formatDuration,
  useActiveShifts,
  useClockIn,
  useClockOut,
  useMyTimeState,
} from '@/lib/timetracking';
import { cn } from '@/lib/utils';

export default function ClockInPage() {
  const me = useCurrentMembership();
  const { data: user } = useUser();
  const myState = useMyTimeState();
  const active = useActiveShifts();
  const clockIn = useClockIn();
  const clockOut = useClockOut();

  const [now, setNow] = useState(() => Date.now());

  // Tick the live clock once a second when there's an open entry.
  // Pure cosmetic — the duration shown updates without refetching.
  useEffect(() => {
    if (!myState.data?.open_entry) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [myState.data?.open_entry]);

  const onClockIn = () => {
    clockIn.mutate(
      {},
      {
        onSuccess: () => toast.success("You're clocked in"),
        onError: (err) => {
          if (err instanceof ApiError && err.body && typeof err.body === 'object') {
            const body = err.body as { detail?: string };
            if (body.detail) {
              toast.error(body.detail);
              return;
            }
          }
          toast.error("Couldn't clock in.");
        },
      },
    );
  };

  const onClockOut = () => {
    clockOut.mutate(
      {},
      {
        onSuccess: () => toast.success("You're clocked out"),
        onError: (err) => {
          if (err instanceof ApiError && err.body && typeof err.body === 'object') {
            const body = err.body as { detail?: string };
            if (body.detail) {
              toast.error(body.detail);
              return;
            }
          }
          toast.error("Couldn't clock out.");
        },
      },
    );
  };

  if (!me || !user) {
    return (
      <div className="px-4 py-10 sm:px-6 sm:py-14 max-w-xl mx-auto text-center">
        <p className="text-sm text-muted-foreground">
          Sign in to use clock-in.
        </p>
      </div>
    );
  }

  const isLoading = myState.isLoading;
  const openEntry = myState.data?.open_entry ?? null;
  const recent = myState.data?.recent ?? [];

  return (
    <div className="min-h-full bg-background">
      <div className="mx-auto w-full max-w-xl px-4 py-8 sm:px-6 sm:py-12 space-y-8">
        <header>
          <h1 className="font-serif text-3xl font-semibold tracking-tight">
            Clock in
          </h1>
          <p className="text-sm text-muted-foreground mt-1.5">
            {user.first_name ? `Hi, ${user.first_name}.` : 'Hi.'}{' '}
            Tap the big button when you start or end your shift.
          </p>
        </header>

        {isLoading ? (
          <div className="rounded-2xl border bg-card p-12 text-center text-sm text-muted-foreground">
            <Loader2 className="size-5 animate-spin mx-auto mb-3" />
            Loading…
          </div>
        ) : openEntry ? (
          <ClockedInCard
            entry={openEntry}
            now={now}
            onClockOut={onClockOut}
            isPending={clockOut.isPending}
          />
        ) : (
          <ClockedOutCard
            onClockIn={onClockIn}
            isPending={clockIn.isPending}
          />
        )}

        <RecentShifts entries={recent} />

        <ActiveCoworkersPanel
          entries={active.data ?? []}
          isLoading={active.isLoading}
          ownEmail={user.email}
        />
      </div>
    </div>
  );
}

// ── Clocked-in / clocked-out hero cards ─────────────────────────────

function ClockedInCard({
  entry,
  now,
  onClockOut,
  isPending,
}: {
  entry: TimeEntry;
  now: number;
  onClockOut: () => void;
  isPending: boolean;
}) {
  const elapsed = elapsedSeconds(entry, now);
  return (
    <div className="rounded-2xl border bg-emerald-50/50 px-6 py-8 text-center space-y-6">
      <div className="inline-flex items-center gap-2 text-emerald-800">
        <span className="size-2 rounded-full bg-emerald-500 animate-pulse" />
        <span className="text-xs uppercase tracking-[0.18em] font-medium">
          On the clock
        </span>
      </div>

      <div>
        <p className="font-mono text-5xl font-semibold tabular-nums tracking-tight text-emerald-900">
          {formatDuration(elapsed)}
        </p>
        <p className="text-sm text-emerald-800/80 mt-2">
          since{' '}
          {new Date(entry.clock_in_at).toLocaleTimeString(undefined, {
            hour: 'numeric',
            minute: '2-digit',
          })}
        </p>
      </div>

      <button
        type="button"
        onClick={onClockOut}
        disabled={isPending}
        className={cn(
          'w-full inline-flex items-center justify-center gap-2',
          'h-16 sm:h-14 rounded-2xl',
          'bg-foreground text-background',
          'text-base sm:text-sm font-medium',
          'hover:bg-foreground/90 active:bg-foreground/80',
          'transition-colors',
          'disabled:opacity-60 disabled:cursor-not-allowed',
        )}
      >
        {isPending ? (
          <Loader2 className="size-5 animate-spin" />
        ) : (
          <LogOut className="size-5" />
        )}
        Clock out
      </button>
    </div>
  );
}

function ClockedOutCard({
  onClockIn,
  isPending,
}: {
  onClockIn: () => void;
  isPending: boolean;
}) {
  return (
    <div className="rounded-2xl border bg-card px-6 py-8 text-center space-y-6">
      <div className="inline-flex items-center gap-2 text-muted-foreground">
        <Clock className="size-4" />
        <span className="text-xs uppercase tracking-[0.18em] font-medium">
          Off the clock
        </span>
      </div>

      <p className="text-sm text-muted-foreground max-w-xs mx-auto">
        Ready when you are. Tap below to start your shift.
      </p>

      <button
        type="button"
        onClick={onClockIn}
        disabled={isPending}
        className={cn(
          'w-full inline-flex items-center justify-center gap-2',
          'h-16 sm:h-14 rounded-2xl',
          'bg-emerald-600 text-white',
          'text-base sm:text-sm font-medium',
          'hover:bg-emerald-700 active:bg-emerald-800',
          'transition-colors',
          'disabled:opacity-60 disabled:cursor-not-allowed',
        )}
      >
        {isPending ? (
          <Loader2 className="size-5 animate-spin" />
        ) : (
          <LogIn className="size-5" />
        )}
        Clock in
      </button>
    </div>
  );
}

// ── Recent shifts ───────────────────────────────────────────────────

function RecentShifts({ entries }: { entries: TimeEntry[] }) {
  if (entries.length === 0) {
    return null;
  }
  return (
    <section>
      <header className="flex items-baseline justify-between mb-3">
        <h2 className="text-[11px] uppercase tracking-wider text-muted-foreground font-medium">
          Recent shifts
        </h2>
        <p className="text-[11px] text-muted-foreground/70">
          last 5
        </p>
      </header>
      <ul className="rounded-xl border bg-card overflow-hidden divide-y">
        {entries.map((entry) => (
          <li key={entry.id} className="px-4 py-3 flex items-center gap-3">
            <div className="inline-flex size-8 items-center justify-center rounded-md bg-emerald-50 text-emerald-700 shrink-0">
              <CheckCircle2 className="size-4" />
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium">
                {new Date(entry.clock_in_at).toLocaleDateString(undefined, {
                  weekday: 'short',
                  month: 'short',
                  day: 'numeric',
                })}
              </p>
              <p className="text-xs text-muted-foreground">
                {new Date(entry.clock_in_at).toLocaleTimeString(
                  undefined,
                  { hour: 'numeric', minute: '2-digit' },
                )}
                {' → '}
                {entry.clock_out_at
                  ? new Date(entry.clock_out_at).toLocaleTimeString(
                      undefined,
                      { hour: 'numeric', minute: '2-digit' },
                    )
                  : '—'}
              </p>
            </div>
            <p className="font-mono tabular-nums text-sm shrink-0">
              {formatDuration(entry.duration_seconds)}
            </p>
          </li>
        ))}
      </ul>
    </section>
  );
}

// ── Who else is clocked in ──────────────────────────────────────────

function ActiveCoworkersPanel({
  entries,
  isLoading,
  ownEmail,
}: {
  entries: TimeEntry[];
  isLoading: boolean;
  ownEmail: string;
}) {
  const others = entries.filter(
    (e) => e.membership_user_email !== ownEmail,
  );
  return (
    <section>
      <header className="flex items-baseline justify-between mb-3">
        <h2 className="text-[11px] uppercase tracking-wider text-muted-foreground font-medium">
          Who&rsquo;s on the clock
        </h2>
        <Link
          href="/staff/time-entries"
          className="text-[11px] text-muted-foreground hover:text-foreground"
        >
          View all →
        </Link>
      </header>
      {isLoading ? (
        <div className="rounded-xl border bg-card p-6 text-center text-sm text-muted-foreground">
          Loading…
        </div>
      ) : others.length === 0 ? (
        <div className="rounded-xl border border-dashed bg-muted/20 p-6 text-center">
          <UsersIcon className="size-5 mx-auto text-muted-foreground/50 mb-2" />
          <p className="text-sm text-muted-foreground">
            No other staff currently clocked in.
          </p>
        </div>
      ) : (
        <ul className="rounded-xl border bg-card overflow-hidden divide-y">
          {others.map((entry) => {
            const fullName = (
              `${entry.membership_user_first_name ?? ''} ${entry.membership_user_last_name ?? ''}`
                .trim()
              || entry.membership_user_email
            );
            return (
              <li key={entry.id} className="px-4 py-3 flex items-center gap-3">
                <div className="size-8 rounded-full bg-emerald-100 text-emerald-800 flex items-center justify-center text-xs font-medium uppercase shrink-0">
                  {(entry.membership_user_first_name?.[0] ?? '?')}
                </div>
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium truncate">{fullName}</p>
                  <p className="text-xs text-muted-foreground capitalize">
                    {entry.membership_role.replace('_', ' ')}
                  </p>
                </div>
                <p className="text-xs text-muted-foreground shrink-0">
                  since{' '}
                  {new Date(entry.clock_in_at).toLocaleTimeString(undefined, {
                    hour: 'numeric',
                    minute: '2-digit',
                  })}
                </p>
              </li>
            );
          })}
        </ul>
      )}
      {entries.length > 0 && others.length === 0 ? (
        <p className="mt-3 text-xs text-muted-foreground inline-flex items-center gap-1.5">
          <AlertCircle className="size-3.5" />
          You&rsquo;re the only one on the clock.
        </p>
      ) : null}
    </section>
  );
}
