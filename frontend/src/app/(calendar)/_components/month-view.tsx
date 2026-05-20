/**
 * Month view — a calendar grid for the focus month.
 *
 * Google-Calendar-style: a 6×7 grid of day cells, each showing the
 * date number plus up to three appointment bars (color from the
 * service category) and a "+N" overflow chip. Tapping a day drops
 * the operator into that day's detailed view.
 *
 * Works the same on mobile and desktop — the grid just gets roomier
 * cells with more breathing room on wider screens. This is the
 * surface that finally gives phones a month overview (previously
 * mobile was list-view-only).
 */

'use client';

import { cn } from '@/lib/utils';
import { type Appointment } from '@/lib/appointments';

const WEEKDAY_LABELS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

export interface MonthViewProps {
  /** Any date inside the month to render (YYYY-MM-DD). */
  date: string;
  timezone: string;
  /** Every appointment overlapping the visible 6-week window. */
  appointments: Appointment[];
  /** Tapping a day cell — hands back that day's YYYY-MM-DD. */
  onSelectDay: (date: string) => void;
}

export function MonthView({ date, appointments, onSelectDay }: MonthViewProps) {
  const focus = parseLocalDate(date);
  const todayStr = toISODate(new Date());

  // First cell is the Sunday on/before the 1st of the month; render a
  // fixed 6-week (42-cell) grid so the height doesn't jump month to
  // month.
  const firstOfMonth = new Date(focus.getFullYear(), focus.getMonth(), 1);
  const gridStart = new Date(firstOfMonth);
  gridStart.setDate(gridStart.getDate() - gridStart.getDay());

  const cells: Date[] = [];
  for (let i = 0; i < 42; i++) {
    const d = new Date(gridStart);
    d.setDate(d.getDate() + i);
    cells.push(d);
  }

  // Bucket appointments by their local start date.
  const byDay = new Map<string, Appointment[]>();
  for (const appt of appointments) {
    const key = toISODate(new Date(appt.start_time));
    const arr = byDay.get(key) ?? [];
    arr.push(appt);
    byDay.set(key, arr);
  }
  for (const arr of byDay.values()) {
    arr.sort((a, b) => (a.start_time < b.start_time ? -1 : 1));
  }

  return (
    <div className="flex-1 min-h-0 flex flex-col bg-card">
      {/* Weekday header */}
      <div className="grid grid-cols-7 border-b shrink-0">
        {WEEKDAY_LABELS.map((label) => (
          <div
            key={label}
            className="px-1 py-2 text-center text-[10px] sm:text-[11px] font-medium uppercase tracking-wide text-muted-foreground"
          >
            <span className="sm:hidden">{label[0]}</span>
            <span className="hidden sm:inline">{label}</span>
          </div>
        ))}
      </div>

      {/* 6-week grid */}
      <div className="grid grid-cols-7 grid-rows-6 flex-1 min-h-0">
        {cells.map((cellDate) => {
          const iso = toISODate(cellDate);
          const inMonth = cellDate.getMonth() === focus.getMonth();
          const isToday = iso === todayStr;
          const isFocus = iso === date;
          const dayAppts = byDay.get(iso) ?? [];
          return (
            <DayCell
              key={iso}
              iso={iso}
              dayNumber={cellDate.getDate()}
              inMonth={inMonth}
              isToday={isToday}
              isFocus={isFocus}
              appointments={dayAppts}
              onClick={() => onSelectDay(iso)}
            />
          );
        })}
      </div>
    </div>
  );
}

function DayCell({
  dayNumber,
  inMonth,
  isToday,
  isFocus,
  appointments,
  onClick,
}: {
  iso: string;
  dayNumber: number;
  inMonth: boolean;
  isToday: boolean;
  isFocus: boolean;
  appointments: Appointment[];
  onClick: () => void;
}) {
  // Mobile shows up to 2 bars, desktop up to 3 — phone cells are
  // shorter. The overflow chip absorbs the rest.
  const MOBILE_MAX = 2;
  const DESKTOP_MAX = 3;
  const overflowMobile = appointments.length - MOBILE_MAX;
  const overflowDesktop = appointments.length - DESKTOP_MAX;

  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        'group relative border-b border-r text-left p-1 sm:p-1.5 flex flex-col gap-0.5 overflow-hidden transition-colors',
        'min-h-[64px] sm:min-h-0',
        inMonth ? 'bg-card hover:bg-muted/40' : 'bg-muted/20 hover:bg-muted/30',
        isFocus && 'ring-1 ring-inset ring-accent/60',
      )}
    >
      <span
        className={cn(
          'inline-flex items-center justify-center text-[11px] sm:text-xs tabular-nums shrink-0',
          'size-5 sm:size-6 rounded-full',
          isToday && 'bg-foreground text-background font-semibold',
          !isToday && inMonth && 'text-foreground',
          !isToday && !inMonth && 'text-muted-foreground/50',
        )}
      >
        {dayNumber}
      </span>

      {appointments.length > 0 ? (
        <div className="flex flex-col gap-0.5 min-w-0">
          {/* Mobile bars */}
          <div className="sm:hidden flex flex-col gap-0.5">
            {appointments.slice(0, MOBILE_MAX).map((a) => (
              <ApptBar key={a.id} appt={a} />
            ))}
            {overflowMobile > 0 ? (
              <span className="text-[9px] text-muted-foreground pl-0.5">
                +{overflowMobile}
              </span>
            ) : null}
          </div>
          {/* Desktop bars */}
          <div className="hidden sm:flex flex-col gap-0.5">
            {appointments.slice(0, DESKTOP_MAX).map((a) => (
              <ApptBar key={a.id} appt={a} desktop />
            ))}
            {overflowDesktop > 0 ? (
              <span className="text-[10px] text-muted-foreground pl-0.5">
                +{overflowDesktop} more
              </span>
            ) : null}
          </div>
        </div>
      ) : null}
    </button>
  );
}

function ApptBar({ appt, desktop }: { appt: Appointment; desktop?: boolean }) {
  const cancelled = appt.status === 'cancelled' || appt.status === 'no_show';
  const color = appt.service.category_color ?? 'hsl(220 9% 46%)';
  return (
    <div
      className={cn(
        'rounded-[3px] truncate leading-tight',
        desktop ? 'text-[10px] px-1 py-0.5' : 'text-[9px] px-1 py-px',
        cancelled && 'line-through opacity-60',
      )}
      style={{ background: `${color}22`, color: '#1c1917' }}
    >
      <span
        className="inline-block size-1.5 rounded-full mr-1 align-middle"
        style={{ background: color }}
        aria-hidden
      />
      {desktop ? (
        <>
          {formatTime(appt.start_time)} {appt.customer.full_name}
        </>
      ) : (
        appt.customer.full_name
      )}
    </div>
  );
}

// ── date helpers ────────────────────────────────────────────────────

function parseLocalDate(iso: string): Date {
  return new Date(`${iso}T00:00:00`);
}

function toISODate(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString('en-US', {
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
  });
}
