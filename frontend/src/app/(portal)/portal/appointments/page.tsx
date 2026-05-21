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

import { ApiError } from '@/lib/api';
import {
  type BookableSlot,
  type PortalAppointment,
  useBookableSlots,
  useCancelAppointment,
  usePortalAppointments,
  usePortalMe,
  useRescheduleAppointment,
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
  const [rescheduling, setRescheduling] = useState(false);
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
          rescheduling ? (
            <ReschedulePanel
              appointment={appointment}
              onClose={() => setRescheduling(false)}
              onDone={() => setRescheduling(false)}
            />
          ) : (
            <div className="mt-4 pt-4 border-t flex flex-wrap items-center justify-end gap-2">
              {error ? (
                <p className="text-xs text-destructive flex-1">{error}</p>
              ) : null}
              {confirming ? (
                <>
                  <span className="text-xs text-muted-foreground">
                    Cancel this appointment?
                  </span>
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
                <>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => setRescheduling(true)}
                  >
                    Reschedule
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => setConfirming(true)}
                  >
                    Cancel appointment
                  </Button>
                </>
              )}
            </div>
          )
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

// ── Reschedule panel ────────────────────────────────────────────────


function ReschedulePanel({
  appointment,
  onClose,
  onDone,
}: {
  appointment: PortalAppointment;
  onClose: () => void;
  onDone: () => void;
}) {
  const { data: me } = usePortalMe();
  const dates = useMemo(() => nextDates(14), []);
  const [date, setDate] = useState<string>(() => dates[0].iso);
  const [slotStart, setSlotStart] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const { data: slots, isLoading } = useBookableSlots(me?.tenant.slug, {
    serviceId: appointment.service_id,
    providerId: appointment.provider_id,
    date,
  });
  const reschedule = useRescheduleAppointment();

  const onConfirm = async () => {
    if (!slotStart) return;
    setError(null);
    try {
      await reschedule.mutateAsync({
        id: appointment.id,
        start_time: slotStart,
      });
      onDone();
    } catch (err) {
      if (err instanceof ApiError && err.body && typeof err.body === 'object') {
        const body = err.body as Record<string, string | string[]>;
        const first = Object.values(body)[0];
        const msg = Array.isArray(first) ? first[0] : first;
        setError(typeof msg === 'string' ? msg : 'Could not reschedule.');
      } else {
        setError('Could not reschedule. Try again or contact the spa.');
      }
    }
  };

  return (
    <div className="mt-4 space-y-4 border-t pt-4">
      <div className="flex items-center justify-between">
        <p className="text-sm font-medium">Pick a new time</p>
        <button
          type="button"
          onClick={onClose}
          className="text-xs text-muted-foreground hover:text-foreground"
        >
          Cancel
        </button>
      </div>

      <div className="-mx-1 flex gap-2 overflow-x-auto px-1 pb-1">
        {dates.map((d) => {
          const isActive = d.iso === date;
          return (
            <button
              key={d.iso}
              type="button"
              onClick={() => {
                setDate(d.iso);
                setSlotStart(null);
              }}
              className={cn(
                'flex min-w-[3.75rem] shrink-0 flex-col items-center justify-center rounded-xl border bg-card px-3 py-2 transition-all',
                isActive
                  ? 'border-transparent ring-2 ring-[var(--portal-brand,#1f2937)]'
                  : 'hover:border-foreground/20',
              )}
            >
              <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
                {d.weekday}
              </span>
              <span className="mt-0.5 text-base font-semibold tabular-nums">
                {d.day}
              </span>
              <span className="text-[10px] text-muted-foreground">{d.month}</span>
            </button>
          );
        })}
      </div>

      {isLoading ? (
        <div className="flex justify-center py-6 text-muted-foreground">
          <Loader2 className="size-4 animate-spin" />
        </div>
      ) : !slots?.length ? (
        <p className="rounded-lg border border-dashed px-4 py-5 text-center text-sm text-muted-foreground">
          No times available on this date. Try another day.
        </p>
      ) : (
        <ul className="grid grid-cols-3 gap-2 sm:grid-cols-4">
          {slots.map((s: BookableSlot) => {
            const isSelected = slotStart === s.start;
            return (
              <li key={s.start}>
                <button
                  type="button"
                  disabled={!s.available}
                  onClick={() => setSlotStart(s.start)}
                  className={cn(
                    'w-full rounded-md border bg-card px-2 py-2 text-sm tabular-nums transition-all',
                    !s.available
                      ? 'cursor-not-allowed opacity-40'
                      : isSelected
                        ? 'border-transparent font-medium ring-2 ring-[var(--portal-brand,#1f2937)]'
                        : 'hover:border-foreground/30',
                  )}
                >
                  {formatSlotTime(s.start)}
                </button>
              </li>
            );
          })}
        </ul>
      )}

      {error ? <p className="text-xs text-destructive">{error}</p> : null}

      <div className="flex justify-end">
        <Button
          type="button"
          onClick={onConfirm}
          disabled={!slotStart || reschedule.isPending}
          style={{ background: 'var(--portal-brand, #1f2937)', color: '#fff' }}
        >
          {reschedule.isPending ? (
            <Loader2 className="size-4 animate-spin" />
          ) : null}
          Confirm new time
        </Button>
      </div>
    </div>
  );
}

function nextDates(count: number): Array<{
  iso: string;
  weekday: string;
  day: string;
  month: string;
}> {
  const out: Array<{ iso: string; weekday: string; day: string; month: string }> = [];
  const today = new Date();
  for (let i = 0; i < count; i++) {
    const d = new Date(today);
    d.setDate(today.getDate() + i);
    out.push({
      iso: `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`,
      weekday: d.toLocaleDateString(undefined, { weekday: 'short' }),
      day: String(d.getDate()),
      month: d.toLocaleDateString(undefined, { month: 'short' }),
    });
  }
  return out;
}

function formatSlotTime(iso: string): string {
  return new Date(iso).toLocaleTimeString(undefined, {
    hour: 'numeric',
    minute: '2-digit',
  });
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
