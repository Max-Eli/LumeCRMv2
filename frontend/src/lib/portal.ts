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
  service_name: string;
  service_duration_minutes: number;
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
