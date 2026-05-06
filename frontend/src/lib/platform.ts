/**
 * Platform admin hooks.
 *
 * The `/platform/*` surface lets Lumè-the-company manage its
 * customer tenants (the spas). Backend endpoints are gated to
 * `is_superuser=True`; the frontend mirrors that gate before
 * even rendering the route group.
 *
 * Distinct from the tenant-scoped CRM hooks under `/lib/` —
 * platform endpoints are CROSS-TENANT and don't need (or use)
 * the X-Tenant-Slug header. The shared `api` wrapper still
 * forwards it harmlessly.
 */

'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from './api';

export type PlatformTenantStatus = 'trial' | 'active' | 'suspended' | 'cancelled';

export interface PlatformTenantListItem {
  id: number;
  name: string;
  slug: string;
  status: PlatformTenantStatus;
  member_count: number;
  location_count: number;
  owner_email: string | null;
  created_at: string;
  updated_at: string;
}

export interface PlatformTenantMember {
  id: number;
  user_email: string;
  user_first_name: string;
  user_last_name: string;
  role: string;
  role_display: string;
  is_active: boolean;
  is_bookable: boolean;
  created_at: string;
}

export interface PlatformTenantDetail extends PlatformTenantListItem {
  primary_color: string;
  logo_url: string;
  members: PlatformTenantMember[];
}

export interface PlatformTenantDetailWithTempPassword extends PlatformTenantDetail {
  /** Returned ONLY on POST /tenants/ when a new owner user was provisioned. */
  owner_temp_password?: string;
}

export interface PlatformSummary {
  total_tenants: number;
  by_status: Record<PlatformTenantStatus, number>;
  recent_signups: PlatformTenantListItem[];
  recent_activity: {
    timestamp: string;
    action: string;
    user_email: string | null;
    event: string | null;
    tenant_slug: string | null;
  }[];
}

const PLATFORM_KEY = ['platform'] as const;

// ── Tenants ─────────────────────────────────────────────────────────

export function usePlatformTenants() {
  return useQuery<PlatformTenantListItem[]>({
    queryKey: [...PLATFORM_KEY, 'tenants'],
    queryFn: () => api.get<PlatformTenantListItem[]>('/api/platform/tenants/'),
    staleTime: 30 * 1000,
  });
}

export function usePlatformTenant(slug: string | undefined) {
  return useQuery<PlatformTenantDetail>({
    queryKey: [...PLATFORM_KEY, 'tenant', slug ?? ''],
    queryFn: () => api.get<PlatformTenantDetail>(`/api/platform/tenants/${slug}/`),
    enabled: !!slug,
  });
}

export interface CreatePlatformTenantInput {
  name: string;
  slug: string;
  owner_email: string;
  owner_first_name?: string;
  owner_last_name?: string;
  status?: PlatformTenantStatus;
}

export function useCreatePlatformTenant() {
  const qc = useQueryClient();
  return useMutation<PlatformTenantDetailWithTempPassword, Error, CreatePlatformTenantInput>({
    mutationFn: (input) =>
      api.post<PlatformTenantDetailWithTempPassword>('/api/platform/tenants/', input),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: [...PLATFORM_KEY, 'tenants'] });
      qc.invalidateQueries({ queryKey: [...PLATFORM_KEY, 'summary'] });
    },
  });
}

export interface UpdatePlatformTenantInput {
  name?: string;
  primary_color?: string;
  logo_url?: string;
}

export function useUpdatePlatformTenant(slug: string) {
  const qc = useQueryClient();
  return useMutation<PlatformTenantDetail, Error, UpdatePlatformTenantInput>({
    mutationFn: (input) =>
      api.patch<PlatformTenantDetail>(`/api/platform/tenants/${slug}/`, input),
    onSuccess: (updated) => {
      qc.setQueryData([...PLATFORM_KEY, 'tenant', slug], updated);
      qc.invalidateQueries({ queryKey: [...PLATFORM_KEY, 'tenants'] });
    },
  });
}

export function useSuspendPlatformTenant(slug: string) {
  const qc = useQueryClient();
  return useMutation<PlatformTenantDetail, Error, { reason: string }>({
    mutationFn: (input) =>
      api.post<PlatformTenantDetail>(`/api/platform/tenants/${slug}/suspend/`, input),
    onSuccess: (updated) => {
      qc.setQueryData([...PLATFORM_KEY, 'tenant', slug], updated);
      qc.invalidateQueries({ queryKey: [...PLATFORM_KEY, 'tenants'] });
      qc.invalidateQueries({ queryKey: [...PLATFORM_KEY, 'summary'] });
    },
  });
}

export function useReactivatePlatformTenant(slug: string) {
  const qc = useQueryClient();
  return useMutation<PlatformTenantDetail, Error, void>({
    mutationFn: () =>
      api.post<PlatformTenantDetail>(`/api/platform/tenants/${slug}/reactivate/`, {}),
    onSuccess: (updated) => {
      qc.setQueryData([...PLATFORM_KEY, 'tenant', slug], updated);
      qc.invalidateQueries({ queryKey: [...PLATFORM_KEY, 'tenants'] });
      qc.invalidateQueries({ queryKey: [...PLATFORM_KEY, 'summary'] });
    },
  });
}

// ── Summary ─────────────────────────────────────────────────────────

export function usePlatformSummary() {
  return useQuery<PlatformSummary>({
    queryKey: [...PLATFORM_KEY, 'summary'],
    queryFn: () => api.get<PlatformSummary>('/api/platform/summary/'),
    staleTime: 30 * 1000,
  });
}

// ── Display helpers ────────────────────────────────────────────────

export const STATUS_LABELS: Record<PlatformTenantStatus, string> = {
  trial: 'Trial',
  active: 'Active',
  suspended: 'Suspended',
  cancelled: 'Cancelled',
};

/** Tone classes for status pills under the dark theme. */
export const STATUS_TONE: Record<PlatformTenantStatus, string> = {
  trial: 'bg-amber-500/15 text-amber-300 ring-amber-500/30',
  active: 'bg-emerald-500/15 text-emerald-300 ring-emerald-500/30',
  suspended: 'bg-rose-500/15 text-rose-300 ring-rose-500/30',
  cancelled: 'bg-foreground/10 text-foreground/60 ring-foreground/20',
};
