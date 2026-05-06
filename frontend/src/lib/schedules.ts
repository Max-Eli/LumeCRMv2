/**
 * Per-provider weekly schedule hooks (Phase 1C session 4).
 *
 * Wraps `GET / PUT /api/schedules/{membership_location_id}/`. Each
 * `MembershipLocation` (a person assigned to a site) has at most one
 * schedule — the same person at two sites has two distinct schedules.
 *
 * Read shape always returns the canonical 7-weekday object; the
 * backend fills in empty arrays for unset days. Write is a full
 * replace — pass the entire weekly_hours dict and the backend
 * reconciles. The audit log captures before/after diffs so the SOC 2
 * trail answers "who changed Sarah's Tuesday hours and when."
 *
 * Calendar consumption: the bookable-memberships endpoint embeds
 * `schedule_for_location` per provider so the day view can render the
 * dimmed overlay without a per-provider round-trip.
 */

'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from './api';

export const WEEKDAYS = [
  'monday',
  'tuesday',
  'wednesday',
  'thursday',
  'friday',
  'saturday',
  'sunday',
] as const;

export type Weekday = (typeof WEEKDAYS)[number];

/** A single working time block within a day. HH:MM 24-hour. */
export interface ScheduleBlock {
  start: string;
  end: string;
}

/** Per-weekday array of working blocks. Empty array = "off." */
export type WeeklyHours = Record<Weekday, ScheduleBlock[]>;

export interface ScheduleResponse {
  membership_location_id: number;
  weekly_hours: WeeklyHours;
}

/** Canonical "every day off" template. Used as a default when
 *  building a fresh schedule client-side before the user has touched
 *  any day. Mirrors the backend's `ProviderSchedule.empty_weekly_hours`. */
export function emptyWeeklyHours(): WeeklyHours {
  return {
    monday: [],
    tuesday: [],
    wednesday: [],
    thursday: [],
    friday: [],
    saturday: [],
    sunday: [],
  };
}

/** Get a Weekday name from a Date — Date.getDay returns 0=Sun..6=Sat;
 *  we use Mon..Sun ordering, so map accordingly. The calendar's day
 *  view passes a date string; this resolves it to the right weekday
 *  key for schedule lookup. */
export function weekdayFromDate(date: Date): Weekday {
  const idx = date.getDay(); // 0=Sun..6=Sat
  // Sun=6, Mon=0, Tue=1, ...
  const ordered: Weekday[] = [
    'sunday',
    'monday',
    'tuesday',
    'wednesday',
    'thursday',
    'friday',
    'saturday',
  ];
  return ordered[idx];
}

const SCHEDULE_KEY = (id: number) => ['schedule', id] as const;

/** Fetch the schedule for one MembershipLocation. Always resolves to
 *  the canonical shape (7 weekday keys) — the backend fills empty
 *  arrays for never-set days. */
export function useSchedule(membershipLocationId: number | undefined) {
  return useQuery<ScheduleResponse>({
    queryKey: SCHEDULE_KEY(membershipLocationId ?? 0),
    queryFn: () =>
      api.get<ScheduleResponse>(`/api/schedules/${membershipLocationId}/`),
    enabled:
      typeof membershipLocationId === 'number' && membershipLocationId > 0,
  });
}

/** Replace the entire weekly schedule for one MembershipLocation.
 *  Owner+manager only. Invalidates the per-schedule cache + the
 *  bookable-memberships cache (which embeds schedule_for_location). */
export function useUpdateSchedule(membershipLocationId: number) {
  const qc = useQueryClient();
  return useMutation<ScheduleResponse, Error, WeeklyHours>({
    mutationFn: (weekly) =>
      api.put<ScheduleResponse>(`/api/schedules/${membershipLocationId}/`, {
        weekly_hours: weekly,
      }),
    onSuccess: (response) => {
      qc.setQueryData(SCHEDULE_KEY(membershipLocationId), response);
      // The calendar's bookable-providers query embeds the schedule;
      // invalidate so the overlay re-renders with the new hours.
      qc.invalidateQueries({ queryKey: ['memberships'] });
    },
  });
}

// ── Display helpers ────────────────────────────────────────────────

/** Format a single block for compact display. "9 AM – 5 PM". */
export function formatBlock(block: ScheduleBlock): string {
  return `${formatTime12(block.start)} – ${formatTime12(block.end)}`;
}

/** "9 AM" / "9:30 AM" / "5 PM" — drop minutes when on the hour. */
export function formatTime12(hhmm: string): string {
  const m = /^(\d{1,2}):(\d{2})/.exec(hhmm);
  if (!m) return hhmm;
  const h24 = Number(m[1]);
  const min = Number(m[2]);
  const period = h24 >= 12 ? 'PM' : 'AM';
  const h12 = ((h24 + 11) % 12) + 1;
  return min === 0 ? `${h12} ${period}` : `${h12}:${pad2(min)} ${period}`;
}

function pad2(n: number): string {
  return String(n).padStart(2, '0');
}

/** Sum of block minutes across the week — used to show "32 hrs/week"
 *  per provider in the scheduler header. */
export function totalWeeklyMinutes(weekly: WeeklyHours): number {
  let total = 0;
  for (const day of WEEKDAYS) {
    for (const block of weekly[day]) {
      total += parseHHMMToMinutes(block.end) - parseHHMMToMinutes(block.start);
    }
  }
  return total;
}

export function parseHHMMToMinutes(hhmm: string): number {
  const m = /^(\d{1,2}):(\d{2})/.exec(hhmm);
  if (!m) return 0;
  return Number(m[1]) * 60 + Number(m[2]);
}

/** Format minute total as "32h" or "32h 30m". */
export function formatWeeklyTotal(minutes: number): string {
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return m === 0 ? `${h}h` : `${h}h ${m}m`;
}

/** Validate a single proposed block client-side. Mirrors the backend
 *  rules for instant feedback in the editor. Returns null if valid,
 *  an error message otherwise. */
export function validateBlock(block: ScheduleBlock): string | null {
  if (!/^\d{1,2}:\d{2}$/.test(block.start)) return 'Start time invalid.';
  if (!/^\d{1,2}:\d{2}$/.test(block.end)) return 'End time invalid.';
  if (parseHHMMToMinutes(block.end) <= parseHHMMToMinutes(block.start)) {
    return 'End must be after start.';
  }
  return null;
}

/** Validate a day's blocks — mirrors backend no-overlap rule. Returns
 *  null if valid, an error message otherwise. Sorts a copy; doesn't
 *  mutate input. */
export function validateDayBlocks(blocks: ScheduleBlock[]): string | null {
  for (const block of blocks) {
    const err = validateBlock(block);
    if (err) return err;
  }
  const sorted = [...blocks].sort(
    (a, b) => parseHHMMToMinutes(a.start) - parseHHMMToMinutes(b.start),
  );
  for (let i = 1; i < sorted.length; i++) {
    if (
      parseHHMMToMinutes(sorted[i].start) <
      parseHHMMToMinutes(sorted[i - 1].end)
    ) {
      return `Blocks overlap: ${formatBlock(sorted[i - 1])} and ${formatBlock(sorted[i])}.`;
    }
  }
  return null;
}
