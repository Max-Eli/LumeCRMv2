/**
 * Employee time clock. Pairs with `apps.timetracking` at
 * `/api/time-entries/`. `me/` returns the operator's own open shift +
 * recent history; clock-in / clock-out act on the signed-in user.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { useAuth } from './auth';

export interface TimeEntry {
  id: number;
  clock_in_at: string;
  clock_out_at: string | null;
  is_open: boolean;
  duration_seconds: number | null;
}

export interface MyTimeState {
  open_entry: TimeEntry | null;
  recent: TimeEntry[];
}

/** "2h 34m" / "45m" from a second count. */
export function formatDuration(seconds: number | null): string {
  if (seconds == null) return '—';
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return h === 0 ? `${m}m` : `${h}h ${m}m`;
}

/** The operator's own clock state — open shift + recent shifts. */
export function useMyTimeState() {
  const { authedFetch } = useAuth();
  return useQuery({
    queryKey: ['time-entries', 'me'],
    queryFn: () => authedFetch<MyTimeState>('/api/time-entries/me/'),
    refetchInterval: 30000,
  });
}

/** Clock the signed-in operator in. */
export function useClockIn() {
  const { authedFetch } = useAuth();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () =>
      authedFetch<TimeEntry>('/api/time-entries/clock-in/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source: 'self' }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['time-entries'] });
    },
  });
}

/** Clock the signed-in operator out. */
export function useClockOut() {
  const { authedFetch } = useAuth();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () =>
      authedFetch<TimeEntry>('/api/time-entries/clock-out/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['time-entries'] });
    },
  });
}
