/**
 * `/book/[slug]/[serviceId]/details` — customer info + submit (step 3).
 *
 * Final step before the booking is created. The slot, provider, and
 * location are all pinned via search params from step 2; the customer
 * fills in their identity here. Submit POSTs to the backend's
 * `/api/booking/<slug>/book/`. On success → redirect to
 * `/book/confirmed/<token>`. On 409 (slot got taken) → kick back to
 * step 2 with an error so they can pick a different time.
 *
 * Customer info is intentionally NOT persisted to localStorage.
 * It's PHI-adjacent (name + email + phone tied to a booking
 * intent), and the value of "remember last entry" is low — the spa's
 * existing-customer matching reuses records server-side anyway.
 */

'use client';

import { ChevronLeft, Loader2 } from 'lucide-react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { use, useState } from 'react';

import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Field, FieldError, FieldLabel } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { ApiError } from '@/lib/api';
import {
  formatDuration,
  formatPriceCents,
  formatSlotDate,
  formatSlotTime,
  useBookingServices,
  useBookingTenantInfo,
  useSubmitBooking,
} from '@/lib/booking';

import { BrandHeader } from '../../../../_components/brand-header';
import {
  BookingContainer,
  BookingLoadingState,
  BookingNotFoundState,
} from '../../../../_components/page-shell';

export default function BookingDetailsPage({
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
      <DetailsForm
        slug={slug}
        service={service}
        tenant={tenantQ.data}
      />
    </>
  );
}

function DetailsForm({
  slug,
  service,
  tenant,
}: {
  slug: string;
  service: import('@/lib/booking').BookableService;
  tenant: import('@/lib/booking').BookingTenantInfo;
}) {
  const router = useRouter();
  const searchParams = useSearchParams();

  const locationId = searchParams.get('location');
  const providerId = searchParams.get('provider');
  const start = searchParams.get('start');
  const location = tenant.locations.find((l) => String(l.id) === locationId);

  const [firstName, setFirstName] = useState('');
  const [lastName, setLastName] = useState('');
  const [email, setEmail] = useState('');
  const [phone, setPhone] = useState('');
  const [notes, setNotes] = useState('');
  const [emailMarketingOptIn, setEmailMarketingOptIn] = useState(false);
  const [smsMarketingOptIn, setSmsMarketingOptIn] = useState(false);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [topError, setTopError] = useState<string | null>(null);

  const submit = useSubmitBooking(slug);

  if (!locationId || !providerId || !start || !location) {
    return (
      <BookingContainer>
        <p className="text-sm text-stone-700">
          Your time slot information is missing. Please pick a slot again.
        </p>
        <Link
          href={`/book/${slug}/${service.id}${locationId ? `?location=${locationId}` : ''}`}
          className="mt-4 inline-block text-sm font-medium text-stone-900 underline"
        >
          Pick a time
        </Link>
      </BookingContainer>
    );
  }

  const validate = (): boolean => {
    const errs: Record<string, string> = {};
    if (!firstName.trim()) errs.firstName = 'First name is required.';
    if (!lastName.trim()) errs.lastName = 'Last name is required.';
    if (!email.trim()) errs.email = 'Email is required.';
    else if (!/.+@.+\..+/.test(email)) errs.email = 'Enter a valid email.';
    if (!phone.trim()) errs.phone = 'Phone is required.';
    setFieldErrors(errs);
    return Object.keys(errs).length === 0;
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setTopError(null);
    if (!validate()) return;

    submit.mutate(
      {
        service_id: service.id,
        provider_id: Number(providerId),
        location_id: Number(locationId),
        start_time: start,
        customer_first_name: firstName.trim(),
        customer_last_name: lastName.trim(),
        customer_email: email.trim(),
        customer_phone: phone.trim(),
        notes: notes.trim() || undefined,
        email_marketing_opt_in: emailMarketingOptIn,
        sms_marketing_opt_in: smsMarketingOptIn,
      },
      {
        onSuccess: (booking) => {
          router.push(`/book/confirmed/${booking.booking_token}`);
        },
        onError: (err) => {
          if (err instanceof ApiError) {
            if (err.status === 409) {
              setTopError(
                'That time was just booked by someone else. Please pick another slot.',
              );
              return;
            }
            if (err.status === 400 && err.body && typeof err.body === 'object') {
              const body = err.body as Record<string, unknown>;
              if (typeof body.detail === 'string') {
                setTopError(body.detail);
                return;
              }
              const firstField = Object.keys(body)[0];
              if (firstField) {
                const v = body[firstField];
                setTopError(Array.isArray(v) ? String(v[0]) : String(v));
                return;
              }
            }
          }
          setTopError('Something went wrong. Please try again.');
        },
      },
    );
  };

  return (
    <BookingContainer>
      <Link
        href={`/book/${slug}/${service.id}?location=${locationId}`}
        className="inline-flex items-center gap-1.5 text-sm text-stone-600 hover:text-stone-900 mb-6"
      >
        <ChevronLeft className="size-4" />
        Change time
      </Link>

      <h1 className="font-serif text-3xl font-semibold tracking-tight text-stone-900 mb-2">
        Almost there
      </h1>
      <p className="text-stone-600 mb-8">
        Just need a few quick details to confirm your booking.
      </p>

      {/* Booking summary card */}
      <div className="rounded-lg border border-stone-200 bg-white px-5 py-4 mb-8">
        <div className="text-[11px] uppercase tracking-wider text-stone-500 font-medium mb-1.5">
          Your booking
        </div>
        <div className="text-stone-900 font-medium">{service.name}</div>
        <div className="text-sm text-stone-600 mt-1">
          {formatSlotDate(start, location.timezone)} ·{' '}
          {formatSlotTime(start, location.timezone)}
        </div>
        <div className="text-sm text-stone-600 mt-0.5">
          {formatDuration(service.duration_minutes)}
          {service.price_cents > 0 ? (
            <>
              <span className="mx-1.5">·</span>
              {formatPriceCents(service.price_cents)}
            </>
          ) : null}
          <span className="mx-1.5">·</span>
          {location.name}
        </div>
      </div>

      <form onSubmit={handleSubmit} className="space-y-5">
        <div className="grid sm:grid-cols-2 gap-4">
          <Field>
            <FieldLabel>First name</FieldLabel>
            <Input
              value={firstName}
              onChange={(e) => setFirstName(e.target.value)}
              autoComplete="given-name"
            />
            {fieldErrors.firstName ? (
              <FieldError>{fieldErrors.firstName}</FieldError>
            ) : null}
          </Field>
          <Field>
            <FieldLabel>Last name</FieldLabel>
            <Input
              value={lastName}
              onChange={(e) => setLastName(e.target.value)}
              autoComplete="family-name"
            />
            {fieldErrors.lastName ? (
              <FieldError>{fieldErrors.lastName}</FieldError>
            ) : null}
          </Field>
        </div>

        <Field>
          <FieldLabel>Email</FieldLabel>
          <Input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            autoComplete="email"
            inputMode="email"
          />
          {fieldErrors.email ? <FieldError>{fieldErrors.email}</FieldError> : null}
        </Field>

        <Field>
          <FieldLabel>Phone</FieldLabel>
          <Input
            type="tel"
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
            autoComplete="tel"
            inputMode="tel"
          />
          {fieldErrors.phone ? <FieldError>{fieldErrors.phone}</FieldError> : null}
        </Field>

        <Field>
          <FieldLabel>Anything we should know? (optional)</FieldLabel>
          <textarea
            className="w-full rounded-md border border-stone-300 bg-white px-3 py-2 text-sm focus:outline-hidden focus:ring-2 focus:ring-stone-900/20 focus:border-stone-900"
            rows={3}
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            maxLength={500}
            placeholder="Allergies, accessibility needs, special requests…"
          />
        </Field>

        {/* Marketing consent — TCPA + CAN-SPAM. Both default unchecked;
            opt-in is captured per-channel with timestamp + source on the
            backend (consent_source='booking_form'). Transactional
            booking emails are independent and always sent. */}
        <fieldset className="space-y-3 rounded-lg border border-stone-200 bg-stone-50/60 px-4 py-3">
          <legend className="px-1 text-[11px] uppercase tracking-wider text-stone-500 font-medium">
            Stay in touch (optional)
          </legend>
          <label className="flex items-start gap-3 cursor-pointer">
            <Checkbox
              checked={emailMarketingOptIn}
              onCheckedChange={(v) => setEmailMarketingOptIn(v === true)}
              className="mt-0.5"
            />
            <span className="text-sm text-stone-700 leading-snug">
              Email me promotions, news, and special offers from{' '}
              {tenant.name}. Unsubscribe any time.
            </span>
          </label>
          <label className="flex items-start gap-3 cursor-pointer">
            <Checkbox
              checked={smsMarketingOptIn}
              onCheckedChange={(v) => setSmsMarketingOptIn(v === true)}
              className="mt-0.5"
            />
            <span className="text-sm text-stone-700 leading-snug">
              Text me promotions and special offers. Msg &amp; data rates
              may apply. Reply STOP to opt out.
            </span>
          </label>
        </fieldset>

        {topError ? (
          <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2.5 text-sm text-red-800">
            {topError}
          </div>
        ) : null}

        <Button
          type="submit"
          size="lg"
          className="w-full sm:w-auto"
          disabled={submit.isPending}
        >
          {submit.isPending ? (
            <>
              <Loader2 className="size-4 animate-spin" />
              Confirming…
            </>
          ) : (
            'Confirm booking'
          )}
        </Button>

        <p className="text-[11px] text-stone-500 leading-relaxed pt-2">
          By confirming, you agree to receive booking-related communications
          from {tenant.name}. You can cancel any time using the link in your
          confirmation email.
        </p>
      </form>

      {tenant.cancellation_policy ? (
        <section className="mt-10 pt-6 border-t border-stone-200">
          <h2 className="text-[11px] uppercase tracking-wider text-stone-500 font-medium mb-2">
            Cancellation policy
          </h2>
          <div className="text-sm text-stone-700 leading-relaxed whitespace-pre-line">
            {tenant.cancellation_policy}
          </div>
        </section>
      ) : null}
    </BookingContainer>
  );
}
