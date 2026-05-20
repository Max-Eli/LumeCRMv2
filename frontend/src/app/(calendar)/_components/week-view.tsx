/**
 * Week view — a 7-day time grid, Google-Calendar style.
 *
 * Layout:
 *   - A sticky header row: time-gutter spacer + 7 day headers
 *     (weekday abbrev + date pill, today emphasized).
 *   - A vertically scrollable body: hour-labelled time gutter on the
 *     left + 7 day columns. Appointments are absolutely-positioned
 *     colored blocks.
 *   - Overlapping appointments within a day are packed side-by-side
 *     (cluster → sub-column assignment) so a busy day doesn't render
 *     a single block hiding five others.
 *   - A red "now" line is drawn across today's column when the
 *     visible week contains the current date.
 *
 * Columns are deliberately narrow on phones — that's how Google's
 * mobile week view works. Blocks show the start time + customer
 * name, truncated; tapping opens the full <AppointmentPopover>.
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
const HOUR_PX = 56;
const DEFAULT_START_HOUR = 8;
const DEFAULT_END_HOUR = 20;

export interface WeekViewProps {
  /** Any date inside the week to render (YYYY-MM-DD). */
  date: string;
  timezone: string;
  /** Every appointment overlapping the visible week. */
  appointments: Appointment[];
  /** Tapping a day header — jumps to that day's detailed view. */
  onSelectDay: (date: string) => void;
  /** Tenant business hours (integer hours); window expands past
   *  these if an appointment falls outside. */
  dayStartHour?: number;
  dayEndHour?: number;
}

interface Positioned {
  appt: Appointment;
  topMin: number;
  durationMin: number;
  col: number;
  cols: number;
}

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
                className="absolute inset-x-0 border-t border-border/60"
                style={{ top: i * HOUR_PX }}
                aria-hidden
              />
            ))}

            {days.map((day) => {
              const iso = toISODate(day);
              const dayAppts = byDay.get(iso) ?? [];
              const positioned = packDay(dayAppts);
              const isToday = iso === nowStr;
              return (
                <div
                  key={iso}
                  className="flex-1 min-w-0 relative border-r border-border/60 last:border-r-0"
                >
                  {positioned.map((p) => (
                    <WeekEventBlock
                      key={p.appt.id}
                      positioned={p}
                      startMin={startMin}
                      timezone={timezone}
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

function WeekEventBlock({
  positioned,
  startMin,
  timezone,
}: {
  positioned: Positioned;
  startMin: number;
  timezone: string;
}) {
  const { appt, topMin, durationMin, col, cols } = positioned;
  const cancelled = appt.status === 'cancelled' || appt.status === 'no_show';
  const color = appt.service.category_color ?? 'hsl(220 9% 46%)';
  const top = ((topMin - startMin) / 60) * HOUR_PX;
  const height = Math.max(14, (durationMin / 60) * HOUR_PX);
  const widthPct = 100 / cols;

  const trigger = (
    <button
      type="button"
      className={cn(
        'absolute rounded-[3px] overflow-hidden text-left leading-tight',
        'border-l-2 px-1 py-0.5 transition-opacity hover:opacity-90',
        cancelled && 'opacity-60',
      )}
      style={{
        top,
        height,
        left: `calc(${col * widthPct}% + 1px)`,
        width: `calc(${widthPct}% - 2px)`,
        background: `${color}1f`,
        borderLeftColor: color,
      }}
    >
      <span
        className={cn(
          'block text-[9px] font-medium text-foreground/90 truncate',
          cancelled && 'line-through',
        )}
      >
        {formatTime(appt.start_time, timezone)}
      </span>
      <span className="block text-[9px] text-foreground/75 truncate">
        {appt.customer.full_name}
      </span>
    </button>
  );

  return <AppointmentPopover appointment={appt} timezone={timezone} trigger={trigger} />;
}

// ── overlap packing ─────────────────────────────────────────────────

/** Assign each appointment a (col, cols) so overlapping ones render
 *  side-by-side. Events are grouped into clusters of mutual overlap;
 *  within a cluster each event takes the first free sub-column. */
function packDay(appts: Appointment[]): Positioned[] {
  const items = appts
    .map((appt) => {
      const s = new Date(appt.start_time);
      const e = new Date(appt.end_time);
      const topMin = s.getHours() * 60 + s.getMinutes();
      const endMin = e.getHours() * 60 + e.getMinutes();
      return { appt, topMin, endMin: Math.max(endMin, topMin + 5) };
    })
    .sort((a, b) => a.topMin - b.topMin || a.endMin - b.endMin);

  const result: Positioned[] = [];
  let cluster: typeof items = [];
  let clusterEnd = -1;

  const flush = () => {
    if (cluster.length === 0) return;
    // Greedy column assignment.
    const columns: number[] = []; // columns[c] = end-min of last event in col c
    const colOf = new Map<Appointment, number>();
    for (const it of cluster) {
      let placed = -1;
      for (let c = 0; c < columns.length; c++) {
        if (it.topMin >= columns[c]) {
          placed = c;
          break;
        }
      }
      if (placed === -1) {
        placed = columns.length;
        columns.push(it.endMin);
      } else {
        columns[placed] = it.endMin;
      }
      colOf.set(it.appt, placed);
    }
    const cols = columns.length;
    for (const it of cluster) {
      result.push({
        appt: it.appt,
        topMin: it.topMin,
        durationMin: it.endMin - it.topMin,
        col: colOf.get(it.appt) ?? 0,
        cols,
      });
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

function formatTime(iso: string, timezone: string): string {
  return new Date(iso).toLocaleTimeString('en-US', {
    timeZone: timezone,
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
  });
}
