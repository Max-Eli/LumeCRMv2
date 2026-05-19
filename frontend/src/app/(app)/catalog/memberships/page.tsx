/**
 * `/catalog/memberships` — recurring-billing membership plan catalog.
 *
 * Stat strip + state filter + searchable data table. Each row shows
 * the SKU, name, included services summary, billing interval, price,
 * implicit discount vs. a-la-carte, and active status. Click → detail/edit.
 *
 * v1 ships without auto-recurring billing — operator manually
 * generates next-cycle invoices. The "Auto-renew" badge is a forward-
 * compat indicator that lights up when Phase 2A wires a processor.
 */

'use client';

import {
  CreditCard,
  Plus,
  Search,
} from 'lucide-react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useState } from 'react';

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
import {
  type MembershipPlan,
  BILLING_INTERVAL_LABELS,
  useMembershipPlans,
} from '@/lib/subscriptions';
import { useDebounce } from '@/lib/use-debounce';
import { cn } from '@/lib/utils';

type StateFilter = 'all' | 'active' | 'inactive';

export default function MembershipPlansListPage() {
  const me = useCurrentMembership();
  const canEdit = me?.role === 'owner' || me?.role === 'manager';
  const router = useRouter();
  const [search, setSearch] = useState('');
  const debouncedSearch = useDebounce(search, 250);
  const [filter, setFilter] = useState<StateFilter>('all');
  const { data, isLoading, error } = useMembershipPlans({
    q: debouncedSearch,
    activeOnly:
      filter === 'active' ? true : filter === 'inactive' ? false : undefined,
  });

  const all = useMembershipPlans();
  const allRows = all.data ?? [];
  const plans = data ?? [];
  const activeCount = allRows.filter((p) => p.is_active).length;
  const monthlyCount = allRows.filter(
    (p) => p.billing_interval === 'monthly',
  ).length;

  return (
    <div className="px-4 sm:px-8 py-4 sm:py-8 space-y-4 sm:space-y-6">
      <PageHeader
        title="Memberships"
        description="Recurring-billing plans for regular clients. Bundle services + member-only pricing into a monthly or annual rate."
        actions={
          canEdit ? (
            <Button render={<Link href="/catalog/memberships/new" />} nativeButton={false}>
              <Plus className="size-4" />
              New plan
            </Button>
          ) : null
        }
      />

      <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
        <Stat label="Total plans" value={allRows.length} />
        <Stat label="Active" value={activeCount} tone="emerald" />
        <Stat
          label="Monthly cycle"
          value={monthlyCount}
          sublabel={
            allRows.length === monthlyCount
              ? 'all plans bill monthly'
              : `${allRows.length - monthlyCount} annual`
          }
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
          Could not load membership plans.
        </div>
      ) : isLoading ? (
        <div className="rounded-lg border bg-card p-12 text-center text-sm text-muted-foreground">
          Loading plans…
        </div>
      ) : plans.length === 0 ? (
        allRows.length === 0 ? (
          <EmptyState canCreate={canEdit} />
        ) : (
          <div className="rounded-lg border bg-card p-12 text-center">
            <Search className="size-8 mx-auto text-muted-foreground/40 mb-3" />
            <p className="text-sm text-muted-foreground">
              No plans match the current filters.
            </p>
          </div>
        )
      ) : (
        <PlansTable
          rows={plans}
          onClick={(id) => router.push(`/catalog/memberships/${id}`)}
        />
      )}
    </div>
  );
}

function PlansTable({
  rows,
  onClick,
}: {
  rows: MembershipPlan[];
  onClick: (id: number) => void;
}) {
  return (
    <div className="rounded-lg border bg-card overflow-x-auto">
      <Table className="min-w-[720px]">
        <TableHeader>
          <TableRow className="bg-muted/30 hover:bg-muted/30">
            <TableHead className="w-[110px]">SKU</TableHead>
            <TableHead className="w-[26%]">Plan</TableHead>
            <TableHead>Includes</TableHead>
            <TableHead className="w-[110px]">Cycle</TableHead>
            <TableHead className="text-right w-[110px]">Price</TableHead>
            <TableHead className="text-right w-[140px]">Savings</TableHead>
            <TableHead className="w-[110px]">Status</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((p) => (
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
                  <div className="inline-flex size-8 items-center justify-center rounded-md bg-violet-50 text-violet-700 shrink-0">
                    <CreditCard className="size-4" />
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
                    No items
                  </span>
                ) : (
                  <div className="space-y-0.5">
                    {p.items.slice(0, 2).map((it) => (
                      <div key={it.id} className="truncate">
                        <span className="font-medium text-foreground">
                          {it.quantity_per_cycle}×
                        </span>{' '}
                        {it.service_name}
                        <span className="text-muted-foreground/70"> /cycle</span>
                      </div>
                    ))}
                    {p.items.length > 2 ? (
                      <p className="text-xs text-muted-foreground/70">
                        + {p.items.length - 2} more service{p.items.length - 2 === 1 ? '' : 's'}
                      </p>
                    ) : null}
                  </div>
                )}
              </TableCell>
              <TableCell>
                <span className="inline-flex items-center rounded-md bg-muted px-2 py-0.5 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
                  {BILLING_INTERVAL_LABELS[p.billing_interval]}
                </span>
              </TableCell>
              <TableCell className="text-right font-mono font-medium tabular-nums">
                {p.price_dollars}
                <span className="block text-[10px] text-muted-foreground/70 font-normal">
                  per {p.billing_interval === 'annual' ? 'year' : 'month'}
                </span>
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
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

function Stat({
  label,
  value,
  tone,
  sublabel,
}: {
  label: string;
  value: number | string;
  tone?: 'emerald';
  sublabel?: string;
}) {
  return (
    <div className="rounded-lg border bg-card px-5 py-4">
      <p className="text-[11px] uppercase tracking-wider text-muted-foreground font-medium">
        {label}
      </p>
      <p
        className={cn(
          'text-2xl font-semibold tabular-nums leading-tight mt-1',
          tone === 'emerald' && 'text-emerald-700',
        )}
      >
        {typeof value === 'number' ? value.toLocaleString() : value}
      </p>
      {sublabel ? (
        <p className="text-[11px] text-muted-foreground mt-0.5 truncate">
          {sublabel}
        </p>
      ) : null}
    </div>
  );
}

function EmptyState({ canCreate }: { canCreate: boolean }) {
  return (
    <div className="rounded-lg border bg-card p-12 text-center">
      <div className="inline-flex size-12 items-center justify-center rounded-full bg-violet-50 text-violet-700 mb-4">
        <CreditCard className="size-6" />
      </div>
      <h3 className="font-serif text-xl font-semibold tracking-tight">
        No membership plans yet
      </h3>
      <p className="text-sm text-muted-foreground mt-2 max-w-md mx-auto leading-relaxed">
        Bundle services into a recurring-billing plan and sell it on a
        customer&rsquo;s invoice. v1 supports manual monthly/annual
        billing &mdash; auto-charge wires up when a payment processor is
        added.
      </p>
      {canCreate ? (
        <Button render={<Link href="/catalog/memberships/new" />} nativeButton={false} className="mt-6">
          <Plus className="size-4" />
          Create your first plan
        </Button>
      ) : null}
    </div>
  );
}
