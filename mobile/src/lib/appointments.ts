/**
 * Appointment data — types, display helpers, and React Query hooks.
 *
 * Pairs with `apps.appointments` at `/api/appointments/`. Times are
 * ISO-8601 UTC; the app formats them in the device's local timezone,
 * which matches the spa's timezone for on-site staff.
 */

import { useQuery } from '@tanstack/react-query';

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

/** A single appointment by id. */
export function useAppointment(id: number) {
  const { authedFetch } = useAuth();
  return useQuery({
    queryKey: ['appointments', 'detail', id],
    queryFn: () => authedFetch<Appointment>(`/api/appointments/${id}/`),
    enabled: Number.isFinite(id) && id > 0,
  });
}
