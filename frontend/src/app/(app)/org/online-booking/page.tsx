/**
 * `/org/online-booking` — owner-editable online booking settings.
 *
 * Five things on this page:
 *   1. The shareable booking URL with a copy-to-clipboard button.
 *   2. Killswitch (on/off). When off, the public URL returns 404 —
 *      same posture as a non-existent slug, so paused tenants don't
 *      leak.
 *   3. Lead time: minimum minutes before a slot can be booked.
 *   4. Booking window: how many days into the future are visible.
 *   5. Customer-facing copy: welcome message + cancellation policy.
 *
 * Branding (primary color + logo) is intentionally NOT duplicated
 * here — those live on `/org/business`. We link to that page so the
 * operator has a clear path when tweaking the booking page's look.
 *
 * Saves go through the existing `useUpdateTenantSettings` hook
 * (the booking fields ride on the same Tenant endpoint as branding).
 */

'use client';

import { zodResolver } from '@hookform/resolvers/zod';
import {
  Calendar,
  Check,
  Copy,
  ExternalLink,
  Info,
  MessageSquare,
  Power,
  Sparkles,
} from 'lucide-react';
import Link from 'next/link';
import { useEffect, useMemo, useState } from 'react';
import { useForm } from 'react-hook-form';
import { toast } from 'sonner';
import { z } from 'zod';

import { PageHeader } from '@/components/page-header';
import { Button } from '@/components/ui/button';
import { Field, FieldError, FieldLabel } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { ApiError } from '@/lib/api';
import {
  type TenantSettings,
  useTenantSettings,
  useUpdateTenantSettings,
} from '@/lib/tenant';
import { cn } from '@/lib/utils';

// Numeric inputs come through react-hook-form as strings (HTML form
// values are always strings); we coerce-and-validate manually rather
// than via zod's `coerce.number()`, which trips a known resolver-
// typing edge case where the inferred input type widens to `unknown`.
// Plain `z.number()` here means we register the inputs with
// `valueAsNumber: true` to do the conversion at the input boundary.
const schema = z.object({
  online_booking_enabled: z.boolean(),
  online_booking_lead_minutes: z
    .number()
    .int('Whole minutes only')
    .min(0, 'Cannot be negative')
    .max(60 * 24 * 7, 'Max 7 days (10080 min)'),
  online_booking_window_days: z
    .number()
    .int('Whole days only')
    .min(1, 'Must allow at least 1 day')
    .max(365, 'Max 365 days'),
  online_booking_welcome_message: z.string().max(500),
  online_booking_cancellation_policy: z.string().max(1000),
});

type FormValues = z.infer<typeof schema>;

export default function OrgOnlineBookingPage() {
  const { data: tenant, isLoading, error } = useTenantSettings();

  if (isLoading) {
    return (
      <div className="px-10 py-10 max-w-7xl">
        <PageHeader title="Online booking" description="Loading…" />
      </div>
    );
  }
  if (error || !tenant) {
    return (
      <div className="px-10 py-10 max-w-7xl">
        <PageHeader title="Online booking" />
        <p className="text-sm text-destructive">Could not load settings.</p>
      </div>
    );
  }
  return <OnlineBookingForm tenant={tenant} />;
}

function OnlineBookingForm({ tenant }: { tenant: TenantSettings }) {
  const update = useUpdateTenantSettings();

  const defaultValues: FormValues = useMemo(
    () => ({
      online_booking_enabled: tenant.online_booking_enabled,
      online_booking_lead_minutes: tenant.online_booking_lead_minutes,
      online_booking_window_days: tenant.online_booking_window_days,
      online_booking_welcome_message: tenant.online_booking_welcome_message,
      online_booking_cancellation_policy: tenant.online_booking_cancellation_policy,
    }),
    [tenant],
  );

  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues,
  });

  useEffect(() => {
    form.reset(defaultValues);
  }, [defaultValues, form]);

  const enabled = form.watch('online_booking_enabled');

  const onSubmit = form.handleSubmit((values) => {
    update.mutate(values, {
      onSuccess: () => toast.success('Online booking settings saved'),
      onError: (err) => {
        if (err instanceof ApiError && err.status === 403) {
          toast.error("You don't have permission to edit booking settings.");
        } else if (
          err instanceof ApiError &&
          err.status === 400 &&
          typeof err.body === 'object' &&
          err.body
        ) {
          const body = err.body as Record<string, string[] | string>;
          const firstField = Object.keys(body)[0];
          const detail = firstField
            ? Array.isArray(body[firstField])
              ? (body[firstField] as string[])[0]
              : String(body[firstField])
            : 'Could not save changes.';
          toast.error(detail);
        } else {
          toast.error('Could not save changes. Please try again.');
        }
      },
    });
  });

  return (
    <div className="px-10 py-10 max-w-7xl">
      <PageHeader
        title="Online booking"
        description="Configure your public booking page — what customers see, how far ahead they can book, and your cancellation policy."
      />

      <BookingUrlCard tenant={tenant} enabled={enabled} />

      <form onSubmit={onSubmit}>
        <div className="divide-y border-t border-b mt-8">
          <Section
            title="Availability"
            description="When the booking page is live and how far in advance customers can reserve."
            icon={<Power className="size-4 text-muted-foreground" />}
          >
            <ToggleRow
              label="Accept online bookings"
              description={
                enabled
                  ? 'Your booking URL is live and accepting customers.'
                  : 'Your booking URL returns 404 to customers. Existing bookings are unaffected.'
              }
              checked={enabled}
              onChange={(v) => form.setValue('online_booking_enabled', v, { shouldDirty: true })}
            />

            <Field>
              <FieldLabel htmlFor="lead">Minimum lead time (minutes)</FieldLabel>
              <Input
                id="lead"
                type="number"
                inputMode="numeric"
                min={0}
                max={60 * 24 * 7}
                step={5}
                className="max-w-[160px]"
                {...form.register('online_booking_lead_minutes', { valueAsNumber: true })}
              />
              <p className="text-[11px] text-muted-foreground mt-1 leading-relaxed">
                Customers can&rsquo;t book a slot starting sooner than this. 30 min
                gives front desk a moment to prep; 120+ is common for med-spas
                with consult-required services.
              </p>
              <FieldError>
                {form.formState.errors.online_booking_lead_minutes?.message}
              </FieldError>
            </Field>

            <Field>
              <FieldLabel htmlFor="window">Booking window (days)</FieldLabel>
              <Input
                id="window"
                type="number"
                inputMode="numeric"
                min={1}
                max={365}
                step={1}
                className="max-w-[160px]"
                {...form.register('online_booking_window_days', { valueAsNumber: true })}
              />
              <p className="text-[11px] text-muted-foreground mt-1 leading-relaxed">
                How far into the future the booking calendar shows openings.
                Shorter = fewer no-shows from far-out speculative bookings.
              </p>
              <FieldError>
                {form.formState.errors.online_booking_window_days?.message}
              </FieldError>
            </Field>
          </Section>

          <Section
            title="Customer-facing copy"
            description="Optional messages shown on the public booking page. Keep it brief — most customers skim."
            icon={<MessageSquare className="size-4 text-muted-foreground" />}
          >
            <Field>
              <FieldLabel htmlFor="welcome">Welcome message</FieldLabel>
              <textarea
                id="welcome"
                rows={3}
                maxLength={500}
                placeholder="New patient? First consult is on us. Validated parking on Madison."
                className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-hidden focus:ring-2 focus:ring-ring/40"
                {...form.register('online_booking_welcome_message')}
              />
              <p className="text-[11px] text-muted-foreground mt-1 leading-relaxed">
                Shown above the service catalog. Skip if you have nothing to
                say — the page works fine without it.
              </p>
              <FieldError>
                {form.formState.errors.online_booking_welcome_message?.message}
              </FieldError>
            </Field>

            <Field>
              <FieldLabel htmlFor="cancellation">Cancellation policy</FieldLabel>
              <textarea
                id="cancellation"
                rows={5}
                maxLength={1000}
                placeholder="We require 24-hour notice for cancellations. Late cancellations are charged 50% of the service price; no-shows are charged in full."
                className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-hidden focus:ring-2 focus:ring-ring/40"
                {...form.register('online_booking_cancellation_policy')}
              />
              <p className="text-[11px] text-muted-foreground mt-1 leading-relaxed">
                Shown on the booking detail page and on the manage-booking page
                customers see when they click their email link.
              </p>
              <FieldError>
                {form.formState.errors.online_booking_cancellation_policy?.message}
              </FieldError>
            </Field>
          </Section>

          <Section
            title="Branding"
            description="Logo and primary color live with your business profile because they apply to multiple surfaces (sign-in page + booking page)."
            icon={<Sparkles className="size-4 text-muted-foreground" />}
          >
            <Link
              href="/org/business"
              className="inline-flex items-center gap-1.5 text-sm font-medium text-foreground hover:underline"
            >
              Edit logo and color
              <ExternalLink className="size-3.5" />
            </Link>
          </Section>
        </div>

        <div className="flex items-center justify-end gap-2 pt-4">
          <Button
            type="button"
            variant="outline"
            disabled={!form.formState.isDirty || update.isPending}
            onClick={() => form.reset(defaultValues)}
          >
            Reset
          </Button>
          <Button
            type="submit"
            disabled={!form.formState.isDirty || update.isPending}
          >
            {update.isPending ? 'Saving…' : 'Save changes'}
          </Button>
        </div>
      </form>
    </div>
  );
}

// ── Booking URL card ─────────────────────────────────────────────────

function BookingUrlCard({
  tenant,
  enabled,
}: {
  tenant: TenantSettings;
  enabled: boolean;
}) {
  const [copied, setCopied] = useState(false);

  // In dev we run from localhost:3000; in prod the booking URL would
  // be on the tenant's subdomain. Both cases get a usable link from
  // window.origin at render time. Falls back to a sensible default
  // during SSR before hydration.
  const origin =
    typeof window !== 'undefined' ? window.location.origin : 'https://lumecrm.com';
  const url = `${origin}/book/${tenant.slug}`;

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      toast.error('Could not copy. Select the URL and copy manually.');
    }
  };

  return (
    <div className="rounded-lg border border-border bg-muted/30 p-5 mt-4">
      <div className="flex items-start gap-4 flex-wrap">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <Calendar className="size-4 text-muted-foreground" />
            <p className="text-[11px] uppercase tracking-wide text-muted-foreground font-medium">
              Your booking URL
            </p>
            <StatusPill enabled={enabled} />
          </div>
          <p className="font-mono text-sm text-foreground break-all">{url}</p>
          <p className="text-xs text-muted-foreground mt-1.5">
            Share this in your Instagram bio, email signature, business cards,
            and SMS replies.
          </p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={handleCopy}
          >
            {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
            {copied ? 'Copied' : 'Copy'}
          </Button>
          <Link
            href={`/book/${tenant.slug}`}
            target="_blank"
            className="inline-flex items-center gap-1.5 rounded-md bg-primary text-primary-foreground hover:bg-primary/90 px-3 h-8 text-sm font-medium transition-colors"
          >
            <ExternalLink className="size-3.5" />
            Preview
          </Link>
        </div>
      </div>
    </div>
  );
}

function StatusPill({ enabled }: { enabled: boolean }) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider',
        enabled
          ? 'bg-emerald-50 text-emerald-700'
          : 'bg-stone-100 text-stone-600',
      )}
    >
      {enabled ? (
        <>
          <span className="size-1.5 rounded-full bg-emerald-500" /> Live
        </>
      ) : (
        <>
          <span className="size-1.5 rounded-full bg-stone-400" /> Paused
        </>
      )}
    </span>
  );
}

// ── Layout primitives (mirror /org/business) ─────────────────────────

function Section({
  title,
  description,
  icon,
  children,
}: {
  title: string;
  description?: string;
  icon?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className="grid grid-cols-1 lg:grid-cols-[300px_1fr] gap-6 lg:gap-12 py-6 first:pt-8 last:pb-8">
      <header>
        <div className="flex items-center gap-2">
          {icon}
          <h2 className="font-serif text-base font-semibold tracking-tight">
            {title}
          </h2>
        </div>
        {description ? (
          <p className="text-xs text-muted-foreground mt-1.5 leading-relaxed">
            {description}
          </p>
        ) : null}
      </header>
      <div className="space-y-4 max-w-2xl">{children}</div>
    </section>
  );
}

function ToggleRow({
  label,
  description,
  checked,
  onChange,
}: {
  label: string;
  description: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <div className="rounded-md border border-border bg-background px-4 py-3 flex items-start gap-3">
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        onClick={() => onChange(!checked)}
        className={cn(
          'relative inline-flex shrink-0 mt-0.5 h-5 w-9 rounded-full transition-colors',
          checked ? 'bg-emerald-500' : 'bg-stone-300',
        )}
      >
        <span
          className={cn(
            'absolute top-0.5 h-4 w-4 rounded-full bg-white shadow-sm transition-transform',
            checked ? 'translate-x-4' : 'translate-x-0.5',
          )}
        />
      </button>
      <div className="flex-1 min-w-0">
        <div className="text-sm font-medium text-foreground">{label}</div>
        <div className="text-xs text-muted-foreground leading-relaxed mt-0.5">
          {description}
        </div>
      </div>
      {!checked ? (
        <div className="flex items-center gap-1 text-[10px] uppercase tracking-wider text-stone-500 font-medium shrink-0">
          <Info className="size-3" />
          Paused
        </div>
      ) : null}
    </div>
  );
}
