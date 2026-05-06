/**
 * `/book/confirmed/[token]` — post-submit confirmation.
 *
 * The customer just finished `/details` and we redirected here. The
 * page reads the appointment by token from the manage endpoint —
 * same data shape as `/manage/[token]` because the customer should
 * see the full details immediately, including the manage URL they
 * just received via email.
 *
 * Why a separate route from `/manage`: the confirmation copy is
 * different ("You're booked!"), and we want a clean shareable URL
 * that isn't the same as the long-term manage link. The manage page
 * is the recurring destination; this is the one-time celebration.
 */

'use client';

import { CalendarCheck, MapPin, User } from 'lucide-react';
import Link from 'next/link';
import { use } from 'react';

import { ApiError } from '@/lib/api';
import {
  formatDuration,
  formatPriceCents,
  formatSlotDate,
  formatSlotTime,
  useManageBooking,
} from '@/lib/booking';

import { BrandHeader } from '../../../_components/brand-header';
import {
  BookingContainer,
  BookingLoadingState,
  BookingNotFoundState,
} from '../../../_components/page-shell';

export default function BookingConfirmedPage({
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
        title={is404 ? 'Booking not found' : 'Could not load this confirmation'}
        message={
          is404
            ? "This confirmation link doesn't exist or has expired."
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
      <BookingContainer>
        <div className="text-center mb-8">
          <div
            className="size-12 mx-auto rounded-full flex items-center justify-center mb-4"
            style={{ background: `${b.tenant.primary_color}1a` }}
          >
            <CalendarCheck
              className="size-6"
              style={{ color: b.tenant.primary_color }}
            />
          </div>
          <h1 className="font-serif text-3xl sm:text-4xl font-semibold tracking-tight text-stone-900">
            You&rsquo;re booked
          </h1>
          <p className="text-stone-600 mt-2">
            We sent a confirmation to{' '}
            <span className="font-medium text-stone-800">{b.customer_email}</span>.
          </p>
        </div>

        <div className="rounded-xl border border-stone-200 bg-white overflow-hidden">
          <div
            className="px-5 py-4 border-b border-stone-200"
            style={{ background: `${b.tenant.primary_color}08` }}
          >
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
                </div>
              }
            />
          </ul>
        </div>

        <div className="mt-8 text-center">
          <Link
            href={`/book/manage/${token}`}
            className="inline-block rounded-md px-5 py-2.5 text-sm font-medium text-white"
            style={{ background: b.tenant.primary_color }}
          >
            Manage booking
          </Link>
          <p className="text-xs text-stone-500 mt-3">
            Bookmark this link to reschedule or cancel later.
          </p>
        </div>
      </BookingContainer>
    </>
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
