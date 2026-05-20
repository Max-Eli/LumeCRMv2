/**
 * Commission data. Pairs with `apps.commissions` at
 * `/api/commission-entries/` (read-only ledger + per-provider totals).
 * A provider sees their own rows; owners/managers see the team's.
 */

import { useQuery } from '@tanstack/react-query';

import { useAuth } from './auth';

export type CommissionEntryKind = 'accrual' | 'reversal';

export interface CommissionEntry {
  id: number;
  membership_user_first_name: string;
  membership_user_last_name: string;
  invoice_number: string;
  line_description: string;
  kind: CommissionEntryKind;
  rate_percent: string;
  line_subtotal_cents: number;
  amount_cents: number;
  accrued_at: string;
}

export interface CommissionTotalRow {
  membership_id: number;
  first_name: string;
  last_name: string;
  net_cents: number;
  accrual_total_cents: number;
  reversal_total_cents: number;
}

/** "$120.00" from a cents amount. */
export function formatCents(cents: number): string {
  const sign = cents < 0 ? '-' : '';
  return `${sign}$${(Math.abs(cents) / 100).toFixed(2)}`;
}

interface Range {
  from: string;
  to: string;
}

/** Per-provider commission totals for a period. */
export function useCommissionTotals(range: Range) {
  const { authedFetch } = useAuth();
  return useQuery({
    queryKey: ['commissions', 'totals', range.from, range.to],
    queryFn: () =>
      authedFetch<CommissionTotalRow[]>(
        `/api/commission-entries/totals/?from=${encodeURIComponent(range.from)}` +
          `&to=${encodeURIComponent(range.to)}`,
      ),
  });
}

/** The commission ledger for a period — one row per invoice line. */
export function useCommissionEntries(range: Range) {
  const { authedFetch } = useAuth();
  return useQuery({
    queryKey: ['commissions', 'entries', range.from, range.to],
    queryFn: () =>
      authedFetch<CommissionEntry[]>(
        `/api/commission-entries/?from=${encodeURIComponent(range.from)}` +
          `&to=${encodeURIComponent(range.to)}`,
      ),
  });
}
