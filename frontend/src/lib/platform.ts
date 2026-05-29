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

import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query';

import { api } from './api';

export type PlatformTenantStatus =
  | 'trial'
  | 'active'
  | 'past_due'
  | 'suspended'
  | 'cancelled';

export type PlatformPlan = 'trial' | 'starter' | 'pro' | 'enterprise';
export type PlatformBillingCycle = 'monthly' | 'annual';

export interface PlatformTenantListItem {
  id: number;
  name: string;
  slug: string;
  status: PlatformTenantStatus;
  /** Subscription tier — drives feature gating + capacity caps. */
  plan: PlatformPlan;
  billing_cycle: PlatformBillingCycle;
  /** True for the original launch spas that predate self-serve.
   *  Exempt from capacity gates + Stripe enrollment. Always show
   *  a "legacy" badge in the admin UI so ops knows not to touch
   *  their billing. */
  grandfathered: boolean;
  member_count: number;
  location_count: number;
  owner_email: string | null;
  billing_email: string;
  trial_ends_at: string | null;
  current_period_end: string | null;
  /** Integer days until trial expiry, rounded up; null when the
   *  tenant isn't in trial. Drives the "X days left" countdown chip. */
  trial_days_remaining: number | null;
  has_stripe_subscription: boolean;
  /** True when the tenant has a Stripe Customer on file — proxy for
   *  "they can be auto-charged when the trial ends." */
  has_payment_method: boolean;
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
  /** Stripe identifiers — useful for ops reconciliation against the
   *  Stripe dashboard. Empty for grandfathered tenants. */
  stripe_customer_id: string;
  stripe_subscription_id: string;
  /** Add-on quantities the tenant has purchased, keyed by addon
   *  identifier. Mirrors Stripe SubscriptionItem quantities. */
  addon_quantities: Record<string, number>;
  /** Current-period usage counters — reset on Stripe period roll. */
  current_period_sms_count: number;
  current_period_email_count: number;
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
  past_due: 'Past due',
  suspended: 'Suspended',
  cancelled: 'Cancelled',
};

/** Tone classes for status pills under the dark theme. */
export const STATUS_TONE: Record<PlatformTenantStatus, string> = {
  trial: 'bg-amber-500/15 text-amber-300 ring-amber-500/30',
  active: 'bg-emerald-500/15 text-emerald-300 ring-emerald-500/30',
  past_due: 'bg-orange-500/15 text-orange-300 ring-orange-500/30',
  suspended: 'bg-rose-500/15 text-rose-300 ring-rose-500/30',
  cancelled: 'bg-foreground/10 text-foreground/60 ring-foreground/20',
};

export const PLAN_LABELS: Record<PlatformPlan, string> = {
  trial: 'Trial',
  starter: 'Starter',
  pro: 'Pro',
  enterprise: 'Enterprise',
};


// ── Cross-tenant audit log (Platform Logs page) ────────────────────

/**
 * Action enum mirrors `apps.audit.models.AuditLog.Action` on the
 * backend. Keep these in sync — the platform filter UI lists them
 * verbatim.
 */
export type AuditAction =
  | 'create'
  | 'read'
  | 'update'
  | 'delete'
  | 'login'
  | 'logout'
  | 'login_failed'
  | 'export'
  | 'permission_granted'
  | 'permission_revoked';

export const AUDIT_ACTION_LABELS: Record<AuditAction, string> = {
  create: 'Create',
  read: 'Read',
  update: 'Update',
  delete: 'Delete',
  login: 'Login',
  logout: 'Logout',
  login_failed: 'Login failed',
  export: 'Export',
  permission_granted: 'Permission granted',
  permission_revoked: 'Permission revoked',
};

/** Tone class per action — dark theme. */
export const AUDIT_ACTION_TONE: Record<AuditAction, string> = {
  create: 'bg-emerald-500/15 text-emerald-300 ring-emerald-500/30',
  read: 'bg-foreground/10 text-foreground/70 ring-foreground/20',
  update: 'bg-sky-500/15 text-sky-300 ring-sky-500/30',
  delete: 'bg-rose-500/15 text-rose-300 ring-rose-500/30',
  login: 'bg-emerald-500/15 text-emerald-300 ring-emerald-500/30',
  logout: 'bg-foreground/10 text-foreground/70 ring-foreground/20',
  login_failed: 'bg-rose-500/15 text-rose-300 ring-rose-500/30',
  export: 'bg-violet-500/15 text-violet-300 ring-violet-500/30',
  permission_granted: 'bg-amber-500/15 text-amber-300 ring-amber-500/30',
  permission_revoked: 'bg-amber-500/15 text-amber-300 ring-amber-500/30',
};

export interface AuditEntry {
  id: number;
  timestamp: string;
  action: AuditAction;
  resource_type: string;
  resource_id: string;
  ip_address: string | null;
  metadata: Record<string, unknown>;
  tenant: { id: number; slug: string; name: string } | null;
  user: { id: number; email: string; full_name: string } | null;
}

export interface AuditLogPage {
  results: AuditEntry[];
  next_cursor: string | null;
}

export interface AuditLogFilters {
  q?: string;
  tenant?: string[];       // tenant slugs (multi-select)
  action?: AuditAction[];  // action enum (multi-select)
  resource_type?: string[];
  from?: string;           // ISO datetime
  to?: string;             // ISO datetime
  limit?: number;
  cursor?: string;
}

function buildAuditLogQuery(f: AuditLogFilters): string {
  const params = new URLSearchParams();
  if (f.q) params.set('q', f.q);
  if (f.tenant && f.tenant.length) params.set('tenant', f.tenant.join(','));
  if (f.action && f.action.length) params.set('action', f.action.join(','));
  if (f.resource_type && f.resource_type.length) {
    params.set('resource_type', f.resource_type.join(','));
  }
  if (f.from) params.set('from', f.from);
  if (f.to) params.set('to', f.to);
  if (f.limit) params.set('limit', String(f.limit));
  if (f.cursor) params.set('cursor', f.cursor);
  return params.toString();
}

/**
 * Cursor-paginated cross-tenant audit log query. Uses TanStack
 * `useInfiniteQuery` because we want the operator to scroll/load-
 * more rather than jump pages — newest-first reads naturally as a
 * timeline.
 */
export function usePlatformAuditLog(filters: AuditLogFilters) {
  const baseFilters = { ...filters };
  delete baseFilters.cursor;

  return useInfiniteQuery<AuditLogPage, Error>({
    queryKey: [...PLATFORM_KEY, 'audit-log', baseFilters],
    queryFn: ({ pageParam }) => {
      const q = buildAuditLogQuery({
        ...baseFilters,
        cursor: (pageParam as string | undefined) ?? undefined,
      });
      return api.get<AuditLogPage>(`/api/platform/audit-log/${q ? `?${q}` : ''}`);
    },
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
    staleTime: 10 * 1000,
  });
}
