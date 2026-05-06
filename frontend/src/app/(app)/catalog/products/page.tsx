/**
 * `/catalog/products` — retail product catalog list.
 *
 * Stat strip + filter chips + searchable data table. Rows show
 * the SKU, name, category, price, on-hand stock (with low-stock
 * indicator), and active state. Click → detail/edit + stock-
 * adjustment surface.
 */

'use client';

import {
  AlertCircle,
  ListFilter,
  Package as PackageIcon,
  Plus,
  Search,
} from 'lucide-react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useMemo, useState } from 'react';

import { PageHeader } from '@/components/page-header';
import { Badge } from '@/components/ui/badge';
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
  type Product,
  useProductCategories,
  useProducts,
} from '@/lib/products';
import { cn } from '@/lib/utils';

type StateFilter = 'all' | 'active' | 'inactive' | 'low-stock';

export default function ProductsListPage() {
  const me = useCurrentMembership();
  const canEdit = me?.role === 'owner' || me?.role === 'manager';
  const router = useRouter();
  const [search, setSearch] = useState('');
  const [filter, setFilter] = useState<StateFilter>('all');
  const [categoryId, setCategoryId] = useState<number | null>(null);

  const { data: categories } = useProductCategories();
  const { data, isLoading, error } = useProducts({
    q: search,
    categoryId: categoryId ?? undefined,
    activeOnly:
      filter === 'active' ? true : filter === 'inactive' ? false : undefined,
    lowStockOnly: filter === 'low-stock',
  });

  // Stats off the unfiltered fetch so the strip stays stable while
  // filters change. Same endpoint, no filter — cheap.
  const all = useProducts();
  const products = data ?? [];
  const allRows = all.data ?? [];
  const activeCount = allRows.filter((p) => p.is_active).length;
  const lowStockCount = allRows.filter((p) => p.is_low_stock).length;
  const inventoryValueCents = useMemo(() => {
    const rows = all.data ?? [];
    return rows.reduce((s, p) => {
      if (!p.track_inventory) return s;
      return s + Math.max(0, p.stock_quantity) * p.price_cents;
    }, 0);
  }, [all.data]);

  return (
    <div className="px-8 py-8 space-y-6">
      <PageHeader
        title="Products"
        description="Retail items you sell over the counter — skincare, supplements, gift cards, intake fees."
        actions={
          canEdit ? (
            <Button render={<Link href="/catalog/products/new" />} nativeButton={false}>
              <Plus className="size-4" />
              New product
            </Button>
          ) : null
        }
      />

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Stat label="Total products" value={allRows.length} />
        <Stat label="Active" value={activeCount} tone="emerald" />
        <Stat
          label="Low stock"
          value={lowStockCount}
          tone={lowStockCount > 0 ? 'amber' : undefined}
        />
        <Stat
          label="Inventory value"
          value={`$${(inventoryValueCents / 100).toLocaleString(undefined, {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
          })}`}
          isCurrency
        />
      </div>

      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div className="flex items-center gap-3 flex-wrap">
          <div className="inline-flex items-center gap-0.5 rounded-md border bg-muted/40 p-0.5">
            {(['all', 'active', 'inactive', 'low-stock'] as const).map((f) => (
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
                {f === 'low-stock' ? 'Low stock' : f}
              </button>
            ))}
          </div>

          {categories && categories.length > 0 ? (
            <div className="flex items-center gap-1 flex-wrap">
              <button
                type="button"
                onClick={() => setCategoryId(null)}
                className={cn(
                  'inline-flex items-center gap-1.5 rounded-full px-2.5 h-7 text-xs transition-colors',
                  categoryId === null
                    ? 'bg-foreground text-background'
                    : 'bg-muted text-foreground/70 hover:bg-muted/80',
                )}
              >
                <ListFilter className="size-3" />
                All categories
              </button>
              {categories.map((c) => (
                <button
                  key={c.id}
                  type="button"
                  onClick={() => setCategoryId(categoryId === c.id ? null : c.id)}
                  className={cn(
                    'inline-flex items-center rounded-full px-2.5 h-7 text-xs transition-colors',
                    categoryId === c.id
                      ? 'bg-foreground text-background'
                      : 'bg-muted text-foreground/70 hover:bg-muted/80',
                  )}
                  style={
                    categoryId === c.id
                      ? undefined
                      : { borderLeft: `3px solid ${c.color}` }
                  }
                >
                  {c.name}
                </button>
              ))}
            </div>
          ) : null}
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
          Could not load products.
        </div>
      ) : isLoading ? (
        <div className="rounded-lg border bg-card p-12 text-center text-sm text-muted-foreground">
          Loading products…
        </div>
      ) : products.length === 0 ? (
        allRows.length === 0 ? (
          <EmptyState canCreate={canEdit} />
        ) : (
          <div className="rounded-lg border bg-card p-12 text-center">
            <Search className="size-8 mx-auto text-muted-foreground/40 mb-3" />
            <p className="text-sm text-muted-foreground">
              No products match the current filters.
            </p>
          </div>
        )
      ) : (
        <ProductsTable
          rows={products}
          onClick={(id) => router.push(`/catalog/products/${id}`)}
        />
      )}
    </div>
  );
}

function ProductsTable({
  rows,
  onClick,
}: {
  rows: Product[];
  onClick: (id: number) => void;
}) {
  return (
    <div className="rounded-lg border bg-card overflow-hidden">
      <Table>
        <TableHeader>
          <TableRow className="bg-muted/30 hover:bg-muted/30">
            <TableHead className="w-[110px]">SKU</TableHead>
            <TableHead className="w-[34%]">Product</TableHead>
            <TableHead>Category</TableHead>
            <TableHead className="text-right w-[110px]">Price</TableHead>
            <TableHead className="text-right w-[140px]">Stock</TableHead>
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
                  <div className="inline-flex size-8 items-center justify-center rounded-md bg-amber-50 text-amber-700 shrink-0">
                    <PackageIcon className="size-4" />
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
              <TableCell>
                {p.category ? (
                  <Badge
                    variant="outline"
                    style={{
                      borderColor: `${p.category.color}66`,
                      color: p.category.color,
                    }}
                    className="font-normal"
                  >
                    {p.category.name}
                  </Badge>
                ) : (
                  <span className="text-xs text-muted-foreground/70">—</span>
                )}
              </TableCell>
              <TableCell className="text-right font-mono font-medium tabular-nums">
                {p.price_dollars}
              </TableCell>
              <TableCell className="text-right">
                {p.track_inventory ? (
                  <div className="inline-flex items-center justify-end gap-2">
                    <span
                      className={cn(
                        'tabular-nums font-medium',
                        p.stock_quantity < 0 && 'text-red-700',
                        p.is_low_stock &&
                          p.stock_quantity >= 0 &&
                          'text-amber-700',
                      )}
                    >
                      {p.stock_quantity.toLocaleString()}
                    </span>
                    {p.is_low_stock ? (
                      <span
                        title={`At or below threshold (${p.low_stock_threshold})`}
                        className="inline-flex items-center"
                      >
                        <AlertCircle className="size-3.5 text-amber-600" />
                      </span>
                    ) : null}
                  </div>
                ) : (
                  <span className="text-xs text-muted-foreground/70">
                    Untracked
                  </span>
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
  isCurrency,
}: {
  label: string;
  value: number | string;
  tone?: 'amber' | 'emerald';
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
          tone === 'amber' && 'text-amber-700',
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
      <div className="inline-flex size-12 items-center justify-center rounded-full bg-amber-50 text-amber-700 mb-4">
        <PackageIcon className="size-6" />
      </div>
      <h3 className="font-serif text-xl font-semibold tracking-tight">
        No products yet
      </h3>
      <p className="text-sm text-muted-foreground mt-2 max-w-md mx-auto leading-relaxed">
        Add your first retail product to start tracking inventory and selling
        on customer invoices. Skincare, supplements, gift cards, intake
        fees &mdash; anything you ring up at the front desk.
      </p>
      {canCreate ? (
        <Button render={<Link href="/catalog/products/new" />} nativeButton={false} className="mt-6">
          <Plus className="size-4" />
          Add first product
        </Button>
      ) : null}
    </div>
  );
}
