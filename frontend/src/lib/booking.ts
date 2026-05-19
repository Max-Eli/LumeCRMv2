/**
 * Public booking API client + React Query hooks.
 *
 * Talks to `/api/booking/...` on the Django backend. NO auth — these
 * endpoints accept anonymous traffic and the backend's
 * PublicBookingPermission allows-any. The `api` helper from
 * `lib/api.ts` would attach CSRF + tenant-slug cookies that don't
 * apply here, so we use a tiny dedicated fetch wrapper instead.
 *
 * The tenant slug rides in the URL (path param) so cross-origin
 * marketing pages can build deep links without depending on
 * subdomain resolution. The backend resolves the tenant from the
 * slug; the X-Tenant-Slug header is intentionally NOT set.
 *
 * Mutations are POST-only and have no CSRF (the backend's
 * PublicBookingViewMixin disables CSRF since there's no session to
 * ride; the booking_token is the security boundary on manage flows).
 */

'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { ApiError } from './api';

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

async function bookingFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
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
      `Booking request failed: ${res.status} ${res.statusText}`,
    );
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

// ── Types ───────────────────────────────────────────────────────────

export type BookingStatus =
  | 'booked'
  | 'confirmed'
  | 'checked_in'
  | 'completed'
  | 'no_show'
  | 'cancelled';

export interface BookingLocation {
  id: number;
  name: string;
  slug: string;
  timezone: string;
  address_line1: string;
  address_line2: string;
  city: string;
  state: string;
  zip_code: string;
  phone: string;
  business_open_time: string;
  business_close_time: string;
}

export interface BookingTenantInfo {
  name: string;
  slug: string;
  primary_color: string;
  logo_url: string;
  /** Optional operator-edited welcome copy shown above the catalog. */
  welcome_message: string;
  /** Cancellation/no-show policy shown on details + manage pages. */
  cancellation_policy: string;
  /** How many days into the future bookings are allowed; the calendar
   *  uses this to disable far-future dates. */
  booking_window_days: number;
  locations: BookingLocation[];
}

export interface BookableService {
  id: number;
  name: string;
  description: string;
  duration_minutes: number;
  price_cents: number;
  category_name: string;
  category_color: string;
  /** Optional tenant-uploaded marketing image. Rendered at the top
   *  of each service card on the public catalog. */
  hero_photo_url: string | null;
}

export interface EligibleProvider {
  id: number;
  display_name: string;
  job_title: string;
}

export interface AvailableSlot {
  start: string;
  end: string;
  /** False when the slot is taken or sits inside the lead-time
   *  buffer. Frontend renders these grayed-out so customers see the
   *  full availability picture rather than confusing gaps. */
  available: boolean;
  /** Only populated on `available=true` slots. Null/undefined for
   *  taken slots — there's no provider to attribute the conflict to. */
  provider_id?: number | null;
}

export interface BookingConfirmation {
  id: number;
  booking_token: string;
  start_time: string;
  end_time: string;
  service_name: string;
  duration_minutes: number;
  location_name: string;
  provider_display_name: string;
  quoted_price_cents: number;
  status: BookingStatus;
}

export interface ManageBooking extends BookingConfirmation {
  service_id: number;
  provider_id: number;
  customer_first_name: string;
  customer_last_name: string;
  customer_email: string;
  location: BookingLocation;
  tenant: {
    name: string;
    slug: string;
    primary_color: string;
    logo_url: string;
    cancellation_policy: string;
  };
}

export interface SubmitBookingInput {
  service_id: number;
  provider_id: number;
  location_id: number;
  start_time: string;
  customer_first_name: string;
  customer_last_name: string;
  customer_email: string;
  customer_phone: string;
  notes?: string;
  email_marketing_opt_in?: boolean;
  sms_marketing_opt_in?: boolean;
}

// ── Query keys ──────────────────────────────────────────────────────

const tenantInfoKey = (slug: string) => ['booking', 'tenant', slug] as const;
const serviceListKey = (slug: string) => ['booking', 'services', slug] as const;
const providerListKey = (slug: string, serviceId: number, locationId: number) =>
  ['booking', 'providers', slug, serviceId, locationId] as const;
const slotListKey = (
  slug: string,
  serviceId: number,
  locationId: number,
  date: string,
  provider: string,
) => ['booking', 'slots', slug, serviceId, locationId, date, provider] as const;
const manageKey = (token: string) => ['booking', 'manage', token] as const;

// ── Read hooks ──────────────────────────────────────────────────────

export function useBookingTenantInfo(slug: string | undefined) {
  return useQuery<BookingTenantInfo>({
    queryKey: tenantInfoKey(slug ?? ''),
    queryFn: () => bookingFetch<BookingTenantInfo>(`/api/booking/${slug}/info/`),
    enabled: !!slug,
    staleTime: 5 * 60 * 1000,
    retry: false,
  });
}

export function useBookingServices(slug: string | undefined) {
  return useQuery<BookableService[]>({
    queryKey: serviceListKey(slug ?? ''),
    queryFn: () => bookingFetch<BookableService[]>(`/api/booking/${slug}/services/`),
    enabled: !!slug,
    staleTime: 60 * 1000,
  });
}

export function useBookingProviders(
  slug: string | undefined,
  serviceId: number | undefined,
  locationId: number | undefined,
) {
  return useQuery<EligibleProvider[]>({
    queryKey: providerListKey(slug ?? '', serviceId ?? 0, locationId ?? 0),
    queryFn: () =>
      bookingFetch<EligibleProvider[]>(
        `/api/booking/${slug}/providers/?service=${serviceId}&location=${locationId}`,
      ),
    enabled: !!slug && !!serviceId && !!locationId,
    staleTime: 60 * 1000,
  });
}

export function useBookingSlots(
  slug: string | undefined,
  args: {
    serviceId?: number;
    locationId?: number;
    date?: string;
    provider?: number | 'any';
  },
) {
  const { serviceId, locationId, date } = args;
  const provider = args.provider ?? 'any';
  const providerKey = String(provider);
  return useQuery<AvailableSlot[]>({
    queryKey: slotListKey(slug ?? '', serviceId ?? 0, locationId ?? 0, date ?? '', providerKey),
    queryFn: () => {
      const params = new URLSearchParams({
        service: String(serviceId),
        location: String(locationId),
        date: String(date),
        provider: providerKey,
        // Always request the full picture — taken slots come back
        // with `available: false` so the picker can render them
        // grayed-out instead of showing confusing gaps.
        include_unavailable: 'true',
      });
      return bookingFetch<AvailableSlot[]>(
        `/api/booking/${slug}/slots/?${params}`,
      );
    },
    enabled: !!slug && !!serviceId && !!locationId && !!date,
    // Slots change as other customers book — keep this fresh.
    staleTime: 15 * 1000,
  });
}

export function useManageBooking(token: string | undefined) {
  return useQuery<ManageBooking>({
    queryKey: manageKey(token ?? ''),
    queryFn: () => bookingFetch<ManageBooking>(`/api/booking/manage/${token}/`),
    enabled: !!token,
    refetchOnWindowFocus: false,
    retry: false,
  });
}

// ── Mutations ───────────────────────────────────────────────────────

export function useSubmitBooking(slug: string) {
  return useMutation<BookingConfirmation, Error, SubmitBookingInput>({
    mutationFn: (input) =>
      bookingFetch<BookingConfirmation>(`/api/booking/${slug}/book/`, {
        method: 'POST',
        body: JSON.stringify(input),
      }),
  });
}

export function useCancelBooking(token: string) {
  const qc = useQueryClient();
  return useMutation<ManageBooking, Error, void>({
    mutationFn: () =>
      bookingFetch<ManageBooking>(`/api/booking/manage/${token}/cancel/`, {
        method: 'POST',
      }),
    onSuccess: (updated) => {
      qc.setQueryData(manageKey(token), updated);
    },
  });
}

export interface RescheduleBookingInput {
  /** ISO-8601 datetime (UTC offset preserved) for the new slot. The
   *  backend re-validates against `compute_provider_slots` so a
   *  stale UI submitting an unavailable time loses cleanly with 409. */
  start_time: string;
}

/** Reschedule an existing booking to a new time. Same provider,
 *  service, and location — only `start_time` changes. The backend
 *  rejects (400) terminal-state appointments (cancelled, completed,
 *  no-show), and (409) when the new slot was taken between the slot
 *  fetch and submit. */
export function useRescheduleBooking(token: string) {
  const qc = useQueryClient();
  return useMutation<ManageBooking, Error, RescheduleBookingInput>({
    mutationFn: (input) =>
      bookingFetch<ManageBooking>(
        `/api/booking/manage/${token}/reschedule/`,
        {
          method: 'POST',
          body: JSON.stringify(input),
        },
      ),
    onSuccess: (updated) => {
      qc.setQueryData(manageKey(token), updated);
    },
  });
}

// ── Display helpers ────────────────────────────────────────────────

export function formatPriceCents(cents: number): string {
  return `$${(cents / 100).toFixed(0)}`;
}

export function formatDuration(minutes: number): string {
  if (minutes < 60) return `${minutes} min`;
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return m === 0 ? `${h} hr` : `${h} hr ${m} min`;
}

export function formatSlotTime(iso: string, timezone: string): string {
  // Render in the location's timezone so a Brooklyn customer sees
  // 3:00 PM, not whatever their device tz happens to be.
  const d = new Date(iso);
  return d.toLocaleTimeString('en-US', {
    hour: 'numeric',
    minute: '2-digit',
    timeZone: timezone,
  });
}

export function formatSlotDate(iso: string, timezone: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString('en-US', {
    weekday: 'long',
    month: 'long',
    day: 'numeric',
    timeZone: timezone,
  });
}
