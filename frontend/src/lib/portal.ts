/**
 * Customer-portal data hooks + types.
 *
 * Pairs with the Django `apps.portal` API at `/api/portal/...`. The
 * portal is a separate identity surface from the staff CRM —
 * customers authenticate via a magic-link cookie, not a User
 * session — so this module exposes its own hooks rather than reusing
 * the staff auth surface in `@/lib/auth`.
 */

'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from './api';

// ── Shapes ──────────────────────────────────────────────────────────


export interface TenantBranding {
  name: string;
  slug: string;
  primary_color: string;
  logo_url: string;
}

export interface PortalCustomer {
  id: number;
  first_name: string;
  last_name: string;
  email: string;
  phone: string;
  email_marketing_opt_in: boolean;
  sms_marketing_opt_in: boolean;
  sms_opt_in: boolean;
  tenant: TenantBranding;
}

export interface PortalAppointment {
  id: number;
  start_time: string;
  end_time: string;
  status:
    | 'booked'
    | 'confirmed'
    | 'checked_in'
    | 'completed'
    | 'no_show'
    | 'cancelled';
  status_display: string;
  service_id: number;
  service_name: string;
  service_duration_minutes: number;
  provider_id: number;
  provider_name: string;
  location_name: string;
  location_timezone: string;
  cancellable: boolean;
}

export interface ProfileUpdateInput {
  phone?: string;
  email_marketing_opt_in?: boolean;
  sms_marketing_opt_in?: boolean;
}

// ── Query keys ──────────────────────────────────────────────────────


const ME_KEY = ['portal', 'me'] as const;
const APPOINTMENTS_KEY = ['portal', 'appointments'] as const;

// ── Auth ────────────────────────────────────────────────────────────


/** Kicks off the login flow: customer enters email → backend sends
 *  magic-link email. Always resolves successfully — the same response
 *  is returned whether the email matched a customer or not, to defeat
 *  email-enumeration. */
export function useRequestMagicLink() {
  return useMutation<{ detail: string }, Error, { email: string }>({
    mutationFn: (input) =>
      api.post<{ detail: string }>('/api/portal/auth/request-magic-link/', input),
  });
}

/** Consumes the token from the magic-link URL. On success the backend
 *  sets the session cookie + returns the customer; the frontend
 *  redirects to /portal. */
export function useConsumeMagicLink() {
  const qc = useQueryClient();
  return useMutation<PortalCustomer, Error, { token: string }>({
    mutationFn: (input) =>
      api.post<PortalCustomer>('/api/portal/auth/consume/', input),
    onSuccess: (customer) => {
      qc.setQueryData(ME_KEY, customer);
    },
  });
}

/** Revokes the current session + clears the cookie. Idempotent. */
export function useLogout() {
  const qc = useQueryClient();
  return useMutation<{ detail: string }, Error, void>({
    mutationFn: () => api.post<{ detail: string }>('/api/portal/auth/logout/'),
    onSuccess: () => {
      qc.clear();
    },
  });
}

// ── Data hooks ──────────────────────────────────────────────────────


/** The signed-in customer + their tenant's branding. Used by the
 *  portal layout to apply primary_color + logo on every page. */
export function usePortalMe() {
  return useQuery<PortalCustomer>({
    queryKey: ME_KEY,
    queryFn: () => api.get<PortalCustomer>('/api/portal/me/'),
    retry: false,
    // Surface auth state changes promptly so the layout can redirect
    // to /portal/login when the session expires.
    refetchOnWindowFocus: true,
  });
}

/** PATCH profile fields (phone + marketing consents). */
export function useUpdatePortalProfile() {
  const qc = useQueryClient();
  return useMutation<PortalCustomer, Error, ProfileUpdateInput>({
    mutationFn: (input) => api.patch<PortalCustomer>('/api/portal/me/', input),
    onSuccess: (fresh) => {
      qc.setQueryData(ME_KEY, fresh);
    },
  });
}

/** Appointments for the signed-in customer, ordered with newest first.
 *  The frontend partitions into upcoming + past. */
export function usePortalAppointments() {
  return useQuery<PortalAppointment[]>({
    queryKey: APPOINTMENTS_KEY,
    queryFn: () =>
      api.get<PortalAppointment[]>('/api/portal/appointments/'),
    refetchOnWindowFocus: true,
  });
}

export function useCancelAppointment() {
  const qc = useQueryClient();
  return useMutation<PortalAppointment, Error, number>({
    mutationFn: (id) =>
      api.post<PortalAppointment>(`/api/portal/appointments/${id}/cancel/`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: APPOINTMENTS_KEY });
    },
  });
}

/** Move an upcoming appointment to a new start time. Service, provider
 *  and location stay the same — only the time changes. */
export function useRescheduleAppointment() {
  const qc = useQueryClient();
  return useMutation<
    PortalAppointment,
    Error,
    { id: number; start_time: string }
  >({
    mutationFn: ({ id, start_time }) =>
      api.post<PortalAppointment>(
        `/api/portal/appointments/${id}/reschedule/`,
        { start_time },
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: APPOINTMENTS_KEY });
    },
  });
}

// ── Memberships ─────────────────────────────────────────────────────


export type SubscriptionStatus =
  | 'pending'
  | 'active'
  | 'expired'
  | 'cancelled';

export interface PortalSubscription {
  id: number;
  name: string;
  description: string;
  status: SubscriptionStatus;
  status_display: string;
  price_cents: number;
  billing_interval: string;
  member_discount_percent: string;
  started_at: string | null;
  current_period_starts_at: string | null;
  current_period_ends_at: string | null;
  cancelled_at: string | null;
  auto_renew: boolean;
}

const MEMBERSHIPS_KEY = ['portal', 'memberships'] as const;

export function usePortalMemberships() {
  return useQuery<PortalSubscription[]>({
    queryKey: MEMBERSHIPS_KEY,
    queryFn: () => api.get<PortalSubscription[]>('/api/portal/memberships/'),
    refetchOnWindowFocus: true,
  });
}

// ── Packages ────────────────────────────────────────────────────────


export type PortalPackageStatus = 'pending' | 'active' | 'voided';

export interface PortalPackageItem {
  /** Null only for a legacy item whose service FK was cleared.
   *  Drives the package quick-book deep link. */
  service_id: number | null;
  service_name: string;
  quantity_purchased: number;
  quantity_remaining: number;
}

export interface PortalPackage {
  id: number;
  name: string;
  description: string;
  status: PortalPackageStatus;
  price_cents: number;
  purchased_at: string | null;
  expires_at: string | null;
  is_expired: boolean;
  total_credits_remaining: number;
  items: PortalPackageItem[];
}

const PACKAGES_KEY = ['portal', 'packages'] as const;

export function usePortalPackages() {
  return useQuery<PortalPackage[]>({
    queryKey: PACKAGES_KEY,
    queryFn: () => api.get<PortalPackage[]>('/api/portal/packages/'),
    refetchOnWindowFocus: true,
  });
}

// ── Forms ───────────────────────────────────────────────────────────


export type PortalFormStatus = 'pending' | 'completed' | 'voided';

export interface PortalFormSubmission {
  id: number;
  template_name: string;
  template_form_type: 'intake' | 'consent';
  status: PortalFormStatus;
  status_display: string;
  sign_url: string | null;
  signed_at: string | null;
  voided_at: string | null;
  created_at: string;
}

const FORMS_KEY = ['portal', 'forms'] as const;

export function usePortalForms() {
  return useQuery<PortalFormSubmission[]>({
    queryKey: FORMS_KEY,
    queryFn: () => api.get<PortalFormSubmission[]>('/api/portal/forms/'),
    refetchOnWindowFocus: true,
  });
}

// ── Portal invoices (Phase 2 chunk 2.6) ──────────────────────────
//
// Customer-facing read + self-pay surface. The wire shape mirrors
// the operator-side ``Invoice`` exactly — backend reuses
// ``apps.invoices.serializers.InvoiceSerializer`` for the portal
// endpoint so the operator + portal payment-history surfaces
// render identically.

import type { Invoice as OperatorInvoice } from './invoices';

/** Re-exported under a portal-specific name so portal code paths
 *  don't reach into the operator namespace. Same shape — backend
 *  uses one serializer for both surfaces. */
export type PortalInvoice = OperatorInvoice;

const PORTAL_INVOICES_KEY = ['portal', 'invoices'] as const;

/** ``GET /api/portal/invoices/`` — the customer's invoices, OPEN
 *  first then PAID then VOIDED. Includes nested charges + refunds
 *  so the Pay-now button + payment-history timeline render in one
 *  query. */
export function usePortalInvoices() {
  return useQuery<PortalInvoice[]>({
    queryKey: PORTAL_INVOICES_KEY,
    queryFn: () => api.get<PortalInvoice[]>('/api/portal/invoices/'),
    refetchOnWindowFocus: true,
  });
}


// ── Booking (public read endpoints + portal-authed submit) ────────


export interface BookableService {
  id: number;
  name: string;
  description: string;
  duration_minutes: number;
  price_cents: number;
  category_name: string;
  category_color: string;
}

export interface BookableProvider {
  id: number;
  display_name: string;
  job_title: string;
}

export interface BookableSlot {
  start: string;
  end: string;
  available: boolean;
  provider_id: number | null;
}

/** Services available for online booking on a given tenant. Public
 *  endpoint — no portal auth required since the same data also drives
 *  the unauthenticated booking page. */
export function useBookableServices(tenantSlug: string | undefined) {
  return useQuery<BookableService[]>({
    queryKey: ['portal', 'booking', 'services', tenantSlug ?? ''],
    queryFn: () =>
      api.get<BookableService[]>(`/api/booking/${tenantSlug}/services/`),
    enabled: !!tenantSlug,
    staleTime: 5 * 60 * 1000,
  });
}

export function useBookableProviders(
  tenantSlug: string | undefined,
  serviceId: number | undefined,
) {
  return useQuery<BookableProvider[]>({
    queryKey: ['portal', 'booking', 'providers', tenantSlug ?? '', serviceId ?? 0],
    queryFn: () =>
      api.get<BookableProvider[]>(
        `/api/booking/${tenantSlug}/providers/?service=${serviceId}`,
      ),
    enabled: !!tenantSlug && !!serviceId,
    staleTime: 60 * 1000,
  });
}

export function useBookableSlots(
  tenantSlug: string | undefined,
  opts: { serviceId?: number; providerId?: number; date?: string },
) {
  const params = new URLSearchParams();
  if (opts.serviceId) params.set('service', String(opts.serviceId));
  if (opts.providerId) params.set('provider', String(opts.providerId));
  if (opts.date) params.set('date', opts.date);

  return useQuery<BookableSlot[]>({
    queryKey: [
      'portal', 'booking', 'slots',
      tenantSlug ?? '', opts.serviceId ?? 0, opts.providerId ?? 0, opts.date ?? '',
    ],
    queryFn: () =>
      api.get<BookableSlot[]>(
        `/api/booking/${tenantSlug}/slots/?${params.toString()}`,
      ),
    enabled:
      !!tenantSlug && !!opts.serviceId && !!opts.providerId && !!opts.date,
    // Don't cache aggressively — slot availability changes the moment
    // someone else books a slot. 30s feels OK without being chatty.
    staleTime: 30 * 1000,
  });
}

export interface BookAppointmentInput {
  service_id: number;
  provider_id: number;
  start_time: string;
  notes?: string;
}

export function useBookAppointment() {
  const qc = useQueryClient();
  return useMutation<PortalAppointment, Error, BookAppointmentInput>({
    mutationFn: (input) =>
      api.post<PortalAppointment>('/api/portal/booking/submit/', input),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: APPOINTMENTS_KEY });
    },
  });
}
