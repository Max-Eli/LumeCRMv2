/**
 * Shared form for creating + editing a Location. Both `/org/locations/new`
 * and `/org/locations/[id]` use this — same fields, same validation,
 * same layout. The only difference is the "Default" / "Active" toggles
 * which are only meaningful on the edit screen (a freshly created
 * location is always active; the create form exposes "make this the
 * default" as a single boolean).
 *
 * Fields are split into the same two-column "section" layout the
 * `/settings/business` form uses, so all admin/settings pages feel like
 * one surface.
 *
 * Save behavior is supplied by the caller (a TanStack Mutation) so the
 * form stays presentational — the create page wires up
 * `useCreateLocation`, the edit page wires `useUpdateLocation`.
 */

'use client';

import { zodResolver } from '@hookform/resolvers/zod';
import { Building2, Clock, Globe, MapPin, Phone, Star } from 'lucide-react';
import { useEffect } from 'react';
import { useForm } from 'react-hook-form';
import { z } from 'zod';

import { Button } from '@/components/ui/button';
import { Field, FieldError, FieldLabel } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { TimePicker } from '@/components/ui/time-picker';
import type { CreateLocationInput, Location } from '@/lib/locations';

const TIMEZONE_CHOICES = [
  'America/New_York',
  'America/Chicago',
  'America/Denver',
  'America/Phoenix',
  'America/Los_Angeles',
  'America/Anchorage',
  'Pacific/Honolulu',
];

const TIME_HHMM = /^\d{1,2}:\d{2}$/;
const SLUG_PATTERN = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

const schema = z
  .object({
    name: z.string().min(1, 'Name is required').max(120),
    // Slug is optional on create — backend slugifies the name when
    // omitted. On edit we always show the current slug; users CAN
    // change it but typos in the slug field are validated client-side
    // for nicer feedback than a server round-trip.
    slug: z
      .string()
      .max(63)
      .refine(
        (s) => s === '' || SLUG_PATTERN.test(s),
        'Use lowercase letters, numbers, and hyphens (e.g. "manhattan" or "hudson-yards").',
      ),
    is_default: z.boolean(),
    // Edit-only — create page hides this field and always sends true.
    is_active: z.boolean(),
    timezone: z.string().min(1),
    phone: z.string().max(20),
    email: z.string().max(254),
    address_line1: z.string().max(200),
    address_line2: z.string().max(200),
    city: z.string().max(100),
    state: z.string().max(2),
    zip_code: z.string().max(10),
    business_open_time: z.string().regex(TIME_HHMM, 'Invalid open time'),
    business_close_time: z.string().regex(TIME_HHMM, 'Invalid close time'),
  })
  .refine(
    (v) => parseHHMM(v.business_close_time) > parseHHMM(v.business_open_time),
    {
      message: 'Close time must be after open time',
      path: ['business_close_time'],
    },
  )
  .refine(
    // Email is optional but if provided, must be a valid email. Plain
    // `.email()` would reject empty string; we accept either.
    (v) => v.email === '' || /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v.email),
    { message: 'Enter a valid email or leave blank.', path: ['email'] },
  );

export type LocationFormValues = z.infer<typeof schema>;

export interface LocationFormProps {
  /** When provided, the form is in edit mode (renders Active toggle,
   *  pre-fills slug, disables guarded actions per the location's
   *  current state). When undefined, the form is in create mode. */
  existing?: Location;

  /** Whether the parent has detected the existing location is the only
   *  active location. Used to disable the "deactivate" toggle with a
   *  helpful tooltip — mirrors the backend guardrail. Edit mode only. */
  isOnlyActiveLocation?: boolean;

  /** Submit handler. Receives the form values; the parent shapes them
   *  into the API payload (create vs update differ slightly). */
  onSubmit: (values: LocationFormValues) => void;

  /** Cancel handler — typically routes back to the list. */
  onCancel: () => void;

  /** True while the parent's mutation is in flight. */
  isSubmitting: boolean;
}

export function LocationForm({
  existing,
  isOnlyActiveLocation = false,
  onSubmit,
  onCancel,
  isSubmitting,
}: LocationFormProps) {
  const isEdit = existing !== undefined;
  const defaultValues: LocationFormValues = existing
    ? {
        name: existing.name,
        slug: existing.slug,
        is_default: existing.is_default,
        is_active: existing.is_active,
        timezone: existing.timezone,
        phone: existing.phone,
        email: existing.email,
        address_line1: existing.address_line1,
        address_line2: existing.address_line2,
        city: existing.city,
        state: existing.state,
        zip_code: existing.zip_code,
        business_open_time: trimToHHMM(existing.business_open_time),
        business_close_time: trimToHHMM(existing.business_close_time),
      }
    : {
        name: '',
        slug: '',
        is_default: false,
        is_active: true,
        timezone: 'America/New_York',
        phone: '',
        email: '',
        address_line1: '',
        address_line2: '',
        city: '',
        state: '',
        zip_code: '',
        business_open_time: '08:00',
        business_close_time: '20:00',
      };

  const form = useForm<LocationFormValues>({
    resolver: zodResolver(schema),
    defaultValues,
  });

  // Re-seed when an edited record refetches (mutation onSuccess swaps
  // the cache with the canonical server version).
  useEffect(() => {
    if (existing) {
      form.reset({
        name: existing.name,
        slug: existing.slug,
        is_default: existing.is_default,
        is_active: existing.is_active,
        timezone: existing.timezone,
        phone: existing.phone,
        email: existing.email,
        address_line1: existing.address_line1,
        address_line2: existing.address_line2,
        city: existing.city,
        state: existing.state,
        zip_code: existing.zip_code,
        business_open_time: trimToHHMM(existing.business_open_time),
        business_close_time: trimToHHMM(existing.business_close_time),
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [existing?.updated_at, existing?.id]);

  const handleSubmit = form.handleSubmit(onSubmit);

  // Edit-mode UX guards mirroring the backend invariants:
  //   - Can't un-set is_default on the current default (toggle disabled).
  //   - Can't deactivate the current default (toggle disabled).
  //   - Can't deactivate the only active location (toggle disabled).
  const cannotUnsetDefault = isEdit && existing!.is_default;
  const cannotDeactivate =
    isEdit && (existing!.is_default || isOnlyActiveLocation);

  return (
    <form onSubmit={handleSubmit}>
      <div className="divide-y border-t border-b">
        <Section
          title="Identity"
          description="What this site is called and how it's identified in URLs and the active-location cookie. The slug is auto-derived from the name on create — change only if needed."
          icon={<Building2 className="size-4 text-muted-foreground" />}
        >
          <Field>
            <FieldLabel htmlFor="name">Name</FieldLabel>
            <Input
              id="name"
              {...form.register('name')}
              placeholder="e.g. Manhattan, Brooklyn, Hudson Yards"
              autoFocus={!isEdit}
            />
            <FieldError>{form.formState.errors.name?.message}</FieldError>
          </Field>

          <Field>
            <FieldLabel htmlFor="slug">URL slug</FieldLabel>
            <Input
              id="slug"
              {...form.register('slug')}
              placeholder={isEdit ? '' : 'auto-derived from name'}
              className="font-mono"
            />
            <p className="text-[11px] text-muted-foreground mt-1">
              Used internally to remember which site your team picks. Leave
              blank to auto-derive (e.g. &ldquo;Hudson Yards&rdquo; → &ldquo;hudson-yards&rdquo;).
            </p>
            <FieldError>{form.formState.errors.slug?.message}</FieldError>
          </Field>

          <ToggleRow
            label="Make this the default location"
            description={
              cannotUnsetDefault
                ? 'This is currently the default — set another location as default to demote this one.'
                : 'The default site is the fallback when no specific location is selected (fresh login, missing cookie). Exactly one location is the default at all times.'
            }
            value={form.watch('is_default')}
            onChange={(next) =>
              form.setValue('is_default', next, { shouldDirty: true })
            }
            disabled={cannotUnsetDefault}
            icon={<Star className="size-3.5" />}
          />

          {isEdit ? (
            <ToggleRow
              label="Active"
              description={
                cannotDeactivate
                  ? existing!.is_default
                    ? "Can't deactivate the default location. Set another active location as default first."
                    : "Can't deactivate the only active location. Add another location first."
                  : 'Inactive locations are hidden from the location switcher and dashboards. Their history is preserved.'
              }
              value={form.watch('is_active')}
              onChange={(next) =>
                form.setValue('is_active', next, { shouldDirty: true })
              }
              disabled={cannotDeactivate}
            />
          ) : null}
        </Section>

        <Section
          title="Operations"
          description="The timezone drives every wall-clock time on this location's calendar and on customer-facing emails. Different sites of the same business can have different timezones."
          icon={<Globe className="size-4 text-muted-foreground" />}
        >
          <Field>
            <FieldLabel htmlFor="timezone">Timezone</FieldLabel>
            <select
              id="timezone"
              {...form.register('timezone')}
              className="h-9 w-full rounded-md border bg-background px-3 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
            >
              {TIMEZONE_CHOICES.map((tz) => (
                <option key={tz} value={tz}>
                  {tz}
                </option>
              ))}
            </select>
          </Field>
        </Section>

        <Section
          title="Contact"
          description="How customers reach this site. Per-location so a multi-site business can put each phone number on the right confirmation email."
          icon={<Phone className="size-4 text-muted-foreground" />}
        >
          <div className="grid grid-cols-2 gap-3">
            <Field>
              <FieldLabel htmlFor="phone">Phone</FieldLabel>
              <Input id="phone" type="tel" {...form.register('phone')} />
            </Field>
            <Field>
              <FieldLabel htmlFor="email">Email (optional)</FieldLabel>
              <Input id="email" type="email" {...form.register('email')} />
              <FieldError>{form.formState.errors.email?.message}</FieldError>
            </Field>
          </div>
        </Section>

        <Section
          title="Address"
          description="The physical location. Shown on confirmation emails, the public booking page (Phase 1I), and used for tax / payroll filings."
          icon={<MapPin className="size-4 text-muted-foreground" />}
        >
          <Field>
            <FieldLabel htmlFor="address_line1">Street address</FieldLabel>
            <Input id="address_line1" {...form.register('address_line1')} />
          </Field>
          <Field>
            <FieldLabel htmlFor="address_line2">Suite / unit (optional)</FieldLabel>
            <Input id="address_line2" {...form.register('address_line2')} />
          </Field>
          <div className="grid grid-cols-[1fr_80px_120px] gap-3">
            <Field>
              <FieldLabel htmlFor="city">City</FieldLabel>
              <Input id="city" {...form.register('city')} />
            </Field>
            <Field>
              <FieldLabel htmlFor="state">State</FieldLabel>
              <Input
                id="state"
                {...form.register('state')}
                maxLength={2}
                placeholder="NY"
                className="uppercase"
              />
            </Field>
            <Field>
              <FieldLabel htmlFor="zip_code">ZIP</FieldLabel>
              <Input id="zip_code" {...form.register('zip_code')} />
            </Field>
          </div>
        </Section>

        <Section
          title="Business hours"
          description="When this site is open. Drives the calendar's day-axis bounds for this location and (later) the public booking page's bookable-slot range."
          icon={<Clock className="size-4 text-muted-foreground" />}
        >
          <div className="flex items-end gap-3">
            <Field>
              <FieldLabel>Open</FieldLabel>
              <TimePicker
                value={form.watch('business_open_time')}
                onChange={(v) =>
                  form.setValue('business_open_time', v, { shouldDirty: true })
                }
                step={1}
                minHour={0}
                maxHour={24}
                ariaLabel="Business open time"
              />
            </Field>
            <span className="pb-2 text-muted-foreground text-sm">to</span>
            <Field>
              <FieldLabel>Close</FieldLabel>
              <TimePicker
                value={form.watch('business_close_time')}
                onChange={(v) =>
                  form.setValue('business_close_time', v, { shouldDirty: true })
                }
                step={1}
                minHour={0}
                maxHour={24}
                ariaLabel="Business close time"
              />
            </Field>
          </div>
          <FieldError>{form.formState.errors.business_close_time?.message}</FieldError>
          <p className="text-[11px] text-muted-foreground">
            Per-day schedules and per-provider overrides land with Phase 1C
            session 4 (provider working hours).
          </p>
        </Section>
      </div>

      <div className="flex items-center justify-end gap-2 pt-4">
        <Button
          type="button"
          variant="outline"
          disabled={isSubmitting}
          onClick={onCancel}
        >
          Cancel
        </Button>
        <Button
          type="submit"
          disabled={
            isSubmitting || (isEdit ? !form.formState.isDirty : false)
          }
        >
          {isSubmitting
            ? 'Saving…'
            : isEdit
              ? 'Save changes'
              : 'Add location'}
        </Button>
      </div>
    </form>
  );
}

/** Convert form values into the API create payload. Slug is omitted
 *  when blank so the backend slugifies the name. */
export function valuesToCreatePayload(values: LocationFormValues): CreateLocationInput {
  return {
    name: values.name,
    ...(values.slug ? { slug: values.slug } : {}),
    is_default: values.is_default,
    timezone: values.timezone,
    phone: values.phone,
    email: values.email,
    address_line1: values.address_line1,
    address_line2: values.address_line2,
    city: values.city,
    state: values.state.toUpperCase(),
    zip_code: values.zip_code,
    business_open_time: `${values.business_open_time}:00`,
    business_close_time: `${values.business_close_time}:00`,
  };
}

/** Convert form values into the API update payload. Sends every field
 *  — backend treats PATCH as partial so unchanged fields are no-ops. */
export function valuesToUpdatePayload(values: LocationFormValues) {
  return {
    name: values.name,
    slug: values.slug,
    is_default: values.is_default,
    is_active: values.is_active,
    timezone: values.timezone,
    phone: values.phone,
    email: values.email,
    address_line1: values.address_line1,
    address_line2: values.address_line2,
    city: values.city,
    state: values.state.toUpperCase(),
    zip_code: values.zip_code,
    business_open_time: `${values.business_open_time}:00`,
    business_close_time: `${values.business_close_time}:00`,
  };
}

// ── Layout primitives (mirror /settings/business) ───────────────────

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
      <div className="space-y-3 max-w-2xl">{children}</div>
    </section>
  );
}

function ToggleRow({
  label,
  description,
  value,
  onChange,
  disabled,
  icon,
}: {
  label: string;
  description: string;
  value: boolean;
  onChange: (next: boolean) => void;
  disabled?: boolean;
  icon?: React.ReactNode;
}) {
  return (
    <label className="flex items-start gap-3 py-2 cursor-pointer">
      <input
        type="checkbox"
        checked={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
        className="mt-0.5 size-4 rounded border-border text-foreground focus-visible:ring-2 focus-visible:ring-ring/50 disabled:opacity-50"
      />
      <div className="min-w-0 flex-1">
        <span className="text-sm font-medium inline-flex items-center gap-1.5">
          {icon}
          {label}
        </span>
        <p className="text-[11px] text-muted-foreground leading-relaxed">
          {description}
        </p>
      </div>
    </label>
  );
}

// ── Helpers ─────────────────────────────────────────────────────────

function trimToHHMM(time: string | null | undefined): string {
  if (!time) return '08:00';
  const m = /^(\d{1,2}:\d{2})/.exec(time);
  return m ? m[1] : '08:00';
}

function parseHHMM(s: string): number {
  const [h, m] = s.split(':').map(Number);
  return (h ?? 0) * 60 + (m ?? 0);
}
