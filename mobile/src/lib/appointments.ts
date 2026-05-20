/**
 * Appointment data — types, display helpers, and React Query hooks.
 *
 * Pairs with `apps.appointments` at `/api/appointments/`. Times are
 * ISO-8601 UTC; the app formats them in the device's local timezone,
 * which matches the spa's timezone for on-site staff.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { useAuth } from './auth';

export type AppointmentStatus =
  | 'booked'
  | 'confirmed'
  | 'checked_in'
  | 'completed'
  | 'no_show'
  | 'cancelled';

export interface AppointmentCustomer {
  id: number;
  full_name: string;
  phone: string;
}

export interface AppointmentService {
  id: number;
  name: string;
  duration_minutes: number;
  category_name: string | null;
  category_color: string | null;
}

export interface AppointmentProvider {
  id: number;
  user_first_name: string;
  user_last_name: string;
  job_title_name: string | null;
}

export interface Appointment {
  id: number;
  customer: AppointmentCustomer;
  service: AppointmentService;
  provider: AppointmentProvider;
  start_time: string;
  end_time: string;
  duration_minutes: number;
  status: AppointmentStatus;
  invoice_status: 'open' | 'paid' | 'void' | null;
  notes: string;
  quoted_price_cents: number;
}

/** Statuses that still represent live, on-the-books work today. */
export const ACTIVE_STATUSES: AppointmentStatus[] = [
  'booked',
  'confirmed',
  'checked_in',
];

/** Per-status display metadata — label + pill colours. */
export const STATUS_META: Record<
  AppointmentStatus,
  { label: string; fg: string; bg: string }
> = {
  booked: { label: 'Booked', fg: '#5F6061', bg: '#ECEDEE' },
  confirmed: { label: 'Confirmed', fg: '#2D5A8A', bg: '#E7EEF6' },
  checked_in: { label: 'Checked in', fg: '#95122C', bg: '#FBEAEF' },
  completed: { label: 'Completed', fg: '#2F7D52', bg: '#E5F0EA' },
  no_show: { label: 'No-show', fg: '#CA3F16', bg: '#FBE7DF' },
  cancelled: { label: 'Cancelled', fg: '#9A9B9C', bg: '#ECEDEE' },
};

/** Valid status transitions, mirroring the backend serializer's state
 *  machine. `completed` is intentionally absent everywhere — per
 *  ADR 0007 the only path to it is closing the linked invoice, never a
 *  one-tap action. */
export const STATUS_TRANSITIONS: Record<
  AppointmentStatus,
  AppointmentStatus[]
> = {
  booked: ['confirmed', 'checked_in', 'cancelled', 'no_show'],
  confirmed: ['checked_in', 'cancelled', 'no_show'],
  checked_in: ['confirmed', 'cancelled', 'no_show'],
  completed: [],
  cancelled: [],
  no_show: [],
};

/** Operator-facing label for a status-transition action. */
export function transitionLabel(
  from: AppointmentStatus,
  to: AppointmentStatus,
): string {
  if (from === 'checked_in' && to === 'confirmed') return 'Undo check-in';
  switch (to) {
    case 'confirmed':
      return 'Confirm';
    case 'checked_in':
      return 'Check in';
    case 'cancelled':
      return 'Cancel appointment';
    case 'no_show':
      return 'Mark no-show';
    default:
      return STATUS_META[to].label;
  }
}

// ─── Display helpers ─────────────────────────────────────────────────

const DAYS = [
  'Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday',
  'Saturday',
];
const MONTHS = [
  'January', 'February', 'March', 'April', 'May', 'June', 'July',
  'August', 'September', 'October', 'November', 'December',
];

/** Today's date as `YYYY-MM-DD` in the device's local timezone. */
export function todayString(): string {
  const d = new Date();
  const mm = String(d.getMonth() + 1).padStart(2, '0');
  const dd = String(d.getDate()).padStart(2, '0');
  return `${d.getFullYear()}-${mm}-${dd}`;
}

/** "Tuesday, May 20" for a `YYYY-MM-DD` string. */
export function formatDayLabel(date: string): string {
  const [y, m, d] = date.split('-').map(Number);
  const dt = new Date(y, m - 1, d);
  return `${DAYS[dt.getDay()]}, ${MONTHS[dt.getMonth()]} ${d}`;
}

/** "Tuesday, May 20" for an ISO-8601 timestamp, in the device timezone. */
export function formatLongDate(iso: string): string {
  const d = new Date(iso);
  return `${DAYS[d.getDay()]}, ${MONTHS[d.getMonth()]} ${d.getDate()}`;
}

/** "9:05 AM" for an ISO-8601 timestamp, in the device timezone. */
export function formatTime(iso: string): string {
  const d = new Date(iso);
  let h = d.getHours();
  const m = d.getMinutes();
  const meridiem = h >= 12 ? 'PM' : 'AM';
  h = h % 12 || 12;
  return `${h}:${String(m).padStart(2, '0')} ${meridiem}`;
}

/** "45 min" / "1h 30m". */
export function formatDuration(minutes: number): string {
  if (minutes < 60) return `${minutes} min`;
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return m === 0 ? `${h}h` : `${h}h ${m}m`;
}

/** Time-of-day greeting for the dashboard. */
export function greeting(): string {
  const h = new Date().getHours();
  if (h < 12) return 'Good morning';
  if (h < 18) return 'Good afternoon';
  return 'Good evening';
}

/** "Dr. Jane Lee" — provider display name. */
export function providerName(p: AppointmentProvider): string {
  return `${p.user_first_name} ${p.user_last_name}`.trim();
}

/** "$120" — whole-dollar formatting of a cents amount. */
export function formatPrice(cents: number): string {
  return `$${Math.round(cents / 100).toLocaleString('en-US')}`;
}

// ─── Calendar date math (all on `YYYY-MM-DD` local-date strings) ──────

function ymd(d: Date): string {
  const mm = String(d.getMonth() + 1).padStart(2, '0');
  const dd = String(d.getDate()).padStart(2, '0');
  return `${d.getFullYear()}-${mm}-${dd}`;
}

/** Shift a date string by `n` days. */
export function addDays(date: string, n: number): string {
  const [y, m, d] = date.split('-').map(Number);
  return ymd(new Date(y, m - 1, d + n));
}

/** Shift a date string by `n` whole months (lands on the 1st). */
export function addMonths(date: string, n: number): string {
  const [y, m] = date.split('-').map(Number);
  return ymd(new Date(y, m - 1 + n, 1));
}

/** The Sunday on or before `date` — the web calendar is Sunday-anchored. */
export function startOfWeek(date: string): string {
  const [y, m, d] = date.split('-').map(Number);
  const dt = new Date(y, m - 1, d);
  return ymd(new Date(y, m - 1, d - dt.getDay()));
}

/** The seven `YYYY-MM-DD` days of the week containing `date`. */
export function weekDays(date: string): string[] {
  const start = startOfWeek(date);
  return Array.from({ length: 7 }, (_, i) => addDays(start, i));
}

/** The 42 days of a 6×7 month grid (first cell = Sunday on/before the 1st). */
export function monthGridDays(date: string): string[] {
  const [y, m] = date.split('-').map(Number);
  const lead = new Date(y, m - 1, 1).getDay();
  return Array.from({ length: 42 }, (_, i) => ymd(new Date(y, m - 1, 1 - lead + i)));
}

/** True when the date string is the device's today. */
export function isToday(date: string): boolean {
  return date === todayString();
}

/** The local calendar date of an appointment, as `YYYY-MM-DD`. */
export function appointmentDate(appt: Appointment): string {
  return ymd(new Date(appt.start_time));
}

/** "May 2026" for any date in that month. */
export function formatMonthLabel(date: string): string {
  const [y, m] = date.split('-').map(Number);
  return `${MONTHS[m - 1]} ${y}`;
}

/** "May 18 – 24" / "Apr 27 – May 3" for the week containing `date`. */
export function formatWeekLabel(date: string): string {
  const days = weekDays(date);
  const [, sm, sd] = days[0].split('-').map(Number);
  const [, em, ed] = days[6].split('-').map(Number);
  const left = `${MONTHS[sm - 1].slice(0, 3)} ${sd}`;
  const right =
    sm === em ? `${ed}` : `${MONTHS[em - 1].slice(0, 3)} ${ed}`;
  return `${left} – ${right}`;
}

// ─── Hooks ───────────────────────────────────────────────────────────

/** Every appointment on a given `YYYY-MM-DD`, in the active workspace. */
export function useAppointmentsForDate(date: string) {
  const { authedFetch } = useAuth();
  return useQuery({
    queryKey: ['appointments', 'date', date],
    queryFn: () =>
      authedFetch<Appointment[]>(`/api/appointments/?date=${date}`),
  });
}

/** Every appointment overlapping a `[startDate, endDate]` window
 *  (inclusive `YYYY-MM-DD`). Over-fetches a day on each side to absorb
 *  timezone skew; screens bucket the result by `appointmentDate`. */
export function useAppointmentsRange(startDate: string, endDate: string) {
  const { authedFetch } = useAuth();
  const start = `${addDays(startDate, -1)}T00:00:00`;
  const end = `${addDays(endDate, 1)}T23:59:59`;
  return useQuery({
    queryKey: ['appointments', 'range', startDate, endDate],
    queryFn: () =>
      authedFetch<Appointment[]>(
        `/api/appointments/?start=${encodeURIComponent(start)}` +
          `&end=${encodeURIComponent(end)}`,
      ),
  });
}

/** A single appointment by id. */
export function useAppointment(id: number) {
  const { authedFetch } = useAuth();
  return useQuery({
    queryKey: ['appointments', 'detail', id],
    queryFn: () => authedFetch<Appointment>(`/api/appointments/${id}/`),
    enabled: Number.isFinite(id) && id > 0,
  });
}

/** Move an appointment to a new status (`PATCH /api/appointments/:id/`).
 *  On success the detail cache is updated and every appointment list
 *  is invalidated so the dashboard + calendar reflect the change. */
export function useUpdateAppointmentStatus(id: number) {
  const { authedFetch } = useAuth();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (status: AppointmentStatus) =>
      authedFetch<Appointment>(`/api/appointments/${id}/`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status }),
      }),
    onSuccess: (updated) => {
      queryClient.setQueryData(['appointments', 'detail', id], updated);
      queryClient.invalidateQueries({ queryKey: ['appointments'] });
    },
  });
}

export interface CreateAppointmentInput {
  customer_id: number;
  service_id: number;
  provider_id: number;
  start_time: string;
  end_time: string;
  notes?: string;
}

/** Create an appointment (`POST /api/appointments/`). Invalidates every
 *  appointment list so the dashboard + calendar pick it up. */
export function useCreateAppointment() {
  const { authedFetch } = useAuth();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: CreateAppointmentInput) =>
      authedFetch<Appointment>('/api/appointments/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(input),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['appointments'] });
    },
  });
}
