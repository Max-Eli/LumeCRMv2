/**
 * `OnlineBookingsPanel` — review inbox for public-site bookings.
 *
 * Shows every appointment with `source='online'` from now forward,
 * sorted by start_time. Front desk uses this to:
 *
 *   - Spot-check who booked and what — names + services scroll past
 *     so the team feels the day's flow before it starts.
 *   - **Approve** a booking (status `booked` → `confirmed`) once
 *     they've reviewed for fit, conflicts, or VIP handling.
 *   - **Cancel** a booking that doesn't make sense (duplicate,
 *     someone the spa doesn't serve, suspicious entry).
 *   - **Jump** to the booking's date on the calendar so they can see
 *     the surrounding day at a glance before approving.
 *
 * Grouped by relative date (Today / Tomorrow / [Mon, Jun 3]) so the
 * list reads inbox-style. Newly-booked rows (status=booked) sit
 * above confirmed/checked-in/etc within each date — operators
 * naturally want to triage the unreviewed ones first.
 *
 * Approve is the dominant action so it gets the primary button
 * treatment; everything else is a secondary text button.
 */

'use client';

import {
  Calendar,
  Check,
  Clock,
  ExternalLink,
  Globe,
  Loader2,
  X,
} from 'lucide-react';
import Link from 'next/link';
import { useMemo, useState } from 'react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { ApiError } from '@/lib/api';
import {
  type Appointment,
  STATUS_LABELS,
  type AppointmentStatus,
  useUpcomingOnlineBookings,
  useUpdateAppointment,
} from '@/lib/appointments';
import { useActiveLocation } from '@/lib/locations';
import { cn } from '@/lib/utils';

export function OnlineBookingsPanel() {
  const { data: bookings, isLoading, error } = useUpcomingOnlineBookings();
  const { location } = useActiveLocation();
  const tz = location?.timezone || 'UTC';

  if (isLoading) {
    return (
      <div className="p-6 flex items-center justify-center text-sm text-muted-foreground">
        <Loader2 className="size-4 animate-spin mr-2" />
        Loading…
      </div>
    );
  }
  if (error) {
    return (
      <div className="p-6 text-sm text-destructive">
        Could not load online bookings.
      </div>
    );
  }
  const list = bookings ?? [];
  if (list.length === 0) {
    return <EmptyState />;
  }

  return (
    <div className="px-3 py-3 space-y-4">
      <Summary count={list.length} />
      <GroupedList bookings={list} timezone={tz} />
    </div>
  );
}

function Summary({ count }: { count: number }) {
  const needsReview = count; // could split by status later
  return (
    <div className="px-2 text-xs text-muted-foreground">
      <span className="font-medium text-foreground">{needsReview}</span> upcoming
      {needsReview === 1 ? ' booking' : ' bookings'} from your public booking page.
    </div>
  );
}

function EmptyState() {
  return (
    <div className="p-4">
      <div className="rounded-lg border border-dashed bg-muted/30 p-5 text-center">
        <div className="inline-flex size-10 items-center justify-center rounded-full bg-card text-muted-foreground border mb-3">
          <Globe className="size-4" />
        </div>
        <h3 className="font-serif text-base font-semibold tracking-tight">
          No online bookings yet
        </h3>
        <p className="text-xs text-muted-foreground mt-1.5 leading-relaxed">
          When someone books through your public page, they&rsquo;ll show up
          here so you can review before the day.
        </p>
        <Link
          href="/org/online-booking"
          className="inline-flex items-center gap-1 mt-4 text-xs font-medium text-foreground hover:underline"
        >
          Manage booking page settings
          <ExternalLink className="size-3" />
        </Link>
      </div>
    </div>
  );
}

// ── Grouped list ─────────────────────────────────────────────────────

function GroupedList({
  bookings,
  timezone,
}: {
  bookings: Appointment[];
  timezone: string;
}) {
  const groups = useMemo(() => groupByLocalDate(bookings, timezone), [bookings, timezone]);
  return (
    <ul className="space-y-3">
      {groups.map(({ key, label, items }) => (
        <li key={key}>
          <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-medium px-2 mb-1.5">
            {label}
          </p>
          <ul className="space-y-1.5">
            {items.map((appt) => (
              <BookingRow key={appt.id} booking={appt} timezone={timezone} dateKey={key} />
            ))}
          </ul>
        </li>
      ))}
    </ul>
  );
}

function BookingRow({
  booking,
  timezone,
  dateKey,
}: {
  booking: Appointment;
  timezone: string;
  dateKey: string;
}) {
  const update = useUpdateAppointment(booking.id);
  const [pending, setPending] = useState<'approve' | 'cancel' | null>(null);

  const isApproved = booking.status !== 'booked';
  const time = formatLocalTime(booking.start_time, timezone);
  const tone = STATUS_TONE[booking.status];

  const submit = (next: AppointmentStatus, label: string) => {
    setPending(next === 'confirmed' ? 'approve' : 'cancel');
    update.mutate(
      { status: next },
      {
        onSuccess: () => toast.success(`${booking.customer.first_name}: ${label}`),
        onError: (err) => {
          if (err instanceof ApiError && err.status === 403) {
            toast.error("You don't have permission to change this booking.");
          } else {
            toast.error('Could not update booking. Please try again.');
          }
        },
        onSettled: () => setPending(null),
      },
    );
  };

  return (
    <li className="rounded-md border border-border bg-card p-3">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5 mb-0.5">
            <Clock className="size-3 text-muted-foreground shrink-0" />
            <span className="text-xs font-medium text-foreground tabular-nums">
              {time}
            </span>
            <span
              className={cn(
                'ml-auto inline-flex items-center rounded-full px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wider',
                tone === 'pending' && 'bg-amber-50 text-amber-800',
                tone === 'approved' && 'bg-emerald-50 text-emerald-700',
                tone === 'terminal' && 'bg-stone-100 text-stone-600',
                tone === 'destructive' && 'bg-red-50 text-red-700',
              )}
            >
              {STATUS_LABELS[booking.status]}
            </span>
          </div>
          <div className="text-sm font-medium text-foreground truncate">
            {booking.customer.full_name}
          </div>
          <div className="text-xs text-muted-foreground truncate">
            {booking.service.name} · {booking.provider.user_first_name}{' '}
            {booking.provider.user_last_name?.[0]
              ? `${booking.provider.user_last_name[0]}.`
              : ''}
          </div>
        </div>
      </div>

      <div className="mt-2.5 flex items-center gap-1.5 flex-wrap">
        {!isApproved ? (
          <Button
            type="button"
            size="sm"
            className="h-7 px-2 text-xs"
            onClick={() => submit('confirmed', 'approved')}
            disabled={pending !== null}
          >
            {pending === 'approve' ? (
              <Loader2 className="size-3 animate-spin" />
            ) : (
              <Check className="size-3" />
            )}
            Approve
          </Button>
        ) : null}
        <Link
          href={`/calendar?date=${dateKey}&tool=online-bookings`}
          className="inline-flex items-center gap-1 h-7 rounded-md border border-border bg-card px-2 text-xs font-medium text-foreground hover:bg-muted transition-colors"
        >
          <Calendar className="size-3" />
          Open
        </Link>
        {booking.status === 'booked' || booking.status === 'confirmed' ? (
          <button
            type="button"
            onClick={() => submit('cancelled', 'cancelled')}
            disabled={pending !== null}
            className="inline-flex items-center gap-1 h-7 px-2 text-xs text-muted-foreground hover:text-red-700 transition-colors disabled:opacity-50"
          >
            {pending === 'cancel' ? (
              <Loader2 className="size-3 animate-spin" />
            ) : (
              <X className="size-3" />
            )}
            Cancel
          </button>
        ) : null}
      </div>
    </li>
  );
}

// ── Helpers ──────────────────────────────────────────────────────────

const STATUS_TONE: Record<AppointmentStatus, 'pending' | 'approved' | 'terminal' | 'destructive'> = {
  booked: 'pending',
  confirmed: 'approved',
  checked_in: 'approved',
  completed: 'approved',
  cancelled: 'terminal',
  no_show: 'destructive',
};

function formatLocalTime(iso: string, timezone: string): string {
  return new Date(iso).toLocaleTimeString('en-US', {
    hour: 'numeric',
    minute: '2-digit',
    timeZone: timezone,
  });
}

function localDateKey(iso: string, timezone: string): string {
  // Format date in the active location's timezone as YYYY-MM-DD so
  // we group by the spa's calendar day, not the operator's browser tz.
  const d = new Date(iso);
  const parts = new Intl.DateTimeFormat('en-CA', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    timeZone: timezone,
  }).formatToParts(d);
  const y = parts.find((p) => p.type === 'year')?.value ?? '';
  const m = parts.find((p) => p.type === 'month')?.value ?? '';
  const da = parts.find((p) => p.type === 'day')?.value ?? '';
  return `${y}-${m}-${da}`;
}

function relativeDateLabel(key: string, timezone: string): string {
  // "Today" / "Tomorrow" if the key matches; otherwise short date.
  const today = localDateKey(new Date().toISOString(), timezone);
  if (key === today) return 'Today';
  const tmrw = new Date();
  tmrw.setDate(tmrw.getDate() + 1);
  if (key === localDateKey(tmrw.toISOString(), timezone)) return 'Tomorrow';
  // Otherwise "Mon, Jun 3" style. Build from the key directly to
  // avoid tz drift — the key was already in the spa's timezone.
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(key);
  if (!m) return key;
  const d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  return d.toLocaleDateString('en-US', {
    weekday: 'short',
    month: 'short',
    day: 'numeric',
  });
}

function groupByLocalDate(
  bookings: Appointment[],
  timezone: string,
): { key: string; label: string; items: Appointment[] }[] {
  const map = new Map<string, Appointment[]>();
  for (const b of bookings) {
    const key = localDateKey(b.start_time, timezone);
    const list = map.get(key) ?? [];
    list.push(b);
    map.set(key, list);
  }
  // Within each date, sort booked (needs-review) above approved.
  const statusWeight: Record<AppointmentStatus, number> = {
    booked: 0,
    confirmed: 1,
    checked_in: 2,
    completed: 3,
    cancelled: 4,
    no_show: 5,
  };
  for (const list of map.values()) {
    list.sort((a, b) => {
      const w = statusWeight[a.status] - statusWeight[b.status];
      if (w !== 0) return w;
      return a.start_time.localeCompare(b.start_time);
    });
  }
  return Array.from(map.entries())
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([key, items]) => ({
      key,
      label: relativeDateLabel(key, timezone),
      items,
    }));
}
