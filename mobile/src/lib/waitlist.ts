/**
 * Waitlist data. Pairs with `apps.waitlist` at `/api/waitlist/` — the
 * operator side of clients waiting for a slot.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { useAuth } from './auth';

export type WaitlistStatus = 'waiting' | 'contacted' | 'booked' | 'declined';

export const WAITLIST_STATUS_LABEL: Record<WaitlistStatus, string> = {
  waiting: 'Waiting',
  contacted: 'Contacted',
  booked: 'Booked',
  declined: 'Declined',
};

export interface WaitlistEntry {
  id: number;
  customer_id: number;
  customer_first_name: string;
  customer_last_name: string;
  customer_phone: string;
  service_name: string;
  provider_display_name: string;
  preferred_date: string;
  notes: string;
  status: WaitlistStatus;
  created_at: string;
}

/** Operator waitlist, optionally filtered by status. */
export function useWaitlistEntries(status?: WaitlistStatus) {
  const { authedFetch } = useAuth();
  return useQuery({
    queryKey: ['waitlist', status ?? 'all'],
    queryFn: () =>
      authedFetch<WaitlistEntry[]>(
        status ? `/api/waitlist/?status=${status}` : '/api/waitlist/',
      ),
  });
}

/** Move a waitlist entry to a new status. The backend stamps the
 *  matching timestamp (contacted/booked/declined) automatically. */
export function useUpdateWaitlistEntry(id: number) {
  const { authedFetch } = useAuth();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (status: WaitlistStatus) =>
      authedFetch<WaitlistEntry>(`/api/waitlist/${id}/`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['waitlist'] });
    },
  });
}
