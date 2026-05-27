/**
 * New-appointment bottom sheet.
 *
 * Slides up from the bottom edge of the calendar so the rest of the
 * day-view stays visible above a backdrop — the front desk can see
 * what they're booking around without a centered modal stealing focus.
 * The sheet is centered horizontally with `max-w-3xl` so it reads as
 * a deliberate "drawer" rather than a full-bleed slab on wide screens.
 *
 * Composition is built from the design-system primitives, NOT bespoke
 * controls per field:
 *
 *   - **Customer** — `CustomerPicker` (typeahead search via
 *     `useCustomers({ q })`) with an inline "+ Create new customer"
 *     mini-form (first / last / phone / email) that auto-selects the
 *     newly-created customer on success. Saves the front desk a tab-
 *     switch to /clients/new for walk-ins.
 *   - **Service** — `ServicePicker` (client-side typeahead over the
 *     full service list — names + codes match).
 *   - **Provider** — Select, filtered by `isProviderEligible` against
 *     the chosen service's category. Backend re-validates.
 *   - **Date** — `<DatePicker>` (with quick picks today / +2w / +4w / +6w).
 *   - **Time** — `<TimePicker>` (custom hour/minute popup, 5-min snap,
 *     scoped to business hours).
 *   - **Notes** — optional textarea.
 *
 * On submit:
 *   1. Validate via zod.
 *   2. Convert local date+time → UTC ISO using the IANA-aware offset
 *      helper (same one drag-drop / right-click reschedule use).
 *   3. POST `/api/appointments/`.
 *   4. The backend signal auto-creates an OPEN invoice (ADR 0007).
 *   5. Soft conflict warning (same-provider overlap on the focus date)
 *      surfaces in a banner — does NOT block submit; the front desk
 *      sometimes intentionally double-books a flexible provider.
 */

'use client';

import { zodResolver } from '@hookform/resolvers/zod';
import { AlertTriangle, Plus, Search, UserPlus, X } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { Controller, useForm } from 'react-hook-form';
import { toast } from 'sonner';
import { z } from 'zod';

import { Button } from '@/components/ui/button';
import { DatePicker } from '@/components/ui/date-picker';
import { Field, FieldError, FieldLabel } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  Sheet,
  SheetBody,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet';
import { TimePicker } from '@/components/ui/time-picker';
import { ApiError } from '@/lib/api';
import { useAppointmentsForDate, useCreateAppointment } from '@/lib/appointments';
import {
  defaultStartTimeLabel,
  localDateTimeToUtcIso,
  parseHHMM,
  todayLocalISODate,
} from '@/lib/calendar-datetime';
import { type CustomerListItem, useCreateCustomer, useCustomers } from '@/lib/customers';
import { isProviderEligible } from '@/lib/eligibility';
import {
  type Membership,
  membershipName,
  useBookableMemberships,
} from '@/lib/memberships';
import { type Service, useServiceCategories, useServices } from '@/lib/services';

// ── Validation ───────────────────────────────────────────────────────────

const schema = z.object({
  customer_id: z.number().int().positive({ message: 'Pick a customer' }),
  service_id: z.number().int().positive({ message: 'Pick a service' }),
  // Additional services on the same visit (Facial + Botox, etc.).
  // Each row carries its own `service_id` plus an optional
  // `provider_id` override — null means "inherit the appointment's
  // primary provider" (the common case). Duplicate service_ids are
  // allowed (two areas of Botox is a legit booking). Always present
  // in form state (defaulted to []); zod's `.default()` would
  // introduce an asymmetric input/output type that breaks the resolver.
  extras: z.array(
    z.object({
      service_id: z.number().int().positive(),
      provider_id: z.number().int().nullable(),
    }),
  ),
  provider_id: z.number().int().positive({ message: 'Pick a provider' }),
  date: z.string().regex(/^\d{4}-\d{2}-\d{2}$/, 'Pick a date'),
  time: z.string().regex(/^\d{2}:\d{2}$/, 'Pick a time'),
  notes: z.string().max(2000).optional(),
});

type FormValues = z.infer<typeof schema>;

export interface NewAppointmentSheetProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Tenant timezone — used to convert the local date/time into UTC. */
  timezone: string;
  /** Pre-filled date in YYYY-MM-DD (defaults to today if not provided). */
  defaultDate?: string;
  /** Pre-filled time in HH:MM (24h). When present, e.g. opened from an
   *  empty-slot click, focuses the chosen slot. */
  defaultTime?: string;
  /** Pre-filled provider id (e.g. when the empty-slot click occurred in
   *  a specific provider column). */
  defaultProviderId?: number;
  /** Called after a successful create — typically to bump the calendar
   *  to the booked appointment's date if it differs from the focus date. */
  onCreated?: (createdDate: string) => void;
}

export function NewAppointmentSheet({
  open,
  onOpenChange,
  timezone,
  defaultDate,
  defaultTime,
  defaultProviderId,
  onCreated,
}: NewAppointmentSheetProps) {
  const create = useCreateAppointment();

  // Single source of truth for the form's blank state — used for both
  // `useForm({ defaultValues })` and `form.reset(...)`. Keeping these
  // in two separate object literals invited a class of bugs where a
  // newly-added field would be present on one path and missing on the
  // other — silently producing an `undefined` value that fails zod
  // (e.g. `extra_service_ids: []` was missing from the reset object,
  // which made single-service bookings fail validation while
  // multi-service ones happened to populate the field via setValue).
  const buildDefaults = (): FormValues => ({
    customer_id: 0,
    service_id: 0,
    extras: [],
    provider_id: defaultProviderId ?? 0,
    date: defaultDate ?? todayLocalISODate(),
    time: defaultTime ?? defaultStartTimeLabel(),
    notes: '',
  });

  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: buildDefaults(),
  });

  // Reset whenever the sheet re-opens with potentially new defaults.
  useEffect(() => {
    if (open) form.reset(buildDefaults());
    // form.reset is stable; only react to open/defaults.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, defaultDate, defaultTime, defaultProviderId]);

  const { data: services } = useServices({ activeOnly: true });
  const { data: providers } = useBookableMemberships();
  const { data: categories } = useServiceCategories();

  const watched = form.watch();
  const selectedService = useMemo(
    () => (services ?? []).find((s) => s.id === watched.service_id) ?? null,
    [services, watched.service_id],
  );

  // Resolve each extras row to the full Service + (optional) provider
  // membership so the card can show name/duration/price and the
  // "performed by" select can render the chosen staff name. Skips any
  // service id that no longer matches an active service
  // (cache-staleness guard).
  type ResolvedExtra = {
    service: Service;
    /** The per-service provider override resolved to a full
     *  membership row, or null when the extra inherits the primary
     *  provider (the common case). */
    provider: Membership | null;
  };
  const extraServicesResolved = useMemo<ResolvedExtra[]>(() => {
    const rows = watched.extras ?? [];
    const allServices = services ?? [];
    const allProviders = providers ?? [];
    return rows
      .map((row) => {
        const service = allServices.find((s) => s.id === row.service_id);
        if (!service) return null;
        const provider = row.provider_id != null
          ? allProviders.find((p) => p.id === row.provider_id) ?? null
          : null;
        return { service, provider };
      })
      .filter((r): r is ResolvedExtra => r !== null);
  }, [services, providers, watched.extras]);

  // Total visit duration — drives both the calendar block end_time and
  // the conflict-window check below so a multi-service booking can't
  // sneak over the next appointment.
  const totalDurationMinutes =
    (selectedService?.duration_minutes ?? 0)
    + extraServicesResolved.reduce(
        (sum, r) => sum + r.service.duration_minutes,
        0,
      );

  const totalPriceCents =
    (selectedService?.price_cents ?? 0)
    + extraServicesResolved.reduce(
        (sum, r) => sum + r.service.price_cents,
        0,
      );

  // True while the inline "+ Add another service" picker is open.
  const [addingExtra, setAddingExtra] = useState(false);

  const appendExtraService = (serviceId: number) => {
    if (serviceId <= 0) return;
    const current = form.getValues('extras') ?? [];
    form.setValue(
      'extras',
      [...current, { service_id: serviceId, provider_id: null }],
      { shouldValidate: false, shouldDirty: true },
    );
    setAddingExtra(false);
  };

  const removeExtraAt = (index: number) => {
    const current = form.getValues('extras') ?? [];
    form.setValue(
      'extras',
      current.filter((_, i) => i !== index),
      { shouldValidate: false, shouldDirty: true },
    );
  };

  const setExtraProviderAt = (
    index: number, providerId: number | null,
  ) => {
    const current = form.getValues('extras') ?? [];
    form.setValue(
      'extras',
      current.map((row, i) =>
        i === index ? { ...row, provider_id: providerId } : row,
      ),
      { shouldValidate: false, shouldDirty: true },
    );
  };

  // Reset the inline picker when the sheet closes / reopens so it
  // doesn't carry state across two unrelated bookings.
  useEffect(() => {
    if (!open) setAddingExtra(false);
  }, [open]);

  // Filter providers down to those eligible for the selected service's
  // category (`ServiceCategory.eligible_job_titles`). Backend re-validates
  // on submit; this just shapes the dropdown so ineligible providers
  // don't even show up. Note: `Service.category` is a nested object
  // (`{ id, name, color }` | null), NOT a flat `category_id` — reading
  // the wrong field silently returns "no category" and admits every
  // provider.
  const eligibleProviders = useMemo(() => {
    const all = providers ?? [];
    if (!selectedService) return all;
    const serviceRef = {
      category: selectedService.category ? { id: selectedService.category.id } : null,
    };
    return all.filter((p) =>
      isProviderEligible(serviceRef, { job_title_id: p.job_title_id }, categories ?? []).ok,
    );
  }, [providers, selectedService, categories]);

  // Clear stale provider when service change makes them ineligible.
  useEffect(() => {
    if (
      watched.provider_id &&
      !eligibleProviders.some((p) => p.id === watched.provider_id)
    ) {
      form.setValue('provider_id', 0, { shouldValidate: false });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [watched.provider_id, eligibleProviders.length]);

  // Soft conflict detection — overlap on any involved provider's day.
  //
  // With per-service provider overrides one visit can touch multiple
  // providers' columns at different slots (e.g. Botox by Dr. A
  // 14:00-14:30, Facial by Esth. B 14:30-15:30). We walk the planned
  // services in order, compute each one's slot, and check every
  // involved provider's existing day for overlap with the matching
  // slice. Surfaces the FIRST overlap so the operator sees a concrete
  // "this provider already has X with Y" message.
  const { data: focusDateAppts } = useAppointmentsForDate(watched.date);
  const conflict = useMemo(() => {
    if (!selectedService || !watched.provider_id || !watched.time) {
      return null;
    }
    const startUtc = localDateTimeToUtcIso(
      watched.date,
      ...parseHHMM(watched.time),
      timezone,
    );
    const visitStartMs = new Date(startUtc).getTime();

    type Slot = { providerId: number; startMs: number; endMs: number };
    const slots: Slot[] = [];
    let cursorMs = visitStartMs;
    // Primary first.
    const primaryEndMs =
      cursorMs + selectedService.duration_minutes * 60_000;
    slots.push({
      providerId: watched.provider_id,
      startMs: cursorMs,
      endMs: primaryEndMs,
    });
    cursorMs = primaryEndMs;
    // Then extras in form order (matches the backend's sort_order
    // assignment in perform_create).
    for (const row of extraServicesResolved) {
      const endMs = cursorMs + row.service.duration_minutes * 60_000;
      slots.push({
        providerId: row.provider?.id ?? watched.provider_id,
        startMs: cursorMs,
        endMs,
      });
      cursorMs = endMs;
    }

    for (const slot of slots) {
      const overlap = (focusDateAppts ?? []).find((a) => {
        if (a.provider.id !== slot.providerId) return false;
        if (a.status === 'cancelled' || a.status === 'no_show') return false;
        const aStart = new Date(a.start_time).getTime();
        const aEnd = new Date(a.end_time).getTime();
        return aStart < slot.endMs && aEnd > slot.startMs;
      });
      if (overlap) return overlap;
    }
    return null;
  }, [
    focusDateAppts,
    selectedService,
    extraServicesResolved,
    watched.provider_id,
    watched.date,
    watched.time,
    timezone,
  ]);

  const onSubmit = form.handleSubmit((values) => {
    const service = (services ?? []).find((s) => s.id === values.service_id);
    if (!service) {
      toast.error('Service not found.');
      return;
    }
    const startIso = localDateTimeToUtcIso(
      values.date,
      ...parseHHMM(values.time),
      timezone,
    );
    const start = new Date(startIso);
    // Block length covers primary + every extra so the calendar reflects
    // the real time commitment and the backend doesn't have to guess.
    const end = new Date(start.getTime() + totalDurationMinutes * 60_000);
    const extras = values.extras ?? [];

    create.mutate(
      {
        customer_id: values.customer_id,
        service_id: values.service_id,
        extras,
        provider_id: values.provider_id,
        start_time: start.toISOString(),
        end_time: end.toISOString(),
        notes: values.notes ?? '',
      },
      {
        onSuccess: () => {
          toast.success('Appointment booked');
          onOpenChange(false);
          onCreated?.(values.date);
        },
        onError: (err) => {
          if (err instanceof ApiError && err.status === 400 && typeof err.body === 'object' && err.body) {
            const body = err.body as Record<string, string[] | string>;
            const firstField = Object.keys(body)[0];
            const detail = firstField
              ? Array.isArray(body[firstField])
                ? (body[firstField] as string[])[0]
                : String(body[firstField])
              : 'Could not book appointment.';
            toast.error(detail);
          } else {
            toast.error('Could not book appointment. Please try again.');
          }
        },
      },
    );
  });

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right">
        <SheetHeader>
          <SheetTitle>New appointment</SheetTitle>
          <SheetDescription>
            Pick a customer, service, provider, and time. Eligibility is
            enforced server-side; an invoice is opened automatically.
          </SheetDescription>
        </SheetHeader>

        <form onSubmit={onSubmit} className="contents">
          <SheetBody className="space-y-4">
            <Controller
              control={form.control}
              name="customer_id"
              render={({ field, fieldState }) => (
                <Field>
                  <FieldLabel>Customer</FieldLabel>
                  <CustomerPicker
                    value={field.value}
                    onChange={(id) => field.onChange(id)}
                  />
                  {fieldState.error ? (
                    <FieldError>{fieldState.error.message}</FieldError>
                  ) : null}
                </Field>
              )}
            />

            <Controller
              control={form.control}
              name="service_id"
              render={({ field, fieldState }) => (
                <Field>
                  <FieldLabel>Service</FieldLabel>
                  <ServicePicker
                    value={field.value}
                    services={services ?? []}
                    onChange={(id) => field.onChange(id)}
                  />
                  {fieldState.error ? (
                    <FieldError>{fieldState.error.message}</FieldError>
                  ) : null}
                </Field>
              )}
            />

            {/* Additional services — one visit can cover multiple
                services (e.g. Facial + Botox). Each one stretches the
                appointment block and becomes its own invoice line at
                booking time. */}
            {extraServicesResolved.length > 0 ? (
              <Field>
                <FieldLabel>Additional services</FieldLabel>
                <ul className="space-y-2">
                  {extraServicesResolved.map((row, index) => {
                    const { service: svc, provider: pickedProv } = row;
                    return (
                      <li
                        key={`${svc.id}-${index}`}
                        className="rounded-md border bg-muted/30 p-2.5 space-y-2"
                      >
                        <div className="flex items-start gap-2">
                          <div className="min-w-0 flex-1 text-sm">
                            <p className="font-medium truncate">{svc.name}</p>
                            <p className="text-[11px] text-muted-foreground font-mono tabular-nums mt-0.5">
                              {svc.duration_minutes}m · $
                              {(svc.price_cents / 100).toFixed(2)}
                            </p>
                          </div>
                          <button
                            type="button"
                            onClick={() => removeExtraAt(index)}
                            aria-label={`Remove ${svc.name}`}
                            className="shrink-0 inline-flex size-6 items-center justify-center rounded text-muted-foreground hover:bg-muted hover:text-destructive transition-colors"
                          >
                            <X className="size-3.5" />
                          </button>
                        </div>
                        <div className="flex items-center gap-2">
                          <label
                            className="text-[11px] text-muted-foreground shrink-0"
                            htmlFor={`extra-prov-${index}`}
                          >
                            Performed by
                          </label>
                          <Select
                            value={
                              pickedProv ? String(pickedProv.id) : ''
                            }
                            onValueChange={(v) =>
                              setExtraProviderAt(
                                index,
                                v && v.length > 0 ? Number(v) : null,
                              )
                            }
                          >
                            <SelectTrigger
                              id={`extra-prov-${index}`}
                              className="h-7 text-xs"
                            >
                              <SelectValue placeholder="Same as main provider">
                                {(v) =>
                                  pickedProv && v
                                    ? membershipName(pickedProv)
                                    : 'Same as main provider'
                                }
                              </SelectValue>
                            </SelectTrigger>
                            <SelectContent>
                              <SelectItem value="">
                                Same as main provider
                              </SelectItem>
                              {(providers ?? []).map((p) => (
                                <SelectItem
                                  key={p.id}
                                  value={String(p.id)}
                                >
                                  {membershipName(p)}
                                  {p.job_title_name ? (
                                    <span className="text-muted-foreground">
                                      {' '}· {p.job_title_name}
                                    </span>
                                  ) : null}
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                        </div>
                      </li>
                    );
                  })}
                </ul>
              </Field>
            ) : null}

            {addingExtra ? (
              <Field>
                <FieldLabel>Pick an additional service</FieldLabel>
                <ServicePicker
                  value={0}
                  services={services ?? []}
                  onChange={appendExtraService}
                />
                <button
                  type="button"
                  onClick={() => setAddingExtra(false)}
                  className="mt-1 text-[11px] text-muted-foreground hover:text-foreground self-start"
                >
                  Cancel
                </button>
              </Field>
            ) : (
              <button
                type="button"
                disabled={!selectedService}
                onClick={() => setAddingExtra(true)}
                className="inline-flex items-center gap-1.5 text-xs font-medium text-accent hover:underline disabled:opacity-50 disabled:no-underline self-start"
              >
                <Plus className="size-3.5" />
                Add another service
              </button>
            )}

            <Controller
              control={form.control}
              name="provider_id"
              render={({ field, fieldState }) => (
                <Field>
                  <FieldLabel>Provider</FieldLabel>
                  <Select
                    value={field.value ? String(field.value) : ''}
                    onValueChange={(v) => field.onChange(Number(v))}
                    disabled={!selectedService}
                  >
                    <SelectTrigger>
                      <SelectValue
                        placeholder={
                          selectedService ? 'Pick a provider' : 'Select a service first'
                        }
                      >
                        {(v) => {
                          // Base UI's SelectValue defaults to showing the
                          // raw value (a numeric ID here) — render the
                          // matching provider's name + job title instead.
                          if (!v) {
                            return selectedService
                              ? 'Pick a provider'
                              : 'Select a service first';
                          }
                          const picked = eligibleProviders.find(
                            (p) => String(p.id) === v,
                          );
                          if (!picked) return v;
                          const name = membershipName(picked);
                          return picked.job_title_name
                            ? `${name} · ${picked.job_title_name}`
                            : name;
                        }}
                      </SelectValue>
                    </SelectTrigger>
                    <SelectContent>
                      {eligibleProviders.map((p) => (
                        <SelectItem key={p.id} value={String(p.id)}>
                          {membershipName(p)}
                          {p.job_title_name ? (
                            <span className="text-muted-foreground"> · {p.job_title_name}</span>
                          ) : null}
                        </SelectItem>
                      ))}
                      {selectedService && eligibleProviders.length === 0 ? (
                        <div className="px-2 py-1.5 text-xs text-muted-foreground">
                          No bookable providers are eligible for this service&apos;s
                          category. Configure eligibility in Services.
                        </div>
                      ) : null}
                    </SelectContent>
                  </Select>
                  {fieldState.error ? (
                    <FieldError>{fieldState.error.message}</FieldError>
                  ) : null}
                </Field>
              )}
            />

            <div className="grid grid-cols-2 gap-3">
              <Controller
                control={form.control}
                name="date"
                render={({ field, fieldState }) => (
                  <Field>
                    <FieldLabel>Date</FieldLabel>
                    <DatePicker
                      value={field.value}
                      onChange={field.onChange}
                      ariaLabel="Appointment date"
                      className="w-full justify-start"
                    />
                    {fieldState.error ? (
                      <FieldError>{fieldState.error.message}</FieldError>
                    ) : null}
                  </Field>
                )}
              />
              <Controller
                control={form.control}
                name="time"
                render={({ field, fieldState }) => (
                  <Field>
                    <FieldLabel>Time</FieldLabel>
                    <TimePicker
                      value={field.value}
                      onChange={field.onChange}
                      ariaLabel="Appointment start time"
                      className="w-full justify-start"
                    />
                    {fieldState.error ? (
                      <FieldError>{fieldState.error.message}</FieldError>
                    ) : null}
                  </Field>
                )}
              />
            </div>

            <Controller
              control={form.control}
              name="notes"
              render={({ field }) => (
                <Field>
                  <FieldLabel>Notes (optional)</FieldLabel>
                  <textarea
                    {...field}
                    rows={3}
                    placeholder="Internal notes — visible to staff only."
                    className="w-full rounded-md border bg-background px-3 py-2 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 placeholder:text-muted-foreground/70 resize-y"
                  />
                </Field>
              )}
            />

            {extraServicesResolved.length > 0 && selectedService ? (
              <div className="flex items-baseline justify-between border-t pt-3 text-sm">
                <span className="text-muted-foreground">
                  Total · {totalDurationMinutes}m
                </span>
                <span className="font-mono font-semibold tabular-nums">
                  ${(totalPriceCents / 100).toFixed(2)}
                </span>
              </div>
            ) : null}

            {conflict ? (
              <div className="rounded-md border border-destructive/40 bg-destructive/5 px-3 py-2.5 flex items-start gap-2 text-xs">
                <AlertTriangle className="size-4 shrink-0 text-destructive mt-0.5" />
                <div className="text-destructive">
                  <span className="font-medium">Conflict:</span> this provider already
                  has &quot;{conflict.service.name}&quot; with{' '}
                  {conflict.customer.full_name} at this time. You can still book
                  if intentional.
                </div>
              </div>
            ) : null}
          </SheetBody>

          <SheetFooter>
            <Button
              type="button"
              variant="outline"
              disabled={create.isPending}
              onClick={() => onOpenChange(false)}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={create.isPending}>
              {create.isPending ? 'Booking…' : 'Book appointment'}
            </Button>
          </SheetFooter>
        </form>
      </SheetContent>
    </Sheet>
  );
}

// ── Customer picker (search + inline create) ────────────────────────────

type CustomerPickerMode = 'search' | 'create';

function CustomerPicker({
  value,
  onChange,
}: {
  value: number;
  onChange: (id: number) => void;
}) {
  const [mode, setMode] = useState<CustomerPickerMode>('search');
  const [query, setQuery] = useState('');
  const [debounced, setDebounced] = useState('');
  const [showResults, setShowResults] = useState(false);

  useEffect(() => {
    const t = setTimeout(() => setDebounced(query.trim()), 200);
    return () => clearTimeout(t);
  }, [query]);

  const { data: results, isFetching } = useCustomers(
    debounced.length >= 2 ? { q: debounced } : undefined,
  );

  // Cache the picked customer's display info so the chip survives a
  // search-list reset.
  const [pickedSnapshot, setPickedSnapshot] = useState<{ id: number; label: string } | null>(null);
  const pickedFromResults = useMemo(
    () => (results ?? []).find((c) => c.id === value) ?? null,
    [results, value],
  );
  useEffect(() => {
    if (pickedFromResults) {
      setPickedSnapshot({ id: pickedFromResults.id, label: customerDisplayName(pickedFromResults) });
    }
  }, [pickedFromResults]);

  const clearSelection = () => {
    onChange(0);
    setPickedSnapshot(null);
    setQuery('');
    setShowResults(true);
    setMode('search');
  };

  if (value > 0 && pickedSnapshot && pickedSnapshot.id === value) {
    return (
      <div className="flex items-center justify-between gap-2 rounded-md border bg-muted/40 px-3 h-9 text-sm">
        <span className="truncate">{pickedSnapshot.label}</span>
        <button
          type="button"
          onClick={clearSelection}
          className="inline-flex size-6 items-center justify-center rounded text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
          aria-label="Clear customer"
        >
          <X className="size-3.5" />
        </button>
      </div>
    );
  }

  if (mode === 'create') {
    return (
      <InlineCreateCustomer
        onCreated={(c) => {
          setPickedSnapshot({ id: c.id, label: customerDisplayName(c) });
          onChange(c.id);
          setMode('search');
          setQuery('');
        }}
        onCancel={() => setMode('search')}
      />
    );
  }

  return (
    <div className="relative">
      <div className="relative">
        <Search className="absolute left-2 top-1/2 -translate-y-1/2 size-3.5 text-muted-foreground pointer-events-none" />
        <Input
          type="text"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setShowResults(true);
          }}
          onFocus={() => setShowResults(true)}
          placeholder="Search by name, email, or phone…"
          className="pl-7"
        />
      </div>
      {showResults ? (
        <div className="absolute z-20 left-0 right-0 mt-1 rounded-md border bg-popover shadow-lg ring-1 ring-foreground/10 max-h-72 overflow-y-auto">
          {debounced.length >= 2 ? (
            isFetching && !results ? (
              <p className="px-3 py-2 text-xs text-muted-foreground">Searching…</p>
            ) : (results ?? []).length === 0 ? (
              <p className="px-3 py-2 text-xs text-muted-foreground italic">
                No matches.
              </p>
            ) : (
              <ul className="py-1">
                {(results ?? []).slice(0, 8).map((c) => (
                  <li key={c.id}>
                    <button
                      type="button"
                      onClick={() => {
                        onChange(c.id);
                        setPickedSnapshot({ id: c.id, label: customerDisplayName(c) });
                        setShowResults(false);
                        setQuery('');
                      }}
                      className="block w-full text-left px-3 py-2 text-sm hover:bg-muted transition-colors"
                    >
                      <p className="font-medium truncate">{customerDisplayName(c)}</p>
                      <p className="text-[11px] text-muted-foreground truncate">
                        {[c.email, c.phone].filter(Boolean).join(' · ') || '—'}
                      </p>
                    </button>
                  </li>
                ))}
              </ul>
            )
          ) : (
            <p className="px-3 py-2 text-xs text-muted-foreground/80">
              Type at least 2 characters to search.
            </p>
          )}
          <div className="border-t">
            <button
              type="button"
              onClick={() => {
                setShowResults(false);
                setMode('create');
              }}
              className="block w-full text-left px-3 py-2 text-sm text-accent hover:bg-accent hover:text-accent-foreground transition-colors flex items-center gap-1.5"
            >
              <UserPlus className="size-3.5" />
              Create new customer
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

/** Inline mini-form for creating a customer without leaving the sheet. */
function InlineCreateCustomer({
  onCreated,
  onCancel,
}: {
  onCreated: (customer: CustomerListItem) => void;
  onCancel: () => void;
}) {
  const create = useCreateCustomer();
  const [first, setFirst] = useState('');
  const [last, setLast] = useState('');
  const [phone, setPhone] = useState('');
  const [email, setEmail] = useState('');

  const canSubmit = first.trim().length > 0 && last.trim().length > 0;

  const submit = () => {
    if (!canSubmit) return;
    create.mutate(
      {
        first_name: first.trim(),
        last_name: last.trim(),
        phone: phone.trim(),
        email: email.trim(),
        email_opt_in: true,
        sms_opt_in: true,
      },
      {
        onSuccess: (c) => {
          toast.success('Customer created');
          // Cast to CustomerListItem-shaped — CustomerDetail extends it.
          onCreated({
            id: c.id,
            first_name: c.first_name,
            last_name: c.last_name,
            preferred_name: c.preferred_name,
            full_name: c.full_name,
            email: c.email,
            phone: c.phone,
            status: c.status,
            tags: c.tags,
            created_at: c.created_at,
          });
        },
        onError: (err) => {
          if (err instanceof ApiError && err.status === 400 && typeof err.body === 'object' && err.body) {
            const body = err.body as Record<string, string[] | string>;
            const firstField = Object.keys(body)[0];
            const detail = firstField
              ? Array.isArray(body[firstField])
                ? (body[firstField] as string[])[0]
                : String(body[firstField])
              : 'Could not create customer.';
            toast.error(detail);
          } else {
            toast.error('Could not create customer.');
          }
        },
      },
    );
  };

  return (
    <div className="rounded-md border bg-muted/30 px-3 py-3 space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-[11px] uppercase tracking-wide text-muted-foreground">
          New customer
        </p>
        <button
          type="button"
          onClick={onCancel}
          className="text-[11px] text-muted-foreground hover:text-foreground transition-colors"
        >
          Cancel
        </button>
      </div>
      <div className="grid grid-cols-2 gap-2">
        <Input
          type="text"
          value={first}
          onChange={(e) => setFirst(e.target.value)}
          placeholder="First name *"
          aria-label="First name"
        />
        <Input
          type="text"
          value={last}
          onChange={(e) => setLast(e.target.value)}
          placeholder="Last name *"
          aria-label="Last name"
        />
        <Input
          type="tel"
          value={phone}
          onChange={(e) => setPhone(e.target.value)}
          placeholder="Phone"
          aria-label="Phone"
        />
        <Input
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="Email"
          aria-label="Email"
        />
      </div>
      <p className="text-[11px] text-muted-foreground/80">
        Quick add — fill out the chart later from the customer profile.
      </p>
      <div className="flex justify-end">
        <Button
          type="button"
          size="sm"
          disabled={!canSubmit || create.isPending}
          onClick={submit}
        >
          <Plus className="size-3.5" />
          {create.isPending ? 'Creating…' : 'Create & select'}
        </Button>
      </div>
    </div>
  );
}

// ── Service picker (typeahead) ──────────────────────────────────────────

function ServicePicker({
  value,
  services,
  onChange,
}: {
  value: number;
  services: Service[];
  onChange: (id: number) => void;
}) {
  const [query, setQuery] = useState('');
  const [showResults, setShowResults] = useState(false);

  const picked = useMemo(() => services.find((s) => s.id === value) ?? null, [services, value]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return services.slice(0, 12);
    return services
      .filter(
        (s) =>
          s.name.toLowerCase().includes(q) ||
          (s.code ?? '').toLowerCase().includes(q),
      )
      .slice(0, 12);
  }, [services, query]);

  if (picked && picked.id === value) {
    return (
      <div className="flex items-center justify-between gap-2 rounded-md border bg-muted/40 px-3 h-9 text-sm">
        <span className="truncate">
          {picked.name}
          <span className="text-muted-foreground">
            {' '}
            · {picked.duration_minutes}m · ${(picked.price_cents / 100).toFixed(2)}
          </span>
        </span>
        <button
          type="button"
          onClick={() => {
            onChange(0);
            setQuery('');
            setShowResults(true);
          }}
          className="inline-flex size-6 items-center justify-center rounded text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
          aria-label="Clear service"
        >
          <X className="size-3.5" />
        </button>
      </div>
    );
  }

  return (
    <div className="relative">
      <div className="relative">
        <Search className="absolute left-2 top-1/2 -translate-y-1/2 size-3.5 text-muted-foreground pointer-events-none" />
        <Input
          type="text"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setShowResults(true);
          }}
          onFocus={() => setShowResults(true)}
          placeholder="Search services by name or code…"
          className="pl-7"
        />
      </div>
      {showResults ? (
        <div className="absolute z-20 left-0 right-0 mt-1 rounded-md border bg-popover shadow-lg ring-1 ring-foreground/10 max-h-72 overflow-y-auto">
          {filtered.length === 0 ? (
            <p className="px-3 py-2 text-xs text-muted-foreground italic">
              No matches.
            </p>
          ) : (
            <ul className="py-1">
              {filtered.map((s) => (
                <li key={s.id}>
                  <button
                    type="button"
                    onClick={() => {
                      onChange(s.id);
                      setShowResults(false);
                      setQuery('');
                    }}
                    className="block w-full text-left px-3 py-2 text-sm hover:bg-muted transition-colors"
                  >
                    <p className="font-medium truncate">{s.name}</p>
                    <p className="text-[11px] text-muted-foreground truncate">
                      {s.duration_minutes}m · ${(s.price_cents / 100).toFixed(2)}
                      {s.code ? ` · ${s.code}` : ''}
                    </p>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : null}
    </div>
  );
}

// ── Helpers ──────────────────────────────────────────────────────────────

function customerDisplayName(c: CustomerListItem): string {
  return c.full_name || `${c.first_name} ${c.last_name}`.trim();
}

