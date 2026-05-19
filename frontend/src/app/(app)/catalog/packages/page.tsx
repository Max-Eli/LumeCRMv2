/**
 * `/catalog/packages` — pre-paid service bundle catalog list.
 *
 * Stat strip + state filter + searchable data table. Each row
 * shows the SKU, name, included services summary, package price,
 * implicit discount vs. a-la-carte total, validity window, and
 * active state. Click → detail/edit.
 */

'use client';

import {
  Layers,
  Plus,
  Search,
} from 'lucide-react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useMemo, useState } from 'react';

import { PageHeader } from '@/components/page-header';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { useCurrentMembership } from '@/lib/auth';
import { type Package, usePackages } from '@/lib/packages';
import { useDebounce } from '@/lib/use-debounce';
import { cn } from '@/lib/utils';

type StateFilter = 'all' | 'active' | 'inactive';

export default function PackagesListPage() {
  const me = useCurrentMembership();
  const canEdit = me?.role === 'owner' || me?.role === 'manager';
  const router = useRouter();
  const [search, setSearch] = useState('');
  const debouncedSearch = useDebounce(search, 250);
  const [filter, setFilter] = useState<StateFilter>('all');
  const { data, isLoading, error } = usePackages({
    q: debouncedSearch,
    activeOnly:
      filter === 'active' ? true : filter === 'inactive' ? false : undefined,
  });

  const all = usePackages();
  const packages = data ?? [];
  const allRows = all.data ?? [];

  const activeCount = allRows.filter((p) => p.is_active).length;
  const totalDiscountCents = useMemo(() => {
    const rows = all.data ?? [];
    return rows.reduce((s, p) => s + Math.max(0, p.implicit_discount_cents), 0);
  }, [all.data]);

  return (
    <div className="px-4 sm:px-8 py-4 sm:py-8 space-y-4 sm:space-y-6">
      <PageHeader
        title="Packages"
        description="Pre-paid service bundles. Customer pays once, draws down credits across multiple visits."
        actions={
          canEdit ? (
            <Button render={<Link href="/catalog/packages/new" />} nativeButton={false}>
              <Plus className="size-4" />
              New package
            </Button>
          ) : null
        }
      />

      <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
        <Stat label="Total packages" value={allRows.length} />
        <Stat label="Active" value={activeCount} tone="emerald" />
        <Stat
          label="Avg savings vs. a la carte"
          value={
            allRows.length > 0
              ? `$${(totalDiscountCents / allRows.length / 100).toLocaleString(
                  undefined,
                  { minimumFractionDigits: 2, maximumFractionDigits: 2 },
                )}`
              : '$0.00'
          }
          isCurrency
        />
      </div>

      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div className="inline-flex items-center gap-0.5 rounded-md border bg-muted/40 p-0.5">
          {(['all', 'active', 'inactive'] as const).map((f) => (
            <button
              key={f}
              type="button"
              onClick={() => setFilter(f)}
              className={cn(
                'px-3 h-8 rounded-md text-sm transition-colors capitalize',
                filter === f
                  ? 'bg-card text-foreground shadow-sm font-medium'
                  : 'text-muted-foreground hover:text-foreground',
              )}
            >
              {f}
            </button>
          ))}
        </div>
        <div className="relative max-w-md flex-1 min-w-[240px]">
          <Search className="size-4 absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground pointer-events-none" />
          <Input
            placeholder="Search by name, SKU, or description…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-9"
          />
        </div>
      </div>

      {error ? (
        <div className="rounded-lg border border-destructive/40 bg-destructive/5 p-6 text-sm text-destructive">
          Could not load packages.
        </div>
      ) : isLoading ? (
        <div className="rounded-lg border bg-card p-12 text-center text-sm text-muted-foreground">
          Loading packages…
        </div>
      ) : packages.length === 0 ? (
        allRows.length === 0 ? (
          <EmptyState canCreate={canEdit} />
        ) : (
          <div className="rounded-lg border bg-card p-12 text-center">
            <Search className="size-8 mx-auto text-muted-foreground/40 mb-3" />
            <p className="text-sm text-muted-foreground">
              No packages match the current filters.
            </p>
          </div>
        )
      ) : (
        <PackagesTable
          rows={packages}
          onClick={(id) => router.push(`/catalog/packages/${id}`)}
        />
      )}
    </div>
  );
}

function PackagesTable({
  rows,
  onClick,
}: {
  rows: Package[];
  onClick: (id: number) => void;
}) {
  return (
    <div className="rounded-lg border bg-card overflow-x-auto">
      <Table className="min-w-[720px]">
        <TableHeader>
          <TableRow className="bg-muted/30 hover:bg-muted/30">
            <TableHead className="w-[110px]">SKU</TableHead>
            <TableHead className="w-[28%]">Package</TableHead>
            <TableHead>Includes</TableHead>
            <TableHead className="text-right w-[110px]">Price</TableHead>
            <TableHead className="text-right w-[140px]">Savings</TableHead>
            <TableHead className="w-[110px]">Validity</TableHead>
            <TableHead className="w-[110px]">Status</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((p) => {
            const totalCredits = p.items.reduce((s, it) => s + it.quantity, 0);
            return (
              <TableRow
                key={p.id}
                className="cursor-pointer"
                onClick={() => onClick(p.id)}
              >
                <TableCell className="py-3.5 text-xs font-mono text-muted-foreground">
                  {p.sku || '—'}
                </TableCell>
                <TableCell>
                  <div className="flex items-center gap-3">
                    <div className="inline-flex size-8 items-center justify-center rounded-md bg-emerald-50 text-emerald-700 shrink-0">
                      <Layers className="size-4" />
                    </div>
                    <div className="min-w-0">
                      <p className="font-medium truncate">{p.name}</p>
                      {p.description ? (
                        <p className="text-xs text-muted-foreground mt-0.5 truncate max-w-md">
                          {p.description}
                        </p>
                      ) : null}
                    </div>
                  </div>
                </TableCell>
                <TableCell className="text-sm text-muted-foreground">
                  {p.items.length === 0 ? (
                    <span className="text-xs text-muted-foreground/70">
                      No items yet
                    </span>
                  ) : (
                    <div className="space-y-0.5">
                      {p.items.slice(0, 2).map((it) => (
                        <div key={it.id} className="truncate">
                          <span className="font-medium text-foreground">
                            {it.quantity}×
                          </span>{' '}
                          {it.service_name}
                        </div>
                      ))}
                      {p.items.length > 2 ? (
                        <p className="text-xs text-muted-foreground/70">
                          + {p.items.length - 2} more · {totalCredits} credits
                          total
                        </p>
                      ) : (
                        <p className="text-xs text-muted-foreground/70">
                          {totalCredits} credit{totalCredits === 1 ? '' : 's'} total
                        </p>
                      )}
                    </div>
                  )}
                </TableCell>
                <TableCell className="text-right font-mono font-medium tabular-nums">
                  {p.price_dollars}
                </TableCell>
                <TableCell className="text-right">
                  {p.implicit_discount_cents > 0 ? (
                    <span className="font-mono text-emerald-700 tabular-nums">
                      $
                      {(p.implicit_discount_cents / 100).toLocaleString(
                        undefined,
                        {
                          minimumFractionDigits: 2,
                          maximumFractionDigits: 2,
                        },
                      )}
                    </span>
                  ) : (
                    <span className="text-xs text-muted-foreground/70">—</span>
                  )}
                </TableCell>
                <TableCell className="text-xs text-muted-foreground tabular-nums">
                  {p.validity_days
                    ? `${p.validity_days} days`
                    : 'No expiration'}
                </TableCell>
                <TableCell>
                  {p.is_active ? (
                    <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 text-emerald-700 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider">
                      <span className="size-1.5 rounded-full bg-emerald-500" />
                      Active
                    </span>
                  ) : (
                    <span className="inline-flex items-center rounded-full bg-stone-100 text-stone-600 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider">
                      Inactive
                    </span>
                  )}
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}

function Stat({
  label,
  value,
  tone,
  isCurrency,
}: {
  label: string;
  value: number | string;
  tone?: 'emerald';
  isCurrency?: boolean;
}) {
  return (
    <div className="rounded-lg border bg-card px-5 py-4">
      <p className="text-[11px] uppercase tracking-wider text-muted-foreground font-medium">
        {label}
      </p>
      <p
        className={cn(
          'font-semibold tabular-nums leading-tight mt-1',
          isCurrency ? 'text-xl font-mono' : 'text-2xl',
          tone === 'emerald' && 'text-emerald-700',
        )}
      >
        {typeof value === 'number' ? value.toLocaleString() : value}
      </p>
    </div>
  );
}

function EmptyState({ canCreate }: { canCreate: boolean }) {
  return (
    <div className="rounded-lg border bg-card p-12 text-center">
      <div className="inline-flex size-12 items-center justify-center rounded-full bg-emerald-50 text-emerald-700 mb-4">
        <Layers className="size-6" />
      </div>
      <h3 className="font-serif text-xl font-semibold tracking-tight">
        No packages yet
      </h3>
      <p className="text-sm text-muted-foreground mt-2 max-w-md mx-auto leading-relaxed">
        Bundle services at a discount and sell them as a single line on a
        customer&rsquo;s invoice. Each visit they redeem a credit; the
        balance shows on their profile.
      </p>
      {canCreate ? (
        <Button render={<Link href="/catalog/packages/new" />} nativeButton={false} className="mt-6">
          <Plus className="size-4" />
          Create your first package
        </Button>
      ) : null}
    </div>
  );
}
