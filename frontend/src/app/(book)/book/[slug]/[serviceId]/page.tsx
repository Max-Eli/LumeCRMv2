/**
 * `/book/[slug]/[serviceId]` — provider + date + slot picker (step 2).
 *
 * Three picker dimensions on one page:
 *   - **Provider**: "any available" by default, or a specific person.
 *     "Any" lets the customer get the earliest possible slot
 *     regardless of who's open; specific is for repeat customers
 *     who like Sarah.
 *   - **Date**: a horizontal scroll of the next 14 days.
 *   - **Slot**: a grid of available start times for the chosen
 *     (provider, date) combo.
 *
 * Picking a slot navigates to `/details` with the slot encoded in the
 * URL (provider_id, start_time). The details page is dumb about
 * availability — it just collects the customer's contact info and
 * POSTs the booking. The backend re-validates the slot at submit
 * time, so a stale URL still produces a clean 409 error.
 */

'use client';

import { ChevronLeft } from 'lucide-react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { use, useMemo, useState } from 'react';

import { ApiError } from '@/lib/api';
import {
  formatDuration,
  formatPriceCents,
  formatSlotTime,
  useBookingProviders,
  useBookingServices,
  useBookingSlots,
  useBookingTenantInfo,
} from '@/lib/booking';
import { cn } from '@/lib/utils';

import { BookingCalendar } from '../../../_components/booking-calendar';
import { BrandHeader } from '../../../_components/brand-header';
import {
  BookingContainer,
  BookingLoadingState,
  BookingNotFoundState,
} from '../../../_components/page-shell';
import { WaitlistInvite } from '../../../_components/waitlist-invite';

export default function ProviderSlotPickerPage({
  params,
}: {
  params: Promise<{ slug: string; serviceId: string }>;
}) {
  const { slug, serviceId: serviceIdStr } = use(params);
  const serviceId = Number(serviceIdStr);
  const tenantQ = useBookingTenantInfo(slug);
  const servicesQ = useBookingServices(slug);

  if (tenantQ.isLoading || servicesQ.isLoading) {
    return <BookingLoadingState />;
  }
  if (tenantQ.error || !tenantQ.data) {
    const is404 = tenantQ.error instanceof ApiError && tenantQ.error.status === 404;
    return (
      <BookingNotFoundState
        title={is404 ? 'Spa not found' : 'Could not load this booking page'}
      />
    );
  }
  const service = (servicesQ.data ?? []).find((s) => s.id === serviceId);
  if (!service) {
    return (
      <BookingNotFoundState
        title="Service not available"
        message="This service may have been retired. Pick another from the menu."
      />
    );
  }

  return (
    <>
      <BrandHeader
        tenantName={tenantQ.data.name}
        logoUrl={tenantQ.data.logo_url}
        primaryColor={tenantQ.data.primary_color}
        bookingHref={`/book/${slug}`}
      />
      <PickerBody
        slug={slug}
        serviceId={service.id}
        serviceName={service.name}
        serviceDuration={service.duration_minutes}
        servicePriceCents={service.price_cents}
        primaryColor={tenantQ.data.primary_color}
        locations={tenantQ.data.locations}
        bookingWindowDays={tenantQ.data.booking_window_days}
      />
    </>
  );
}

function PickerBody({
  slug,
  serviceId,
  serviceName,
  serviceDuration,
  servicePriceCents,
  primaryColor,
  locations,
  bookingWindowDays,
}: {
  slug: string;
  serviceId: number;
  serviceName: string;
  serviceDuration: number;
  servicePriceCents: number;
  primaryColor: string;
  locations: import('@/lib/booking').BookingLocation[];
  bookingWindowDays: number;
}) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const urlLocationId = searchParams.get('location');
  const activeLocation = useMemo(() => {
    if (urlLocationId) {
      const found = locations.find((l) => String(l.id) === urlLocationId);
      if (found) return found;
    }
    return locations[0];
  }, [locations, urlLocationId]);

  const [providerChoice, setProviderChoice] = useState<number | 'any'>('any');
  const todayIso = useMemo(() => toLocalIsoDate(new Date()), []);
  const maxDateIso = useMemo(() => {
    const d = new Date();
    d.setDate(d.getDate() + bookingWindowDays);
    return toLocalIsoDate(d);
  }, [bookingWindowDays]);
  const [activeDate, setActiveDate] = useState<string>(todayIso);

  const providersQ = useBookingProviders(slug, serviceId, activeLocation?.id);
  const slotsQ = useBookingSlots(slug, {
    serviceId,
    locationId: activeLocation?.id,
    date: activeDate,
    provider: providerChoice,
  });

  const handlePickSlot = (slot: {
    start: string;
    available: boolean;
    provider_id?: number | null;
  }) => {
    if (!activeLocation || !slot.available) return;
    const resolvedProvider =
      slot.provider_id ?? (providerChoice !== 'any' ? providerChoice : undefined);
    if (!resolvedProvider) return;
    const params = new URLSearchParams({
      location: String(activeLocation.id),
      provider: String(resolvedProvider),
      start: slot.start,
    });
    router.push(`/book/${slug}/${serviceId}/details?${params}`);
  };

  return (
    <BookingContainer>
      <Link
        href={`/book/${slug}${activeLocation ? `?location=${activeLocation.id}` : ''}`}
        className="inline-flex items-center gap-1.5 text-sm text-stone-600 hover:text-stone-900 mb-6"
      >
        <ChevronLeft className="size-4" />
        Back to services
      </Link>

      <div className="mb-10 rounded-2xl border border-stone-200 bg-white p-5 sm:p-6 shadow-sm">
        <p className="text-[11px] uppercase tracking-[0.18em] text-stone-500 font-semibold mb-2.5">
          Service
        </p>
        <h1 className="font-serif text-2xl sm:text-3xl font-semibold tracking-tight text-stone-900 leading-tight">
          {serviceName}
        </h1>
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-stone-600 mt-3">
          <span className="font-medium text-stone-700">{formatDuration(serviceDuration)}</span>
          {servicePriceCents > 0 ? (
            <>
              <span className="text-stone-300">·</span>
              <span className="font-semibold" style={{ color: primaryColor }}>
                {formatPriceCents(servicePriceCents)}
              </span>
            </>
          ) : null}
          {activeLocation ? (
            <>
              <span className="text-stone-300">·</span>
              <span>{activeLocation.name}</span>
            </>
          ) : null}
        </div>
      </div>

      {/* Provider picker */}
      <section className="mb-10">
        <h2 className="text-[11px] uppercase tracking-[0.18em] text-stone-500 font-semibold mb-3">
          Choose your provider
        </h2>
        <div className="flex flex-wrap gap-2">
          <ProviderPill
            label="Anyone available"
            sublabel="Earliest opening"
            active={providerChoice === 'any'}
            onClick={() => setProviderChoice('any')}
          />
          {(providersQ.data ?? []).map((p) => (
            <ProviderPill
              key={p.id}
              label={p.display_name}
              sublabel={p.job_title}
              active={providerChoice === p.id}
              onClick={() => setProviderChoice(p.id)}
            />
          ))}
        </div>
      </section>

      {/* Date picker — month-view calendar */}
      <section className="mb-10">
        <h2 className="text-[11px] uppercase tracking-[0.18em] text-stone-500 font-semibold mb-3">
          Pick a date
        </h2>
        <BookingCalendar
          value={activeDate}
          onChange={setActiveDate}
          minDate={todayIso}
          maxDate={maxDateIso}
          primaryColor={primaryColor}
        />
        <p className="text-xs text-stone-500 mt-3">
          Selected: <span className="font-medium text-stone-700">{formatPickedDate(activeDate)}</span>
        </p>
      </section>

      {/* Slots */}
      <section>
        <h2 className="text-[11px] uppercase tracking-[0.18em] text-stone-500 font-semibold mb-3">
          Available times
        </h2>
        {slotsQ.isLoading ? (
          <p className="text-sm text-stone-500">Loading slots…</p>
        ) : slotsQ.error ? (
          <p className="text-sm text-red-600">Could not load times. Refresh and try again.</p>
        ) : (slotsQ.data ?? []).length === 0 ? (
          <>
            <div className="rounded-lg border border-dashed border-stone-300 bg-stone-50 px-5 py-8 text-center">
              <p className="text-sm text-stone-700 font-medium">No openings on this day.</p>
              <p className="text-xs text-stone-500 mt-1">Try another date or provider.</p>
            </div>
            {activeLocation ? (
              <WaitlistInvite
                slug={slug}
                serviceId={serviceId}
                serviceName={serviceName}
                locationId={activeLocation.id}
                providerId={providerChoice === 'any' ? null : providerChoice}
                preferredDate={activeDate}
                primaryColor={primaryColor}
              />
            ) : null}
          </>
        ) : (
          <>
            <div className="grid grid-cols-3 sm:grid-cols-4 gap-2 sm:gap-2.5">
              {(slotsQ.data ?? []).map((slot) => {
                const label = activeLocation
                  ? formatSlotTime(slot.start, activeLocation.timezone)
                  : new Date(slot.start).toLocaleTimeString();
                if (!slot.available) {
                  return (
                    <button
                      key={`${slot.start}-taken`}
                      type="button"
                      disabled
                      title="This time is already booked"
                      className="rounded-lg border border-stone-200 bg-stone-50/60 px-3 py-3 text-sm font-medium text-stone-400 line-through cursor-not-allowed"
                    >
                      {label}
                    </button>
                  );
                }
                return (
                  <button
                    key={`${slot.start}-${slot.provider_id ?? 'p'}`}
                    type="button"
                    onClick={() => handlePickSlot(slot)}
                    className="rounded-lg border border-stone-300 bg-white px-3 py-3 text-sm font-semibold text-stone-800 hover:border-stone-900 hover:bg-stone-900 hover:text-white hover:shadow-sm transition-all"
                    style={{ ['--brand' as string]: primaryColor }}
                  >
                    {label}
                  </button>
                );
              })}
            </div>
            {(slotsQ.data ?? []).every((s) => !s.available) ? (
              <>
                <p className="text-xs text-stone-500 mt-3">
                  All slots on this day are taken. Try a different date or
                  provider — or join the waitlist below.
                </p>
                {activeLocation ? (
                  <WaitlistInvite
                    slug={slug}
                    serviceId={serviceId}
                    serviceName={serviceName}
                    locationId={activeLocation.id}
                    providerId={providerChoice === 'any' ? null : providerChoice}
                    preferredDate={activeDate}
                    primaryColor={primaryColor}
                  />
                ) : null}
              </>
            ) : null}
          </>
        )}
      </section>
    </BookingContainer>
  );
}

function ProviderPill({
  label,
  sublabel,
  active,
  onClick,
}: {
  label: string;
  sublabel?: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        'rounded-xl border px-4 py-2.5 text-left transition-all',
        active
          ? 'border-stone-900 bg-stone-900 text-white shadow-sm'
          : 'border-stone-300 bg-white text-stone-800 hover:border-stone-900 hover:bg-stone-50',
      )}
    >
      <div className="text-sm font-semibold leading-tight">{label}</div>
      {sublabel ? (
        <div
          className={cn(
            'text-[11px] mt-0.5',
            active ? 'text-white/75' : 'text-stone-500',
          )}
        >
          {sublabel}
        </div>
      ) : null}
    </button>
  );
}

function toLocalIsoDate(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const da = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${da}`;
}

function formatPickedDate(iso: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  if (!m) return iso;
  const d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  return d.toLocaleDateString('en-US', {
    weekday: 'long',
    month: 'long',
    day: 'numeric',
    year: 'numeric',
  });
}
