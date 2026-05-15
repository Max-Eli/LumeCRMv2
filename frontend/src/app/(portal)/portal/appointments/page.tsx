/**
 * `/portal/appointments` — full list of the customer's appointments.
 *
 * Two sections, both empty-state-friendly:
 *   - Upcoming (active statuses, start_time in future)
 *   - Past (everything else)
 *
 * Cancel button appears only on rows the backend marks `cancellable`
 * — the gate is server-enforced; this is the affordance.
 */

'use client';

import {
  CalendarClock,
  CheckCircle2,
  Loader2,
  MapPin,
  UserCircle2,
  XCircle,
} from 'lucide-react';
import { useMemo, useState } from 'react';

import {
  type PortalAppointment,
  useCancelAppointment,
  usePortalAppointments,
} from '@/lib/portal';
import { cn } from '@/lib/utils';

import { Button } from '@/components/ui/button';

export default function PortalAppointmentsPage() {
  const { data: appointments, isLoading } = usePortalAppointments();

  const { upcoming, past } = useMemo(() => {
    const list = appointments ?? [];
    const now = Date.now();
    const upcoming: PortalAppointment[] = [];
    const past: PortalAppointment[] = [];
    for (const a of list) {
      const isFuture = new Date(a.start_time).getTime() > now;
      const isLiveStatus =
        a.status === 'booked' || a.status === 'confirmed' || a.status === 'checked_in';
      if (isFuture && isLiveStatus) {
        upcoming.push(a);
      } else {
        past.push(a);
      }
    }
    upcoming.sort(
      (a, b) => new Date(a.start_time).getTime() - new Date(b.start_time).getTime(),
    );
    past.sort(
      (a, b) => new Date(b.start_time).getTime() - new Date(a.start_time).getTime(),
    );
    return { upcoming, past };
  }, [appointments]);

  return (
    <div className="max-w-4xl mx-auto w-full px-6 py-10">
      <header className="mb-8">
        <h1 className="font-serif text-3xl font-semibold tracking-tight">
          Appointments
        </h1>
        <p className="text-sm text-muted-foreground mt-1.5">
          Your upcoming and past visits.
        </p>
      </header>

      {isLoading ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : (
        <div className="space-y-8">
          <Section
            title="Upcoming"
            count={upcoming.length}
            empty="No upcoming appointments. The front desk can book your next visit."
          >
            {upcoming.map((a) => (
              <AppointmentRow key={a.id} appointment={a} />
            ))}
          </Section>
          <Section
            title="Past"
            count={past.length}
            empty="No previous appointments yet."
          >
            {past.map((a) => (
              <AppointmentRow key={a.id} appointment={a} />
            ))}
          </Section>
        </div>
      )}
    </div>
  );
}

function Section({
  title,
  count,
  empty,
  children,
}: {
  title: string;
  count: number;
  empty: string;
  children: React.ReactNode;
}) {
  return (
    <section>
      <div className="flex items-baseline gap-2 mb-3">
        <h2 className="text-xs uppercase tracking-wide text-muted-foreground font-medium">
          {title}
        </h2>
        {count > 0 ? (
          <span className="text-xs text-muted-foreground">({count})</span>
        ) : null}
      </div>
      {count === 0 ? (
        <p className="text-sm text-muted-foreground border border-dashed rounded-lg px-4 py-6 text-center">
          {empty}
        </p>
      ) : (
        <ul className="space-y-2">{children}</ul>
      )}
    </section>
  );
}

function AppointmentRow({ appointment }: { appointment: PortalAppointment }) {
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const cancel = useCancelAppointment();

  const onCancel = async () => {
    setError(null);
    try {
      await cancel.mutateAsync(appointment.id);
      setConfirming(false);
    } catch {
      setError('Could not cancel. Try again or contact the spa.');
    }
  };

  return (
    <li className="rounded-xl border bg-card shadow-sm overflow-hidden">
      <div className="p-5">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0 flex-1">
            <p className="font-medium truncate">{appointment.service_name}</p>
            <p className="text-sm text-muted-foreground flex items-center gap-1.5 mt-1">
              <CalendarClock className="size-3.5 shrink-0" />
              {formatFullDate(appointment.start_time)}
              <span className="text-muted-foreground/60">
                · {appointment.service_duration_minutes} min
              </span>
            </p>
            <div className="text-xs text-muted-foreground mt-2 space-y-1">
              {appointment.provider_name ? (
                <p className="flex items-center gap-1.5">
                  <UserCircle2 className="size-3 shrink-0" />
                  with {appointment.provider_name}
                </p>
              ) : null}
              <p className="flex items-center gap-1.5">
                <MapPin className="size-3 shrink-0" />
                {appointment.location_name}
              </p>
            </div>
          </div>
          <StatusBadge status={appointment.status} display={appointment.status_display} />
        </div>

        {appointment.cancellable ? (
          <div className="mt-4 pt-4 border-t flex items-center justify-end gap-2">
            {error ? (
              <p className="text-xs text-destructive flex-1">{error}</p>
            ) : null}
            {confirming ? (
              <>
                <span className="text-xs text-muted-foreground">Cancel this appointment?</span>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => setConfirming(false)}
                  disabled={cancel.isPending}
                >
                  Keep
                </Button>
                <Button
                  type="button"
                  variant="destructive"
                  size="sm"
                  onClick={onCancel}
                  disabled={cancel.isPending}
                >
                  {cancel.isPending ? (
                    <Loader2 className="size-3.5 animate-spin" />
                  ) : null}
                  Confirm cancel
                </Button>
              </>
            ) : (
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => setConfirming(true)}
              >
                Cancel appointment
              </Button>
            )}
          </div>
        ) : null}
      </div>
    </li>
  );
}

function StatusBadge({
  status,
  display,
}: {
  status: PortalAppointment['status'];
  display: string;
}) {
  const tone =
    status === 'cancelled'
      ? 'bg-muted text-muted-foreground border-muted-foreground/20'
      : status === 'no_show'
        ? 'bg-amber-50 text-amber-800 border-amber-200'
        : status === 'completed'
          ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
          : status === 'checked_in'
            ? 'bg-sky-50 text-sky-700 border-sky-200'
            : 'border';

  const Icon =
    status === 'cancelled' ? XCircle : status === 'completed' ? CheckCircle2 : null;

  return (
    <span
      className={cn(
        'shrink-0 inline-flex items-center gap-1 text-[10px] uppercase tracking-wide font-medium px-2 py-1 rounded-full border whitespace-nowrap',
        tone,
      )}
    >
      {Icon ? <Icon className="size-3" /> : null}
      {display}
    </span>
  );
}

function formatFullDate(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString(undefined, {
    weekday: 'short',
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  });
}
