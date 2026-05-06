/**
 * Date-window helpers for the dashboard.
 *
 * The dashboard composes multiple report endpoints with different
 * "what window do we mean" semantics — today, this month, last 30
 * days, and a few comparison windows for delta arrows. Centralizing
 * the window math here keeps the page components free of date
 * arithmetic and makes the "vs same day last week" comparisons
 * audit-able from one place.
 *
 * All windows are computed in the browser's local timezone (the
 * tenant's per-location timezone bucketing is a Phase 0c polish
 * item — see ADR 0013). For US-based tenants on US-Eastern this is
 * indistinguishable; multi-tenant cross-timezone cases drift up to
 * one day at the boundary.
 */

import { toIsoDate } from '@/lib/reports';

export interface Window {
  date_from: string;
  date_to: string;
  // Index signature so a `Window` satisfies the report hooks'
  // `DateRangeParams` (which has the index signature for the same
  // reason — see lib/reports.ts).
  [k: string]: string | undefined;
}

/** A `Window` plus a parallel "comparison" window used to compute deltas. */
export interface WindowWithComparison {
  current: Window;
  comparison: Window;
  /** Human-readable label of what the comparison represents
   *  ("vs. same day last week", "vs. last month"). */
  comparisonLabel: string;
}

function startOfDay(d: Date): Date {
  const out = new Date(d);
  out.setHours(0, 0, 0, 0);
  return out;
}

function addDays(d: Date, n: number): Date {
  const out = new Date(d);
  out.setDate(out.getDate() + n);
  return out;
}

function firstOfMonth(d: Date): Date {
  return new Date(d.getFullYear(), d.getMonth(), 1);
}

function firstOfPreviousMonth(d: Date): Date {
  return new Date(d.getFullYear(), d.getMonth() - 1, 1);
}

function lastOfPreviousMonth(d: Date): Date {
  return new Date(d.getFullYear(), d.getMonth(), 0);
}

/** Today (start-of-day → start-of-day) — single-day window. */
export function todayWindow(): Window {
  const today = startOfDay(new Date());
  return { date_from: toIsoDate(today), date_to: toIsoDate(today) };
}

/** Today vs. the same day last week. Used for "today's revenue" delta. */
export function todayVsSameDayLastWeek(): WindowWithComparison {
  const today = startOfDay(new Date());
  const lastWeekSameDay = addDays(today, -7);
  return {
    current: { date_from: toIsoDate(today), date_to: toIsoDate(today) },
    comparison: { date_from: toIsoDate(lastWeekSameDay), date_to: toIsoDate(lastWeekSameDay) },
    comparisonLabel: 'vs. same day last week',
  };
}

/** This month so far. Used for "new clients this month" + "no-show this month." */
export function monthToDateWindow(): Window {
  const today = startOfDay(new Date());
  return { date_from: toIsoDate(firstOfMonth(today)), date_to: toIsoDate(today) };
}

/** This-month-to-date vs. the equivalent days of last month. The comparison
 *  is "first N days of last month" where N matches the elapsed days of this
 *  month — apples to apples. On the 4th of June we compare June 1-4 to May 1-4. */
export function monthToDateVsLastMonth(): WindowWithComparison {
  const today = startOfDay(new Date());
  const monthStart = firstOfMonth(today);
  const elapsed = today.getDate(); // 1-31
  const lastMonthStart = firstOfPreviousMonth(today);
  const lastMonthEquivalentEnd = addDays(lastMonthStart, elapsed - 1);
  // Cap at the actual last day of last month (e.g. comparing March 31 has no
  // direct counterpart in February — clamp to Feb 28 / 29).
  const lastMonthLastDay = lastOfPreviousMonth(today);
  const cappedEnd = lastMonthEquivalentEnd > lastMonthLastDay ? lastMonthLastDay : lastMonthEquivalentEnd;
  return {
    current: { date_from: toIsoDate(monthStart), date_to: toIsoDate(today) },
    comparison: { date_from: toIsoDate(lastMonthStart), date_to: toIsoDate(cappedEnd) },
    comparisonLabel: 'vs. same days last month',
  };
}

/** Last 30 days, ending today. Used for the hero revenue chart. */
export function last30DaysWindow(): Window {
  const today = startOfDay(new Date());
  const start = addDays(today, -29);
  return { date_from: toIsoDate(start), date_to: toIsoDate(today) };
}

/** Compute a delta percentage between two cents values, safe for /0. */
export function deltaPct(current: number, comparison: number): number | null {
  if (comparison === 0) {
    // Going from 0 to anything is technically "infinite" growth — we
    // surface that as null and let the UI show "—" rather than a
    // misleadingly huge percentage. Exception: 0→0 returns 0.
    return current === 0 ? 0 : null;
  }
  return ((current - comparison) / comparison) * 100;
}

/** Pick a tone for a delta — positive = good for revenue / new clients,
 *  positive = BAD for no-show rate. The dashboard caller specifies which
 *  semantic it wants. */
export type DeltaSemantic = 'higher_is_better' | 'lower_is_better';

export function deltaTone(
  pct: number | null,
  semantic: DeltaSemantic,
): 'positive' | 'negative' | 'neutral' {
  if (pct === null || pct === 0) return 'neutral';
  const isUp = pct > 0;
  if (semantic === 'higher_is_better') return isUp ? 'positive' : 'negative';
  return isUp ? 'negative' : 'positive';
}
