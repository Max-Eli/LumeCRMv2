/**
 * Shared time-grid math for the calendar's week + day-grid views:
 * the hour window, overlap packing, and layout constants.
 */

import type { Appointment } from './appointments';

export const HOUR_PX = 60;
export const GUTTER_PX = 44;
export const MAX_COLS = 3;
export const DEFAULT_START_HOUR = 8;
export const DEFAULT_END_HOUR = 20;
/** Block colour when a service has no category colour. */
export const FALLBACK_COLOR = '#71717a';

export interface ApptCell {
  kind: 'appt';
  appt: Appointment;
  topMin: number;
  durationMin: number;
  col: number;
  cols: number;
}
export interface OverflowCell {
  kind: 'overflow';
  topMin: number;
  durationMin: number;
  col: number;
  cols: number;
  count: number;
}
export type Cell = ApptCell | OverflowCell;

/** Local minutes-from-midnight of an ISO timestamp. */
export function minutesOf(iso: string): number {
  const d = new Date(iso);
  return d.getHours() * 60 + d.getMinutes();
}

/** "8 AM" / "12 PM" — gutter hour label. */
export function hourLabel(h: number): string {
  if (h === 0 || h === 24) return '12 AM';
  if (h === 12) return '12 PM';
  return h < 12 ? `${h} AM` : `${h - 12} PM`;
}

/** Visible hour window — business hours, widened to fit any outliers. */
export function computeHourWindow(appts: Appointment[]): {
  startHour: number;
  endHour: number;
} {
  let lo = DEFAULT_START_HOUR;
  let hi = DEFAULT_END_HOUR;
  for (const a of appts) {
    const s = new Date(a.start_time);
    const e = new Date(a.end_time);
    lo = Math.min(lo, s.getHours());
    hi = Math.max(hi, e.getMinutes() > 0 ? e.getHours() + 1 : e.getHours());
  }
  const startHour = Math.max(0, lo);
  const endHour = Math.min(24, Math.max(hi, startHour + 1));
  return { startHour, endHour };
}

/** Overlap packing — clusters of mutually-overlapping appointments are
 *  packed side-by-side, capped at MAX_COLS columns; anything past the
 *  cap collapses into one "+N" tile. */
export function packDay(appts: Appointment[]): Cell[] {
  const items = appts
    .map((appt) => {
      const topMin = minutesOf(appt.start_time);
      const endMin = minutesOf(appt.end_time);
      return { appt, topMin, endMin: Math.max(endMin, topMin + 5) };
    })
    .sort((a, b) => a.topMin - b.topMin || a.endMin - b.endMin);

  const result: Cell[] = [];
  let cluster: typeof items = [];
  let clusterEnd = -1;

  const flush = () => {
    if (cluster.length === 0) return;
    const columnEnds: number[] = [];
    const colOf = new Map<Appointment, number>();
    for (const it of cluster) {
      let placed = -1;
      for (let c = 0; c < columnEnds.length; c++) {
        if (it.topMin >= columnEnds[c]) {
          placed = c;
          break;
        }
      }
      if (placed === -1) {
        placed = columnEnds.length;
        columnEnds.push(it.endMin);
      } else {
        columnEnds[placed] = it.endMin;
      }
      colOf.set(it.appt, placed);
    }
    const neededCols = columnEnds.length;

    if (neededCols <= MAX_COLS) {
      for (const it of cluster) {
        result.push({
          kind: 'appt',
          appt: it.appt,
          topMin: it.topMin,
          durationMin: it.endMin - it.topMin,
          col: colOf.get(it.appt) ?? 0,
          cols: neededCols,
        });
      }
    } else {
      const visibleCol = MAX_COLS - 1;
      const overflow: typeof items = [];
      for (const it of cluster) {
        const c = colOf.get(it.appt) ?? 0;
        if (c < visibleCol) {
          result.push({
            kind: 'appt',
            appt: it.appt,
            topMin: it.topMin,
            durationMin: it.endMin - it.topMin,
            col: c,
            cols: MAX_COLS,
          });
        } else {
          overflow.push(it);
        }
      }
      if (overflow.length > 0) {
        const ovTop = Math.min(...overflow.map((o) => o.topMin));
        const ovEnd = Math.max(...overflow.map((o) => o.endMin));
        result.push({
          kind: 'overflow',
          topMin: ovTop,
          durationMin: ovEnd - ovTop,
          col: visibleCol,
          cols: MAX_COLS,
          count: overflow.length,
        });
      }
    }
    cluster = [];
  };

  for (const it of items) {
    if (cluster.length > 0 && it.topMin >= clusterEnd) {
      flush();
      clusterEnd = -1;
    }
    cluster.push(it);
    clusterEnd = Math.max(clusterEnd, it.endMin);
  }
  flush();
  return result;
}
