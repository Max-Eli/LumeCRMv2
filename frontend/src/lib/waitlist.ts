/**
 * Waitlist hooks — public submit (no auth) + internal CRUD.
 *
 * Mirrors `lib/booking.ts` for the public side and the standard
 * `lib/api.ts`-backed pattern for the internal side. Public submit
 * uses a dedicated fetch wrapper that doesn't attach session
 * cookies / CSRF — same posture as the booking POST.
 */

'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { ApiError, api } from './api';

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

// ── Types ───────────────────────────────────────────────────────────

export type WaitlistStatus = 'waiting' | 'contacted' | 'booked' | 'declined';

/** Internal-side detail — what the operator panel renders. Includes
 *  PHI (phone + email) so front-desk can call the customer back. */
export interface WaitlistEntry {
  id: number;
  customer_id: number;
  customer_first_name: string;
  customer_last_name: string;
  customer_phone: string;
  customer_email: string;
  service_id: number;
  service_name: string;
  service_duration_minutes: number;
  location_id: number;
  location_name: string;
  provider_id: number | null;
  provider_display_name: string;
  preferred_date: string;
  notes: string;
  status: WaitlistStatus;
  source: string;
  contacted_at: string | null;
  declined_at: string | null;
  booked_at: string | null;
  created_at: string;
  updated_at: string;
}

/** Public-side confirmation — minimum-necessary echo back to the
 *  customer ("you're on the list for X on Y"). */
export interface PublicWaitlistConfirmation {
  id: number;
  service_name: string;
  location_name: string;
  preferred_date: string;
  status: WaitlistStatus;
  created_at: string;
}

export interface PublicWaitlistJoinInput {
  service_id: number;
  location_id: number;
  provider_id?: number | null;
  preferred_date: string;
  customer_first_name: string;
  customer_last_name: string;
  customer_email: string;
  customer_phone: string;
  notes?: string;
}

// ── Public submit (no auth) ────────────────────────────────────────

async function publicFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      Accept: 'application/json',
      ...(init.headers as Record<string, string> | undefined),
    },
  });
  if (!res.ok) {
    let body: unknown = null;
    try {
      body = await res.json();
    } catch {
      // empty
    }
    throw new ApiError(
      res.status,
      body,
      `Waitlist request failed: ${res.status} ${res.statusText}`,
    );
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

/** Submit a waitlist entry from the public booking flow. The backend
 *  silently dedupes against an identical waiting entry — calling
 *  twice with the same payload returns the same row, so the UI can
 *  treat the "201 Created" and "200 OK" cases identically. */
export function useJoinWaitlist(slug: string) {
  return useMutation<PublicWaitlistConfirmation, Error, PublicWaitlistJoinInput>({
    mutationFn: (input) =>
      publicFetch<PublicWaitlistConfirmation>(`/api/booking/${slug}/waitlist/`, {
        method: 'POST',
        body: JSON.stringify(input),
      }),
  });
}

// ── Internal (operator-side) ───────────────────────────────────────

const WAITLIST_KEY = ['waitlist'] as const;

/** List waitlist entries for the active tenant. Default scope is
 *  status=waiting (the inbox). Pass undefined to show all. */
export function useWaitlistEntries(filter: { status?: WaitlistStatus | 'all' } = {}) {
  const statusParam = filter.status === 'all' ? undefined : filter.status ?? 'waiting';
  const qs = statusParam ? `?status=${statusParam}` : '';
  return useQuery<WaitlistEntry[]>({
    queryKey: [...WAITLIST_KEY, 'list', statusParam ?? 'all'],
    queryFn: () => api.get<WaitlistEntry[]>(`/api/waitlist/${qs}`),
    staleTime: 30 * 1000,
  });
}

export interface UpdateWaitlistInput {
  status?: WaitlistStatus;
  notes?: string;
}

/** Update a waitlist entry's status or notes. The backend stamps
 *  the corresponding timestamp (contacted_at / declined_at /
 *  booked_at) automatically on transition. */
export function useUpdateWaitlistEntry(id: number) {
  const qc = useQueryClient();
  return useMutation<WaitlistEntry, Error, UpdateWaitlistInput>({
    mutationFn: (input) =>
      api.patch<WaitlistEntry>(`/api/waitlist/${id}/`, input),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: WAITLIST_KEY });
    },
  });
}

/** Two customer paths — pass `customer_id` for an existing record,
 *  OR all four `customer_*` fields for a new customer. The backend
 *  matches by email/phone, so a returning customer gets re-attached
 *  silently if they're already on file. */
export interface CreateWaitlistInput {
  customer_id?: number;
  customer_first_name?: string;
  customer_last_name?: string;
  customer_email?: string;
  customer_phone?: string;
  service_id: number;
  location_id: number;
  provider_id?: number | null;
  preferred_date: string;
  notes?: string;
}

/** Operator-side manual add. Different from the public submit —
 *  this expects an existing `customer_id`, not raw name/email/phone.
 *  Created entries are tagged `source='staff'` so the panel can
 *  distinguish them from self-service submissions at a glance. */
export function useCreateWaitlistEntry() {
  const qc = useQueryClient();
  return useMutation<WaitlistEntry, Error, CreateWaitlistInput>({
    mutationFn: (input) => api.post<WaitlistEntry>('/api/waitlist/', input),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: WAITLIST_KEY });
    },
  });
}

// ── Display helpers ────────────────────────────────────────────────

export const WAITLIST_STATUS_LABELS: Record<WaitlistStatus, string> = {
  waiting: 'Waiting',
  contacted: 'Contacted',
  booked: 'Booked',
  declined: 'Declined',
};
