'use client';

import { Plus, Search, Users } from 'lucide-react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useState } from 'react';

import { InitialsAvatar } from '@/components/initials-avatar';
import { PageHeader } from '@/components/page-header';
import { StatusBadge, customerStatusTone } from '@/components/status-badge';
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
import { useCustomers } from '@/lib/customers';

export default function ClientsListPage() {
  const router = useRouter();
  const [search, setSearch] = useState('');
  const { data: customers, isLoading, error } = useCustomers({ q: search });
  const count = customers?.length ?? 0;

  return (
    <div className="px-10 py-10">
      {/* Sticky header strip: page title + New client + search bar all
          stay pinned to the top while the table below scrolls. Critical
          now that real tenants carry thousands of customer rows —
          scrolling to row 4000 shouldn't bury the search input. */}
      <div className="sticky top-0 z-10 -mx-10 -mt-10 px-10 pt-10 pb-4 bg-background border-b border-border">
        <PageHeader
          title="Clients"
          description={
            isLoading
              ? 'Loading…'
              : `${count} ${count === 1 ? 'client' : 'clients'}${search ? ` matching “${search}”` : ''}`
          }
          actions={
            <Button render={<Link href="/clients/new" />} nativeButton={false}>
              <Plus className="size-4" />
              New client
            </Button>
          }
        />

        <div className="relative max-w-md mt-4">
          <Search className="size-4 absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground pointer-events-none" />
          <Input
            placeholder="Search by name, email, or phone…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-9"
          />
        </div>
      </div>

      {/* mt-6 spaces the content below the sticky header strip */}
      {error ? (
        <div className="mt-6 rounded-lg border border-destructive/40 bg-destructive/5 p-6 text-sm text-destructive">
          Failed to load clients. Try refreshing the page.
        </div>
      ) : isLoading ? (
        <div className="mt-6 rounded-lg border bg-card p-12 text-center text-sm text-muted-foreground">
          Loading clients…
        </div>
      ) : count === 0 ? (
        <div className="mt-6">
          <EmptyState search={search} />
        </div>
      ) : (
        <div className="mt-6 rounded-lg border bg-card overflow-hidden">
          <Table>
            <TableHeader>
              <TableRow className="bg-muted/30 hover:bg-muted/30">
                <TableHead className="w-[40%]">Name</TableHead>
                <TableHead>Contact</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Tags</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {customers!.map((c) => (
                <TableRow
                  key={c.id}
                  className="cursor-pointer"
                  onClick={() => router.push(`/clients/${c.id}`)}
                >
                  <TableCell className="font-medium py-3">
                    <div className="flex items-center gap-3">
                      <InitialsAvatar name={c.full_name} />
                      <div className="min-w-0">
                        <p className="font-medium truncate">{c.full_name || '(no name)'}</p>
                        {c.preferred_name ? (
                          <p className="text-xs text-muted-foreground truncate">
                            {c.first_name} {c.last_name}
                          </p>
                        ) : null}
                      </div>
                    </div>
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    <div className="space-y-0.5">
                      {c.email ? <p className="text-sm">{c.email}</p> : null}
                      {c.phone ? <p className="text-xs">{c.phone}</p> : null}
                      {!c.email && !c.phone ? <span>—</span> : null}
                    </div>
                  </TableCell>
                  <TableCell>
                    <StatusBadge tone={customerStatusTone(c.status)}>{c.status}</StatusBadge>
                  </TableCell>
                  <TableCell>
                    <div className="flex flex-wrap gap-1">
                      {c.tags.length === 0 ? (
                        <span className="text-xs text-muted-foreground/70">—</span>
                      ) : (
                        c.tags.map((t) => (
                          <Badge
                            key={t.id}
                            variant="outline"
                            style={{ borderColor: `${t.color}66`, color: t.color }}
                            className="font-normal"
                          >
                            {t.name}
                          </Badge>
                        ))
                      )}
                    </div>
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

function EmptyState({ search }: { search: string }) {
  if (search) {
    return (
      <div className="rounded-lg border bg-card p-12 text-center">
        <Search className="size-8 mx-auto text-muted-foreground/40 mb-3" />
        <p className="text-sm text-muted-foreground">
          No clients match <span className="font-medium text-foreground">“{search}”</span>.
        </p>
      </div>
    );
  }

  return (
    <div className="rounded-lg border bg-card p-12 text-center">
      <div className="inline-flex size-12 items-center justify-center rounded-full bg-accent/15 text-accent-foreground mb-4">
        <Users className="size-6" />
      </div>
      <h3 className="font-serif text-xl font-semibold tracking-tight">No clients yet</h3>
      <p className="text-sm text-muted-foreground mt-1.5 max-w-sm mx-auto">
        Add your first client to start booking appointments and tracking history.
      </p>
      <Button render={<Link href="/clients/new" />} nativeButton={false} className="mt-6">
        <Plus className="size-4" />
        Add first client
      </Button>
    </div>
  );
}
