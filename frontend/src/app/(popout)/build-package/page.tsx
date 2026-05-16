/**
 * `/build-package` — standalone popout window for building a custom
 * (per-customer, one-off) package.
 *
 * Spawned by the calendar right-rail "Custom packages" tile via
 * `window.open('/build-package', 'lume-build-package', 'popup,…')`.
 * The named window means clicking the tile again from another
 * calendar view focuses the existing window rather than opening
 * a second copy.
 *
 * Workflow (mirrors the user's mental model — "build a package
 * for a specific client"):
 *   1. Search + pick the client. The page surface adapts to that
 *      client (name in the header, their active packages listed
 *      in the right rail for context).
 *   2. Compose the package — name, service rows with quantities,
 *      price, validity period.
 *   3. Save. The backend atomically creates a draft Invoice + the
 *      PurchasedPackage (with source_template=NULL). The success
 *      screen routes the operator straight to the customer's
 *      Wallet tab to take payment — closing the invoice flips the
 *      package from PENDING → ACTIVE.
 */

'use client';

import {
  ArrowLeft,
  ArrowUpRight,
  CalendarDays,
  Check,
  Layers,
  Loader2,
  Package as PackageIcon,
  Plus,
  Search,
  Trash2,
  UserRound,
} from 'lucide-react';
import Link from 'next/link';
import { useEffect, useMemo, useState } from 'react';

import { InitialsAvatar } from '@/components/initials-avatar';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { ApiError } from '@/lib/api';
import { useCustomers, type CustomerListItem } from '@/lib/customers';
import {
  centsFromDollars,
  dollarsFromCents,
  useBuildCustomPackage,
  useCustomerPurchasedPackages,
  type BuildCustomPackageResult,
  type PurchasedPackage,
} from '@/lib/packages';
import { useServices, type Service } from '@/lib/services';
import { cn } from '@/lib/utils';

export default function BuildPackagePopoutPage() {
  const [customer, setCustomer] = useState<CustomerListItem | null>(null);
  const [success, setSuccess] = useState<BuildCustomPackageResult | null>(null);

  return (
    <div className="flex flex-col h-screen bg-muted/30">
      <header className="shrink-0 border-b bg-card px-6 py-3 flex items-center gap-3">
        <div
          className="inline-flex size-8 items-center justify-center rounded-md bg-accent/15 text-accent-foreground"
          aria-hidden
        >
          <Layers className="size-4" />
        </div>
        <div className="leading-tight">
          <h1 className="text-sm font-serif font-semibold tracking-tight">
            Build a custom package
          </h1>
          <p className="text-[10px] uppercase tracking-wide text-muted-foreground">
            One-off bundle for a specific client
          </p>
        </div>
      </header>

      <main className="flex-1 min-h-0 overflow-y-auto">
        {success ? (
          <SuccessView
            result={success}
            onBuildAnother={() => {
              setSuccess(null);
            }}
          />
        ) : !customer ? (
          <CustomerPickerStep onPick={setCustomer} />
        ) : (
          <BuilderStep
            customer={customer}
            onChangeCustomer={() => setCustomer(null)}
            onCreated={setSuccess}
          />
        )}
      </main>
    </div>
  );
}

// ── Step 1: pick a customer ────────────────────────────────────────


function CustomerPickerStep({
  onPick,
}: {
  onPick: (c: CustomerListItem) => void;
}) {
  const [search, setSearch] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');

  useEffect(() => {
    const t = window.setTimeout(() => setDebouncedSearch(search.trim()), 200);
    return () => window.clearTimeout(t);
  }, [search]);

  const { data: customers, isFetching } = useCustomers({ q: debouncedSearch });
  const showResults = debouncedSearch.length >= 2;
  const results = showResults ? (customers ?? []) : [];

  return (
    <div className="max-w-xl mx-auto px-6 py-12 space-y-5">
      <div className="text-center space-y-2">
        <div
          className="size-12 mx-auto inline-flex items-center justify-center rounded-full bg-card border"
          aria-hidden
        >
          <UserRound className="size-5 text-muted-foreground" />
        </div>
        <h2 className="text-lg font-medium tracking-tight">Who is this for?</h2>
        <p className="text-sm text-muted-foreground">
          Find the client first — every custom package is built for one
          specific person.
        </p>
      </div>

      <div className="relative">
        <Search className="size-4 absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground pointer-events-none" />
        <Input
          autoFocus
          placeholder="Search by name, email, or phone…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="pl-9"
        />
      </div>

      {!showResults ? (
        <p className="text-xs text-muted-foreground text-center">
          Start typing a client&apos;s name.
        </p>
      ) : isFetching && results.length === 0 ? (
        <div className="flex items-center justify-center py-4 text-muted-foreground">
          <Loader2 className="size-4 animate-spin" />
        </div>
      ) : results.length === 0 ? (
        <p className="text-sm text-muted-foreground text-center py-4">
          No clients matching “{debouncedSearch}”.
        </p>
      ) : (
        <ul className="rounded-xl border bg-card divide-y overflow-hidden">
          {results.map((c) => {
            const name = c.full_name || `${c.first_name} ${c.last_name}`;
            return (
              <li key={c.id}>
                <button
                  type="button"
                  onClick={() => onPick(c)}
                  className="w-full text-left px-4 py-3 hover:bg-muted transition-colors flex items-center gap-3"
                >
                  <InitialsAvatar name={name} size="sm" />
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium truncate">{name}</p>
                    <p className="text-xs text-muted-foreground truncate">
                      {c.email || c.phone || 'No contact'}
                    </p>
                  </div>
                  <ArrowUpRight className="size-3.5 text-muted-foreground/60 shrink-0" />
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

// ── Step 2: build the package ──────────────────────────────────────


interface ItemRow {
  rowId: number;
  service_id: string;
  quantity: string;
}

let _nextRowId = 1;
function makeRow(): ItemRow {
  return { rowId: _nextRowId++, service_id: '', quantity: '1' };
}

interface FormErrors {
  name?: string;
  price?: string;
  items?: string;
  general?: string;
}

function BuilderStep({
  customer,
  onChangeCustomer,
  onCreated,
}: {
  customer: CustomerListItem;
  onChangeCustomer: () => void;
  onCreated: (result: BuildCustomPackageResult) => void;
}) {
  const [name, setName] = useState('');
  const [priceDollars, setPriceDollars] = useState('');
  const [validityDays, setValidityDays] = useState('365');
  const [items, setItems] = useState<ItemRow[]>(() => [makeRow()]);
  const [errors, setErrors] = useState<FormErrors>({});

  const servicesQ = useServices({ activeOnly: true });
  const serviceList = servicesQ.data ?? [];
  const build = useBuildCustomPackage();
  const existingPackagesQ = useCustomerPurchasedPackages(customer.id, {
    status: 'active',
  });

  const aLaCarteCents = useMemo(() => {
    return items.reduce((sum, row) => {
      const svc = serviceList.find((s) => String(s.id) === row.service_id);
      if (!svc) return sum;
      const qty = Number(row.quantity) || 0;
      return sum + svc.price_cents * qty;
    }, 0);
  }, [items, serviceList]);
  const priceCents = centsFromDollars(priceDollars || '0');
  const savingsCents = aLaCarteCents - priceCents;

  const validate = (): FormErrors => {
    const next: FormErrors = {};
    if (!name.trim()) next.name = 'Name is required.';
    if (priceDollars === '' || Number.isNaN(Number(priceDollars))) {
      next.price = 'Enter a price.';
    } else if (Number(priceDollars) < 0) {
      next.price = "Price can't be negative.";
    }
    if (items.length === 0) {
      next.items = 'Add at least one service.';
    } else {
      const seen = new Set<string>();
      for (const r of items) {
        if (!r.service_id) {
          next.items = 'Pick a service for every row.';
          break;
        }
        if (!r.quantity || Number(r.quantity) < 1) {
          next.items = 'Quantity must be at least 1 for every row.';
          break;
        }
        if (seen.has(r.service_id)) {
          next.items = 'Each service may only appear once.';
          break;
        }
        seen.add(r.service_id);
      }
    }
    return next;
  };

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const next = validate();
    setErrors(next);
    if (Object.keys(next).length > 0) return;
    try {
      const result = await build.mutateAsync({
        customer_id: customer.id,
        name: name.trim(),
        price_cents: priceCents,
        validity_days:
          validityDays && Number(validityDays) > 0 ? Number(validityDays) : null,
        items: items.map((r) => ({
          service_id: Number(r.service_id),
          quantity: Number(r.quantity),
        })),
      });
      onCreated(result);
    } catch (err) {
      if (err instanceof ApiError && err.body && typeof err.body === 'object') {
        const body = err.body as Record<string, string | string[]>;
        const firstKey = Object.keys(body)[0];
        const raw = firstKey ? body[firstKey] : undefined;
        const msg = Array.isArray(raw) ? raw[0] : raw;
        setErrors({ general: typeof msg === 'string' ? msg : 'Could not save.' });
      } else {
        setErrors({ general: 'Could not save.' });
      }
    }
  };

  const customerName =
    customer.full_name || `${customer.first_name} ${customer.last_name}`;

  return (
    <form onSubmit={onSubmit} className="max-w-5xl mx-auto px-6 py-8 grid grid-cols-1 lg:grid-cols-[1fr_320px] gap-6">
      <div className="space-y-6">
        <CustomerStrip
          name={customerName}
          customer={customer}
          onChange={onChangeCustomer}
        />

        <section className="rounded-xl border bg-card p-6 space-y-5">
          <header>
            <h2 className="text-base font-medium tracking-tight">
              Package details
            </h2>
            <p className="text-xs text-muted-foreground mt-0.5">
              How the package shows up on the client&apos;s receipt and in the
              portal.
            </p>
          </header>

          <div>
            <label htmlFor="pkg-name" className="text-xs font-medium block mb-1.5">
              Name
            </label>
            <Input
              id="pkg-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. 5 HydraFacials package"
            />
            {errors.name ? (
              <p className="mt-1 text-xs text-destructive">{errors.name}</p>
            ) : null}
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label htmlFor="pkg-price" className="text-xs font-medium block mb-1.5">
                Price ($)
              </label>
              <Input
                id="pkg-price"
                type="number"
                inputMode="decimal"
                step="0.01"
                min="0"
                value={priceDollars}
                onChange={(e) => setPriceDollars(e.target.value)}
                placeholder="0.00"
              />
              {errors.price ? (
                <p className="mt-1 text-xs text-destructive">{errors.price}</p>
              ) : null}
            </div>
            <div>
              <label htmlFor="pkg-validity" className="text-xs font-medium block mb-1.5">
                Valid for (days)
              </label>
              <Input
                id="pkg-validity"
                type="number"
                inputMode="numeric"
                min="0"
                value={validityDays}
                onChange={(e) => setValidityDays(e.target.value)}
                placeholder="365"
              />
              <p className="mt-1 text-[10px] text-muted-foreground inline-flex items-center gap-1">
                <CalendarDays className="size-3" />
                Leave 0 or blank for no expiration.
              </p>
            </div>
          </div>
        </section>

        <section className="rounded-xl border bg-card p-6">
          <header className="flex items-baseline justify-between mb-3">
            <div>
              <h2 className="text-base font-medium tracking-tight">Services</h2>
              <p className="text-xs text-muted-foreground mt-0.5">
                Each service line is one redeemable credit count.
              </p>
            </div>
            <button
              type="button"
              onClick={() => setItems((prev) => [...prev, makeRow()])}
              className="text-xs text-muted-foreground hover:text-foreground transition-colors inline-flex items-center gap-1"
            >
              <Plus className="size-3.5" />
              Add row
            </button>
          </header>

          <ul className="space-y-2.5">
            {items.map((row, idx) => (
              <ServiceRowEditor
                key={row.rowId}
                row={row}
                services={serviceList}
                servicesLoading={servicesQ.isLoading}
                onChange={(next) =>
                  setItems((prev) => prev.map((r, i) => (i === idx ? next : r)))
                }
                onRemove={
                  items.length > 1
                    ? () =>
                        setItems((prev) => prev.filter((_, i) => i !== idx))
                    : undefined
                }
              />
            ))}
          </ul>
          {errors.items ? (
            <p className="mt-2 text-xs text-destructive">{errors.items}</p>
          ) : null}
        </section>

        {errors.general ? (
          <p className="text-sm text-destructive">{errors.general}</p>
        ) : null}

        <div className="sticky bottom-0 -mx-6 px-6 py-3 bg-background/95 backdrop-blur border-t flex items-center justify-end gap-2">
          <Button type="button" variant="outline" onClick={onChangeCustomer} disabled={build.isPending}>
            <ArrowLeft className="size-3.5" />
            Cancel
          </Button>
          <Button type="submit" disabled={build.isPending}>
            {build.isPending ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <Check className="size-4" />
            )}
            Save &amp; continue to payment
          </Button>
        </div>
      </div>

      <aside className="space-y-4">
        <SummaryCard
          aLaCarteCents={aLaCarteCents}
          priceCents={priceCents}
          savingsCents={savingsCents}
          validityDays={validityDays}
        />
        <ExistingPackagesCard
          packages={existingPackagesQ.data ?? []}
          loading={existingPackagesQ.isLoading}
        />
      </aside>
    </form>
  );
}

function CustomerStrip({
  name,
  customer,
  onChange,
}: {
  name: string;
  customer: CustomerListItem;
  onChange: () => void;
}) {
  return (
    <div className="rounded-xl border bg-card p-4 flex items-center gap-3">
      <InitialsAvatar name={name} />
      <div className="min-w-0 flex-1">
        <p className="font-medium truncate">{name}</p>
        <p className="text-xs text-muted-foreground truncate">
          {customer.email || customer.phone || 'No contact'}
        </p>
      </div>
      <Button type="button" variant="outline" size="sm" onClick={onChange}>
        Change
      </Button>
    </div>
  );
}

function ServiceRowEditor({
  row,
  services,
  servicesLoading,
  onChange,
  onRemove,
}: {
  row: ItemRow;
  services: Service[];
  servicesLoading: boolean;
  onChange: (next: ItemRow) => void;
  onRemove?: () => void;
}) {
  return (
    <li className="flex items-start gap-2">
      <div className="flex-1 min-w-0">
        <Select
          value={row.service_id || undefined}
          onValueChange={(v) => onChange({ ...row, service_id: v ?? '' })}
        >
          <SelectTrigger>
            <SelectValue
              placeholder={servicesLoading ? 'Loading services…' : 'Pick a service'}
            >
              {(v) => {
                if (!v) {
                  return servicesLoading ? 'Loading services…' : 'Pick a service';
                }
                const picked = services.find((s) => String(s.id) === v);
                if (!picked) return v;
                return `${picked.name} · $${dollarsFromCents(picked.price_cents)}`;
              }}
            </SelectValue>
          </SelectTrigger>
          <SelectContent>
            {services.map((s) => (
              <SelectItem key={s.id} value={String(s.id)}>
                {s.name}{' '}
                <span className="text-xs text-muted-foreground">
                  · ${dollarsFromCents(s.price_cents)}
                </span>
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <Input
        type="number"
        inputMode="numeric"
        min="1"
        value={row.quantity}
        onChange={(e) => onChange({ ...row, quantity: e.target.value })}
        className="w-20 text-center tabular-nums"
        aria-label="Quantity"
      />
      {onRemove ? (
        <button
          type="button"
          onClick={onRemove}
          aria-label="Remove row"
          title="Remove row"
          className="size-10 inline-flex items-center justify-center rounded-md text-muted-foreground hover:text-destructive hover:bg-destructive/10 transition-colors shrink-0"
        >
          <Trash2 className="size-4" />
        </button>
      ) : (
        <span className="size-10 shrink-0" aria-hidden />
      )}
    </li>
  );
}

function SummaryCard({
  aLaCarteCents,
  priceCents,
  savingsCents,
  validityDays,
}: {
  aLaCarteCents: number;
  priceCents: number;
  savingsCents: number;
  validityDays: string;
}) {
  return (
    <article className="rounded-xl border bg-card p-5">
      <h3 className="text-[11px] uppercase tracking-wide text-muted-foreground font-medium mb-3">
        Summary
      </h3>
      <dl className="space-y-1.5 text-sm">
        <div className="flex justify-between text-muted-foreground">
          <dt>À-la-carte total</dt>
          <dd className="tabular-nums">${dollarsFromCents(aLaCarteCents)}</dd>
        </div>
        <div className="flex justify-between text-muted-foreground">
          <dt>Package price</dt>
          <dd className="tabular-nums">${dollarsFromCents(priceCents)}</dd>
        </div>
        <div
          className={cn(
            'flex justify-between font-medium pt-2 border-t',
            savingsCents > 0 && 'text-emerald-700',
          )}
        >
          <dt>{savingsCents >= 0 ? 'Client saves' : 'Premium'}</dt>
          <dd className="tabular-nums">
            ${dollarsFromCents(Math.abs(savingsCents))}
          </dd>
        </div>
      </dl>
      <p className="text-[11px] text-muted-foreground mt-3 inline-flex items-center gap-1.5">
        <CalendarDays className="size-3" />
        {validityDays && Number(validityDays) > 0
          ? `Valid for ${validityDays} days after sale`
          : 'No expiration'}
      </p>
    </article>
  );
}

function ExistingPackagesCard({
  packages,
  loading,
}: {
  packages: PurchasedPackage[];
  loading: boolean;
}) {
  if (loading) {
    return (
      <article className="rounded-xl border bg-card p-5">
        <h3 className="text-[11px] uppercase tracking-wide text-muted-foreground font-medium mb-2">
          Existing packages
        </h3>
        <div className="flex items-center justify-center py-4 text-muted-foreground">
          <Loader2 className="size-4 animate-spin" />
        </div>
      </article>
    );
  }
  if (packages.length === 0) {
    return (
      <article className="rounded-xl border bg-card p-5">
        <h3 className="text-[11px] uppercase tracking-wide text-muted-foreground font-medium mb-2">
          Existing packages
        </h3>
        <p className="text-xs text-muted-foreground">
          This client has no active packages.
        </p>
      </article>
    );
  }
  return (
    <article className="rounded-xl border bg-card p-5">
      <h3 className="text-[11px] uppercase tracking-wide text-muted-foreground font-medium mb-3">
        Existing packages
      </h3>
      <ul className="space-y-2">
        {packages.map((p) => (
          <li key={p.id} className="text-xs">
            <p className="font-medium text-sm truncate">{p.name}</p>
            <p className="text-muted-foreground">
              {p.total_credits_remaining} credit
              {p.total_credits_remaining === 1 ? '' : 's'} remaining
            </p>
          </li>
        ))}
      </ul>
    </article>
  );
}

// ── Success view ──────────────────────────────────────────────────


function SuccessView({
  result,
  onBuildAnother,
}: {
  result: BuildCustomPackageResult;
  onBuildAnother: () => void;
}) {
  const pkg = result.purchased_package;
  // Standalone invoices don't have a dedicated detail page yet
  // (Phase 2A POS work). Send the operator to the customer's
  // Wallet tab — the new invoice appears there and payment flows
  // through the existing close-invoice path.
  const walletHref = `/clients/${result.customer_id}?tab=wallet`;

  return (
    <div className="max-w-xl mx-auto px-6 py-12 text-center">
      <div
        className="size-14 mx-auto inline-flex items-center justify-center rounded-full bg-emerald-100 text-emerald-700 mb-4"
        aria-hidden
      >
        <Check className="size-6" />
      </div>
      <h2 className="text-2xl font-serif font-semibold tracking-tight">
        Package created
      </h2>
      <p className="text-sm text-muted-foreground mt-2">
        <span className="font-medium text-foreground">{pkg.name}</span> ·
        ${dollarsFromCents(pkg.price_cents)}
      </p>
      {result.invoice_number ? (
        <p className="text-xs text-muted-foreground mt-1">
          Invoice <span className="font-mono">{result.invoice_number}</span>
        </p>
      ) : null}

      <div className="mt-6 rounded-xl border bg-muted/40 px-4 py-3 text-sm text-muted-foreground inline-flex items-center gap-2">
        <PackageIcon className="size-4" />
        <span>
          Status: <span className="font-medium text-foreground">Pending</span> —
          activates as soon as the invoice is paid.
        </span>
      </div>

      <div className="mt-6 space-y-2">
        <Button
          render={<Link href={walletHref} target="_blank" />}
          nativeButton={false}
          className="w-full"
          style={{ background: 'var(--portal-brand, currentColor)' }}
        >
          Take payment now
          <ArrowUpRight className="size-4" />
        </Button>
        <Button
          type="button"
          variant="outline"
          onClick={onBuildAnother}
          className="w-full"
        >
          <Plus className="size-4" />
          Build another
        </Button>
      </div>
    </div>
  );
}
