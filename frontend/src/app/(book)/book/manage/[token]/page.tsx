/**
 * `/book/manage/[token]` — manage existing booking.
 *
 * No auth — the token IS the security boundary (see ADR 0011 in
 * apps.forms; same pattern). Lookup by token returns the appointment
 * + tenant branding so the page can theme itself without a separate
 * fetch.
 *
 * Three states:
 *   - **active** (booked / confirmed): show details + Reschedule and
 *     Cancel actions. Reschedule expands an inline date + slot
 *     picker that re-uses the public booking flow's slot calculator.
 *   - **cancelled**: status banner with a CTA to book fresh.
 *   - **other terminal** (completed / no_show / checked_in): show
 *     details with a status banner; no actions.
 */

'use client';

import {
  CalendarCheck,
  CalendarClock,
  CalendarX,
  ChevronLeft,
  Loader2,
  MapPin,
  User,
} from 'lucide-react';
import Link from 'next/link';
import { use, useMemo, useState } from 'react';

import { Button } from '@/components/ui/button';
import { ApiError } from '@/lib/api';
import {
  formatDuration,
  formatPriceCents,
  formatSlotDate,
  formatSlotTime,
  useBookingSlots,
  useBookingTenantInfo,
  useCancelBooking,
  useManageBooking,
  useRescheduleBooking,
} from '@/lib/booking';
import { cn } from '@/lib/utils';

import { BookingCalendar } from '../../../_components/booking-calendar';
import { BrandHeader } from '../../../_components/brand-header';
import {
  BookingContainer,
  BookingLoadingState,
  BookingNotFoundState,
} from '../../../_components/page-shell';

const ACTIVE_STATUSES = new Set(['booked', 'confirmed']);

export default function ManageBookingPage({
  params,
}: {
  params: Promise<{ token: string }>;
}) {
  const { token } = use(params);
  const bookingQ = useManageBooking(token);

  if (bookingQ.isLoading) return <BookingLoadingState />;
  if (bookingQ.error || !bookingQ.data) {
    const is404 = bookingQ.error instanceof ApiError && bookingQ.error.status === 404;
    return (
      <BookingNotFoundState
        title={is404 ? 'Booking not found' : 'Could not load this booking'}
        message={
          is404
            ? "This link doesn't match a booking on file. Check your confirmation email for the correct link."
            : 'Please refresh and try again.'
        }
      />
    );
  }

  const b = bookingQ.data;
  return (
    <>
      <BrandHeader
        tenantName={b.tenant.name}
        logoUrl={b.tenant.logo_url}
        primaryColor={b.tenant.primary_color}
        bookingHref={`/book/${b.tenant.slug}`}
      />
      <ManageBody booking={b} token={token} />
    </>
  );
}

function ManageBody({
  booking: b,
  token,
}: {
  booking: import('@/lib/booking').ManageBooking;
  token: string;
}) {
  const cancel = useCancelBooking(token);
  const [confirmCancel, setConfirmCancel] = useState(false);
  const [cancelError, setCancelError] = useState<string | null>(null);

  // Reschedule UI is collapsed by default; expanded inline below the
  // detail card so the customer doesn't lose context of what they're
  // moving.
  const [reschedulingOpen, setReschedulingOpen] = useState(false);

  const isActive = ACTIVE_STATUSES.has(b.status);
  const isCancelled = b.status === 'cancelled';

  const handleCancel = () => {
    setCancelError(null);
    cancel.mutate(undefined, {
      onSuccess: () => setConfirmCancel(false),
      onError: () => setCancelError('Could not cancel. Please try again or call the spa.'),
    });
  };

  return (
    <BookingContainer>
      <div className="mb-6">
        <p className="text-[11px] uppercase tracking-wider text-stone-500 font-medium mb-1.5">
          Manage booking
        </p>
        <h1 className="font-serif text-3xl font-semibold tracking-tight text-stone-900">
          Hi {b.customer_first_name || 'there'}
        </h1>
      </div>

      {isCancelled ? (
        <div className="rounded-md border border-stone-300 bg-stone-100 px-4 py-3 mb-6 flex items-start gap-2.5">
          <CalendarX className="size-4 text-stone-700 mt-0.5 shrink-0" />
          <div>
            <div className="text-sm font-medium text-stone-900">
              This booking is cancelled
            </div>
            <div className="text-xs text-stone-600 mt-0.5">
              Want to rebook?{' '}
              <Link
                href={`/book/${b.tenant.slug}`}
                className="underline font-medium text-stone-800"
              >
                Pick a new time
              </Link>
              .
            </div>
          </div>
        </div>
      ) : null}

      <div className="rounded-xl border border-stone-200 bg-white overflow-hidden">
        <div
          className="px-5 py-4 border-b border-stone-200"
          style={{ background: `${b.tenant.primary_color}08` }}
        >
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="text-[11px] uppercase tracking-wider text-stone-500 font-medium mb-1">
                {b.service_name}
              </div>
              <div className="text-stone-900 font-medium text-lg">
                {formatSlotDate(b.start_time, b.location.timezone)}
              </div>
              <div className="text-stone-700 text-sm mt-0.5">
                {formatSlotTime(b.start_time, b.location.timezone)} ·{' '}
                {formatDuration(b.duration_minutes)}
                {b.quoted_price_cents > 0 ? (
                  <>
                    <span className="mx-1.5">·</span>
                    {formatPriceCents(b.quoted_price_cents)}
                  </>
                ) : null}
              </div>
            </div>
            <StatusPill status={b.status} primaryColor={b.tenant.primary_color} />
          </div>
        </div>
        <ul className="divide-y divide-stone-200">
          <DetailRow
            icon={<User className="size-4 text-stone-500" />}
            label="Provider"
            value={b.provider_display_name}
          />
          <DetailRow
            icon={<MapPin className="size-4 text-stone-500" />}
            label="Location"
            value={
              <div>
                <div>{b.location.name}</div>
                {b.location.address_line1 ? (
                  <div className="text-stone-500 text-sm">
                    {b.location.address_line1}
                    {b.location.city ? `, ${b.location.city}` : ''}
                    {b.location.state ? `, ${b.location.state}` : ''}
                    {b.location.zip_code ? ` ${b.location.zip_code}` : ''}
                  </div>
                ) : null}
                {b.location.phone ? (
                  <div className="text-stone-500 text-sm">{b.location.phone}</div>
                ) : null}
              </div>
            }
          />
        </ul>
      </div>

      {b.tenant.cancellation_policy ? (
        <section className="mt-8 rounded-lg border border-stone-200 bg-white px-5 py-4">
          <h2 className="text-[11px] uppercase tracking-wider text-stone-500 font-medium mb-2">
            Cancellation policy
          </h2>
          <div className="text-sm text-stone-700 leading-relaxed whitespace-pre-line">
            {b.tenant.cancellation_policy}
          </div>
        </section>
      ) : null}

      {isActive ? (
        <div className="mt-8 space-y-4">
          {/* Action row — primary action is reschedule, secondary is
              cancel. Both collapse expandable panels below. */}
          {!confirmCancel && !reschedulingOpen ? (
            <div className="flex flex-col sm:flex-row gap-3 sm:items-center sm:justify-between">
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => setReschedulingOpen(true)}
                  className="inline-flex items-center gap-1.5 rounded-md px-4 py-2.5 text-sm font-medium text-white"
                  style={{ background: b.tenant.primary_color }}
                >
                  <CalendarClock className="size-4" />
                  Reschedule
                </button>
                <Link
                  href={`/book/${b.tenant.slug}`}
                  className="inline-flex items-center rounded-md border border-stone-300 bg-white px-4 py-2.5 text-sm font-medium text-stone-800 hover:bg-stone-50 transition-colors"
                >
                  Book another appointment
                </Link>
              </div>
              <button
                type="button"
                onClick={() => setConfirmCancel(true)}
                className="text-sm text-stone-600 hover:text-red-700 underline"
              >
                Cancel this booking
              </button>
            </div>
          ) : null}

          {reschedulingOpen ? (
            <RescheduleForm
              token={token}
              booking={b}
              onCancel={() => setReschedulingOpen(false)}
              onDone={() => setReschedulingOpen(false)}
            />
          ) : null}

          {confirmCancel ? (
            <div className="rounded-lg border border-red-200 bg-red-50 px-5 py-4">
              <div className="text-sm font-medium text-red-900 mb-1">
                Cancel this booking?
              </div>
              <p className="text-xs text-red-700 leading-relaxed mb-3">
                The time slot will be released so other customers can book
                it. You&rsquo;ll be able to rebook any time.
              </p>
              <div className="flex flex-wrap items-center gap-2">
                <Button
                  type="button"
                  size="sm"
                  variant="destructive"
                  onClick={handleCancel}
                  disabled={cancel.isPending}
                >
                  {cancel.isPending ? 'Cancelling…' : 'Yes, cancel booking'}
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  onClick={() => setConfirmCancel(false)}
                  disabled={cancel.isPending}
                >
                  Keep booking
                </Button>
              </div>
              {cancelError ? (
                <p className="text-xs text-red-700 mt-2">{cancelError}</p>
              ) : null}
            </div>
          ) : null}
        </div>
      ) : null}
    </BookingContainer>
  );
}

// ── Reschedule inline form ──────────────────────────────────────────

function RescheduleForm({
  token,
  booking,
  onCancel,
  onDone,
}: {
  token: string;
  booking: import('@/lib/booking').ManageBooking;
  onCancel: () => void;
  onDone: () => void;
}) {
  const reschedule = useRescheduleBooking(token);
  // We need the tenant's booking_window_days to cap the calendar's
  // maxDate. Pull tenant info via the existing public endpoint —
  // cached in react-query so subsequent mounts are free.
  const tenantQ = useBookingTenantInfo(booking.tenant.slug);
  const windowDays = tenantQ.data?.booking_window_days ?? 60;

  const todayIso = useMemo(() => toLocalIsoDate(new Date()), []);
  const maxDateIso = useMemo(() => {
    const d = new Date();
    d.setDate(d.getDate() + windowDays);
    return toLocalIsoDate(d);
  }, [windowDays]);

  const [activeDate, setActiveDate] = useState<string>(todayIso);
  const slotsQ = useBookingSlots(booking.tenant.slug, {
    serviceId: booking.service_id,
    locationId: booking.location.id,
    date: activeDate,
    provider: booking.provider_id,
  });

  const [topError, setTopError] = useState<string | null>(null);

  const submit = (slot: { start: string; available: boolean; provider_id?: number | null }) => {
    if (!slot.available) return;
    setTopError(null);
    reschedule.mutate(
      { start_time: slot.start },
      {
        onSuccess: onDone,
        onError: (err) => {
          if (err instanceof ApiError) {
            if (err.status === 409) {
              setTopError(
                'That time was just booked. Please pick another slot.',
              );
              return;
            }
            if (err.status === 400 && err.body && typeof err.body === 'object') {
              const body = err.body as Record<string, unknown>;
              if (typeof body.detail === 'string') {
                setTopError(body.detail);
                return;
              }
            }
          }
          setTopError('Could not reschedule. Please try again.');
        },
      },
    );
  };

  return (
    <div
      className="rounded-lg border bg-white px-5 py-4"
      style={{ borderLeftColor: booking.tenant.primary_color, borderLeftWidth: 3 }}
    >
      <div className="flex items-center justify-between gap-2 mb-4">
        <h3 className="text-sm font-semibold text-stone-900 inline-flex items-center gap-1.5">
          <CalendarClock className="size-4" />
          Pick a new time
        </h3>
        <button
          type="button"
          onClick={onCancel}
          className="inline-flex items-center gap-1 text-xs text-stone-500 hover:text-stone-800"
          disabled={reschedule.isPending}
        >
          <ChevronLeft className="size-3" />
          Back
        </button>
      </div>

      <div className="text-xs text-stone-600 mb-4">
        Currently scheduled for{' '}
        <span className="font-medium text-stone-900">
          {formatSlotDate(booking.start_time, booking.location.timezone)} at{' '}
          {formatSlotTime(booking.start_time, booking.location.timezone)}
        </span>
        . Same {booking.provider_display_name ? `provider (${booking.provider_display_name})` : 'provider'} and
        location ({booking.location.name}).
      </div>

      <div className="mb-4">
        <BookingCalendar
          value={activeDate}
          onChange={setActiveDate}
          minDate={todayIso}
          maxDate={maxDateIso}
          primaryColor={booking.tenant.primary_color}
        />
      </div>

      <div>
        <h4 className="text-sm font-semibold text-stone-900 mb-2">
          Available times
        </h4>
        {slotsQ.isLoading ? (
          <p className="text-sm text-stone-500">Loading slots…</p>
        ) : slotsQ.error ? (
          <p className="text-sm text-red-600">
            Could not load times. Refresh and try again.
          </p>
        ) : (slotsQ.data ?? []).length === 0 ? (
          <p className="text-sm text-stone-700">
            No openings on this day. Try a different date.
          </p>
        ) : (
          <div className="grid grid-cols-3 sm:grid-cols-4 gap-2">
            {(slotsQ.data ?? []).map((slot) => {
              const label = formatSlotTime(
                slot.start,
                booking.location.timezone,
              );
              const isCurrent =
                new Date(slot.start).getTime() ===
                new Date(booking.start_time).getTime();
              if (!slot.available && !isCurrent) {
                return (
                  <button
                    key={`${slot.start}-taken`}
                    type="button"
                    disabled
                    title="This time is already booked"
                    className="rounded-md border border-stone-200 bg-stone-50 px-3 py-2.5 text-sm font-medium text-stone-400 line-through cursor-not-allowed"
                  >
                    {label}
                  </button>
                );
              }
              return (
                <button
                  key={`${slot.start}-pick`}
                  type="button"
                  onClick={() => submit(slot)}
                  disabled={reschedule.isPending}
                  className={cn(
                    'rounded-md border px-3 py-2.5 text-sm font-medium transition-colors',
                    isCurrent
                      ? 'border-stone-900 bg-stone-900 text-white'
                      : 'border-stone-300 bg-white text-stone-800 hover:border-stone-900 hover:bg-stone-900 hover:text-white',
                    reschedule.isPending && 'opacity-60',
                  )}
                >
                  {isCurrent ? 'Current' : label}
                </button>
              );
            })}
          </div>
        )}
      </div>

      {topError ? (
        <p className="mt-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
          {topError}
        </p>
      ) : null}

      {reschedule.isPending ? (
        <p className="mt-3 text-xs text-stone-600 inline-flex items-center gap-1.5">
          <Loader2 className="size-3 animate-spin" />
          Rescheduling…
        </p>
      ) : null}
    </div>
  );
}

function toLocalIsoDate(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const da = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${da}`;
}

function StatusPill({
  status,
  primaryColor,
}: {
  status: import('@/lib/booking').BookingStatus;
  primaryColor: string;
}) {
  const tone = statusTone(status);
  const label = statusLabel(status);
  return (
    <span
      className={cn(
        'shrink-0 inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-medium uppercase tracking-wider',
        tone === 'active' && 'bg-emerald-50 text-emerald-700',
        tone === 'cancelled' && 'bg-stone-100 text-stone-700',
        tone === 'terminal' && 'bg-stone-100 text-stone-700',
      )}
      style={tone === 'active' ? { background: `${primaryColor}1a`, color: primaryColor } : undefined}
    >
      {tone === 'active' ? <CalendarCheck className="size-3" /> : null}
      {label}
    </span>
  );
}

function DetailRow({
  icon,
  label,
  value,
}: {
  icon: React.ReactNode;
  label: string;
  value: React.ReactNode;
}) {
  return (
    <li className="px-5 py-3.5 flex items-start gap-3">
      <div className="pt-0.5">{icon}</div>
      <div className="flex-1 min-w-0">
        <div className="text-[11px] uppercase tracking-wider text-stone-500 font-medium">
          {label}
        </div>
        <div className="text-stone-900 mt-0.5">{value}</div>
      </div>
    </li>
  );
}

function statusLabel(status: import('@/lib/booking').BookingStatus): string {
  switch (status) {
    case 'booked':
      return 'Booked';
    case 'confirmed':
      return 'Confirmed';
    case 'checked_in':
      return 'Checked in';
    case 'completed':
      return 'Completed';
    case 'no_show':
      return 'No-show';
    case 'cancelled':
      return 'Cancelled';
  }
}

function statusTone(status: import('@/lib/booking').BookingStatus): 'active' | 'cancelled' | 'terminal' {
  if (status === 'cancelled') return 'cancelled';
  if (ACTIVE_STATUSES.has(status)) return 'active';
  return 'terminal';
}
