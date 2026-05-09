/**
 * Dashboard tile: the current user's commission earnings month-to-date.
 *
 * Resolves the viewer's own membership id by matching their session
 * email against `useAllMemberships()`, then asks
 * `useCommissionTotals({ membershipId, from, to })` for their net for
 * the current month. Reversal-only periods render as a negative
 * number (intended — visibility into refund clawbacks matters).
 *
 * Reused on every role's dashboard that surfaces commissions
 * (provider/manager/owner). Front-desk + bookkeeper + marketing skip
 * it because they don't accrue commission in v1.
 */

'use client';

import { useMemo, useState } from 'react';

import { useUser } from '@/lib/auth';
import {
  formatCents,
  useCommissionTotals,
} from '@/lib/commissions';
import { useAllMemberships } from '@/lib/tenant';

import { KpiTile } from './kpi-tile';

export function MyEarningsTile() {
  const { data: user } = useUser();

  // Lazy useState to keep `Date.now()` out of render — React Compiler
  // purity rule will reject otherwise. We don't need this to refresh
  // after mount; the tile is a snapshot, not a live ticker.
  const [refMs] = useState<number>(() => Date.now());
  const { from, to } = useMemo(() => mtdWindow(refMs), [refMs]);

  const memberships = useAllMemberships();
  const ownMembershipId = useMemo(() => {
    if (!user) return null;
    const match = (memberships.data ?? []).find(
      (m) => m.user_email === user.email,
    );
    return match?.id ?? null;
  }, [memberships.data, user]);

  const totals = useCommissionTotals({
    membershipId: ownMembershipId ?? undefined,
    from,
    to,
  });

  const loading = memberships.isLoading || totals.isLoading;
  const row = totals.data?.[0] ?? null;
  const net = row?.net_cents ?? 0;
  const accrued = row?.accrual_total_cents ?? 0;
  const reversed = row?.reversal_total_cents ?? 0;

  const subline =
    !loading && row === null
      ? 'No accruals yet this month'
      : reversed < 0
        ? `${formatCents(accrued)} earned, ${formatCents(reversed)} reversed`
        : `${formatCents(accrued)} earned`;

  return (
    <KpiTile
      label="Your commissions MTD"
      value={formatCents(net)}
      subline={subline}
      loading={loading}
    />
  );
}

function mtdWindow(nowMs: number): { from: string; to: string } {
  const now = new Date(nowMs);
  const start = new Date(now.getFullYear(), now.getMonth(), 1, 0, 0, 0);
  return { from: start.toISOString(), to: now.toISOString() };
}
