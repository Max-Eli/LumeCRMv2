/**
 * Appointment data hooks.
 *
 * Pairs with `apps.appointments` at `/api/appointments/`. Times come back as
 * ISO-8601 strings in UTC; the calendar UI is responsible for converting to
 * the tenant's timezone for display (see `formatTimeRange` etc.).
 */

'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from './api';

export type AppointmentStatus =
  | 'booked'
  | 'confirmed'
  | 'checked_in'
  | 'completed'
  | 'no_show'
  | 'cancelled';

export interface AppointmentCustomerSummary {
  id: number;
  first_name: string;
  last_name: string;
  preferred_name: string;
  full_name: string;
  phone: string;
}

export interface AppointmentServiceSummary {
  id: number;
  name: string;
  code: string;
  duration_minutes: number;
  buffer_minutes: number;
  price_cents: number;
  category_id: number | null;
  category_name: string | null;
  category_color: string | null;
}

export interface AppointmentProviderSummary {
  id: number;
  user_email: string;
  user_first_name: string;
  user_last_name: string;
  job_title_id: number | null;
  job_title_name: string | null;
  role: string;
  is_bookable: boolean;
}

export interface Appointment {
  id: number;
  customer: AppointmentCustomerSummary;
  service: AppointmentServiceSummary;
  provider: AppointmentProviderSummary;
  start_time: string;
  end_time: string;
  duration_minutes: number;
  status: AppointmentStatus;
  /** Status of the linked invoice (one-per-appointment). Sourced via the
   *  reverse OneToOne on the backend so the calendar block can render a
   *  paid / open / void pill without N+1 fetching. Null only in the
   *  transient window between appointment creation and the invoice
   *  signal firing — frontend treats null as "no badge yet." */
  invoice_status: 'open' | 'paid' | 'void' | null;
  notes: string;
  source: string;
  checked_in_at: string | null;
  completed_at: string | null;
  cancelled_at: string | null;
  cancelled_reason: string;
  quoted_price_cents: number;
  created_at: string;
  updated_at: string;
}

export interface CreateAppointmentInput {
  customer_id: number;
  provider_id: number;
  service_id: number;
  start_time: string; // ISO-8601 UTC
  end_time: string;
  status?: AppointmentStatus;
  notes?: string;
}

export type UpdateAppointmentInput = Partial<CreateAppointmentInput> & {
  status?: AppointmentStatus;
  /** Why an appointment was cancelled — sent alongside `status:
   *  'cancelled'`. Stored on the appointment + logged to its
   *  activity feed. */
  cancelled_reason?: string;
};

const APPOINTMENTS_KEY = ['appointments'] as const;

/** List appointments for a single calendar day in the tenant's timezone. */
export function useAppointmentsForDate(date: string | undefined) {
  return useQuery<Appointment[]>({
    queryKey: [...APPOINTMENTS_KEY, 'date', date ?? null],
    queryFn: () => api.get<Appointment[]>(`/api/appointments/?date=${date}`),
    enabled: typeof date === 'string' && date.length > 0,
  });
}

/** All appointments for a single customer, newest start_time first.
 *
 *  Drives the customer profile's Appointments tab — the operator
 *  expects to see history + upcoming when they click into a client.
 *  Hits `/api/appointments/?customer=<id>` (filter already supported
 *  on the backend; tenant scoping handled by the existing middleware). */
export function useCustomerAppointments(customerId: number | undefined) {
  return useQuery<Appointment[]>({
    queryKey: [...APPOINTMENTS_KEY, 'customer', customerId ?? 0],
    queryFn: () =>
      api.get<Appointment[]>(`/api/appointments/?customer=${customerId}`),
    enabled: typeof customerId === 'number' && customerId > 0,
  });
}

/** Upcoming online bookings for the active location.
 *
 *  Used by the calendar's "Online bookings" tool panel as a review
 *  inbox — shows everything booked through the public site from now
 *  forward. Sorted server-side by start_time ascending. The filter
 *  combines `start=now` (only future appointments) + `source=online`
 *  (only public-site bookings, never staff-created entries). */
export function useUpcomingOnlineBookings() {
  // Compute "now" once per render — refetching uses the same cutoff
  // so we don't churn the cache key as the second hand ticks. The
  // staff is reviewing inbox-style; a 60s drift in "now" is fine.
  const nowIso = new Date().toISOString();
  // Round the cutoff down to the minute so the query key is stable
  // across renders within the same minute (avoids re-fetch loop).
  const minuteKey = nowIso.slice(0, 16);
  return useQuery<Appointment[]>({
    queryKey: [...APPOINTMENTS_KEY, 'online', minuteKey],
    queryFn: () =>
      api.get<Appointment[]>(
        `/api/appointments/?source=online&start=${encodeURIComponent(nowIso)}`,
      ),
    staleTime: 30 * 1000,
  });
}

/** Appointments overlapping a date range — used by the calendar's
 *  week + month views. `startISO` / `endISO` are ISO-8601 datetimes;
 *  the backend returns every appointment that overlaps the window
 *  (`start_time < end` AND `end_time > start`).
 *
 *  The query key uses the date-only slices so navigating within the
 *  same month/week doesn't churn the cache. */
export function useAppointmentsRange(
  startISO: string | undefined,
  endISO: string | undefined,
) {
  return useQuery<Appointment[]>({
    queryKey: [
      ...APPOINTMENTS_KEY,
      'range',
      startISO?.slice(0, 10) ?? null,
      endISO?.slice(0, 10) ?? null,
    ],
    queryFn: () =>
      api.get<Appointment[]>(
        `/api/appointments/?start=${encodeURIComponent(startISO!)}&end=${encodeURIComponent(endISO!)}`,
      ),
    enabled: !!startISO && !!endISO,
  });
}

/** Fetch a single appointment by ID. */
export function useAppointment(id: number | undefined) {
  return useQuery<Appointment>({
    queryKey: [...APPOINTMENTS_KEY, id ?? 'disabled'],
    queryFn: () => api.get<Appointment>(`/api/appointments/${id}/`),
    enabled: typeof id === 'number' && id > 0,
  });
}

export function useCreateAppointment() {
  const qc = useQueryClient();
  return useMutation<Appointment, Error, CreateAppointmentInput>({
    mutationFn: (input) => api.post<Appointment>('/api/appointments/', input),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: APPOINTMENTS_KEY });
    },
  });
}

export function useUpdateAppointment(id: number) {
  const qc = useQueryClient();
  return useMutation<Appointment, Error, UpdateAppointmentInput>({
    mutationFn: (input) => api.patch<Appointment>(`/api/appointments/${id}/`, input),
    onSuccess: (updated) => {
      qc.setQueryData([...APPOINTMENTS_KEY, updated.id], updated);
      qc.invalidateQueries({ queryKey: APPOINTMENTS_KEY });
    },
  });
}

// ── Display helpers ──────────────────────────────────────────────────────

export const STATUS_LABELS: Record<AppointmentStatus, string> = {
  booked: 'Booked',
  confirmed: 'Confirmed',
  checked_in: 'Checked in',
  completed: 'Completed',
  no_show: 'No-show',
  cancelled: 'Cancelled',
};

export const STATUS_TONE: Record<
  AppointmentStatus,
  'neutral' | 'success' | 'info' | 'warning' | 'destructive'
> = {
  booked: 'neutral',
  confirmed: 'info',
  checked_in: 'warning',
  completed: 'success',
  no_show: 'destructive',
  cancelled: 'neutral',
};

/**
 * Status state machine — mirrors `AppointmentSerializer._STATUS_TRANSITIONS`
 * on the backend. The popover uses this to render only the valid next-state
 * buttons for the current appointment. Backend enforces too — this is purely
 * UI shaping, never a security check.
 *
 * NOTE: `completed` is intentionally absent from every transition list. Per
 * ADR 0007, the only path to `Appointment.status = 'completed'` is closing
 * the linked invoice. The Take Payment flow handles that transition; the
 * status-button row never offers it as a one-click option.
 */
export const STATUS_TRANSITIONS: Record<AppointmentStatus, AppointmentStatus[]> = {
  booked: ['confirmed', 'checked_in', 'cancelled', 'no_show'],
  confirmed: ['checked_in', 'cancelled', 'no_show'],
  // `confirmed` here is the "undo check-in" path — the popover renders
  // it with the verb-form label "Undo check-in" rather than "Confirmed."
  checked_in: ['confirmed', 'cancelled', 'no_show'],
  completed: [],
  cancelled: [],
  no_show: [],
};

/**
 * Verb-form labels for status transition buttons. Most transitions use
 * the to-status label as-is ("Cancelled"), but a couple of cases need a
 * verb that describes the action rather than the destination state.
 *
 * Keyed by `${from}->${to}`. Falls back to STATUS_LABELS[to] when no
 * override exists.
 */
export const STATUS_TRANSITION_VERBS: Record<string, string> = {
  'checked_in->confirmed': 'Undo check-in',
};

// ── Activity log ─────────────────────────────────────────────────────────

export interface ActivityEntry {
  id: number;
  timestamp: string;
  action: 'create' | 'read' | 'update' | 'delete' | string;
  user_email: string | null;
  user_first_name: string | null;
  user_last_name: string | null;
  metadata: {
    transition?: boolean;
    from_status?: AppointmentStatus;
    to_status?: AppointmentStatus;
    fields_changed?: string[];
    [key: string]: unknown;
  };
}

/** Fetch the audit-log timeline for a single appointment. Lazy — only runs
 *  when `enabled` is true, so the popover can hold off until opened. */
export function useAppointmentActivity(id: number | undefined, enabled = true) {
  return useQuery<ActivityEntry[]>({
    queryKey: [...APPOINTMENTS_KEY, id ?? 'disabled', 'activity'],
    queryFn: () => api.get<ActivityEntry[]>(`/api/appointments/${id}/activity/`),
    enabled: enabled && typeof id === 'number' && id > 0,
    staleTime: 10 * 1000,
  });
}
