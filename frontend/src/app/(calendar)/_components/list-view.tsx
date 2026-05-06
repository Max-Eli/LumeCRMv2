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
    <div className="flex-1 min-h-0 overflow-y-auto bg-card">
      <ul className="divide-y">
        {appointments.map((appt) => {
          const cancelled = appt.status === 'cancelled' || appt.status === 'no_show';
          const color = appt.service.category_color ?? 'hsl(220 9% 46%)';
          const trigger = (
            <button
              type="button"
              className={cn(
                'w-full grid grid-cols-[110px_1fr_auto] items-center gap-4 px-6 py-3 text-left',
                'hover:bg-muted/50 transition-colors focus-visible:bg-muted/50 outline-none',
              )}
            >
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
                  <InitialsAvatar
                    name={`${appt.provider.user_first_name} ${appt.provider.user_last_name}`}
                    size="sm"
                  />
                  <span className="hidden md:inline">
                    {appt.provider.user_first_name} {appt.provider.user_last_name}
                  </span>
                </div>
                <StatusBadge tone={STATUS_TONE[appt.status]}>
                  {STATUS_LABELS[appt.status]}
                </StatusBadge>
              </div>
            </button>
          );
          return (
            <li key={appt.id}>
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
