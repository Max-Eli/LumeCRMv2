/**
 * Time-block data layer.
 *
 * A `TimeBlock` is a non-bookable period on a provider's calendar —
 * lunch, personal time, training. Renders alongside appointments on
 * the day-view but never carries a customer or invoice.
 *
 * Naming: the existing `ScheduleBlock` type in `@/lib/schedules` is
 * the working-hours block (Mon 9–12, etc.) — distinct concept,
 * distinct name, distinct API. Keeping the names disjoint keeps
 * imports in the day-view unambiguous.
 */

'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from './api';
import type { AppointmentProviderSummary } from './appointments';

/** Suggested reason labels surfaced in the BlockOutSheet. "Other"
 *  drops the user into a free-form input. The backend stores any
 *  string up to 200 chars — these are display defaults. */
export const TIME_BLOCK_REASON_PRESETS = [
  'Lunch break',
  'Personal time',
  'Training',
  'Meeting',
  'Admin time',
  'Out of office',
] as const;

export interface TimeBlock {
  id: number;
  provider: AppointmentProviderSummary;
  start_time: string;       // ISO-8601 UTC
  end_time: string;
  duration_minutes: number;
  reason: string;
  /** Email of the staff member who created the block. Read-only. */
  created_by_email: string | null;
  created_at: string;
  updated_at: string;
}

export interface CreateTimeBlockInput {
  provider_id: number;
  start_time: string;
  end_time: string;
  reason: string;
}

export type UpdateTimeBlockInput = Partial<CreateTimeBlockInput>;

const TIME_BLOCKS_KEY = ['time-blocks'] as const;

/** Fetch all time blocks overlapping a calendar day in the active
 *  location's timezone. Mirrors `useAppointmentsForDate`. */
export function useTimeBlocksForDate(date: string | undefined) {
  return useQuery<TimeBlock[]>({
    queryKey: [...TIME_BLOCKS_KEY, 'date', date ?? null],
    queryFn: () => api.get<TimeBlock[]>(`/api/time-blocks/?date=${date}`),
    enabled: typeof date === 'string' && date.length > 0,
  });
}

export function useCreateTimeBlock() {
  const qc = useQueryClient();
  return useMutation<TimeBlock, Error, CreateTimeBlockInput>({
    mutationFn: (input) =>
      api.post<TimeBlock>('/api/time-blocks/', input),
    onSuccess: () => qc.invalidateQueries({ queryKey: TIME_BLOCKS_KEY }),
  });
}

export function useUpdateTimeBlock(id: number) {
  const qc = useQueryClient();
  return useMutation<TimeBlock, Error, UpdateTimeBlockInput>({
    mutationFn: (input) =>
      api.patch<TimeBlock>(`/api/time-blocks/${id}/`, input),
    onSuccess: () => qc.invalidateQueries({ queryKey: TIME_BLOCKS_KEY }),
  });
}

export function useDeleteTimeBlock() {
  const qc = useQueryClient();
  return useMutation<void, Error, number>({
    mutationFn: (id) => api.delete<void>(`/api/time-blocks/${id}/`),
    onSuccess: () => qc.invalidateQueries({ queryKey: TIME_BLOCKS_KEY }),
  });
}
