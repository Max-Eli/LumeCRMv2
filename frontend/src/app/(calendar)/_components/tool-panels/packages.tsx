/**
 * Calendar right-rail Custom packages panel.
 *
 * Front-desk use case: customer at the counter, staff needs to see
 * whether they have an active package with sessions remaining (so
 * the appointment can be booked against the package rather than
 * charged at full price) — and/or build a new package on the spot.
 *
 * Two surfaces in one panel:
 *
 *   1. **Customer search → active packages.** Pick a customer; see
 *      their active `PurchasedPackage` rows with sessions remaining
 *      per service line + expiry. Empty state nudges to the catalog
 *      so staff can sell one.
 *   2. **Quick actions.** Direct links into the catalog (browse all
 *      package templates, build a new package + invoice the customer
 *      via the POS-handoff page).
 *
 * The actual package-builder UI (multi-line picker + price overrides
 * + expiration) lives at `/catalog/packages/new`. Surfacing that
 * deep page inside the calendar panel would either duplicate a lot
 * of logic or feel cramped at 340 px — better to keep the build flow
 * on its dedicated page and link to it.
 */

'use client';

import {
  ArrowUpRight,
  CalendarDays,
  Loader2,
  Package as PackageIcon,
  Plus,
  Search,
  UserRound,
} from 'lucide-react';
import Link from 'next/link';
import { useEffect, useMemo, useState } from 'react';

import { InitialsAvatar } from '@/components/initials-avatar';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { useCustomers, type CustomerListItem } from '@/lib/customers';
import {
  dollarsFromCents,
  useCustomerPurchasedPackages,
  type PurchasedPackage,
  type PurchasedPackageItem,
} from '@/lib/packages';
import { cn } from '@/lib/utils';

export function PackagesPanel() {
  const [selectedCustomer, setSelectedCustomer] = useState<CustomerListItem | null>(null);

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
            'Find a client to view their active packages, or jump to the catalog to build a new one.'
          )}
        </p>
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto">
        {selectedCustomer ? (
          <CustomerPackagesView customer={selectedCustomer} />
        ) : (
          <CustomerPicker onPick={setSelectedCustomer} />
        )}
      </div>

      <div className="border-t px-3 py-2.5 space-y-1.5">
        <Button
          render={<Link href="/catalog/packages/new" target="_blank" />}
          nativeButton={false}
          size="sm"
          className="w-full"
        >
          <Plus className="size-3.5" />
          Build new package
        </Button>
        <Button
          render={<Link href="/catalog/packages" target="_blank" />}
          nativeButton={false}
          size="sm"
          variant="outline"
          className="w-full"
        >
          Browse all templates
          <ArrowUpRight className="size-3.5" />
        </Button>
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

// ── Customer's active packages ──────────────────────────────────────


function CustomerPackagesView({ customer }: { customer: CustomerListItem }) {
  const { data: packages, isLoading } = useCustomerPurchasedPackages(customer.id, {
    status: 'active',
  });

  const customerName = customer.full_name || `${customer.first_name} ${customer.last_name}`;

  return (
    <div className="p-3">
      <div className="flex items-center gap-2.5 mb-3 px-1">
        <InitialsAvatar name={customerName} size="sm" />
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium truncate">{customerName}</p>
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

      {isLoading ? (
        <div className="flex items-center justify-center py-8 text-muted-foreground">
          <Loader2 className="size-4 animate-spin" />
        </div>
      ) : (packages?.length ?? 0) === 0 ? (
        <div className="px-2 py-6 text-center">
          <PackageIcon className="size-6 mx-auto mb-2 text-muted-foreground" />
          <p className="text-xs text-muted-foreground">No active packages.</p>
          <p className="text-[11px] text-muted-foreground mt-1">
            Build one for this client below.
          </p>
        </div>
      ) : (
        <ul className="space-y-2">
          {packages!.map((p) => (
            <PackageCard key={p.id} pkg={p} />
          ))}
        </ul>
      )}
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

function formatDate(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });
}
