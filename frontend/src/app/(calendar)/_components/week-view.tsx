/**
 * Week view — a 7-day time grid, Google-Calendar style.
 *
 * Layout:
 *   - A sticky header row: time-gutter spacer + 7 day headers
 *     (weekday abbrev + date pill, today emphasized).
 *   - A vertically scrollable body: hour-labelled time gutter on the
 *     left + 7 day columns. Appointments are absolutely-positioned
 *     colored blocks.
 *   - Overlapping appointments within a day are packed side-by-side,
 *     capped at 3 visible columns. A cluster that needs more collapses
 *     its 3rd+ columns into one "+N" tile — tapping it opens that day.
 *     Capping keeps every visible block at least a third of the column
 *     wide so it stays readable instead of slivering to nothing.
 *   - A red "now" line is drawn across today's column when the
 *     visible week contains the current date.
 *
 * Blocks show the customer name only — vertical position already
 * conveys the time, so printing "11:00 AM" inside a 40px block was
 * pure noise. Tapping a block opens the full <AppointmentPopover>.
 *
 * The visible hour window defaults to the tenant's business hours
 * but expands to cover any appointment that starts earlier / ends
 * later so nothing is clipped.
 */

'use client';

import { useMemo } from 'react';

import { type Appointment } from '@/lib/appointments';
import { cn } from '@/lib/utils';

import { AppointmentPopover } from './appointment-popover';

const GUTTER_PX = 44;
const HOUR_PX = 60;
const DEFAULT_START_HOUR = 8;
const DEFAULT_END_HOUR = 20;
const MAX_COLS = 3;

export interface WeekViewProps {
  /** Any date inside the week to render (YYYY-MM-DD). */
  date: string;
  timezone: string;
  /** Every appointment overlapping the visible week. */
  appointments: Appointment[];
  /** Tapping a day header (or a "+N more" tile) — jumps to that
   *  day's detailed view. */
  onSelectDay: (date: string) => void;
  /** Tenant business hours (integer hours); window expands past
   *  these if an appointment falls outside. */
  dayStartHour?: number;
  dayEndHour?: number;
}

interface ApptCell {
  kind: 'appt';
  appt: Appointment;
  topMin: number;
  durationMin: number;
  col: number;
  cols: number;
}
interface OverflowCell {
  kind: 'overflow';
  topMin: number;
  durationMin: number;
  col: number;
  cols: number;
  count: number;
}
type Cell = ApptCell | OverflowCell;

export function WeekView({
  date,
  timezone,
  appointments,
  onSelectDay,
  dayStartHour,
  dayEndHour,
}: WeekViewProps) {
  const focus = parseLocalDate(date);
  const todayStr = toISODate(new Date());

  // Sunday-anchored week.
  const days = useMemo(() => {
    const start = new Date(focus);
    start.setDate(start.getDate() - start.getDay());
    return Array.from({ length: 7 }, (_, i) => {
      const d = new Date(start);
      d.setDate(d.getDate() + i);
      return d;
    });
  }, [focus]);

  // Bucket appointments by local start date.
  const byDay = useMemo(() => {
    const map = new Map<string, Appointment[]>();
    for (const appt of appointments) {
      const key = toISODate(new Date(appt.start_time));
      const arr = map.get(key) ?? [];
      arr.push(appt);
      map.set(key, arr);
    }
    return map;
  }, [appointments]);

  // Visible window: business hours, widened to cover outliers.
  const { startHour, endHour } = useMemo(() => {
    let lo = dayStartHour ?? DEFAULT_START_HOUR;
    let hi = dayEndHour ?? DEFAULT_END_HOUR;
    for (const appt of appointments) {
      const s = new Date(appt.start_time);
      const e = new Date(appt.end_time);
      lo = Math.min(lo, s.getHours());
      hi = Math.max(hi, e.getMinutes() > 0 ? e.getHours() + 1 : e.getHours());
    }
    return { startHour: Math.max(0, lo), endHour: Math.min(24, Math.max(hi, lo + 1)) };
  }, [appointments, dayStartHour, dayEndHour]);

  const startMin = startHour * 60;
  const totalMin = (endHour - startHour) * 60;
  const bodyHeight = (totalMin / 60) * HOUR_PX;
  const hourLabels = Array.from({ length: endHour - startHour + 1 }, (_, i) => startHour + i);

  // "Now" line offset, only if the current week includes today.
  const now = new Date();
  const nowStr = toISODate(now);
  const showNow = days.some((d) => toISODate(d) === nowStr);
  const nowOffset = ((now.getHours() * 60 + now.getMinutes()) - startMin) / 60 * HOUR_PX;

  return (
    <div className="flex-1 min-h-0 flex flex-col bg-card">
      {/* Sticky day-of-week header */}
      <div
        className="flex shrink-0 border-b bg-card"
        style={{ paddingLeft: GUTTER_PX }}
      >
        {days.map((day) => {
          const iso = toISODate(day);
          const isToday = iso === todayStr;
          const count = (byDay.get(iso) ?? []).length;
          return (
            <button
              key={iso}
              type="button"
              onClick={() => onSelectDay(iso)}
              className="flex-1 min-w-0 flex flex-col items-center py-1.5 gap-0.5 hover:bg-muted/40 transition-colors"
            >
              <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
                {WEEKDAY_ABBR[day.getDay()]}
              </span>
              <span
                className={cn(
                  'inline-flex items-center justify-center size-6 rounded-full text-xs tabular-nums',
                  isToday
                    ? 'bg-foreground text-background font-semibold'
                    : 'text-foreground',
                )}
              >
                {day.getDate()}
              </span>
              {count > 0 ? (
                <span className="text-[9px] text-muted-foreground tabular-nums leading-none">
                  {count}
                </span>
              ) : (
                <span className="h-[9px]" aria-hidden />
              )}
            </button>
          );
        })}
      </div>

      {/* Scrollable time grid */}
      <div className="flex-1 min-h-0 overflow-y-auto">
        <div className="flex" style={{ height: bodyHeight }}>
          {/* Time gutter */}
          <div className="shrink-0 relative" style={{ width: GUTTER_PX }}>
            {hourLabels.map((h, i) => (
              <div
                key={h}
                className="absolute right-1 text-[10px] text-muted-foreground tabular-nums -translate-y-1/2"
                style={{ top: i * HOUR_PX }}
              >
                {i === 0 ? '' : formatHour(h)}
              </div>
            ))}
          </div>

          {/* Day columns */}
          <div className="flex flex-1 min-w-0 relative">
            {/* Hour grid lines spanning all columns */}
            {hourLabels.map((h, i) => (
              <div
                key={h}
                className="absolute inset-x-0 border-t border-border/50"
                style={{ top: i * HOUR_PX }}
                aria-hidden
              />
            ))}

            {days.map((day) => {
              const iso = toISODate(day);
              const dayAppts = byDay.get(iso) ?? [];
              const cells = packDay(dayAppts);
              const isToday = iso === nowStr;
              return (
                <div
                  key={iso}
                  className="flex-1 min-w-0 relative border-r border-border/50 last:border-r-0"
                >
                  {cells.map((cell, i) => (
                    <WeekCell
                      key={cell.kind === 'appt' ? cell.appt.id : `ov-${i}`}
                      cell={cell}
                      startMin={startMin}
                      timezone={timezone}
                      onOverflowClick={() => onSelectDay(iso)}
                    />
                  ))}
                  {isToday && showNow && nowOffset >= 0 && nowOffset <= bodyHeight ? (
                    <div
                      className="absolute inset-x-0 z-10 pointer-events-none"
                      style={{ top: nowOffset }}
                    >
                      <div className="h-px bg-red-500" />
                      <div className="absolute -left-1 -top-1 size-2 rounded-full bg-red-500" />
                    </div>
                  ) : null}
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}

function WeekCell({
  cell,
  startMin,
  timezone,
  onOverflowClick,
}: {
  cell: Cell;
  startMin: number;
  timezone: string;
  onOverflowClick: () => void;
}) {
  const top = ((cell.topMin - startMin) / 60) * HOUR_PX;
  const height = Math.max(16, (cell.durationMin / 60) * HOUR_PX);
  const widthPct = 100 / cell.cols;
  const posStyle: React.CSSProperties = {
    top,
    height,
    left: `calc(${cell.col * widthPct}% + 1px)`,
    width: `calc(${widthPct}% - 2px)`,
  };

  if (cell.kind === 'overflow') {
    return (
      <button
        type="button"
        onClick={onOverflowClick}
        className="absolute rounded-[4px] bg-muted/80 border border-border text-[10px] font-medium text-muted-foreground flex items-center justify-center hover:bg-muted transition-colors"
        style={posStyle}
      >
        +{cell.count}
      </button>
    );
  }

  const { appt } = cell;
  const cancelled = appt.status === 'cancelled' || appt.status === 'no_show';
  const color = appt.service.category_color ?? 'hsl(220 9% 46%)';
  // Print the name only when the block has room for it: tall enough
  // not to clip mid-glyph, and no more than 2 columns wide (a 3-col
  // block on a phone is ~30px — a truncated "Ro…" is just noise, so
  // it becomes a clean color chip instead).
  const showText = height >= 26 && cell.cols <= 2;

  const trigger = (
    <button
      type="button"
      className={cn(
        'absolute rounded-[4px] overflow-hidden text-left border-l-[3px] transition-opacity hover:opacity-90',
        cancelled && 'opacity-55',
      )}
      style={{
        ...posStyle,
        background: `${color}26`,
        borderLeftColor: color,
      }}
    >
      {showText ? (
        <span
          className={cn(
            'block px-1 pt-0.5 text-[10px] font-medium text-foreground/90 truncate leading-tight',
            cancelled && 'line-through',
          )}
        >
          {appt.customer.full_name}
        </span>
      ) : null}
    </button>
  );

  return <AppointmentPopover appointment={appt} timezone={timezone} trigger={trigger} />;
}

// ── overlap packing ─────────────────────────────────────────────────

/** Assign each appointment a (col, cols) so overlapping ones render
 *  side-by-side. Events are grouped into clusters of mutual overlap;
 *  within a cluster each event takes the first free sub-column.
 *
 *  Capped at MAX_COLS visible columns: a cluster that needs more
 *  renders its first (MAX_COLS - 1) columns of events and collapses
 *  everything beyond into a single "+N" overflow tile in the last
 *  column. Without the cap a 6-deep overlap slivered every block to
 *  ~16px on a phone. */
function packDay(appts: Appointment[]): Cell[] {
  const items = appts
    .map((appt) => {
      const s = new Date(appt.start_time);
      const e = new Date(appt.end_time);
      const topMin = s.getHours() * 60 + s.getMinutes();
      const endMin = e.getHours() * 60 + e.getMinutes();
      return { appt, topMin, endMin: Math.max(endMin, topMin + 5) };
    })
    .sort((a, b) => a.topMin - b.topMin || a.endMin - b.endMin);

  const result: Cell[] = [];
  let cluster: typeof items = [];
  let clusterEnd = -1;

  const flush = () => {
    if (cluster.length === 0) return;
    // Greedy column assignment.
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
      // Render columns 0..MAX_COLS-2 of events; collapse the rest.
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

// ── date helpers ────────────────────────────────────────────────────

const WEEKDAY_ABBR = ['S', 'M', 'T', 'W', 'T', 'F', 'S'];

function parseLocalDate(iso: string): Date {
  return new Date(`${iso}T00:00:00`);
}

function toISODate(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

function formatHour(h: number): string {
  if (h === 0 || h === 24) return '12 AM';
  if (h === 12) return '12 PM';
  return h < 12 ? `${h} AM` : `${h - 12} PM`;
}
