/**
 * `AppointmentsTab` — full appointment history for a customer.
 *
 * Splits the list into "Upcoming" and "Past" buckets at `now`. Newest
 * first within each bucket, mirroring the calendar's reverse-chrono
 * convention. Each row is a clickable link to the calendar at the
 * appointment's date so the operator can jump from the customer
 * profile straight to the day in question.
 *
 * Status pills mirror the calendar's tone palette (booked/confirmed/
 * checked-in/completed/no-show/cancelled) for visual continuity. The
 * row's hover state previews the tap-to-jump action.
 */

'use client';

import { Calendar, ChevronRight, Clock, MapPin, User } from 'lucide-react';
import Link from 'next/link';
import { useMemo } from 'react';

import {
  type Appointment,
  type AppointmentStatus,
  STATUS_LABELS,
  useCustomerAppointments,
} from '@/lib/appointments';
import { formatMoneyCents } from '@/lib/invoices';
import { cn } from '@/lib/utils';

const TONE: Record<AppointmentStatus, 'pending' | 'progress' | 'success' | 'terminal' | 'destructive'> = {
  booked: 'pending',
  confirmed: 'progress',
  checked_in: 'progress',
  completed: 'success',
  cancelled: 'terminal',
  no_show: 'destructive',
};

export function AppointmentsTab({ customerId }: { customerId: number }) {
  const { data: appointments, isLoading, error } = useCustomerAppointments(customerId);

  const split = useMemo(() => splitByTime(appointments ?? []), [appointments]);

  if (isLoading) {
    return (
      <div className="rounded-md border bg-card p-6 text-sm text-muted-foreground max-w-3xl">
        Loading appointments…
      </div>
    );
  }
  if (error) {
    return (
      <div className="rounded-md border border-destructive/40 bg-destructive/[0.04] p-4 text-sm text-destructive max-w-3xl">
        Could not load appointments.
      </div>
    );
  }

  const all = appointments ?? [];
  if (all.length === 0) {
    return <EmptyState />;
  }

  return (
    <div className="space-y-8 max-w-3xl">
      {split.upcoming.length > 0 ? (
        <Section title="Upcoming" count={split.upcoming.length}>
          <ApptList items={split.upcoming} />
        </Section>
      ) : null}

      {split.past.length > 0 ? (
        <Section title="Past" count={split.past.length}>
          <ApptList items={split.past} />
        </Section>
      ) : null}
    </div>
  );
}

// ── Sub-components ───────────────────────────────────────────────────

function Section({
  title,
  count,
  children,
}: {
  title: string;
  count: number;
  children: React.ReactNode;
}) {
  return (
    <section>
      <header className="flex items-baseline gap-2 mb-3">
        <h2 className="font-serif text-base font-semibold tracking-tight text-foreground">
          {title}
        </h2>
        <span className="text-xs tabular-nums text-muted-foreground">
          {count}
        </span>
      </header>
      {children}
    </section>
  );
}

function EmptyState() {
  return (
    <div className="rounded-lg border border-dashed bg-muted/20 p-8 text-center max-w-2xl">
      <div className="inline-flex size-10 items-center justify-center rounded-full bg-card text-muted-foreground border mb-3">
        <Calendar className="size-4" />
      </div>
      <h3 className="font-serif text-base font-semibold tracking-tight">
        No appointments yet
      </h3>
      <p className="text-xs text-muted-foreground mt-1.5 leading-relaxed">
        When this customer books — through the public site or with the front
        desk — their history will live here.
      </p>
    </div>
  );
}

function ApptList({ items }: { items: Appointment[] }) {
  return (
    <ul className="divide-y divide-border rounded-lg border bg-card overflow-hidden">
      {items.map((a) => (
        <li key={a.id}>
          <ApptRow appt={a} />
        </li>
      ))}
    </ul>
  );
}

function ApptRow({ appt }: { appt: Appointment }) {
  // Format the date in the user's local tz; the calendar page itself
  // re-renders in the location's tz when viewed there. The customer
  // profile is operator-facing context, not customer-facing display.
  const start = new Date(appt.start_time);
  const dateLabel = start.toLocaleDateString('en-US', {
    weekday: 'short',
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });
  const timeLabel = start.toLocaleTimeString('en-US', {
    hour: 'numeric',
    minute: '2-digit',
  });
  const dateIso = `${start.getFullYear()}-${String(start.getMonth() + 1).padStart(2, '0')}-${String(start.getDate()).padStart(2, '0')}`;

  return (
    <Link
      href={`/calendar?date=${dateIso}`}
      className="flex items-center gap-4 px-4 py-3 hover:bg-muted/40 transition-colors group"
    >
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-sm font-medium text-foreground">
            {appt.service.name}
          </span>
          <StatusPill status={appt.status} />
          {appt.source === 'online' ? (
            <span className="inline-flex items-center rounded-full bg-stone-100 text-stone-700 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wider">
              Online
            </span>
          ) : null}
        </div>
        <div className="flex items-center gap-3 text-xs text-muted-foreground mt-1 tabular-nums flex-wrap">
          <span className="inline-flex items-center gap-1">
            <Clock className="size-3" />
            {dateLabel} · {timeLabel}
          </span>
          <span className="inline-flex items-center gap-1">
            <User className="size-3" />
            {appt.provider.user_first_name} {appt.provider.user_last_name}
          </span>
          {appt.quoted_price_cents > 0 ? (
            <span>{formatMoneyCents(appt.quoted_price_cents)}</span>
          ) : null}
        </div>
      </div>
      <ChevronRight className="size-4 text-muted-foreground/60 group-hover:text-foreground transition-colors shrink-0" />
    </Link>
  );
}

function StatusPill({ status }: { status: AppointmentStatus }) {
  const tone = TONE[status];
  return (
    <span
      className={cn(
        'inline-flex items-center rounded-full px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wider',
        tone === 'pending' && 'bg-amber-50 text-amber-800',
        tone === 'progress' && 'bg-blue-50 text-blue-800',
        tone === 'success' && 'bg-emerald-50 text-emerald-700',
        tone === 'terminal' && 'bg-stone-100 text-stone-600',
        tone === 'destructive' && 'bg-red-50 text-red-700',
      )}
    >
      {STATUS_LABELS[status]}
    </span>
  );
}

// ── Helpers ─────────────────────────────────────────────────────────

function splitByTime(items: Appointment[]): {
  upcoming: Appointment[];
  past: Appointment[];
} {
  const now = Date.now();
  const upcoming: Appointment[] = [];
  const past: Appointment[] = [];
  for (const a of items) {
    const start = new Date(a.start_time).getTime();
    // Cancelled / no-show appointments never count as "upcoming"
    // even if their start_time is in the future — they're terminal,
    // not pending arrival.
    const isTerminal = a.status === 'cancelled' || a.status === 'no_show';
    if (start >= now && !isTerminal) {
      upcoming.push(a);
    } else {
      past.push(a);
    }
  }
  upcoming.sort((a, b) => a.start_time.localeCompare(b.start_time));
  past.sort((a, b) => b.start_time.localeCompare(a.start_time));
  return { upcoming, past };
}
