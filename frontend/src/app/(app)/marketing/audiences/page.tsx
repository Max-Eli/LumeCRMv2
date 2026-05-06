/**
 * `/marketing/audiences` — list all saved customer segments.
 *
 * Stat strip + searchable, sortable data table. Each row shows
 * the name, description, last-known member count, lock status
 * (used in a campaign → read-only by ADR 0016), and last refresh
 * time. Click → detail/edit page.
 */

'use client';

import { Lock, Plus, Search, Users } from 'lucide-react';
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
import { canSendMarketing, useAudiences } from '@/lib/marketing';

export default function AudiencesListPage() {
  const me = useCurrentMembership();
  const canCreate = canSendMarketing(me?.role);
  const { data, isLoading, error } = useAudiences();
  const router = useRouter();
  const [search, setSearch] = useState('');

  const filtered = useMemo(() => {
    const list = data ?? [];
    const q = search.trim().toLowerCase();
    if (!q) return list;
    return list.filter(
      (a) =>
        a.name.toLowerCase().includes(q) ||
        a.description.toLowerCase().includes(q),
    );
  }, [data, search]);
  const audiences = data ?? [];

  const totalMembers = audiences.reduce((s, a) => s + a.last_member_count, 0);
  const lockedCount = audiences.filter((a) => a.is_used_in_campaign).length;

  return (
    <div className="px-8 py-8 space-y-6">
      <PageHeader
        title="Audiences"
        description="Saved customer segments. Build them once, reuse them across campaigns and automations."
        actions={
          canCreate ? (
            <Button render={<Link href="/marketing/audiences/new" />} nativeButton={false}>
              <Plus className="size-4" />
              New audience
            </Button>
          ) : null
        }
      />

      <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
        <Stat label="Total audiences" value={audiences.length} />
        <Stat label="Members across all" value={totalMembers} />
        <Stat label="Locked (in use)" value={lockedCount} />
      </div>

      <div className="relative max-w-md">
        <Search className="size-4 absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground pointer-events-none" />
        <Input
          placeholder="Search by name or description…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="pl-9"
        />
      </div>

      {error ? (
        <div className="rounded-lg border border-destructive/40 bg-destructive/5 p-6 text-sm text-destructive">
          Could not load audiences.
        </div>
      ) : isLoading ? (
        <div className="rounded-lg border bg-card p-12 text-center text-sm text-muted-foreground">
          Loading audiences…
        </div>
      ) : filtered.length === 0 ? (
        audiences.length === 0 ? (
          <EmptyState canCreate={canCreate} />
        ) : (
          <div className="rounded-lg border bg-card p-12 text-center">
            <Search className="size-8 mx-auto text-muted-foreground/40 mb-3" />
            <p className="text-sm text-muted-foreground">
              No audiences match &ldquo;{search}&rdquo;.
            </p>
          </div>
        )
      ) : (
        <div className="rounded-lg border bg-card overflow-hidden">
          <Table>
            <TableHeader>
              <TableRow className="bg-muted/30 hover:bg-muted/30">
                <TableHead className="w-[35%]">Name</TableHead>
                <TableHead>Description</TableHead>
                <TableHead className="text-right">Members</TableHead>
                <TableHead>Last refreshed</TableHead>
                <TableHead className="w-[120px]">State</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filtered.map((a) => (
                <TableRow
                  key={a.id}
                  className="cursor-pointer"
                  onClick={() => router.push(`/marketing/audiences/${a.id}`)}
                >
                  <TableCell className="py-3.5">
                    <div className="flex items-center gap-3">
                      <div className="inline-flex size-8 items-center justify-center rounded-md bg-blue-50 text-blue-700 shrink-0">
                        <Users className="size-4" />
                      </div>
                      <span className="font-medium truncate">{a.name}</span>
                    </div>
                  </TableCell>
                  <TableCell className="text-muted-foreground max-w-md">
                    {a.description ? (
                      <span className="block truncate">{a.description}</span>
                    ) : (
                      <span className="text-muted-foreground/60">—</span>
                    )}
                  </TableCell>
                  <TableCell className="text-right tabular-nums font-medium">
                    {a.last_member_count.toLocaleString()}
                  </TableCell>
                  <TableCell className="text-muted-foreground text-xs">
                    {a.last_counted_at
                      ? new Date(a.last_counted_at).toLocaleDateString()
                      : '—'}
                  </TableCell>
                  <TableCell>
                    {a.is_used_in_campaign ? (
                      <span className="inline-flex items-center gap-1 rounded-full bg-stone-100 text-stone-700 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider">
                        <Lock className="size-2.5" />
                        Locked
                      </span>
                    ) : (
                      <span className="inline-flex items-center rounded-full bg-emerald-50 text-emerald-700 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider">
                        Editable
                      </span>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg border bg-card px-5 py-4">
      <p className="text-[11px] uppercase tracking-wider text-muted-foreground font-medium">
        {label}
      </p>
      <p className="text-2xl font-semibold tabular-nums leading-tight mt-1">
        {value.toLocaleString()}
      </p>
    </div>
  );
}

function EmptyState({ canCreate }: { canCreate: boolean }) {
  return (
    <div className="rounded-lg border bg-card p-12 text-center">
      <div className="inline-flex size-12 items-center justify-center rounded-full bg-blue-50 text-blue-700 mb-4">
        <Users className="size-6" />
      </div>
      <h3 className="font-serif text-xl font-semibold tracking-tight">
        No audiences yet
      </h3>
      <p className="text-sm text-muted-foreground mt-2 max-w-md mx-auto leading-relaxed">
        Audiences are saved customer segments &mdash; birthday this month,
        no-visit-in-90-days, VIP-tagged, and so on. Build them once, reuse
        them across campaigns.
      </p>
      {canCreate ? (
        <Button render={<Link href="/marketing/audiences/new" />} nativeButton={false} className="mt-6">
          <Plus className="size-4" />
          Create your first audience
        </Button>
      ) : null}
    </div>
  );
}
