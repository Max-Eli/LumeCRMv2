/**
 * Concrete KPI tiles wired to specific report endpoints.
 *
 * Each tile is its own client component because each one fetches a
 * different report with a different date window. Wrapping them
 * separately also means tanstack-query caches each independently,
 * so navigating away and back doesn't refetch tiles whose data is
 * still fresh.
 *
 * Tile semantics — which way is "good":
 *   - Revenue today: higher is better
 *   - Today's appointments: neutral (count, not a goal)
 *   - New clients this month: higher is better
 *   - No-show rate this month: LOWER is better
 *
 * Loading states use the KpiTile loading skeleton so the grid
 * doesn't jump on first paint.
 */

'use client';

import {
  formatCents,
  formatNumber,
  useAppointmentsByStatus,
  useNewVsReturning,
  useNoShowRate,
  useSalesByDateRange,
} from '@/lib/reports';

import {
  deltaPct,
  deltaTone,
  monthToDateVsLastMonth,
  monthToDateWindow,
  todayVsSameDayLastWeek,
  todayWindow,
} from './date-windows';
import { KpiTile } from './kpi-tile';

// ── Today's revenue ───────────────────────────────────────────────────

export function RevenueTodayTile() {
  const w = todayVsSameDayLastWeek();
  const today = useSalesByDateRange(w.current);
  const lastWeek = useSalesByDateRange(w.comparison);

  const loading = today.isLoading || lastWeek.isLoading;
  const todayCents = today.data?.summary.total_gross_cents ?? 0;
  const lastWeekCents = lastWeek.data?.summary.total_gross_cents ?? 0;
  const pct = today.data && lastWeek.data ? deltaPct(todayCents, lastWeekCents) : null;
  const invoiceCount = today.data?.summary.paid_invoice_count ?? 0;

  return (
    <KpiTile
      label="Revenue today"
      value={formatCents(todayCents)}
      subline={
        invoiceCount === 0
          ? 'No paid invoices yet today'
          : `${formatNumber(invoiceCount)} paid invoice${invoiceCount === 1 ? '' : 's'}`
      }
      deltaPct={pct}
      deltaTone={deltaTone(pct, 'higher_is_better')}
      deltaHint={w.comparisonLabel}
      loading={loading}
    />
  );
}

// ── Today's appointments ──────────────────────────────────────────────

export function AppointmentsTodayTile() {
  const { data, isLoading } = useAppointmentsByStatus(todayWindow());
  const total = data?.summary.total_appointments ?? 0;

  // Build a tight subline summarizing the day-of-business state.
  const byStatus: Record<string, number> = {};
  (data?.rows ?? []).forEach((r) => {
    byStatus[r.status] = r.appointment_count;
  });
  const completed = (byStatus['completed'] ?? 0) + (byStatus['checked_in'] ?? 0);
  const upcoming = (byStatus['booked'] ?? 0) + (byStatus['confirmed'] ?? 0);
  const subline =
    total === 0
      ? 'No appointments scheduled'
      : `${formatNumber(completed)} done · ${formatNumber(upcoming)} upcoming`;

  return (
    <KpiTile
      label="Appointments today"
      value={formatNumber(total)}
      subline={subline}
      loading={isLoading}
    />
  );
}

// ── New clients this month ────────────────────────────────────────────

export function NewClientsThisMonthTile() {
  const w = monthToDateVsLastMonth();
  const current = useNewVsReturning(w.current);
  const previous = useNewVsReturning(w.comparison);

  const loading = current.isLoading || previous.isLoading;
  const newCount = current.data?.summary.new_count ?? 0;
  const prevNewCount = previous.data?.summary.new_count ?? 0;
  const pct = current.data && previous.data ? deltaPct(newCount, prevNewCount) : null;

  return (
    <KpiTile
      label="New clients this month"
      value={formatNumber(newCount)}
      subline="First-time visits in the window"
      deltaPct={pct}
      deltaTone={deltaTone(pct, 'higher_is_better')}
      deltaHint={w.comparisonLabel}
      loading={loading}
    />
  );
}

// ── No-show rate this month ───────────────────────────────────────────

export function NoShowRateThisMonthTile() {
  const w = monthToDateVsLastMonth();
  const current = useNoShowRate(w.current);
  const previous = useNoShowRate(w.comparison);

  const loading = current.isLoading || previous.isLoading;
  const rate = current.data?.summary.overall_no_show_rate_pct ?? 0;
  const prevRate = previous.data?.summary.overall_no_show_rate_pct ?? 0;
  // Delta is in percentage POINTS for a rate metric (going from 4% to 6%
  // is "+2 points", not "+50%"). We compute as straight subtraction and
  // pass to DeltaArrow which uses the same suffix; semantically it's a
  // small abuse but reads cleanly to operators ("no-show rate down 1.2pp").
  const pct = current.data && previous.data ? rate - prevRate : null;
  const totalAppts = current.data?.summary.total_appointments ?? 0;
  const totalNoShows = current.data?.summary.total_no_shows ?? 0;

  return (
    <KpiTile
      label="No-show rate this month"
      value={`${rate.toFixed(1)}%`}
      subline={
        totalAppts === 0
          ? 'No appointments yet this month'
          : `${formatNumber(totalNoShows)} of ${formatNumber(totalAppts)} appointments`
      }
      deltaPct={pct}
      deltaTone={deltaTone(pct, 'lower_is_better')}
      deltaHint={w.comparisonLabel}
      loading={loading}
    />
  );
}
