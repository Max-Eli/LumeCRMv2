/**
 * `<WaitlistInvite />` — opt-in CTA shown when the customer's
 * preferred date has no available slots.
 *
 * Inline expander rather than a modal: the customer is already on
 * the booking page; popping a dialog would feel like a sales
 * tactic. The expander reveals a four-field form (name, email,
 * phone, optional message) and submits to
 * `POST /api/booking/<slug>/waitlist/`. The dedupe path means
 * double-submitting is harmless — the backend returns the
 * existing entry.
 */

'use client';

import { CheckCircle2, ChevronDown, Clock, Loader2 } from 'lucide-react';
import { useState } from 'react';

import { Button } from '@/components/ui/button';
import { Field, FieldError, FieldLabel } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { ApiError } from '@/lib/api';
import { useJoinWaitlist } from '@/lib/waitlist';
import { cn } from '@/lib/utils';

export interface WaitlistInviteProps {
  slug: string;
  serviceId: number;
  serviceName: string;
  locationId: number;
  /** When `null`, the customer hasn't picked a specific provider —
   *  the waitlist entry's `provider_id` is left null ("anyone"). */
  providerId: number | null;
  preferredDate: string; // YYYY-MM-DD
  primaryColor: string;
}

export function WaitlistInvite({
  slug,
  serviceId,
  serviceName,
  locationId,
  providerId,
  preferredDate,
  primaryColor,
}: WaitlistInviteProps) {
  const [open, setOpen] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [firstName, setFirstName] = useState('');
  const [lastName, setLastName] = useState('');
  const [email, setEmail] = useState('');
  const [phone, setPhone] = useState('');
  const [notes, setNotes] = useState('');
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [topError, setTopError] = useState<string | null>(null);

  const join = useJoinWaitlist(slug);

  const validate = (): boolean => {
    const errs: Record<string, string> = {};
    if (!firstName.trim()) errs.firstName = 'Required';
    if (!lastName.trim()) errs.lastName = 'Required';
    if (!email.trim()) errs.email = 'Required';
    else if (!/.+@.+\..+/.test(email)) errs.email = 'Enter a valid email';
    if (!phone.trim()) errs.phone = 'Required';
    setErrors(errs);
    return Object.keys(errs).length === 0;
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setTopError(null);
    if (!validate()) return;

    join.mutate(
      {
        service_id: serviceId,
        location_id: locationId,
        provider_id: providerId,
        preferred_date: preferredDate,
        customer_first_name: firstName.trim(),
        customer_last_name: lastName.trim(),
        customer_email: email.trim(),
        customer_phone: phone.trim(),
        notes: notes.trim() || undefined,
      },
      {
        onSuccess: () => setSubmitted(true),
        onError: (err) => {
          if (err instanceof ApiError && err.status === 400 && err.body && typeof err.body === 'object') {
            const body = err.body as Record<string, unknown>;
            if (typeof body.detail === 'string') {
              setTopError(body.detail);
              return;
            }
          }
          setTopError("Couldn't add you to the waitlist. Please try again.");
        },
      },
    );
  };

  if (submitted) {
    return (
      <div className="mt-6 rounded-lg border border-emerald-200 bg-emerald-50 px-5 py-4 flex items-start gap-3">
        <CheckCircle2 className="size-5 text-emerald-600 shrink-0 mt-0.5" />
        <div>
          <p className="text-sm font-medium text-emerald-900">
            You&rsquo;re on the waitlist for {serviceName}.
          </p>
          <p className="text-xs text-emerald-800 mt-0.5">
            We&rsquo;ll reach out when something opens up around{' '}
            {formatDate(preferredDate)}.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div
      className="mt-6 rounded-lg border border-stone-200 bg-white overflow-hidden"
      style={{ borderLeftColor: primaryColor, borderLeftWidth: 3 }}
    >
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full px-5 py-4 flex items-center gap-3 text-left hover:bg-stone-50 transition-colors"
      >
        <Clock className="size-4 text-stone-500 shrink-0" />
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium text-stone-900">
            Don&rsquo;t see a time that works?
          </p>
          <p className="text-xs text-stone-600 mt-0.5">
            Join the waitlist and we&rsquo;ll reach out if something opens up
            around {formatDate(preferredDate)}.
          </p>
        </div>
        <ChevronDown
          className={cn(
            'size-4 text-stone-400 transition-transform shrink-0',
            open && 'rotate-180',
          )}
        />
      </button>

      {open ? (
        <form onSubmit={handleSubmit} className="px-5 pb-5 pt-1 space-y-4">
          <div className="grid sm:grid-cols-2 gap-3">
            <Field>
              <FieldLabel>First name</FieldLabel>
              <Input
                value={firstName}
                onChange={(e) => setFirstName(e.target.value)}
                autoComplete="given-name"
              />
              {errors.firstName ? <FieldError>{errors.firstName}</FieldError> : null}
            </Field>
            <Field>
              <FieldLabel>Last name</FieldLabel>
              <Input
                value={lastName}
                onChange={(e) => setLastName(e.target.value)}
                autoComplete="family-name"
              />
              {errors.lastName ? <FieldError>{errors.lastName}</FieldError> : null}
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
            {errors.email ? <FieldError>{errors.email}</FieldError> : null}
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
            {errors.phone ? <FieldError>{errors.phone}</FieldError> : null}
          </Field>
          <Field>
            <FieldLabel>Anything we should know? (optional)</FieldLabel>
            <textarea
              rows={2}
              maxLength={500}
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Mornings preferred, flexible on date, etc."
              className="w-full rounded-md border border-stone-300 bg-white px-3 py-2 text-sm focus:outline-hidden focus:ring-2 focus:ring-stone-900/20 focus:border-stone-900"
            />
          </Field>

          {topError ? (
            <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
              {topError}
            </div>
          ) : null}

          <div className="flex items-center gap-2">
            <Button
              type="submit"
              size="sm"
              disabled={join.isPending}
              style={{ background: primaryColor }}
            >
              {join.isPending ? (
                <>
                  <Loader2 className="size-3.5 animate-spin" />
                  Joining…
                </>
              ) : (
                'Join waitlist'
              )}
            </Button>
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={() => setOpen(false)}
              disabled={join.isPending}
            >
              Cancel
            </Button>
          </div>
        </form>
      ) : null}
    </div>
  );
}

function formatDate(iso: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  if (!m) return iso;
  const d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  return d.toLocaleDateString('en-US', {
    weekday: 'long',
    month: 'long',
    day: 'numeric',
  });
}
