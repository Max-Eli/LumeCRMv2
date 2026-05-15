/**
 * Calendar right-rail Custom packages panel.
 *
 * **Custom packages are per-customer, not template-driven** — every
 * one is built for a specific client right at the front desk.
 * That's why the flow is:
 *
 *   1. Pick the client (search-driven).
 *   2. View their existing active packages, OR
 *   3. Build a new custom package for them — name, service rows
 *      (`{service, quantity}`), price, optional expiry.
 *   4. Save → backend atomically creates a draft Invoice + a
 *      `PurchasedPackage` (with `source_template = NULL`) + line
 *      items. Returns the invoice ID for the POS hand-off.
 *
 * The catalog `Package` template (`/catalog/packages`) is a
 * different surface — those are reusable "bundles every customer
 * can buy." This panel is the one-off "I'm building 5 facials at
 * $399 for Jane right now" flow.
 */

'use client';

import {
  ArrowUpRight,
  CalendarDays,
  Check,
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
  type PurchasedPackageItem,
} from '@/lib/packages';
import { useServices, type Service } from '@/lib/services';
import { cn } from '@/lib/utils';

/** Inner-pane mode for the selected-customer view. */
type Mode = 'list' | 'build' | 'success';

export function PackagesPanel() {
  const [selectedCustomer, setSelectedCustomer] = useState<CustomerListItem | null>(null);
  const [mode, setMode] = useState<Mode>('list');
  const [lastResult, setLastResult] = useState<BuildCustomPackageResult | null>(null);

  // Whenever the operator switches customers, reset to the list view.
  useEffect(() => {
    setMode('list');
    setLastResult(null);
  }, [selectedCustomer?.id]);

  return (
    <div className="flex flex-col h-full">
      <div className="px-4 pt-3 pb-2 border-b">
        <p className="text-xs text-muted-foreground">
          {selectedCustomer ? (
            <button
              type="button"
              onClick={() => setSelectedCustomer(null)}
              className="underline underline-offset-2 hover:text-foreground transition-colors"
            >
              ← Pick a different client
            </button>
          ) : (
            'Custom packages are built per client. Search for one to start.'
          )}
        </p>
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto">
        {!selectedCustomer ? (
          <CustomerPicker onPick={setSelectedCustomer} />
        ) : mode === 'build' ? (
          <CustomPackageBuilder
            customer={selectedCustomer}
            onCancel={() => setMode('list')}
            onCreated={(result) => {
              setLastResult(result);
              setMode('success');
            }}
          />
        ) : mode === 'success' && lastResult ? (
          <SuccessScreen
            result={lastResult}
            onBuildAnother={() => {
              setLastResult(null);
              setMode('build');
            }}
            onBackToList={() => {
              setLastResult(null);
              setMode('list');
            }}
          />
        ) : (
          <CustomerPackagesView
            customer={selectedCustomer}
            onBuildNew={() => setMode('build')}
          />
        )}
      </div>
    </div>
  );
}

// ── Customer picker ────────────────────────────────────────────────


function CustomerPicker({
  onPick,
}: {
  onPick: (c: CustomerListItem) => void;
}) {
  const [search, setSearch] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');

  // Debounce search input so we don't fire a request on every keystroke.
  useEffect(() => {
    const t = window.setTimeout(() => setDebouncedSearch(search.trim()), 200);
    return () => window.clearTimeout(t);
  }, [search]);

  const { data: customers, isFetching } = useCustomers({ q: debouncedSearch });
  const showResults = debouncedSearch.length >= 2;
  const results = showResults ? (customers ?? []) : [];

  return (
    <div className="p-3 space-y-2">
      <div className="relative">
        <Search className="size-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground pointer-events-none" />
        <Input
          autoFocus
          placeholder="Search by name, email, or phone…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="h-9 pl-8 text-sm"
        />
      </div>

      {!showResults ? (
        <div className="px-2 py-6 text-center">
          <UserRound className="size-6 mx-auto mb-2 text-muted-foreground" />
          <p className="text-xs text-muted-foreground">
            Start typing a client&apos;s name.
          </p>
        </div>
      ) : isFetching && results.length === 0 ? (
        <div className="flex items-center justify-center py-4 text-muted-foreground">
          <Loader2 className="size-4 animate-spin" />
        </div>
      ) : results.length === 0 ? (
        <p className="px-2 py-4 text-xs text-muted-foreground text-center">
          No clients matching “{debouncedSearch}”.
        </p>
      ) : (
        <ul className="space-y-px">
          {results.map((c) => (
            <li key={c.id}>
              <button
                type="button"
                onClick={() => onPick(c)}
                className="w-full text-left px-2 py-2 rounded-md hover:bg-muted transition-colors flex items-center gap-2.5"
              >
                <InitialsAvatar
                  name={c.full_name || `${c.first_name} ${c.last_name}`}
                  size="sm"
                />
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium truncate">
                    {c.full_name || `${c.first_name} ${c.last_name}`}
                  </p>
                  <p className="text-[11px] text-muted-foreground truncate">
                    {c.email || c.phone || 'No contact'}
                  </p>
                </div>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// ── Customer's active packages + "build" CTA ───────────────────────


function CustomerPackagesView({
  customer,
  onBuildNew,
}: {
  customer: CustomerListItem;
  onBuildNew: () => void;
}) {
  const { data: packages, isLoading } = useCustomerPurchasedPackages(customer.id, {
    status: 'active',
  });

  return (
    <div className="p-3 space-y-3">
      <CustomerHeader customer={customer} />

      {isLoading ? (
        <div className="flex items-center justify-center py-8 text-muted-foreground">
          <Loader2 className="size-4 animate-spin" />
        </div>
      ) : (packages?.length ?? 0) === 0 ? (
        <div className="px-2 py-6 text-center">
          <PackageIcon className="size-6 mx-auto mb-2 text-muted-foreground" />
          <p className="text-xs text-muted-foreground">No active packages.</p>
        </div>
      ) : (
        <div className="space-y-2">
          <p className="text-[11px] uppercase tracking-wide text-muted-foreground font-medium px-1">
            Active packages
          </p>
          <ul className="space-y-2">
            {packages!.map((p) => (
              <PackageCard key={p.id} pkg={p} />
            ))}
          </ul>
        </div>
      )}

      <Button type="button" onClick={onBuildNew} size="sm" className="w-full mt-2">
        <Plus className="size-3.5" />
        Build custom package for {customer.first_name}
      </Button>
    </div>
  );
}

function CustomerHeader({ customer }: { customer: CustomerListItem }) {
  const name = customer.full_name || `${customer.first_name} ${customer.last_name}`;
  return (
    <div className="flex items-center gap-2.5 px-1">
      <InitialsAvatar name={name} size="sm" />
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium truncate">{name}</p>
        <Link
          href={`/clients/${customer.id}`}
          target="_blank"
          className="text-[11px] text-muted-foreground hover:text-foreground transition-colors inline-flex items-center gap-1 underline underline-offset-2"
        >
          View full profile
          <ArrowUpRight className="size-2.5" />
        </Link>
      </div>
    </div>
  );
}

function PackageCard({ pkg }: { pkg: PurchasedPackage }) {
  const expiringSoon = useMemo(() => {
    if (!pkg.expires_at) return false;
    const days = (new Date(pkg.expires_at).getTime() - Date.now()) / (1000 * 60 * 60 * 24);
    return days >= 0 && days <= 30;
  }, [pkg.expires_at]);

  return (
    <li className="rounded-lg border bg-card p-3 shadow-sm">
      <div className="flex items-start justify-between gap-2">
        <p className="text-sm font-medium truncate">{pkg.name}</p>
        <span className="text-[11px] text-muted-foreground shrink-0">
          ${dollarsFromCents(pkg.price_cents)}
        </span>
      </div>
      {pkg.expires_at ? (
        <p
          className={cn(
            'text-[11px] flex items-center gap-1 mt-1',
            expiringSoon ? 'text-amber-700' : 'text-muted-foreground',
          )}
        >
          <CalendarDays className="size-3" />
          Expires {formatDate(pkg.expires_at)}
          {expiringSoon ? ' · soon' : null}
        </p>
      ) : (
        <p className="text-[11px] text-muted-foreground mt-1">No expiration</p>
      )}
      {pkg.items.length > 0 ? (
        <ul className="mt-2.5 space-y-1">
          {pkg.items.map((item) => (
            <PackageItemRow key={item.id} item={item} />
          ))}
        </ul>
      ) : null}
    </li>
  );
}

function PackageItemRow({ item }: { item: PurchasedPackageItem }) {
  const remaining = item.quantity_remaining;
  const purchased = item.quantity_purchased;
  const depleted = remaining <= 0;

  return (
    <li className="flex items-baseline justify-between gap-2 text-xs">
      <span className={cn('truncate', depleted && 'text-muted-foreground line-through')}>
        {item.service_name}
      </span>
      <span
        className={cn(
          'shrink-0 font-mono tabular-nums',
          depleted
            ? 'text-muted-foreground'
            : remaining <= 1
              ? 'text-amber-700 font-semibold'
              : 'text-foreground',
        )}
      >
        {remaining}/{purchased}
      </span>
    </li>
  );
}

// ── Inline builder ─────────────────────────────────────────────────


interface ItemRow {
  /** Stable id so each row has a key independent of the picked service. */
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

function CustomPackageBuilder({
  customer,
  onCancel,
  onCreated,
}: {
  customer: CustomerListItem;
  onCancel: () => void;
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

  // À-la-carte total (services × quantities at list price) so the
  // operator can see the package's implied savings vs. paying per
  // service. Useful for explaining the offer to the client.
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

  return (
    <form onSubmit={onSubmit} className="p-3 space-y-3">
      <CustomerHeader customer={customer} />

      <div>
        <label htmlFor="pkg-name" className="text-[11px] font-medium block mb-1">
          Package name
        </label>
        <Input
          id="pkg-name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="e.g. 5 HydraFacials"
          className="h-9 text-sm"
        />
        {errors.name ? (
          <p className="mt-1 text-[11px] text-destructive">{errors.name}</p>
        ) : null}
      </div>

      <div>
        <div className="flex items-baseline justify-between mb-1">
          <span className="text-[11px] font-medium">Services</span>
          <button
            type="button"
            onClick={() => setItems((prev) => [...prev, makeRow()])}
            className="text-[11px] text-muted-foreground hover:text-foreground transition-colors inline-flex items-center gap-1"
          >
            <Plus className="size-3" />
            Add row
          </button>
        </div>
        <ul className="space-y-2">
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
          <p className="mt-1.5 text-[11px] text-destructive">{errors.items}</p>
        ) : null}
      </div>

      <div className="grid grid-cols-2 gap-2">
        <div>
          <label htmlFor="pkg-price" className="text-[11px] font-medium block mb-1">
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
            className="h-9 text-sm"
          />
          {errors.price ? (
            <p className="mt-1 text-[11px] text-destructive">{errors.price}</p>
          ) : null}
        </div>
        <div>
          <label htmlFor="pkg-validity" className="text-[11px] font-medium block mb-1">
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
            className="h-9 text-sm"
          />
          <p className="mt-0.5 text-[10px] text-muted-foreground">
            Blank/0 = no expiry
          </p>
        </div>
      </div>

      {aLaCarteCents > 0 && priceCents > 0 ? (
        <div className="rounded-md border bg-muted/30 px-3 py-2 text-[11px] space-y-0.5">
          <div className="flex justify-between text-muted-foreground">
            <span>À-la-carte total</span>
            <span className="font-mono tabular-nums">
              ${dollarsFromCents(aLaCarteCents)}
            </span>
          </div>
          <div className="flex justify-between text-muted-foreground">
            <span>Package price</span>
            <span className="font-mono tabular-nums">
              ${dollarsFromCents(priceCents)}
            </span>
          </div>
          <div
            className={cn(
              'flex justify-between font-medium pt-1 border-t border-muted-foreground/20',
              savingsCents > 0 ? 'text-emerald-700' : 'text-foreground',
            )}
          >
            <span>{savingsCents >= 0 ? 'Client saves' : 'Premium'}</span>
            <span className="font-mono tabular-nums">
              ${dollarsFromCents(Math.abs(savingsCents))}
            </span>
          </div>
        </div>
      ) : null}

      {errors.general ? (
        <p className="text-xs text-destructive">{errors.general}</p>
      ) : null}

      <div className="flex gap-2 pt-1">
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={onCancel}
          disabled={build.isPending}
          className="flex-1"
        >
          Cancel
        </Button>
        <Button type="submit" size="sm" disabled={build.isPending} className="flex-1">
          {build.isPending ? (
            <Loader2 className="size-3.5 animate-spin" />
          ) : (
            <Check className="size-3.5" />
          )}
          Save
        </Button>
      </div>
    </form>
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
    <li className="flex items-start gap-1.5">
      <div className="flex-1 min-w-0">
        <Select
          value={row.service_id || undefined}
          onValueChange={(v) => onChange({ ...row, service_id: v ?? '' })}
        >
          <SelectTrigger className="h-9 text-sm">
            <SelectValue
              placeholder={servicesLoading ? 'Loading…' : 'Pick a service'}
            />
          </SelectTrigger>
          <SelectContent>
            {services.map((s) => (
              <SelectItem key={s.id} value={String(s.id)}>
                {s.name}{' '}
                <span className="text-[10px] text-muted-foreground">
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
        className="h-9 w-14 text-sm text-center tabular-nums"
        aria-label="Quantity"
      />
      {onRemove ? (
        <button
          type="button"
          onClick={onRemove}
          aria-label="Remove row"
          title="Remove row"
          className="size-9 inline-flex items-center justify-center rounded-md text-muted-foreground hover:text-destructive hover:bg-destructive/10 transition-colors shrink-0"
        >
          <Trash2 className="size-3.5" />
        </button>
      ) : (
        // Spacer to keep the row's other controls aligned when there's
        // only one row and the delete button is hidden.
        <span className="size-9 shrink-0" aria-hidden />
      )}
    </li>
  );
}

// ── Success screen ──────────────────────────────────────────────────


function SuccessScreen({
  result,
  onBuildAnother,
  onBackToList,
}: {
  result: BuildCustomPackageResult;
  onBuildAnother: () => void;
  onBackToList: () => void;
}) {
  const pkg = result.purchased_package;
  // Standalone invoices (no appointment) don't have a dedicated
  // detail page yet — Phase 2A POS work. Routing the operator to
  // the customer's Wallet tab is the right "next step" today: the
  // invoice shows up there and they can take payment from the
  // existing invoice flow once one exists.
  const walletHref = `/clients/${result.customer_id}?tab=wallet`;

  return (
    <div className="p-4 space-y-4">
      <div className="text-center pt-2">
        <div
          className="size-10 mx-auto mb-3 rounded-full inline-flex items-center justify-center bg-emerald-100 text-emerald-700"
          aria-hidden
        >
          <Check className="size-5" />
        </div>
        <p className="text-sm font-medium">Package created</p>
        <p className="text-xs text-muted-foreground mt-1">
          {pkg.name} · ${dollarsFromCents(pkg.price_cents)}
        </p>
        {result.invoice_number ? (
          <p className="text-[11px] text-muted-foreground mt-0.5">
            Invoice <span className="font-mono">{result.invoice_number}</span>
          </p>
        ) : null}
      </div>

      <div className="rounded-md border bg-muted/30 px-3 py-2.5 text-[11px] text-muted-foreground">
        Status:{' '}
        <span className="font-medium text-foreground">Pending</span>
        <p className="mt-1 leading-relaxed">
          The package activates as soon as the invoice is paid. Mark it paid
          from the client&apos;s Wallet.
        </p>
      </div>

      <div className="space-y-2">
        <Button
          render={<Link href={walletHref} target="_blank" />}
          nativeButton={false}
          size="sm"
          className="w-full"
        >
          Open client&apos;s Wallet
          <ArrowUpRight className="size-3.5" />
        </Button>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={onBuildAnother}
          className="w-full"
        >
          <Plus className="size-3.5" />
          Build another for this client
        </Button>
        <button
          type="button"
          onClick={onBackToList}
          className="block w-full text-center text-[11px] text-muted-foreground hover:text-foreground transition-colors py-1"
        >
          Back to active packages
        </button>
      </div>
    </div>
  );
}

// ── Helpers ────────────────────────────────────────────────────────


function formatDate(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });
}
