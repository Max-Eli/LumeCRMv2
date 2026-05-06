/**
 * Day-summary stats strip — sits at the bottom of the calendar's main
 * column. Read-only at-a-glance "how busy was today" view for the
 * front desk: bookings count, total invoice $, no-shows, and
 * utilization % (booked minutes / scheduled provider minutes).
 *
 * Computed entirely client-side from data the calendar already
 * fetched — no extra round-trip. Refreshes automatically when the
 * appointment cache or provider schedules change.
 *
 * Conventions:
 *   - **Total $** — sum of `quoted_price_cents` for non-cancelled
 *     appointments. No-shows ARE included because the spa typically
 *     still bills them (slot was held).
 *   - **No-shows** — surfaced as their own stat because they're a
 *     real business signal. Excluded from utilization as "lost" time.
 *   - **Utilization** — booked minutes (non-cancelled, non-no-show)
 *     divided by the sum of provider working minutes for the day.
 *     Falls back to the location's business-hours window when a
 *     provider has no schedule. Caps display at 100% but tooltips
 *     show the raw % so over-booking is visible.
 */

'use client';

import {
  CalendarCheck,
  ChartLine,
  Percent,
  TriangleAlert,
} from 'lucide-react';

import type { Appointment } from '@/lib/appointments';
import type { Membership } from '@/lib/memberships';
import {
  parseHHMMToMinutes,
  type ScheduleBlock,
  type Weekday,
  weekdayFromDate,
} from '@/lib/schedules';
import { cn } from '@/lib/utils';

export interface DayStatsFooterProps {
  /** Filtered, non-loading appointments shown on the calendar. */
  appointments: Appointment[];
  /** Filtered, visible providers — drives the utilization denominator. */
  providers: Membership[];
  /** YYYY-MM-DD — used to pick the correct weekday from each
   *  provider's schedule. */
  date: string;
  /** Day-window bounds [hour). Used as the utilization fallback when
   *  a provider has no schedule (treat as available the whole window). */
  dayStartHour: number;
  dayEndHour: number;
}

export function DayStatsFooter({
  appointments,
  providers,
  date,
  dayStartHour,
  dayEndHour,
}: DayStatsFooterProps) {
  const cancelled = appointments.filter((a) => a.status === 'cancelled');
  const noShows = appointments.filter((a) => a.status === 'no_show');
  const billable = appointments.filter((a) => a.status !== 'cancelled');
  const realized = appointments.filter(
    (a) => a.status !== 'cancelled' && a.status !== 'no_show',
  );

  const bookingsCount = billable.length;
  const totalCents = billable.reduce((sum, a) => sum + (a.quoted_price_cents ?? 0), 0);
  const noShowCount = noShows.length;

  const bookedMinutes = realized.reduce(
    (sum, a) => sum + minutesBetween(a.start_time, a.end_time),
    0,
  );

  const weekday: Weekday = weekdayFromDate(parseLocalDate(date));
  const availableMinutes = providers.reduce((sum, provider) => {
    const blocks = scheduleBlocksForDay(provider.schedule_for_location, weekday);
    if (blocks === null) {
      // No schedule set — fall back to the full business-hours window.
      return sum + (dayEndHour - dayStartHour) * 60;
    }
    return sum + sumBlockMinutes(blocks);
  }, 0);

  const utilizationPct = availableMinutes > 0
    ? Math.round((bookedMinutes / availableMinutes) * 100)
    : null;

  return (
    <div className="border-t bg-card flex flex-wrap items-stretch divide-x">
      <Stat
        icon={<CalendarCheck className="size-3.5" />}
        label="Bookings"
        value={String(bookingsCount)}
        hint={cancelled.length > 0 ? `${cancelled.length} cancelled (excluded)` : undefined}
      />
      <Stat
        icon={<ChartLine className="size-3.5" />}
        label="Total"
        value={formatDollars(totalCents)}
        hint="Sum of quoted prices · no-shows still billable"
      />
      <Stat
        icon={<TriangleAlert className="size-3.5" />}
        label="No-shows"
        value={String(noShowCount)}
        tone={noShowCount > 0 ? 'warning' : undefined}
      />
      <Stat
        icon={<Percent className="size-3.5" />}
        label="Utilization"
        value={
          utilizationPct === null
            ? '—'
            : `${Math.min(utilizationPct, 100)}%`
        }
        hint={
          availableMinutes === 0
            ? 'No scheduled hours for the day'
            : utilizationPct !== null && utilizationPct > 100
              ? `Overbooked: ${utilizationPct}% of scheduled time`
              : `${formatDuration(bookedMinutes)} booked / ${formatDuration(availableMinutes)} scheduled`
        }
        tone={utilizationPct !== null && utilizationPct > 100 ? 'warning' : undefined}
      />
    </div>
  );
}

function Stat({
  icon,
  label,
  value,
  hint,
  tone,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  hint?: string;
  tone?: 'warning';
}) {
  return (
    <div
      className="flex-1 min-w-[160px] px-4 py-3"
      title={hint}
    >
      <div className={cn(
        'flex items-center gap-1.5 text-[11px] uppercase tracking-wide font-medium',
        tone === 'warning' ? 'text-destructive' : 'text-muted-foreground',
      )}>
        {icon}
        {label}
      </div>
      <p className={cn(
        'font-serif text-2xl tracking-tight tabular-nums mt-0.5',
        tone === 'warning' ? 'text-destructive' : 'text-foreground',
      )}>
        {value}
      </p>
      {hint ? (
        <p className="text-[10px] text-muted-foreground mt-0.5 truncate">
          {hint}
        </p>
      ) : null}
    </div>
  );
}

// ── Helpers ──────────────────────────────────────────────────────────

/** Pull the array of working blocks for one weekday from the schedule
 *  embedded in the membership response. Returns null if the provider
 *  has no schedule (caller should fall back to the business-hours
 *  window); empty array is "explicitly off." */
function scheduleBlocksForDay(
  schedule: Membership['schedule_for_location'],
  weekday: Weekday,
): ScheduleBlock[] | null {
  if (schedule == null) return null;
  return (schedule as Record<string, ScheduleBlock[]>)[weekday] ?? [];
}

function sumBlockMinutes(blocks: ScheduleBlock[]): number {
  return blocks.reduce(
    (sum, b) => sum + (parseHHMMToMinutes(b.end) - parseHHMMToMinutes(b.start)),
    0,
  );
}

function minutesBetween(startIso: string, endIso: string): number {
  const start = new Date(startIso).getTime();
  const end = new Date(endIso).getTime();
  return Math.max(0, Math.round((end - start) / 60_000));
}

function parseLocalDate(dateStr: string): Date {
  const [y, m, d] = dateStr.split('-').map(Number);
  return new Date(y, (m ?? 1) - 1, d ?? 1);
}

function formatDollars(cents: number): string {
  if (cents === 0) return '$0';
  const dollars = cents / 100;
  // Use locale-aware formatting; commas and the leading $ are universal
  // enough for the US v1.
  return dollars.toLocaleString('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: dollars % 1 === 0 ? 0 : 2,
    maximumFractionDigits: 2,
  });
}

function formatDuration(minutes: number): string {
  if (minutes === 0) return '0h';
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  if (h === 0) return `${m}m`;
  if (m === 0) return `${h}h`;
  return `${h}h ${m}m`;
}
