/**
 * `/catalog/services` — flat list of every service the spa offers.
 *
 * Optional `?category=<id>` filter narrows to a single category and
 * shows the eligibility summary (which job titles are allowed to
 * perform services in this category) up top — useful for the
 * front desk understanding why a particular provider can't be
 * booked for a given service.
 *
 * Unfiltered, the page shows every service across every category in
 * a single sortable table with category-color badges. Search filters
 * by name + description.
 */

'use client';

import {
  ListFilter,
  Plus,
  Search,
  Settings2,
  Users as UsersIcon,
} from 'lucide-react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { useState } from 'react';

import { PageHeader } from '@/components/page-header';
import { StatusBadge } from '@/components/status-badge';
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
  useServices,
} from '@/lib/services';

interface ServiceRow {
  id: number;
  name: string;
  description: string;
  category: ServiceCategorySummaryRef | null;
  duration_minutes: number;
  buffer_minutes: number;
  price_dollars: string;
  is_active: boolean;
  is_bookable_online: boolean;
}

interface ServiceCategorySummaryRef {
  id: number;
  name: string;
  color: string;
}

export default function ServicesListPage() {
  const params = useSearchParams();
  const categoryParam = params.get('category');
  if (categoryParam) {
    return <CategoryServicesView categoryId={Number(categoryParam)} />;
  }
  return <AllServicesView />;
}

// ── Default: flat list of every service ────────────────────────────────

function AllServicesView() {
  const router = useRouter();
  const [search, setSearch] = useState('');
  const { data: services, isLoading } = useServices({ q: search });
  const count = services?.length ?? 0;

  return (
    <div className="px-10 py-10 max-w-7xl">
      <PageHeader
        title="Services"
        description={`${count} service${count === 1 ? '' : 's'} across every category`}
        actions={
          <>
            <Button render={<Link href="/catalog/categories" />} nativeButton={false} variant="outline">
              <ListFilter className="size-4" />
              Browse by category
            </Button>
            <Button render={<Link href="/catalog/services/new" />} nativeButton={false}>
              <Plus className="size-4" />
              New service
            </Button>
          </>
        }
      />

      <div className="relative max-w-md mb-6">
        <Search className="size-4 absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground pointer-events-none" />
        <Input
          placeholder="Search by name or description…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="pl-9"
        />
      </div>

      {isLoading ? (
        <div className="rounded-lg border bg-card p-12 text-center text-sm text-muted-foreground">
          Loading…
        </div>
      ) : count === 0 ? (
        <div className="rounded-lg border bg-card p-12 text-center text-sm text-muted-foreground">
          No services yet.
        </div>
      ) : (
        <ServicesTable
          services={services as ServiceRow[]}
          onRowClick={(id) => router.push(`/catalog/services/${id}`)}
        />
      )}
    </div>
  );
}

// ── Filtered: services in one category ─────────────────────────────────

function CategoryServicesView({ categoryId }: { categoryId: number }) {
  const router = useRouter();
  const [search, setSearch] = useState('');
  const { data: categories } = useServiceCategories();
  const category = categories?.find((c) => c.id === categoryId);
  const { data: services, isLoading } = useServices({ q: search, categoryId });
  const count = services?.length ?? 0;

  return (
    <div className="px-10 py-10 max-w-7xl">
      <PageHeader
        title={category?.name ?? 'Category'}
        description={category ? `${category.service_count} services in this category` : ''}
        back={{ href: '/catalog/services', label: 'All services' }}
        actions={
          <>
            <Button
              render={<Link href={`/catalog/categories/${categoryId}`} />}
              nativeButton={false}
              variant="outline"
            >
              <Settings2 className="size-4" />
              Edit category
            </Button>
            <Button render={<Link href="/catalog/services/new" />} nativeButton={false}>
              <Plus className="size-4" />
              New service
            </Button>
          </>
        }
      />

      {category ? <EligibilitySummary category={category} /> : null}

      <div className="relative max-w-md mb-6">
        <Search className="size-4 absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground pointer-events-none" />
        <Input
          placeholder="Search services in this category…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="pl-9"
        />
      </div>

      {isLoading ? (
        <div className="rounded-lg border bg-card p-12 text-center text-sm text-muted-foreground">
          Loading…
        </div>
      ) : count === 0 ? (
        <div className="rounded-lg border bg-card p-12 text-center">
          <p className="text-sm text-muted-foreground">
            {search ? 'No services match.' : 'No services in this category yet.'}
          </p>
        </div>
      ) : (
        <ServicesTable
          services={services as ServiceRow[]}
          onRowClick={(id) => router.push(`/catalog/services/${id}`)}
        />
      )}
    </div>
  );
}

function EligibilitySummary({ category }: { category: ServiceCategory }) {
  const eligibility = category.eligible_job_titles;
  return (
    <div className="rounded-lg border bg-muted/30 p-4 mb-6">
      <div className="flex items-start gap-3">
        <UsersIcon className="size-4 text-muted-foreground mt-0.5 shrink-0" />
        <div className="min-w-0 flex-1">
          <p className="text-xs uppercase tracking-wide text-muted-foreground">
            Eligible to perform
          </p>
          {eligibility.length === 0 ? (
            <p className="text-sm text-muted-foreground italic mt-1">
              No restriction — anyone bookable in the tenant can perform these services.
            </p>
          ) : (
            <div className="flex flex-wrap gap-1.5 mt-2">
              {eligibility.map((jt) => (
                <Badge key={jt.id} variant="outline" className="font-normal">
                  {jt.name}
                  {jt.is_clinical ? (
                    <span className="ml-1 text-accent" title="Clinical">·</span>
                  ) : null}
                </Badge>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Shared table ───────────────────────────────────────────────────────

function ServicesTable({
  services,
  onRowClick,
}: {
  services: ServiceRow[];
  onRowClick: (id: number) => void;
}) {
  return (
    <div className="rounded-lg border bg-card overflow-hidden">
      <Table>
        <TableHeader>
          <TableRow className="bg-muted/30 hover:bg-muted/30">
            <TableHead className="w-[40%]">Service</TableHead>
            <TableHead>Category</TableHead>
            <TableHead className="w-[100px]">Duration</TableHead>
            <TableHead className="w-[120px] text-right">Price</TableHead>
            <TableHead className="w-[160px]">Status</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {services.map((s) => (
            <TableRow key={s.id} className="cursor-pointer" onClick={() => onRowClick(s.id)}>
              <TableCell className="font-medium py-3">
                <div>
                  <p className="font-medium">{s.name}</p>
                  {s.description ? (
                    <p className="text-xs text-muted-foreground mt-0.5 truncate max-w-md">
                      {s.description}
                    </p>
                  ) : null}
                </div>
              </TableCell>
              <TableCell>
                {s.category ? (
                  <Badge
                    variant="outline"
                    style={{ borderColor: `${s.category.color}66`, color: s.category.color }}
                    className="font-normal"
                  >
                    {s.category.name}
                  </Badge>
                ) : (
                  <span className="text-xs text-muted-foreground/70">—</span>
                )}
              </TableCell>
              <TableCell className="text-muted-foreground tabular-nums">
                {s.duration_minutes}m
                {s.buffer_minutes > 0 ? (
                  <span className="text-xs text-muted-foreground/60 ml-1">+{s.buffer_minutes}</span>
                ) : null}
              </TableCell>
              <TableCell className="text-right font-mono font-medium tabular-nums">
                {s.price_dollars}
              </TableCell>
              <TableCell>
                <div className="flex items-center gap-2">
                  <StatusBadge tone={s.is_active ? 'success' : 'neutral'}>
                    {s.is_active ? 'active' : 'inactive'}
                  </StatusBadge>
                  {!s.is_bookable_online ? (
                    <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
                      Phone only
                    </span>
                  ) : null}
                </div>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
