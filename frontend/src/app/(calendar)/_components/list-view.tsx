/**
 * List view — chronological feed of the day's appointments.
 *
 * Alternative to the time-grid day view, controlled by the View Settings tool
 * panel. Useful when the front desk wants a sequential read of the day rather
 * than a spatial overview, or on narrow screens where columns get cramped.
 *
 * Each row is wrapped in `AppointmentPopover` so clicking it opens the same
 * detail panel the calendar grid uses — single source of truth for appointment
 * actions across both views.
 */

'use client';

import { CalendarOff } from 'lucide-react';

import { InitialsAvatar } from '@/components/initials-avatar';
import { StatusBadge } from '@/components/status-badge';
import { Badge } from '@/components/ui/badge';
import {
  STATUS_LABELS,
  STATUS_TONE,
  type Appointment,
} from '@/lib/appointments';
import { cn } from '@/lib/utils';

import { AppointmentPopover } from './appointment-popover';

export interface ListViewProps {
  timezone: string;
  appointments: Appointment[];
}

export function ListView({ timezone, appointments }: ListViewProps) {
  if (appointments.length === 0) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center text-center px-6 py-20 bg-card">
        <div className="inline-flex size-12 items-center justify-center rounded-full bg-muted text-muted-foreground mb-4">
          <CalendarOff className="size-5" />
        </div>
        <h3 className="font-serif text-xl font-semibold tracking-tight">No appointments</h3>
        <p className="text-sm text-muted-foreground mt-1.5 max-w-sm">
          Nothing scheduled for this day. Use the New appointment action above or have a client
          book online.
        </p>
      </div>
    );
  }

  // Appointments come from the API ordered by start_time ascending; trust that.
  return (
    <div className="flex-1 min-h-0 overflow-y-auto bg-muted/30 md:bg-card">
      {/* Mobile: rounded cards with breathing room between them — a
          flat divided list crammed dense rows together when the day
          was busy and made the page hard to scan on a phone. Desktop
          keeps the dense divided layout where vertical real estate
          matters more than per-row separation. */}
      <ul className="space-y-2.5 px-3 py-3 md:space-y-0 md:px-0 md:py-0 md:divide-y">
        {appointments.map((appt) => {
          const cancelled = appt.status === 'cancelled' || appt.status === 'no_show';
          const color = appt.service.category_color ?? 'hsl(220 9% 46%)';
          const durationMinutes = Math.max(
            1,
            Math.round(
              (new Date(appt.end_time).getTime() - new Date(appt.start_time).getTime()) / 60000,
            ),
          );
          const providerName = `${appt.provider.user_first_name} ${appt.provider.user_last_name}`;
          // Two layouts — mobile is card-style (modern CRM pattern:
          // big time anchor, service centered, customer + provider
          // + status at the bottom). Desktop keeps the dense grid
          // for high-density scanning.
          const trigger = (
            <button
              type="button"
              className={cn(
                'block w-full text-left px-4 sm:px-6 py-4 transition-colors outline-none',
                'hover:bg-muted/50 focus-visible:bg-muted/50',
              )}
            >
              {/* ─── Mobile card layout ─────────────────────── */}
              <div className="md:hidden flex gap-4">
                {/* Time anchor — bold start time, smaller duration */}
                <div
                  className="shrink-0 w-16 flex flex-col justify-center"
                  style={{ color: cancelled ? 'var(--muted-foreground)' : 'inherit' }}
                >
                  <div className="font-semibold text-base tabular-nums leading-tight whitespace-nowrap">
                    {formatStartTime(appt, timezone)}
                  </div>
                  <div className="text-[11px] uppercase tracking-wide text-muted-foreground mt-0.5">
                    {durationMinutes}m
                  </div>
                </div>

                {/* Left color bar — category accent */}
                <span
                  className="w-1 rounded-full shrink-0 self-stretch"
                  style={{ backgroundColor: color }}
                  aria-hidden
                />

                {/* Service + customer + provider + status */}
                <div className="min-w-0 flex-1 flex flex-col justify-center gap-1">
                  <p
                    className={cn(
                      'font-medium text-[15px] leading-snug',
                      cancelled && 'line-through text-muted-foreground',
                    )}
                  >
                    {appt.service.name}
                  </p>
                  <p className="text-[13px] text-muted-foreground truncate">
                    {appt.customer.full_name}
                  </p>
                  <div className="flex items-center justify-between gap-2 mt-1">
                    <div className="flex items-center gap-1.5 min-w-0">
                      <InitialsAvatar name={providerName} size="sm" />
                      <span className="text-xs text-muted-foreground truncate">
                        {providerName}
                      </span>
                    </div>
                    <StatusBadge tone={STATUS_TONE[appt.status]}>
                      {STATUS_LABELS[appt.status]}
                    </StatusBadge>
                  </div>
                </div>
              </div>

              {/* ─── Desktop dense-grid layout ─────────────── */}
              <div className="hidden md:grid md:grid-cols-[110px_1fr_auto] md:items-center md:gap-4">
                <div
                  className="font-mono tabular-nums text-sm"
                  style={{ color: cancelled ? 'var(--muted-foreground)' : 'inherit' }}
                >
                  {formatTimeRange(appt, timezone)}
                </div>

                <div className="flex items-center gap-3 min-w-0">
                  <span
                    className="size-2 rounded-full shrink-0"
                    style={{ backgroundColor: color }}
                    aria-hidden
                  />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <p
                        className={cn(
                          'font-medium text-sm truncate',
                          cancelled && 'line-through text-muted-foreground',
                        )}
                      >
                        {appt.service.name}
                      </p>
                      {appt.service.category_name ? (
                        <Badge
                          variant="outline"
                          className="font-normal text-[10px] py-0"
                          style={{ borderColor: `${color}66`, color }}
                        >
                          {appt.service.category_name}
                        </Badge>
                      ) : null}
                    </div>
                    <p className="text-xs text-muted-foreground truncate">
                      {appt.customer.full_name}
                    </p>
                  </div>
                </div>

                <div className="flex items-center gap-3 shrink-0">
                  <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                    <InitialsAvatar name={providerName} size="sm" />
                    <span>{providerName}</span>
                  </div>
                  <StatusBadge tone={STATUS_TONE[appt.status]}>
                    {STATUS_LABELS[appt.status]}
                  </StatusBadge>
                </div>
              </div>
            </button>
          );
          return (
            <li
              key={appt.id}
              className="rounded-xl border bg-card overflow-hidden shadow-[0_1px_2px_rgba(28,25,23,0.03)] md:rounded-none md:border-0 md:shadow-none md:bg-transparent"
            >
              <AppointmentPopover appointment={appt} timezone={timezone} trigger={trigger} />
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function formatTimeRange(appt: Appointment, timezone: string): string {
  const opts: Intl.DateTimeFormatOptions = {
    timeZone: timezone,
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
  };
  const start = new Date(appt.start_time).toLocaleTimeString('en-US', opts);
  const end = new Date(appt.end_time).toLocaleTimeString('en-US', opts);
  return `${start} – ${end}`;
}

function formatStartTime(appt: Appointment, timezone: string): string {
  // Mobile-only: a single-line start time, narrow enough to fit a
  // 64px column. We DON'T abbreviate AM/PM further — operators
  // habitually scan for it as a disambiguator.
  return new Date(appt.start_time).toLocaleTimeString('en-US', {
    timeZone: timezone,
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
  });
}
