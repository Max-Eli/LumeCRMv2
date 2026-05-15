/**
 * Calendar right-rail Employee check-in panel.
 *
 * Manager-side view: who's clocked in right now + one-click clock
 * in/out for the rest of the bookable staff. Hours feed into the
 * existing `apps.timetracking` ledger that backs payroll exports.
 *
 * This is the **front-desk** perspective. Self-service punch (a
 * staff member opening `/clock-in` on their own phone) is a separate
 * surface; both write to the same `TimeEntry` rows and respect the
 * same "one open shift per membership" invariant.
 */

'use client';

import {
  Clock,
  Coffee,
  Loader2,
  LogIn,
  LogOut as LogOutIcon,
} from 'lucide-react';
import Link from 'next/link';
import { useEffect, useMemo, useState } from 'react';

import { InitialsAvatar } from '@/components/initials-avatar';
import { Button } from '@/components/ui/button';
import {
  useBookableMemberships,
  type Membership,
  membershipName,
} from '@/lib/memberships';
import {
  elapsedSeconds,
  formatDuration,
  useActiveShifts,
  useClockIn,
  useClockOut,
  type TimeEntry,
} from '@/lib/timetracking';

export function CheckInPanel() {
  const { data: memberships, isLoading: membershipsLoading } = useBookableMemberships();
  const { data: activeShifts, isLoading: activeLoading } = useActiveShifts();

  // Tick state every 30s so open-shift durations stay roughly current.
  // The query refetches at the same cadence; this just refreshes the
  // visible elapsed-time strings between fetches.
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = window.setInterval(() => setNow(Date.now()), 30_000);
    return () => window.clearInterval(t);
  }, []);

  const shiftByMembership = useMemo(() => {
    const map = new Map<number, TimeEntry>();
    for (const s of activeShifts ?? []) {
      map.set(s.membership, s);
    }
    return map;
  }, [activeShifts]);

  const sortedMembers = useMemo(() => {
    const list = (memberships ?? []).filter((m) => m.is_active);
    // Currently-clocked-in first, then alphabetical by display name.
    return list.sort((a, b) => {
      const aIn = shiftByMembership.has(a.id) ? 0 : 1;
      const bIn = shiftByMembership.has(b.id) ? 0 : 1;
      if (aIn !== bIn) return aIn - bIn;
      return membershipName(a).localeCompare(membershipName(b));
    });
  }, [memberships, shiftByMembership]);

  const totalClockedIn = activeShifts?.length ?? 0;
  const loading = membershipsLoading || activeLoading;

  return (
    <div className="flex flex-col h-full">
      <div className="px-4 pt-3 pb-2 border-b">
        <p className="text-xs text-muted-foreground flex items-center justify-between gap-2">
          <span>
            <span className="font-medium text-foreground">{totalClockedIn}</span>
            {' '}
            {totalClockedIn === 1 ? 'person' : 'people'} clocked in
          </span>
          <Link
            href="/staff/check-in"
            className="text-[11px] hover:text-foreground transition-colors underline underline-offset-2"
          >
            Full view
          </Link>
        </p>
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto">
        {loading ? (
          <div className="flex items-center justify-center py-8 text-muted-foreground">
            <Loader2 className="size-4 animate-spin" />
          </div>
        ) : sortedMembers.length === 0 ? (
          <div className="px-4 py-8 text-center">
            <Clock className="size-6 mx-auto mb-2 text-muted-foreground" />
            <p className="text-xs text-muted-foreground">
              No bookable staff at this location yet.
            </p>
          </div>
        ) : (
          <ul className="divide-y">
            {sortedMembers.map((m) => (
              <StaffRow
                key={m.id}
                membership={m}
                shift={shiftByMembership.get(m.id) ?? null}
                now={now}
              />
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function StaffRow({
  membership,
  shift,
  now,
}: {
  membership: Membership;
  shift: TimeEntry | null;
  now: number;
}) {
  const clockIn = useClockIn();
  const clockOut = useClockOut();
  const [error, setError] = useState<string | null>(null);
  const isOpen = shift !== null && shift.is_open;
  const elapsed = isOpen && shift ? elapsedSeconds(shift, now) : 0;
  const pending = clockIn.isPending || clockOut.isPending;

  const handleClockIn = async () => {
    setError(null);
    try {
      await clockIn.mutateAsync({
        membership_id: membership.id,
        source: 'front_desk',
      });
    } catch {
      setError('Could not clock in.');
    }
  };

  const handleClockOut = async () => {
    setError(null);
    try {
      await clockOut.mutateAsync({ membership_id: membership.id });
    } catch {
      setError('Could not clock out.');
    }
  };

  const name = membershipName(membership);

  return (
    <li className="px-3 py-2.5 flex items-center gap-3">
      <InitialsAvatar name={name} size="sm" />
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium truncate">{name}</p>
        <p className="text-[11px] text-muted-foreground truncate">
          {isOpen ? (
            <span className="inline-flex items-center gap-1">
              <span className="inline-block size-1.5 rounded-full bg-emerald-500" aria-hidden />
              In · {formatDuration(elapsed)}
            </span>
          ) : (
            <span className="inline-flex items-center gap-1 text-muted-foreground/80">
              <Coffee className="size-3" />
              Off the clock
            </span>
          )}
        </p>
        {error ? (
          <p className="text-[10px] text-destructive mt-0.5">{error}</p>
        ) : null}
      </div>
      {pending ? (
        <Loader2 className="size-4 animate-spin text-muted-foreground" />
      ) : isOpen ? (
        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={handleClockOut}
          aria-label={`Clock out ${name}`}
          className="shrink-0"
        >
          <LogOutIcon className="size-3.5" />
          <span className="hidden sm:inline">Clock out</span>
        </Button>
      ) : (
        <Button
          type="button"
          size="sm"
          onClick={handleClockIn}
          aria-label={`Clock in ${name}`}
          className="shrink-0"
        >
          <LogIn className="size-3.5" />
          <span className="hidden sm:inline">Clock in</span>
        </Button>
      )}
    </li>
  );
}
