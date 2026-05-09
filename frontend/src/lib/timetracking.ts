/**
 * Time tracking hooks.
 *
 * Pairs with `apps.timetracking` at `/api/time-entries/`.
 *
 * The mobile clock-in experience uses the `me/` endpoint which
 * returns "your open entry (if any) + last 5 closed shifts" in
 * one round-trip — that's everything the panel needs to render.
 */

'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from './api';

// ── Types ───────────────────────────────────────────────────────────

export type TimeEntrySource = 'self' | 'front_desk' | 'kiosk' | 'manual';

export const SOURCE_LABELS: Record<TimeEntrySource, string> = {
  self: 'Self',
  front_desk: 'Front desk',
  kiosk: 'Kiosk',
  manual: 'Manually added',
};

export interface TimeEntry {
  id: number;
  membership: number;
  membership_user_email: string;
  membership_user_first_name: string;
  membership_user_last_name: string;
  membership_role: string;
  clock_in_at: string;
  clock_out_at: string | null;
  notes: string;
  source: TimeEntrySource;
  is_open: boolean;
  duration_seconds: number | null;
  created_by_email: string | null;
  edited_at: string | null;
  edited_by_email: string | null;
  created_at: string;
  updated_at: string;
}

export interface MyTimeState {
  open_entry: TimeEntry | null;
  recent: TimeEntry[];
}

// ── Query keys ──────────────────────────────────────────────────────

const TIME_ENTRIES_KEY = ['time-entries'] as const;
const ME_KEY = [...TIME_ENTRIES_KEY, 'me'] as const;
const ACTIVE_KEY = [...TIME_ENTRIES_KEY, 'active'] as const;

// ── Read hooks ──────────────────────────────────────────────────────

export interface TimeEntryFilter {
  membershipId?: number;
  /** ISO 8601 datetime — entries with clock_in_at >= this. */
  from?: string;
  /** ISO 8601 datetime — entries with clock_in_at < this. */
  to?: string;
  open?: boolean;
}

export function useTimeEntries(opts: TimeEntryFilter = {}) {
  const params = new URLSearchParams();
  if (opts.membershipId) params.set('membership', String(opts.membershipId));
  if (opts.from) params.set('from', opts.from);
  if (opts.to) params.set('to', opts.to);
  if (opts.open !== undefined) {
    params.set('open', opts.open ? 'true' : 'false');
  }
  const qs = params.toString();
  const path = qs ? `/api/time-entries/?${qs}` : '/api/time-entries/';

  return useQuery<TimeEntry[]>({
    queryKey: [
      ...TIME_ENTRIES_KEY,
      opts.membershipId ?? 0,
      opts.from ?? '',
      opts.to ?? '',
      opts.open ?? null,
    ],
    queryFn: () => api.get<TimeEntry[]>(path),
  });
}

/** "Your" view — open entry + last 5 closed shifts. Drives the
 *  mobile clock-in panel. Refetches on a 30s interval so an open
 *  shift's elapsed-time display stays roughly current. */
export function useMyTimeState() {
  return useQuery<MyTimeState>({
    queryKey: ME_KEY,
    queryFn: () => api.get<MyTimeState>('/api/time-entries/me/'),
    refetchInterval: 30 * 1000,
  });
}

/** Currently-open shifts across the tenant. Drives the dashboard
 *  "Who's clocked in" panel. Refetches every 30s. */
export function useActiveShifts() {
  return useQuery<TimeEntry[]>({
    queryKey: ACTIVE_KEY,
    queryFn: () => api.get<TimeEntry[]>('/api/time-entries/active/'),
    refetchInterval: 30 * 1000,
  });
}

// ── Mutation hooks ──────────────────────────────────────────────────

export interface ClockInInput {
  membership_id?: number;
  notes?: string;
  source?: TimeEntrySource;
}

export interface ClockOutInput {
  membership_id?: number;
  notes?: string;
}

export function useClockIn() {
  const qc = useQueryClient();
  return useMutation<TimeEntry, Error, ClockInInput>({
    mutationFn: (input) =>
      api.post<TimeEntry>('/api/time-entries/clock-in/', input),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ME_KEY });
      qc.invalidateQueries({ queryKey: ACTIVE_KEY });
      qc.invalidateQueries({ queryKey: TIME_ENTRIES_KEY });
    },
  });
}

export function useClockOut() {
  const qc = useQueryClient();
  return useMutation<TimeEntry, Error, ClockOutInput>({
    mutationFn: (input) =>
      api.post<TimeEntry>('/api/time-entries/clock-out/', input),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ME_KEY });
      qc.invalidateQueries({ queryKey: ACTIVE_KEY });
      qc.invalidateQueries({ queryKey: TIME_ENTRIES_KEY });
    },
  });
}

export interface UpdateTimeEntryInput {
  clock_in_at?: string;
  clock_out_at?: string | null;
  notes?: string;
}

export function useUpdateTimeEntry(id: number) {
  const qc = useQueryClient();
  return useMutation<TimeEntry, Error, UpdateTimeEntryInput>({
    mutationFn: (input) =>
      api.patch<TimeEntry>(`/api/time-entries/${id}/`, input),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: TIME_ENTRIES_KEY });
    },
  });
}

export function useDeleteTimeEntry() {
  const qc = useQueryClient();
  return useMutation<void, Error, number>({
    mutationFn: (id) => api.delete(`/api/time-entries/${id}/`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: TIME_ENTRIES_KEY });
    },
  });
}

// ── Display helpers ────────────────────────────────────────────────

/** Format `duration_seconds` (or live elapsed) as `Hh Mm`. Pass
 *  null for "still open." */
export function formatDuration(seconds: number | null): string {
  if (seconds === null || seconds < 0) return '—';
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (h === 0) return `${m}m`;
  return `${h}h ${m}m`;
}

/** Sum durations of an entries list (closed only). */
export function totalSeconds(entries: TimeEntry[]): number {
  return entries.reduce(
    (sum, e) => sum + (e.duration_seconds ?? 0),
    0,
  );
}

/** "Live" elapsed seconds for an open entry, given the wall clock now. */
export function elapsedSeconds(entry: TimeEntry, nowMs: number): number {
  const start = new Date(entry.clock_in_at).getTime();
  return Math.max(0, Math.floor((nowMs - start) / 1000));
}
