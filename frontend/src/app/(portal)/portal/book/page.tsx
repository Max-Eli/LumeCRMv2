/**
 * `/portal/book` — customer self-service appointment booking.
 *
 * Three-step wizard:
 *
 *   1. **Service.** All bookable-online services on the tenant, with
 *      duration + price. Grouped by category.
 *   2. **Provider + date.** Eligible providers for the chosen
 *      service; once one is picked, a date selector. Slots load
 *      below.
 *   3. **Time + confirm.** Available time slots on the chosen date.
 *      Picking one + Confirm calls the portal booking endpoint.
 *
 * Service + provider + slot endpoints are the public ones the
 * unauthenticated booking page uses — the data is the same. The
 * submit endpoint is portal-authed; the backend uses the session
 * customer instead of asking for guest info, and re-validates the
 * slot inside a transaction so a stale slot losing to a concurrent
 * booking returns 400 cleanly.
 */

'use client';

import {
  ArrowLeft,
  ArrowRight,
  CalendarClock,
  CheckCircle2,
  ChevronRight,
  Clock,
  Loader2,
  Search,
  Sparkles,
  UserCircle2,
  X,
} from 'lucide-react';
import { useRouter } from 'next/navigation';
import { useEffect, useMemo, useState } from 'react';

import { ApiError } from '@/lib/api';
import { dollarsFromCents } from '@/lib/packages';
import {
  type BookableProvider,
  type BookableService,
  type BookableSlot,
  useBookableProviders,
  useBookableServices,
  useBookableSlots,
  useBookAppointment,
  usePortalMe,
} from '@/lib/portal';
import { cn } from '@/lib/utils';

import { Button } from '@/components/ui/button';

type Step = 1 | 2 | 3;

export default function PortalBookPage() {
  const router = useRouter();
  const { data: me } = usePortalMe();
  const tenantSlug = me?.tenant.slug;

  const [step, setStep] = useState<Step>(1);
  const [service, setService] = useState<BookableService | null>(null);
  const [provider, setProvider] = useState<BookableProvider | null>(null);
  const [date, setDate] = useState<string>(() => isoDateInTodayLocal());
  const [slot, setSlot] = useState<BookableSlot | null>(null);
  const [error, setError] = useState<string | null>(null);

  const book = useBookAppointment();

  const goNext = () => {
    if (step === 1 && service) setStep(2);
    else if (step === 2 && provider) setStep(3);
  };
  const goBack = () => {
    setError(null);
    if (step === 3) {
      setSlot(null);
      setStep(2);
    } else if (step === 2) {
      setProvider(null);
      setSlot(null);
      setStep(1);
    }
  };

  const onConfirm = async () => {
    if (!service || !provider || !slot) return;
    setError(null);
    try {
      const appointment = await book.mutateAsync({
        service_id: service.id,
        provider_id: provider.id,
        start_time: slot.start,
      });
      router.push(`/portal/appointments?booked=${appointment.id}`);
    } catch (err) {
      if (err instanceof ApiError && err.body && typeof err.body === 'object') {
        const body = err.body as Record<string, string | string[]>;
        const firstKey = Object.keys(body)[0];
        const v = firstKey ? body[firstKey] : undefined;
        const msg = Array.isArray(v) ? v[0] : v;
        setError(typeof msg === 'string' ? msg : 'Could not book.');
      } else {
        setError('Could not book.');
      }
    }
  };

  return (
    <div className="max-w-4xl mx-auto w-full px-4 sm:px-6 py-6 sm:py-10">
      <header className="mb-6">
        <h1 className="font-serif text-2xl sm:text-3xl font-semibold tracking-tight">
          Book an appointment
        </h1>
        <p className="text-sm text-muted-foreground mt-1.5">
          Pick a service, choose a provider and time — confirm and you&apos;re set.
        </p>
      </header>

      <StepHeader step={step} />

      <div className="mt-6">
        {step === 1 ? (
          <ServiceStep
            tenantSlug={tenantSlug}
            selected={service}
            onPick={(s) => {
              setService(s);
              setProvider(null);
              setSlot(null);
              setStep(2);
            }}
          />
        ) : step === 2 ? (
          <ProviderDateStep
            tenantSlug={tenantSlug}
            service={service!}
            selected={provider}
            date={date}
            onPickProvider={(p) => {
              setProvider(p);
              setSlot(null);
            }}
            onPickDate={(d) => {
              setDate(d);
              setSlot(null);
            }}
            onAdvance={goNext}
          />
        ) : (
          <SlotStep
            tenantSlug={tenantSlug}
            service={service!}
            provider={provider!}
            date={date}
            selected={slot}
            onPick={setSlot}
          />
        )}
      </div>

      {/* Footer with back / confirm. Step 1 doesn't have a Back since
          there's nothing earlier; step 3 swaps Continue for Confirm. */}
      <div className="mt-8 flex items-center justify-between gap-3">
        {step > 1 ? (
          <Button type="button" variant="outline" onClick={goBack} size="sm">
            <ArrowLeft className="size-3.5" />
            Back
          </Button>
        ) : (
          <div />
        )}

        {error ? (
          <p className="text-xs text-destructive text-center flex-1">{error}</p>
        ) : null}

        {step === 3 ? (
          <Button
            type="button"
            onClick={onConfirm}
            disabled={!slot || book.isPending}
            style={{
              background: 'var(--portal-brand, #1f2937)',
              color: '#fff',
            }}
          >
            {book.isPending ? <Loader2 className="size-4 animate-spin" /> : null}
            Confirm booking
          </Button>
        ) : step === 2 ? (
          <Button
            type="button"
            onClick={goNext}
            disabled={!provider}
            style={{
              background: 'var(--portal-brand, #1f2937)',
              color: '#fff',
            }}
          >
            Continue
            <ArrowRight className="size-4" />
          </Button>
        ) : (
          <div />
        )}
      </div>
    </div>
  );
}

// ── Step header ────────────────────────────────────────────────────


function StepHeader({ step }: { step: Step }) {
  const steps: { id: Step; label: string }[] = [
    { id: 1, label: 'Service' },
    { id: 2, label: 'Provider & date' },
    { id: 3, label: 'Time' },
  ];
  return (
    <ol className="flex items-center gap-2 text-xs font-medium">
      {steps.map((s, idx) => {
        const isActive = s.id === step;
        const isDone = s.id < step;
        return (
          <li key={s.id} className="flex items-center gap-2">
            <span
              className={cn(
                'inline-flex size-6 items-center justify-center rounded-full text-[10px]',
                isActive
                  ? 'bg-[var(--portal-brand,#1f2937)] text-white'
                  : isDone
                    ? 'bg-emerald-100 text-emerald-700'
                    : 'bg-muted text-muted-foreground',
              )}
            >
              {isDone ? <CheckCircle2 className="size-3.5" /> : s.id}
            </span>
            <span
              className={cn(
                isActive ? 'text-foreground' : 'text-muted-foreground',
              )}
            >
              {s.label}
            </span>
            {idx < steps.length - 1 ? (
              <ChevronRight className="size-3 text-muted-foreground/50" />
            ) : null}
          </li>
        );
      })}
    </ol>
  );
}

// ── Step 1 — service picker ────────────────────────────────────────


function ServiceStep({
  tenantSlug,
  selected,
  onPick,
}: {
  tenantSlug: string | undefined;
  selected: BookableService | null;
  onPick: (s: BookableService) => void;
}) {
  const { data: services, isLoading } = useBookableServices(tenantSlug);
  const [query, setQuery] = useState('');
  const q = query.trim().toLowerCase();

  const byCategory = useMemo(() => {
    const map = new Map<string, BookableService[]>();
    for (const s of services ?? []) {
      const key = s.category_name || 'Other';
      if (!map.has(key)) map.set(key, []);
      map.get(key)!.push(s);
    }
    return Array.from(map.entries()).sort(([a], [b]) => a.localeCompare(b));
  }, [services]);

  const matches = useMemo(() => {
    if (!q) return [];
    return (services ?? []).filter(
      (s) =>
        s.name.toLowerCase().includes(q) ||
        (s.description ?? '').toLowerCase().includes(q) ||
        (s.category_name ?? '').toLowerCase().includes(q),
    );
  }, [q, services]);

  return (
    <div>
      {/* Sticky search — pinned just below the portal top bar so the
          customer can filter services without scrolling back up. */}
      <div className="sticky top-14 z-10 -mx-4 border-b bg-background/95 px-4 py-3 backdrop-blur sm:-mx-6 sm:px-6">
        <div className="relative">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search services…"
            aria-label="Search services"
            className="h-11 w-full rounded-xl border bg-card pl-9 pr-9 text-sm outline-none transition-shadow focus:ring-2 focus:ring-[var(--portal-brand,#1f2937)]/30"
          />
          {query ? (
            <button
              type="button"
              onClick={() => setQuery('')}
              aria-label="Clear search"
              className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
            >
              <X className="size-4" />
            </button>
          ) : null}
        </div>
      </div>

      <div className="pt-4">
        {isLoading ? (
          <div className="flex items-center justify-center py-12 text-muted-foreground">
            <Loader2 className="size-4 animate-spin" />
          </div>
        ) : !services?.length ? (
          <div className="rounded-xl border border-dashed bg-card px-8 py-16 text-center">
            <Sparkles className="mx-auto mb-2 size-6 text-muted-foreground" />
            <p className="text-sm font-medium">No services bookable online yet</p>
            <p className="mt-1 text-xs text-muted-foreground">
              Contact the front desk to schedule.
            </p>
          </div>
        ) : q ? (
          matches.length === 0 ? (
            <div className="rounded-xl border border-dashed bg-card px-8 py-12 text-center">
              <p className="text-sm font-medium">
                No services match “{query}”
              </p>
              <p className="mt-1 text-xs text-muted-foreground">
                Try a different word, or clear the search to browse all services.
              </p>
            </div>
          ) : (
            <ul className="space-y-2">
              {matches.map((s) => (
                <li key={s.id}>
                  <ServiceCard
                    service={s}
                    isSelected={selected?.id === s.id}
                    showCategory
                    onPick={() => onPick(s)}
                  />
                </li>
              ))}
            </ul>
          )
        ) : (
          <div className="space-y-6">
            {byCategory.map(([cat, group]) => (
              <section key={cat}>
                <h2 className="mb-2 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                  {cat}
                </h2>
                <ul className="space-y-2">
                  {group.map((s) => (
                    <li key={s.id}>
                      <ServiceCard
                        service={s}
                        isSelected={selected?.id === s.id}
                        onPick={() => onPick(s)}
                      />
                    </li>
                  ))}
                </ul>
              </section>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function ServiceCard({
  service,
  isSelected,
  showCategory = false,
  onPick,
}: {
  service: BookableService;
  isSelected: boolean;
  showCategory?: boolean;
  onPick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onPick}
      className={cn(
        'flex w-full items-center justify-between gap-4 rounded-xl border bg-card px-4 py-3 text-left transition-all hover:shadow-sm',
        isSelected
          ? 'border-transparent ring-2 ring-[var(--portal-brand,#1f2937)]'
          : 'hover:border-foreground/20',
      )}
    >
      <div className="min-w-0 flex-1">
        {showCategory && service.category_name ? (
          <p className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
            {service.category_name}
          </p>
        ) : null}
        <p className="truncate font-medium">{service.name}</p>
        {service.description ? (
          <p className="mt-0.5 line-clamp-2 text-xs text-muted-foreground">
            {service.description}
          </p>
        ) : null}
        <p className="mt-1.5 inline-flex items-center gap-1.5 text-[11px] text-muted-foreground">
          <Clock className="size-3" />
          {service.duration_minutes} min
        </p>
      </div>
      <div className="shrink-0 text-right">
        <p className="text-sm font-medium tabular-nums">
          ${dollarsFromCents(service.price_cents)}
        </p>
        <ChevronRight className="ml-auto mt-1 size-4 text-muted-foreground/60" />
      </div>
    </button>
  );
}

// ── Step 2 — provider + date ───────────────────────────────────────


function ProviderDateStep({
  tenantSlug,
  service,
  selected,
  date,
  onPickProvider,
  onPickDate,
  onAdvance,
}: {
  tenantSlug: string | undefined;
  service: BookableService;
  selected: BookableProvider | null;
  date: string;
  onPickProvider: (p: BookableProvider) => void;
  onPickDate: (d: string) => void;
  onAdvance: () => void;
}) {
  const { data: providers, isLoading } = useBookableProviders(tenantSlug, service.id);
  const dates = useMemo(() => nextDates(14), []);

  return (
    <div className="space-y-6">
      <SelectedServiceSummary service={service} />

      <section>
        <h2 className="text-[11px] uppercase tracking-wide text-muted-foreground font-medium mb-2">
          Choose a provider
        </h2>
        {isLoading ? (
          <div className="flex items-center justify-center py-8 text-muted-foreground">
            <Loader2 className="size-4 animate-spin" />
          </div>
        ) : !providers?.length ? (
          <p className="text-sm text-muted-foreground rounded-lg border border-dashed px-4 py-5 text-center">
            No providers are bookable for this service. Reach out to the spa.
          </p>
        ) : (
          <ul className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            {providers.map((p) => (
              <li key={p.id}>
                <button
                  type="button"
                  onClick={() => onPickProvider(p)}
                  className={cn(
                    'w-full text-left px-4 py-3 rounded-xl border bg-card transition-all flex items-center gap-3',
                    selected?.id === p.id
                      ? 'ring-2 ring-[var(--portal-brand,#1f2937)] border-transparent'
                      : 'hover:border-foreground/20',
                  )}
                >
                  <UserCircle2 className="size-7 text-muted-foreground shrink-0" />
                  <div className="min-w-0 flex-1">
                    <p className="font-medium truncate">{p.display_name}</p>
                    {p.job_title ? (
                      <p className="text-xs text-muted-foreground truncate">
                        {p.job_title}
                      </p>
                    ) : null}
                  </div>
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      {selected ? (
        <section>
          <h2 className="text-[11px] uppercase tracking-wide text-muted-foreground font-medium mb-2">
            Pick a date
          </h2>
          <div className="flex gap-2 overflow-x-auto -mx-1 px-1 pb-1">
            {dates.map((d) => {
              const isActive = d.iso === date;
              return (
                <button
                  key={d.iso}
                  type="button"
                  onClick={() => onPickDate(d.iso)}
                  onDoubleClick={() => {
                    onPickDate(d.iso);
                    onAdvance();
                  }}
                  className={cn(
                    'shrink-0 flex flex-col items-center justify-center rounded-xl border px-3 py-2.5 min-w-16 transition-all',
                    isActive
                      ? 'ring-2 ring-[var(--portal-brand,#1f2937)] border-transparent bg-card'
                      : 'bg-card hover:border-foreground/20',
                  )}
                >
                  <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
                    {d.weekday}
                  </span>
                  <span className="text-base font-semibold tabular-nums mt-0.5">
                    {d.day}
                  </span>
                  <span className="text-[10px] text-muted-foreground">
                    {d.month}
                  </span>
                </button>
              );
            })}
          </div>
        </section>
      ) : null}
    </div>
  );
}

function SelectedServiceSummary({ service }: { service: BookableService }) {
  return (
    <div className="rounded-lg border bg-muted/30 px-4 py-3 flex items-center gap-3">
      <Sparkles className="size-4 text-muted-foreground shrink-0" />
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium truncate">{service.name}</p>
        <p className="text-[11px] text-muted-foreground">
          {service.duration_minutes} min · ${dollarsFromCents(service.price_cents)}
        </p>
      </div>
    </div>
  );
}

// ── Step 3 — time picker ───────────────────────────────────────────


function SlotStep({
  tenantSlug,
  service,
  provider,
  date,
  selected,
  onPick,
}: {
  tenantSlug: string | undefined;
  service: BookableService;
  provider: BookableProvider;
  date: string;
  selected: BookableSlot | null;
  onPick: (s: BookableSlot) => void;
}) {
  const { data: slots, isLoading } = useBookableSlots(tenantSlug, {
    serviceId: service.id,
    providerId: provider.id,
    date,
  });

  return (
    <div className="space-y-6">
      <SelectedServiceSummary service={service} />
      <div className="rounded-lg border bg-muted/30 px-4 py-3 flex items-center gap-3">
        <UserCircle2 className="size-4 text-muted-foreground shrink-0" />
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium truncate">{provider.display_name}</p>
          <p className="text-[11px] text-muted-foreground inline-flex items-center gap-1.5">
            <CalendarClock className="size-3" />
            {formatLongDate(date)}
          </p>
        </div>
      </div>

      <section>
        <h2 className="text-[11px] uppercase tracking-wide text-muted-foreground font-medium mb-3">
          Available times
        </h2>
        {isLoading ? (
          <div className="flex items-center justify-center py-8 text-muted-foreground">
            <Loader2 className="size-4 animate-spin" />
          </div>
        ) : !slots?.length ? (
          <p className="text-sm text-muted-foreground rounded-lg border border-dashed px-4 py-5 text-center">
            No times available on this date. Try another day.
          </p>
        ) : (
          <ul className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-5 gap-2">
            {slots.map((s) => {
              const isSelected = selected?.start === s.start;
              return (
                <li key={s.start}>
                  <button
                    type="button"
                    disabled={!s.available}
                    onClick={() => onPick(s)}
                    className={cn(
                      'w-full px-2 py-2 rounded-md border bg-card text-sm tabular-nums transition-all',
                      !s.available
                        ? 'opacity-40 cursor-not-allowed'
                        : isSelected
                          ? 'ring-2 ring-[var(--portal-brand,#1f2937)] border-transparent text-foreground font-medium'
                          : 'hover:border-foreground/30',
                    )}
                  >
                    {formatTime(s.start)}
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </section>
    </div>
  );
}

// ── Date helpers ───────────────────────────────────────────────────


function isoDateInTodayLocal(): string {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
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

function formatTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleTimeString(undefined, {
    hour: 'numeric',
    minute: '2-digit',
  });
}

function formatLongDate(iso: string): string {
  // iso is YYYY-MM-DD; render as the local date string.
  const d = new Date(`${iso}T00:00:00`);
  return d.toLocaleDateString(undefined, {
    weekday: 'long',
    month: 'long',
    day: 'numeric',
  });
}
