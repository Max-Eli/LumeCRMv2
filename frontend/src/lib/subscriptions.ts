/**
 * Customer-facing membership plans + subscriptions.
 *
 * Pairs with `apps.memberships` at `/api/membership-plans/` (catalog)
 * and `/api/subscriptions/` (per-customer instances), plus invoice
 * action endpoints for sale + redemption.
 *
 * Lives in `subscriptions.ts` (not `memberships.ts`) because the
 * existing `memberships.ts` is the staff tenant-membership surface
 * — different concept. Type-namespacing both files would require
 * a wider rename; this gets us out of the collision cleanly.
 */

'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from './api';

// ── Catalog: MembershipPlan ─────────────────────────────────────────

export type BillingInterval = 'monthly' | 'annual';

export const BILLING_INTERVAL_LABELS: Record<BillingInterval, string> = {
  monthly: 'Monthly',
  annual: 'Annual',
};

export interface PlanItemOutput {
  id: number;
  service_id: number;
  service_name: string;
  service_price_cents: number;
  quantity_per_cycle: number;
  sort_order: number;
}

export interface PlanItemInput {
  service_id: number;
  quantity_per_cycle: number;
  sort_order?: number;
}

export interface MembershipPlan {
  id: number;
  name: string;
  sku: string;
  description: string;
  price_cents: number;
  price_dollars: string;
  /** DRF DecimalField returns as string for precision. */
  tax_rate_percent: string;
  billing_interval: BillingInterval;
  member_discount_percent: string;
  is_active: boolean;
  sort_order: number;
  items: PlanItemOutput[];
  a_la_carte_total_cents: number;
  implicit_discount_cents: number;
  created_at: string;
  updated_at: string;
}

export interface CreateMembershipPlanInput {
  name: string;
  sku?: string;
  description?: string;
  price_cents: number;
  tax_rate_percent?: string | number;
  billing_interval?: BillingInterval;
  member_discount_percent?: string | number;
  is_active?: boolean;
  sort_order?: number;
  items_input: PlanItemInput[];
}

export type UpdateMembershipPlanInput = Partial<CreateMembershipPlanInput>;

const PLANS_KEY = ['membership-plans'] as const;
const planKey = (id: number) => [...PLANS_KEY, id] as const;

export interface MembershipPlanFilter {
  q?: string;
  activeOnly?: boolean;
}

export function useMembershipPlans(opts: MembershipPlanFilter = {}) {
  const params = new URLSearchParams();
  if (opts.q) params.set('q', opts.q);
  if (opts.activeOnly !== undefined) {
    params.set('active', opts.activeOnly ? 'true' : 'false');
  }
  const qs = params.toString();
  const path = qs
    ? `/api/membership-plans/?${qs}`
    : '/api/membership-plans/';
  return useQuery<MembershipPlan[]>({
    queryKey: [...PLANS_KEY, opts.q ?? '', opts.activeOnly ?? null],
    queryFn: () => api.get<MembershipPlan[]>(path),
  });
}

export function useMembershipPlan(id: number | undefined) {
  return useQuery<MembershipPlan>({
    queryKey: id ? planKey(id) : ['membership-plans', 'disabled'],
    queryFn: () => api.get<MembershipPlan>(`/api/membership-plans/${id}/`),
    enabled: typeof id === 'number' && id > 0,
  });
}

export function useCreateMembershipPlan() {
  const qc = useQueryClient();
  return useMutation<MembershipPlan, Error, CreateMembershipPlanInput>({
    mutationFn: (input) =>
      api.post<MembershipPlan>('/api/membership-plans/', input),
    onSuccess: (created) => {
      qc.invalidateQueries({ queryKey: PLANS_KEY });
      qc.setQueryData(planKey(created.id), created);
    },
  });
}

export function useUpdateMembershipPlan(id: number) {
  const qc = useQueryClient();
  return useMutation<MembershipPlan, Error, UpdateMembershipPlanInput>({
    mutationFn: (input) =>
      api.patch<MembershipPlan>(`/api/membership-plans/${id}/`, input),
    onSuccess: (updated) => {
      qc.setQueryData(planKey(updated.id), updated);
      qc.invalidateQueries({ queryKey: PLANS_KEY });
    },
  });
}

export function useDeleteMembershipPlan() {
  const qc = useQueryClient();
  return useMutation<void, Error, number>({
    mutationFn: (id) => api.delete(`/api/membership-plans/${id}/`),
    onSuccess: () => qc.invalidateQueries({ queryKey: PLANS_KEY }),
  });
}

// ── Per-customer Subscription ───────────────────────────────────────

export type SubscriptionStatus =
  | 'pending'
  | 'active'
  | 'expired'
  | 'cancelled';

export interface SubscriptionItem {
  id: number;
  service: number;
  service_name: string;
  quantity_per_cycle: number;
  quantity_remaining: number;
  unit_value_cents: number;
  sort_order: number;
}

export interface SubscriptionRedemptionLedgerRow {
  id: number;
  subscription: number;
  item: number;
  service_name: string;
  quantity: number;
  invoice_line: number | null;
  appointment: number | null;
  by_user_email: string | null;
  note: string;
  redeemed_at: string;
}

export interface Subscription {
  id: number;
  customer: number;
  customer_first_name: string;
  customer_last_name: string;
  plan: number;
  plan_name: string | null;
  source_invoice_line: number;
  name: string;
  description: string;
  price_cents: number;
  billing_interval: BillingInterval;
  member_discount_percent: string;
  started_at: string | null;
  current_period_starts_at: string | null;
  current_period_ends_at: string | null;
  status: SubscriptionStatus;
  auto_renew: boolean;
  cancelled_at: string | null;
  cancelled_by_email: string | null;
  cancel_reason: string;
  is_in_period: boolean;
  is_redeemable: boolean;
  total_credits_remaining: number;
  items: SubscriptionItem[];
  redemptions: SubscriptionRedemptionLedgerRow[];
  created_at: string;
  updated_at: string;
}

const SUBSCRIPTIONS_KEY = ['subscriptions'] as const;
const subscriptionKey = (id: number) => [...SUBSCRIPTIONS_KEY, id] as const;

export function useCustomerSubscriptions(
  customerId: number | undefined,
  opts: { status?: SubscriptionStatus } = {},
) {
  const params = new URLSearchParams();
  if (customerId) params.set('customer', String(customerId));
  if (opts.status) params.set('status', opts.status);
  const qs = params.toString();
  return useQuery<Subscription[]>({
    queryKey: [...SUBSCRIPTIONS_KEY, customerId ?? 0, opts.status ?? ''],
    queryFn: () => api.get<Subscription[]>(`/api/subscriptions/?${qs}`),
    enabled: typeof customerId === 'number' && customerId > 0,
  });
}

export interface CancelSubscriptionInput {
  reason: string;
}

export function useCancelSubscription(subscriptionId: number) {
  const qc = useQueryClient();
  return useMutation<Subscription, Error, CancelSubscriptionInput>({
    mutationFn: (input) =>
      api.post<Subscription>(
        `/api/subscriptions/${subscriptionId}/cancel/`,
        input,
      ),
    onSuccess: (updated) => {
      qc.setQueryData(subscriptionKey(updated.id), updated);
      qc.invalidateQueries({ queryKey: SUBSCRIPTIONS_KEY });
    },
  });
}

// ── Money helpers ───────────────────────────────────────────────────

export function centsFromDollars(input: string | number): number {
  if (input === '' || input == null) return 0;
  const n = typeof input === 'string' ? Number(input) : input;
  if (Number.isNaN(n)) return 0;
  return Math.round(n * 100);
}

export function dollarsFromCents(cents: number): string {
  return (cents / 100).toFixed(2);
}
