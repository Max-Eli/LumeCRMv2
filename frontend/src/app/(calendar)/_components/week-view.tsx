/**
 * Week view — a 7-day agenda for the focus week.
 *
 * Each day in the week is a section: a sticky-ish header (weekday +
 * date, today emphasized) followed by that day's appointment cards.
 * Empty days collapse to a thin "No appointments" line so a quiet
 * week still scans fast.
 *
 * Why agenda and not a 7-column time grid: on a phone, seven time-
 * grid columns are ~45px wide — every customer name and service
 * truncates to nothing. The agenda layout gives each appointment a
 * full-width readable card, which is what modern scheduling apps
 * ship for mobile week views. On desktop the day-view time grid is
 * still the dense option; this is the scannable one.
 *
 * Cards reuse `<AppointmentPopover>` so tapping one opens the exact
 * same detail panel as every other calendar surface.
 */

'use client';

import { CalendarOff } from 'lucide-react';

import { InitialsAvatar } from '@/components/initials-avatar';
import { StatusBadge } from '@/components/status-badge';
import {
  STATUS_LABELS,
  STATUS_TONE,
  type Appointment,
} from '@/lib/appointments';
import { cn } from '@/lib/utils';

import { AppointmentPopover } from './appointment-popover';

export interface WeekViewProps {
  /** Any date inside the week to render (YYYY-MM-DD). */
  date: string;
  timezone: string;
  /** Every appointment overlapping the visible week. */
  appointments: Appointment[];
  /** Tapping a day header — jumps to that day's detailed view. */
  onSelectDay: (date: string) => void;
}

export function WeekView({ date, timezone, appointments, onSelectDay }: WeekViewProps) {
  const focus = parseLocalDate(date);
  const todayStr = toISODate(new Date());

  // Week starts Sunday (matches the month grid).
  const weekStart = new Date(focus);
  weekStart.setDate(weekStart.getDate() - weekStart.getDay());
  const days: Date[] = [];
  for (let i = 0; i < 7; i++) {
    const d = new Date(weekStart);
    d.setDate(d.getDate() + i);
    days.push(d);
  }

  // Bucket appointments by local start date.
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
    <div className="flex-1 min-h-0 overflow-y-auto bg-muted/30">
      <ul className="divide-y">
        {days.map((day) => {
          const iso = toISODate(day);
          const isToday = iso === todayStr;
          const dayAppts = byDay.get(iso) ?? [];
          return (
            <li key={iso}>
              <DaySection
                day={day}
                iso={iso}
                isToday={isToday}
                appointments={dayAppts}
                timezone={timezone}
                onSelectDay={onSelectDay}
              />
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function DaySection({
  day,
  iso,
  isToday,
  appointments,
  timezone,
  onSelectDay,
}: {
  day: Date;
  iso: string;
  isToday: boolean;
  appointments: Appointment[];
  timezone: string;
  onSelectDay: (date: string) => void;
}) {
  const weekday = day.toLocaleDateString('en-US', { weekday: 'long' });
  const monthDay = day.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });

  return (
    <section>
      <button
        type="button"
        onClick={() => onSelectDay(iso)}
        className={cn(
          'w-full flex items-center gap-2.5 px-4 py-2.5 text-left transition-colors hover:bg-muted/50',
          'sticky top-0 z-[1] backdrop-blur bg-card/95 supports-[backdrop-filter]:bg-card/80 border-b',
        )}
      >
        <span
          className={cn(
            'inline-flex items-center justify-center size-7 rounded-full text-xs tabular-nums shrink-0',
            isToday
              ? 'bg-foreground text-background font-semibold'
              : 'text-foreground',
          )}
        >
          {day.getDate()}
        </span>
        <span
          className={cn(
            'text-sm font-medium',
            isToday ? 'text-foreground' : 'text-foreground/90',
          )}
        >
          {weekday}
        </span>
        <span className="text-xs text-muted-foreground">{monthDay}</span>
        {appointments.length > 0 ? (
          <span className="ml-auto text-xs text-muted-foreground tabular-nums">
            {appointments.length} appt{appointments.length === 1 ? '' : 's'}
          </span>
        ) : null}
      </button>

      {appointments.length === 0 ? (
        <div className="px-4 py-3 flex items-center gap-2 text-xs text-muted-foreground/70">
          <CalendarOff className="size-3.5" aria-hidden />
          No appointments
        </div>
      ) : (
        <ul className="divide-y bg-card">
          {appointments.map((appt) => (
            <li key={appt.id}>
              <ApptRow appt={appt} timezone={timezone} />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function ApptRow({ appt, timezone }: { appt: Appointment; timezone: string }) {
  const cancelled = appt.status === 'cancelled' || appt.status === 'no_show';
  const color = appt.service.category_color ?? 'hsl(220 9% 46%)';
  const providerName = `${appt.provider.user_first_name} ${appt.provider.user_last_name}`.trim();

  const trigger = (
    <button
      type="button"
      className="w-full text-left flex items-stretch gap-3 px-4 py-3 hover:bg-muted/40 active:bg-muted/60 transition-colors"
    >
      <div className="w-14 shrink-0 flex flex-col justify-center">
        <span
          className={cn(
            'text-sm font-semibold tabular-nums leading-tight',
            cancelled && 'text-muted-foreground',
          )}
        >
          {formatTime(appt.start_time, timezone)}
        </span>
      </div>
      <span
        className="w-1 rounded-full shrink-0 self-stretch"
        style={{ background: color }}
        aria-hidden
      />
      <div className="min-w-0 flex-1">
        <p
          className={cn(
            'font-medium text-[15px] leading-snug',
            cancelled && 'line-through text-muted-foreground',
          )}
        >
          {appt.service.name}
        </p>
        <p className="text-[13px] text-muted-foreground truncate mt-0.5">
          {appt.customer.full_name}
        </p>
        <div className="flex items-center justify-between gap-2 mt-1.5">
          <span className="inline-flex items-center gap-1.5 min-w-0">
            <InitialsAvatar name={providerName} size="sm" />
            <span className="text-xs text-muted-foreground truncate">
              {providerName}
            </span>
          </span>
          <StatusBadge tone={STATUS_TONE[appt.status]}>
            {STATUS_LABELS[appt.status]}
          </StatusBadge>
        </div>
      </div>
    </button>
  );

  return <AppointmentPopover appointment={appt} timezone={timezone} trigger={trigger} />;
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

function formatTime(iso: string, timezone: string): string {
  return new Date(iso).toLocaleTimeString('en-US', {
    timeZone: timezone,
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
  });
}
