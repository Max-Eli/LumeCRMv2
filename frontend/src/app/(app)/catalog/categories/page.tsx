/**
 * `/catalog/categories` — service categories management surface.
 *
 * Same Table-based layout as `/catalog/services` for visual
 * consistency. The page is the management surface for category
 * records themselves (name, color, eligibility) — clicking a row
 * opens the category's edit page. To browse services within a
 * category, use the Services page; the Category column there is
 * filterable.
 */

'use client';

import { Plus, Search, Sparkles } from 'lucide-react';
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
import {
  type ServiceCategory,
  useServiceCategories,
} from '@/lib/services';

export default function CategoriesPage() {
  const router = useRouter();
  const [search, setSearch] = useState('');
  const { data: categories, isLoading, error } = useServiceCategories();

  const filtered = useMemo(() => {
    if (!categories) return [];
    const q = search.trim().toLowerCase();
    if (!q) return categories;
    return categories.filter((c) => c.name.toLowerCase().includes(q));
  }, [categories, search]);

  const totalCount = categories?.length ?? 0;
  const visibleCount = filtered.length;

  return (
    <div className="px-10 py-10 max-w-7xl">
      <PageHeader
        title="Categories"
        description={
          isLoading
            ? 'Loading categories…'
            : `${totalCount} ${totalCount === 1 ? 'category' : 'categories'} · click a row to edit`
        }
        actions={
          <Button render={<Link href="/catalog/categories/new" />} nativeButton={false}>
            <Plus className="size-4" />
            New category
          </Button>
        }
      />

      <div className="relative max-w-md mb-6">
        <Search className="size-4 absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground pointer-events-none" />
        <Input
          placeholder="Search categories by name…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="pl-9"
        />
      </div>

      {error ? (
        <div className="rounded-lg border border-destructive/40 bg-destructive/5 p-6 text-sm text-destructive">
          Failed to load categories.
        </div>
      ) : isLoading ? (
        <div className="rounded-lg border bg-card p-12 text-center text-sm text-muted-foreground">
          Loading…
        </div>
      ) : totalCount === 0 ? (
        <EmptyCategoriesState />
      ) : visibleCount === 0 ? (
        <div className="rounded-lg border bg-card p-12 text-center text-sm text-muted-foreground">
          No categories match.
        </div>
      ) : (
        <CategoriesTable
          categories={filtered}
          onRowClick={(id) => router.push(`/catalog/categories/${id}`)}
        />
      )}
    </div>
  );
}

function CategoriesTable({
  categories,
  onRowClick,
}: {
  categories: ServiceCategory[];
  onRowClick: (id: number) => void;
}) {
  return (
    <div className="rounded-lg border bg-card overflow-hidden">
      <Table>
        <TableHeader>
          <TableRow className="bg-muted/30 hover:bg-muted/30">
            <TableHead className="w-[40%]">Category</TableHead>
            <TableHead className="w-[120px] text-right">Services</TableHead>
            <TableHead>Performed by</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {categories.map((cat) => (
            <CategoryRow key={cat.id} category={cat} onClick={() => onRowClick(cat.id)} />
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

function CategoryRow({
  category,
  onClick,
}: {
  category: ServiceCategory;
  onClick: () => void;
}) {
  const eligibility = category.eligible_job_titles;
  const eligibilityText =
    eligibility.length === 0
      ? 'Anyone bookable'
      : eligibility.length <= 4
        ? eligibility.map((jt) => jt.name).join(', ')
        : `${eligibility.slice(0, 3).map((jt) => jt.name).join(', ')} +${eligibility.length - 3} more`;

  return (
    <TableRow className="cursor-pointer" onClick={onClick}>
      <TableCell className="py-3">
        <Badge
          variant="outline"
          style={{
            borderColor: `${category.color}66`,
            color: category.color,
          }}
          className="font-medium"
        >
          {category.name}
        </Badge>
      </TableCell>
      <TableCell className="text-right tabular-nums text-muted-foreground">
        {category.service_count}
      </TableCell>
      <TableCell
        className={
          eligibility.length === 0
            ? 'text-muted-foreground italic'
            : 'text-foreground/80'
        }
      >
        <span className="truncate inline-block max-w-md align-bottom" title={eligibility.map((jt) => jt.name).join(', ')}>
          {eligibilityText}
        </span>
      </TableCell>
    </TableRow>
  );
}

function EmptyCategoriesState() {
  return (
    <div className="rounded-lg border bg-card p-12 text-center">
      <div className="inline-flex size-12 items-center justify-center rounded-full bg-accent/15 text-accent-foreground mb-4">
        <Sparkles className="size-6" />
      </div>
      <h3 className="font-serif text-xl font-semibold tracking-tight">No categories yet</h3>
      <p className="text-sm text-muted-foreground mt-1.5 max-w-sm mx-auto">
        Categories group services and define which staff can perform them.
      </p>
      <Button
        render={<Link href="/catalog/categories/new" />}
        nativeButton={false}
        className="mt-6"
      >
        <Plus className="size-4" />
        Create first category
      </Button>
    </div>
  );
}
