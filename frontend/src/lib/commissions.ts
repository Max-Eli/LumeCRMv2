/**
 * Commissions hooks.
 *
 * Pairs with `apps.commissions` at `/api/commission-rules/` (CRUD)
 * and `/api/commission-entries/` (read-only ledger + totals).
 *
 * Mutations on entries happen via the invoice transitions
 * (close → accrue, reopen → reverse) — never via this surface.
 */

'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from './api';

// ── Rules ───────────────────────────────────────────────────────────

export interface CommissionOverrideOutput {
  id: number;
  category: number;
  category_name: string;
  category_color: string;
  rate_percent: string; // DRF Decimal as string
}

export interface CommissionOverrideInput {
  category_id: number;
  rate_percent: string | number;
}

export interface CommissionRule {
  id: number;
  membership: number;
  membership_user_email: string;
  membership_user_first_name: string;
  membership_user_last_name: string;
  membership_role: string;
  base_rate_percent: string;
  is_active: boolean;
  notes: string;
  overrides: CommissionOverrideOutput[];
  created_at: string;
  updated_at: string;
}

export interface CreateCommissionRuleInput {
  membership: number;
  base_rate_percent: string | number;
  is_active?: boolean;
  notes?: string;
  overrides_input?: CommissionOverrideInput[];
}

export type UpdateCommissionRuleInput = Partial<CreateCommissionRuleInput>;

const RULES_KEY = ['commission-rules'] as const;
const ruleKey = (id: number) => [...RULES_KEY, id] as const;

export function useCommissionRules(opts: { activeOnly?: boolean } = {}) {
  const params = new URLSearchParams();
  if (opts.activeOnly !== undefined) {
    params.set('active', opts.activeOnly ? 'true' : 'false');
  }
  const qs = params.toString();
  const path = qs
    ? `/api/commission-rules/?${qs}`
    : '/api/commission-rules/';
  return useQuery<CommissionRule[]>({
    queryKey: [...RULES_KEY, opts.activeOnly ?? null],
    queryFn: () => api.get<CommissionRule[]>(path),
  });
}

export function useCommissionRule(id: number | undefined) {
  return useQuery<CommissionRule>({
    queryKey: id ? ruleKey(id) : ['commission-rules', 'disabled'],
    queryFn: () => api.get<CommissionRule>(`/api/commission-rules/${id}/`),
    enabled: typeof id === 'number' && id > 0,
  });
}

export function useCreateCommissionRule() {
  const qc = useQueryClient();
  return useMutation<CommissionRule, Error, CreateCommissionRuleInput>({
    mutationFn: (input) =>
      api.post<CommissionRule>('/api/commission-rules/', input),
    onSuccess: (created) => {
      qc.invalidateQueries({ queryKey: RULES_KEY });
      qc.setQueryData(ruleKey(created.id), created);
    },
  });
}

export function useUpdateCommissionRule(id: number) {
  const qc = useQueryClient();
  return useMutation<CommissionRule, Error, UpdateCommissionRuleInput>({
    mutationFn: (input) =>
      api.patch<CommissionRule>(`/api/commission-rules/${id}/`, input),
    onSuccess: (updated) => {
      qc.setQueryData(ruleKey(updated.id), updated);
      qc.invalidateQueries({ queryKey: RULES_KEY });
    },
  });
}

export function useDeleteCommissionRule() {
  const qc = useQueryClient();
  return useMutation<void, Error, number>({
    mutationFn: (id) => api.delete(`/api/commission-rules/${id}/`),
    onSuccess: () => qc.invalidateQueries({ queryKey: RULES_KEY }),
  });
}

// ── Entries (ledger) ────────────────────────────────────────────────

export type CommissionEntryKind = 'accrual' | 'reversal';

export interface CommissionEntry {
  id: number;
  membership: number;
  membership_user_email: string;
  membership_user_first_name: string;
  membership_user_last_name: string;
  invoice: number;
  invoice_number: string;
  invoice_line: number;
  line_description: string;
  kind: CommissionEntryKind;
  rate_percent: string;
  line_subtotal_cents: number;
  amount_cents: number;
  reverses: number | null;
  note: string;
  by_user_email: string | null;
  accrued_at: string;
}

const ENTRIES_KEY = ['commission-entries'] as const;

export interface CommissionEntryFilter {
  membershipId?: number;
  invoiceId?: number;
  /** ISO 8601. */
  from?: string;
  /** ISO 8601. */
  to?: string;
  kind?: CommissionEntryKind;
}

export function useCommissionEntries(opts: CommissionEntryFilter = {}) {
  const params = new URLSearchParams();
  if (opts.membershipId) params.set('membership', String(opts.membershipId));
  if (opts.invoiceId) params.set('invoice', String(opts.invoiceId));
  if (opts.from) params.set('from', opts.from);
  if (opts.to) params.set('to', opts.to);
  if (opts.kind) params.set('kind', opts.kind);
  const qs = params.toString();
  const path = qs
    ? `/api/commission-entries/?${qs}`
    : '/api/commission-entries/';
  return useQuery<CommissionEntry[]>({
    queryKey: [
      ...ENTRIES_KEY,
      opts.membershipId ?? 0,
      opts.invoiceId ?? 0,
      opts.from ?? '',
      opts.to ?? '',
      opts.kind ?? '',
    ],
    queryFn: () => api.get<CommissionEntry[]>(path),
  });
}

// ── Totals ──────────────────────────────────────────────────────────

export interface CommissionTotalRow {
  membership_id: number;
  first_name: string;
  last_name: string;
  email: string;
  role: string;
  net_cents: number;
  accrual_total_cents: number;
  reversal_total_cents: number;
}

export interface CommissionTotalsFilter {
  membershipId?: number;
  from?: string;
  to?: string;
}

export function useCommissionTotals(opts: CommissionTotalsFilter = {}) {
  const params = new URLSearchParams();
  if (opts.membershipId) params.set('membership', String(opts.membershipId));
  if (opts.from) params.set('from', opts.from);
  if (opts.to) params.set('to', opts.to);
  const qs = params.toString();
  const path = qs
    ? `/api/commission-entries/totals/?${qs}`
    : '/api/commission-entries/totals/';
  return useQuery<CommissionTotalRow[]>({
    queryKey: [
      ...ENTRIES_KEY,
      'totals',
      opts.membershipId ?? 0,
      opts.from ?? '',
      opts.to ?? '',
    ],
    queryFn: () => api.get<CommissionTotalRow[]>(path),
  });
}

// ── Money helpers ──────────────────────────────────────────────────

export function formatCents(cents: number): string {
  const sign = cents < 0 ? '-' : '';
  return `${sign}$${(Math.abs(cents) / 100).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}
