/**
 * `WaitlistPanel` — operator inbox for public-flow waitlist entries.
 *
 * Shows entries scoped to the current tenant, grouped by their
 * preferred date (Today / Tomorrow / [date]). Each row exposes the
 * customer's contact info (phone + email) and one-tap status
 * actions: **Contacted** → marks the operator reached out;
 * **Booked** → marks an appointment was created (operator does the
 * actual booking elsewhere); **Decline** → dismisses the entry.
 *
 * v1 is **manual** — there's no auto-notify when a slot opens up.
 * The operator works the list with the customer's contact info.
 * Auto-notify lands when 1F SMS infrastructure ships.
 *
 * Status filter at the top lets the operator widen from the default
 * "Waiting" inbox to see contacted / booked / declined entries.
 */

'use client';

import {
  Calendar,
  Check,
  ChevronDown,
  Clock,
  Globe,
  Loader2,
  Mail,
  Phone,
  Plus,
  Search,
  Store,
  X,
} from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Field, FieldError, FieldLabel } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { ApiError } from '@/lib/api';
import { useCustomers } from '@/lib/customers';
import { useActiveLocation } from '@/lib/locations';
import { useBookableMemberships } from '@/lib/memberships';
import { useServices } from '@/lib/services';
import {
  WAITLIST_STATUS_LABELS,
  type CreateWaitlistInput,
  type WaitlistEntry,
  type WaitlistStatus,
  useCreateWaitlistEntry,
  useUpdateWaitlistEntry,
  useWaitlistEntries,
} from '@/lib/waitlist';
import { cn } from '@/lib/utils';

const FILTER_OPTIONS: { value: WaitlistStatus | 'all'; label: string }[] = [
  { value: 'waiting', label: 'Waiting' },
  { value: 'contacted', label: 'Contacted' },
  { value: 'booked', label: 'Booked' },
  { value: 'declined', label: 'Declined' },
  { value: 'all', label: 'All' },
];

export function WaitlistPanel() {
  const [statusFilter, setStatusFilter] = useState<WaitlistStatus | 'all'>('waiting');
  const [addOpen, setAddOpen] = useState(false);
  const { data: entries, isLoading, error } = useWaitlistEntries({ status: statusFilter });

  return (
    <div className="px-3 py-3 space-y-3">
      <div className="flex items-center justify-between gap-2 px-1">
        <FilterRow value={statusFilter} onChange={setStatusFilter} />
        <Button
          type="button"
          size="sm"
          variant={addOpen ? 'outline' : 'default'}
          className="h-7 px-2 text-xs shrink-0"
          onClick={() => setAddOpen((v) => !v)}
        >
          {addOpen ? <X className="size-3" /> : <Plus className="size-3" />}
          {addOpen ? 'Cancel' : 'Add'}
        </Button>
      </div>

      {addOpen ? (
        <AddWaitlistForm onDone={() => setAddOpen(false)} />
      ) : null}

      {isLoading ? (
        <div className="p-6 flex items-center justify-center text-sm text-muted-foreground">
          <Loader2 className="size-4 animate-spin mr-2" />
          Loading…
        </div>
      ) : error ? (
        <div className="p-3 text-sm text-destructive">Could not load waitlist.</div>
      ) : (entries ?? []).length === 0 ? (
        <EmptyState filter={statusFilter} />
      ) : (
        <GroupedList entries={entries ?? []} />
      )}
    </div>
  );
}

// ── Add-to-waitlist inline form ──────────────────────────────────────

function AddWaitlistForm({ onDone }: { onDone: () => void }) {
  const create = useCreateWaitlistEntry();
  const { location } = useActiveLocation();

  // 'existing' = pick from search; 'new' = inline name/email/phone.
  const [mode, setMode] = useState<'existing' | 'new'>('existing');

  const [customerSearch, setCustomerSearch] = useState('');
  const [customerId, setCustomerId] = useState<number | null>(null);
  // New-customer fields (used only when mode === 'new').
  const [firstName, setFirstName] = useState('');
  const [lastName, setLastName] = useState('');
  const [email, setEmail] = useState('');
  const [phone, setPhone] = useState('');

  const [serviceId, setServiceId] = useState<number | null>(null);
  const [providerId, setProviderId] = useState<number | 'any'>('any');
  const [preferredDate, setPreferredDate] = useState<string>(() => toLocalIsoDate(new Date()));
  const [notes, setNotes] = useState('');
  const [topError, setTopError] = useState<string | null>(null);

  // Customer search debounced via React Query's stableness — pass q
  // through and re-fetch as the operator types. The list endpoint
  // already supports `?q=` matching against name/email/phone.
  const customersQ = useCustomers({ q: customerSearch.trim() });
  const servicesQ = useServices({ activeOnly: true });
  const providersQ = useBookableMemberships();

  const selectedCustomer = useMemo(
    () => (customersQ.data ?? []).find((c) => c.id === customerId) ?? null,
    [customersQ.data, customerId],
  );

  // Reset selectedCustomer when search clears so the chosen one
  // appears in the list again before re-selecting.
  useEffect(() => {
    if (!customerSearch && customerId === null) return;
    // No-op: react-query will re-fetch on q change.
  }, [customerSearch, customerId]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setTopError(null);
    if (!serviceId) return setTopError('Pick a service.');
    if (!location) return setTopError('No active location.');
    if (!preferredDate) return setTopError('Pick a preferred date.');

    // Build the customer half of the payload based on which mode we're in.
    let customerPayload: Pick<
      CreateWaitlistInput,
      'customer_id' | 'customer_first_name' | 'customer_last_name'
      | 'customer_email' | 'customer_phone'
    > = {};

    if (mode === 'existing') {
      if (!customerId) return setTopError('Pick a customer.');
      customerPayload = { customer_id: customerId };
    } else {
      if (!firstName.trim()) return setTopError('First name is required.');
      if (!lastName.trim()) return setTopError('Last name is required.');
      if (!email.trim() || !/.+@.+\..+/.test(email)) {
        return setTopError('A valid email is required.');
      }
      if (!phone.trim()) return setTopError('Phone is required.');
      customerPayload = {
        customer_first_name: firstName.trim(),
        customer_last_name: lastName.trim(),
        customer_email: email.trim(),
        customer_phone: phone.trim(),
      };
    }

    create.mutate(
      {
        ...customerPayload,
        service_id: serviceId,
        location_id: location.id,
        provider_id: providerId === 'any' ? null : providerId,
        preferred_date: preferredDate,
        notes: notes.trim() || undefined,
      },
      {
        onSuccess: () => {
          toast.success('Added to waitlist');
          onDone();
        },
        onError: (err) => {
          if (err instanceof ApiError && err.status === 400 && err.body && typeof err.body === 'object') {
            const body = err.body as Record<string, unknown>;
            const firstKey = Object.keys(body)[0];
            const v = firstKey ? body[firstKey] : null;
            setTopError(Array.isArray(v) ? String(v[0]) : (v ? String(v) : "Couldn't add."));
          } else {
            setTopError("Couldn't add to waitlist. Please try again.");
          }
        },
      },
    );
  };

  return (
    <form
      onSubmit={handleSubmit}
      className="rounded-lg border border-border bg-card p-3 space-y-3"
    >
      {/* Customer mode toggle */}
      <div className="flex rounded-md border border-border overflow-hidden">
        <button
          type="button"
          onClick={() => setMode('existing')}
          className={cn(
            'flex-1 px-2 py-1 text-[11px] font-medium transition-colors',
            mode === 'existing'
              ? 'bg-foreground text-background'
              : 'bg-card text-muted-foreground hover:bg-muted/60',
          )}
        >
          Existing customer
        </button>
        <button
          type="button"
          onClick={() => setMode('new')}
          className={cn(
            'flex-1 px-2 py-1 text-[11px] font-medium transition-colors border-l border-border',
            mode === 'new'
              ? 'bg-foreground text-background'
              : 'bg-card text-muted-foreground hover:bg-muted/60',
          )}
        >
          New customer
        </button>
      </div>

      {mode === 'existing' ? (
        <Field>
          <FieldLabel className="text-[11px]">Customer</FieldLabel>
          {selectedCustomer ? (
            <div className="flex items-center justify-between gap-2 rounded-md border border-border bg-muted/40 px-2.5 py-1.5">
              <div className="text-xs min-w-0">
                <div className="font-medium text-foreground truncate">
                  {selectedCustomer.first_name} {selectedCustomer.last_name}
                </div>
                <div className="text-muted-foreground truncate">
                  {selectedCustomer.phone || selectedCustomer.email || '—'}
                </div>
              </div>
              <button
                type="button"
                onClick={() => {
                  setCustomerId(null);
                  setCustomerSearch('');
                }}
                className="text-[11px] text-muted-foreground hover:text-foreground"
              >
                Change
              </button>
            </div>
          ) : (
            <>
              <div className="relative">
                <Search className="absolute left-2 top-1/2 -translate-y-1/2 size-3.5 text-muted-foreground" />
                <Input
                  value={customerSearch}
                  onChange={(e) => setCustomerSearch(e.target.value)}
                  placeholder="Search by name, phone, or email…"
                  className="pl-7 h-8 text-xs"
                />
              </div>
              {customerSearch.trim() ? (
                <ul className="mt-1 max-h-40 overflow-y-auto rounded-md border border-border bg-card divide-y divide-border">
                  {customersQ.isLoading ? (
                    <li className="px-2.5 py-2 text-[11px] text-muted-foreground">Loading…</li>
                  ) : (customersQ.data ?? []).length === 0 ? (
                    <li className="px-2.5 py-2 text-[11px] text-muted-foreground">No matches.</li>
                  ) : (
                    (customersQ.data ?? []).slice(0, 10).map((c) => (
                      <li key={c.id}>
                        <button
                          type="button"
                          onClick={() => setCustomerId(c.id)}
                          className="w-full text-left px-2.5 py-1.5 text-xs hover:bg-muted/60"
                        >
                          <div className="font-medium text-foreground">
                            {c.first_name} {c.last_name}
                          </div>
                          <div className="text-muted-foreground">
                            {c.phone || c.email || '—'}
                          </div>
                        </button>
                      </li>
                    ))
                  )}
                </ul>
              ) : null}
            </>
          )}
        </Field>
      ) : (
        // New-customer fields. Backend matches by email/phone via
        // find_or_create_customer, so a returning client's existing
        // record gets re-used silently — no duplicate created.
        <>
          <div className="grid grid-cols-2 gap-2">
            <Field>
              <FieldLabel className="text-[11px]">First name</FieldLabel>
              <Input
                value={firstName}
                onChange={(e) => setFirstName(e.target.value)}
                className="h-8 text-xs"
                autoComplete="given-name"
              />
            </Field>
            <Field>
              <FieldLabel className="text-[11px]">Last name</FieldLabel>
              <Input
                value={lastName}
                onChange={(e) => setLastName(e.target.value)}
                className="h-8 text-xs"
                autoComplete="family-name"
              />
            </Field>
          </div>
          <Field>
            <FieldLabel className="text-[11px]">Email</FieldLabel>
            <Input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="h-8 text-xs"
              autoComplete="email"
              inputMode="email"
            />
          </Field>
          <Field>
            <FieldLabel className="text-[11px]">Phone</FieldLabel>
            <Input
              type="tel"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              className="h-8 text-xs"
              autoComplete="tel"
              inputMode="tel"
            />
          </Field>
        </>
      )}

      {/* Service */}
      <Field>
        <FieldLabel className="text-[11px]">Service</FieldLabel>
        <select
          value={serviceId ?? ''}
          onChange={(e) => setServiceId(e.target.value ? Number(e.target.value) : null)}
          className="w-full h-8 rounded-md border border-input bg-background px-2 text-xs focus:outline-hidden focus:ring-2 focus:ring-ring/40"
        >
          <option value="">Pick a service…</option>
          {(servicesQ.data ?? []).map((s) => (
            <option key={s.id} value={s.id}>
              {s.name} ({s.duration_minutes} min)
            </option>
          ))}
        </select>
      </Field>

      {/* Provider */}
      <Field>
        <FieldLabel className="text-[11px]">Provider</FieldLabel>
        <select
          value={providerId === 'any' ? 'any' : String(providerId)}
          onChange={(e) =>
            setProviderId(e.target.value === 'any' ? 'any' : Number(e.target.value))
          }
          className="w-full h-8 rounded-md border border-input bg-background px-2 text-xs focus:outline-hidden focus:ring-2 focus:ring-ring/40"
        >
          <option value="any">Anyone available</option>
          {(providersQ.data ?? []).map((p) => (
            <option key={p.id} value={p.id}>
              {p.user_first_name} {p.user_last_name}
            </option>
          ))}
        </select>
      </Field>

      {/* Date + notes */}
      <Field>
        <FieldLabel className="text-[11px]">Preferred date</FieldLabel>
        <Input
          type="date"
          value={preferredDate}
          onChange={(e) => setPreferredDate(e.target.value)}
          className="h-8 text-xs"
          min={toLocalIsoDate(new Date())}
        />
      </Field>

      <Field>
        <FieldLabel className="text-[11px]">Notes (optional)</FieldLabel>
        <textarea
          rows={2}
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          maxLength={500}
          placeholder="Any specifics — flexibility, preferred times, etc."
          className="w-full rounded-md border border-input bg-background px-2 py-1.5 text-xs focus:outline-hidden focus:ring-2 focus:ring-ring/40"
        />
      </Field>

      {topError ? (
        <div className="rounded-md border border-red-200 bg-red-50 px-2 py-1.5 text-[11px] text-red-800">
          {topError}
        </div>
      ) : null}

      <Button
        type="submit"
        size="sm"
        className="h-7 px-2 text-xs w-full"
        disabled={create.isPending}
      >
        {create.isPending ? <Loader2 className="size-3 animate-spin" /> : <Plus className="size-3" />}
        Add to waitlist
      </Button>
    </form>
  );
}

function toLocalIsoDate(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const da = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${da}`;
}

function FilterRow({
  value,
  onChange,
}: {
  value: WaitlistStatus | 'all';
  onChange: (v: WaitlistStatus | 'all') => void;
}) {
  return (
    <div className="flex flex-wrap gap-1 px-1">
      {FILTER_OPTIONS.map((opt) => (
        <button
          key={opt.value}
          type="button"
          onClick={() => onChange(opt.value)}
          className={cn(
            'rounded-full px-2.5 py-1 text-[11px] font-medium transition-colors',
            value === opt.value
              ? 'bg-foreground text-background'
              : 'bg-muted text-foreground/70 hover:bg-muted/80',
          )}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}

function EmptyState({ filter }: { filter: WaitlistStatus | 'all' }) {
  return (
    <div className="p-4">
      <div className="rounded-lg border border-dashed bg-muted/30 p-5 text-center">
        <div className="inline-flex size-10 items-center justify-center rounded-full bg-card text-muted-foreground border mb-3">
          <Clock className="size-4" />
        </div>
        <h3 className="font-serif text-base font-semibold tracking-tight">
          {filter === 'waiting'
            ? 'Nobody on the waitlist'
            : `No ${WAITLIST_STATUS_LABELS[filter as WaitlistStatus] ?? filter} entries`}
        </h3>
        <p className="text-xs text-muted-foreground mt-1.5 leading-relaxed">
          When a customer hits a fully-booked day on your booking page, they
          can opt in here so you can reach out when something opens up.
        </p>
      </div>
    </div>
  );
}

function GroupedList({ entries }: { entries: WaitlistEntry[] }) {
  // Group by preferred_date so the list reads inbox-style ordered by
  // when the customer wants to come in (most relevant first).
  const groups = new Map<string, WaitlistEntry[]>();
  for (const e of entries) {
    const list = groups.get(e.preferred_date) ?? [];
    list.push(e);
    groups.set(e.preferred_date, list);
  }
  const sorted = Array.from(groups.entries()).sort(([a], [b]) =>
    a.localeCompare(b),
  );

  return (
    <ul className="space-y-3">
      {sorted.map(([date, items]) => (
        <li key={date}>
          <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-medium px-2 mb-1.5">
            {relativeDateLabel(date)}
          </p>
          <ul className="space-y-1.5">
            {items.map((entry) => (
              <EntryRow key={entry.id} entry={entry} />
            ))}
          </ul>
        </li>
      ))}
    </ul>
  );
}

function EntryRow({ entry }: { entry: WaitlistEntry }) {
  const update = useUpdateWaitlistEntry(entry.id);
  const [pending, setPending] = useState<WaitlistStatus | null>(null);

  const transition = (next: WaitlistStatus, label: string) => {
    setPending(next);
    update.mutate(
      { status: next },
      {
        onSuccess: () => toast.success(`${entry.customer_first_name}: ${label}`),
        onError: (err) => {
          if (err instanceof ApiError && err.status === 403) {
            toast.error("You don't have permission to update waitlist entries.");
          } else {
            toast.error('Could not update entry. Please try again.');
          }
        },
        onSettled: () => setPending(null),
      },
    );
  };

  const tone = STATUS_TONE[entry.status];

  return (
    <li className="rounded-md border border-border bg-card p-3">
      <div className="flex items-start justify-between gap-2 mb-1">
        <div className="min-w-0 flex-1">
          <div className="text-sm font-medium text-foreground truncate">
            {entry.customer_first_name} {entry.customer_last_name}
          </div>
          <div className="text-xs text-muted-foreground truncate">
            {entry.service_name}
            {entry.provider_display_name ? ` · ${entry.provider_display_name}` : ' · Anyone'}
          </div>
        </div>
        <div className="flex flex-col items-end gap-1 shrink-0">
          <span
            className={cn(
              'rounded-full px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wider',
              tone === 'pending' && 'bg-amber-50 text-amber-800',
              tone === 'progress' && 'bg-blue-50 text-blue-800',
              tone === 'success' && 'bg-emerald-50 text-emerald-700',
              tone === 'terminal' && 'bg-stone-100 text-stone-600',
            )}
          >
            {WAITLIST_STATUS_LABELS[entry.status]}
          </span>
          <SourcePill source={entry.source} />
        </div>
      </div>

      {/* Contact + meta */}
      <div className="text-[11px] text-muted-foreground space-y-0.5 mb-2.5">
        <a
          href={`tel:${entry.customer_phone}`}
          className="inline-flex items-center gap-1 hover:text-foreground"
        >
          <Phone className="size-3" />
          {entry.customer_phone || '—'}
        </a>
        <div>
          <a
            href={`mailto:${entry.customer_email}`}
            className="inline-flex items-center gap-1 hover:text-foreground"
          >
            <Mail className="size-3" />
            {entry.customer_email || '—'}
          </a>
        </div>
        <div className="inline-flex items-center gap-1">
          <Calendar className="size-3" />
          {formatPreferredDate(entry.preferred_date)} · {entry.location_name}
        </div>
      </div>

      {entry.notes ? (
        <p className="text-xs text-foreground/80 bg-muted/50 rounded px-2 py-1.5 mb-2.5 italic">
          “{entry.notes}”
        </p>
      ) : null}

      {/* Status transition actions */}
      {entry.status !== 'booked' && entry.status !== 'declined' ? (
        <div className="flex flex-wrap items-center gap-1.5">
          {entry.status === 'waiting' ? (
            <Button
              type="button"
              size="sm"
              variant="outline"
              className="h-7 px-2 text-xs"
              onClick={() => transition('contacted', 'marked contacted')}
              disabled={pending !== null}
            >
              {pending === 'contacted' ? (
                <Loader2 className="size-3 animate-spin" />
              ) : null}
              Contacted
            </Button>
          ) : null}
          <Button
            type="button"
            size="sm"
            className="h-7 px-2 text-xs"
            onClick={() => transition('booked', 'marked booked')}
            disabled={pending !== null}
          >
            {pending === 'booked' ? (
              <Loader2 className="size-3 animate-spin" />
            ) : (
              <Check className="size-3" />
            )}
            Booked
          </Button>
          <button
            type="button"
            onClick={() => transition('declined', 'declined')}
            disabled={pending !== null}
            className="inline-flex items-center gap-1 h-7 px-2 text-xs text-muted-foreground hover:text-red-700 transition-colors disabled:opacity-50"
          >
            {pending === 'declined' ? (
              <Loader2 className="size-3 animate-spin" />
            ) : (
              <X className="size-3" />
            )}
            Decline
          </button>
        </div>
      ) : null}
    </li>
  );
}

const STATUS_TONE: Record<WaitlistStatus, 'pending' | 'progress' | 'success' | 'terminal'> = {
  waiting: 'pending',
  contacted: 'progress',
  booked: 'success',
  declined: 'terminal',
};

function SourcePill({ source }: { source: string }) {
  // 'online' = self-service from the public booking page;
  // 'staff'  = front desk added them directly. Empty string falls
  // back to a generic neutral chip — older entries from before the
  // source field shipped end up here. Showing it on the panel lets
  // the operator tell at a glance which path the entry came in from
  // (a self-service signup may need different follow-up than a
  // staff-added entry where the front desk already spoke to them).
  const isOnline = source === 'online';
  const isStaff = source === 'staff';
  const label = isOnline ? 'Online' : isStaff ? 'Staff' : 'Other';
  const Icon = isOnline ? Globe : isStaff ? Store : Clock;
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 text-[10px] font-medium tracking-wide',
        isOnline && 'bg-stone-100 text-stone-700',
        isStaff && 'bg-stone-100 text-stone-700',
        !isOnline && !isStaff && 'bg-muted text-muted-foreground',
      )}
      title={`Source: ${label}`}
    >
      <Icon className="size-2.5" aria-hidden />
      {label}
    </span>
  );
}

function relativeDateLabel(iso: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  if (!m) return iso;
  const d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  if (d.getTime() === today.getTime()) return 'Today';
  const tmrw = new Date(today);
  tmrw.setDate(today.getDate() + 1);
  if (d.getTime() === tmrw.getTime()) return 'Tomorrow';
  return d.toLocaleDateString('en-US', {
    weekday: 'short',
    month: 'short',
    day: 'numeric',
  });
}

function formatPreferredDate(iso: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  if (!m) return iso;
  const d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}
