/**
 * Dashboard tile: how many staff are currently on the clock.
 *
 * Live operational awareness for owner/manager/front-desk — a glance
 * at "is anyone actually here?" Backed by `useActiveShifts()` which
 * already polls every 30s, so the number stays fresh on its own.
 *
 * Subline lists up to two first names so the chip reads as
 * "5 — Casey, Jordan +3" rather than a bare count. Tap-through goes
 * to `/staff/check-in` for the manager to drill in.
 */

'use client';

import { useActiveShifts } from '@/lib/timetracking';

import { KpiTile } from './kpi-tile';

export function OnTheClockTile() {
  const { data, isLoading } = useActiveShifts();
  const entries = data ?? [];
  const count = entries.length;

  const names = entries
    .map(
      (e) =>
        e.membership_user_first_name?.trim()
        || e.membership_user_email.split('@')[0],
    )
    .filter((n): n is string => Boolean(n));

  const subline =
    count === 0
      ? 'Nobody is clocked in right now'
      : count <= 2
        ? names.join(', ')
        : `${names.slice(0, 2).join(', ')} +${count - 2} more`;

  return (
    <KpiTile
      label="On the clock"
      value={String(count)}
      subline={subline}
      loading={isLoading}
    />
  );
}
