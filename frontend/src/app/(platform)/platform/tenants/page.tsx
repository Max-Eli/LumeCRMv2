/**
 * `/platform/tenants` — list of every customer tenant on Lumè.
 *
 * Search filters by name + slug + owner email. Click a row → tenant
 * detail. Status chips use the dark-theme tones from
 * `lib/platform.STATUS_TONE`.
 */

'use client';

import { Plus, Search } from 'lucide-react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useMemo, useState } from 'react';

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
  STATUS_LABELS,
  STATUS_TONE,
  type PlatformTenantListItem,
  type PlatformTenantStatus,
  usePlatformTenants,
} from '@/lib/platform';
import { cn } from '@/lib/utils';

export default function PlatformTenantsListPage() {
  const router = useRouter();
  const { data: tenants, isLoading, error } = usePlatformTenants();
  const [search, setSearch] = useState('');

  const filtered = useMemo(() => {
    if (!tenants) return [];
    const q = search.trim().toLowerCase();
    if (!q) return tenants;
    return tenants.filter(
      (t) =>
        t.name.toLowerCase().includes(q) ||
        t.slug.toLowerCase().includes(q) ||
        (t.owner_email ?? '').toLowerCase().includes(q),
    );
  }, [tenants, search]);

  return (
    <div className="px-10 py-10 max-w-7xl">
      <header className="flex flex-wrap items-end justify-between gap-4 mb-8">
        <div>
          <p className="text-[11px] uppercase tracking-[0.16em] text-muted-foreground">
            Platform Admin
          </p>
          <h1 className="mt-2 font-serif text-3xl font-semibold tracking-tight text-foreground">
            Tenants
          </h1>
          <p className="mt-2 text-sm text-muted-foreground">
            {isLoading
              ? 'Loading…'
              : `${tenants?.length ?? 0} customer ${(tenants?.length ?? 0) === 1 ? 'tenant' : 'tenants'} on Lumè`}
          </p>
        </div>
        <Link
          href="/platform/tenants/new"
          className="inline-flex h-10 items-center gap-2 rounded-md bg-foreground px-4 text-sm font-medium text-background hover:bg-foreground/90 transition-colors"
        >
          <Plus className="size-4" />
          New tenant
        </Link>
      </header>

      <div className="relative max-w-md mb-6">
        <Search className="size-4 absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground pointer-events-none" />
        <Input
          placeholder="Search by name, slug, or owner email…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="pl-9"
        />
      </div>

      {error ? (
        <div className="rounded-lg border border-destructive/40 bg-destructive/10 p-6 text-sm text-destructive">
          Failed to load tenants.
        </div>
      ) : isLoading ? (
        <div className="rounded-lg border bg-card p-12 text-center text-sm text-muted-foreground">
          Loading…
        </div>
      ) : filtered.length === 0 ? (
        <div className="rounded-lg border bg-card p-12 text-center text-sm text-muted-foreground">
          {search ? 'No tenants match.' : 'No tenants yet.'}
        </div>
      ) : (
        <div className="rounded-lg border bg-card overflow-hidden">
          <Table>
            <TableHeader>
              <TableRow className="bg-muted/30 hover:bg-muted/30">
                <TableHead className="w-[35%]">Tenant</TableHead>
                <TableHead>Owner</TableHead>
                <TableHead className="w-[120px]">Status</TableHead>
                <TableHead className="w-[100px] text-right">Members</TableHead>
                <TableHead className="w-[120px]">Signed up</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filtered.map((t) => (
                <TenantRow
                  key={t.slug}
                  tenant={t}
                  onClick={() => router.push(`/platform/tenants/${t.slug}`)}
                />
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}

function TenantRow({
  tenant,
  onClick,
}: {
  tenant: PlatformTenantListItem;
  onClick: () => void;
}) {
  return (
    <TableRow className="cursor-pointer" onClick={onClick}>
      <TableCell className="py-3">
        <div className="min-w-0">
          <p className="font-medium text-foreground truncate">{tenant.name}</p>
          <p className="text-xs text-muted-foreground font-mono truncate">
            {tenant.slug}.lumecrm.com
          </p>
        </div>
      </TableCell>
      <TableCell className="text-foreground/80 text-sm truncate max-w-[260px]">
        {tenant.owner_email ?? '—'}
      </TableCell>
      <TableCell>
        <StatusPill status={tenant.status} />
      </TableCell>
      <TableCell className="text-right tabular-nums text-foreground/80">
        {tenant.member_count}
      </TableCell>
      <TableCell className="text-muted-foreground tabular-nums">
        {formatDate(tenant.created_at)}
      </TableCell>
    </TableRow>
  );
}

function StatusPill({ status }: { status: PlatformTenantStatus }) {
  return (
    <span
      className={cn(
        'inline-flex items-center h-5 px-2 rounded text-[10px] uppercase tracking-wide font-medium ring-1',
        STATUS_TONE[status],
      )}
    >
      {STATUS_LABELS[status]}
    </span>
  );
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });
}
