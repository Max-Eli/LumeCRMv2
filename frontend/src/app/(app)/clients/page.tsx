'use client';

import { ChevronRight, Mail, Phone, Plus, Search, Users } from 'lucide-react';
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
import { type CustomerListItem, useCustomers } from '@/lib/customers';
import { useDebounce } from '@/lib/use-debounce';

export default function ClientsListPage() {
  const router = useRouter();
  const [search, setSearch] = useState('');
  // Debounce the search query — the input stays responsive while the
  // backend query only fires 250ms after the user stops typing. The
  // previous behaviour re-fetched on every keystroke and made the page
  // feel laggy on phones with weaker hardware.
  const debouncedSearch = useDebounce(search, 250);
  const { data: customers, isLoading, error } = useCustomers({ q: debouncedSearch });
  const count = customers?.length ?? 0;

  return (
    <div className="px-4 sm:px-10 py-4 sm:py-10">
      {/* Sticky header — title + search pinned so scrolling a long list
          doesn't bury them. Negative margins extend the band edge-to-edge
          (matching the page padding) so the white bg + border line up
          with the viewport, not the content column. */}
      <div className="sticky top-0 lg:top-0 z-10 -mx-4 sm:-mx-10 -mt-4 sm:-mt-10 px-4 sm:px-10 pt-4 sm:pt-10 pb-3 sm:pb-4 bg-background border-b border-border">
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
              <span className="hidden sm:inline">New client</span>
              <span className="sm:hidden">New</span>
            </Button>
          }
        />

        <div className="relative max-w-md mt-3 sm:mt-4">
          <Search className="size-4 absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground pointer-events-none" />
          <Input
            placeholder="Search by name, email, or phone…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-9"
          />
        </div>
      </div>

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
          <EmptyState search={debouncedSearch} />
        </div>
      ) : (
        <>
          {/* Mobile: card list (one row per client). The desktop table
              has 4 columns + tags chips which can't fit on a 375px
              screen without horizontal scroll. Cards drop tag chips
              (most users don't tag enough to fill the column anyway)
              and surface name + contact + status in a compact stack. */}
          <ul className="mt-4 sm:hidden divide-y rounded-lg border bg-card overflow-hidden">
            {customers!.map((c) => (
              <li key={c.id}>
                <ClientCard
                  customer={c}
                  onClick={() => router.push(`/clients/${c.id}`)}
                />
              </li>
            ))}
          </ul>

          {/* Desktop: full table */}
          <div className="hidden sm:block mt-6 rounded-lg border bg-card overflow-hidden">
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
        </>
      )}
    </div>
  );
}

function ClientCard({
  customer,
  onClick,
}: {
  customer: CustomerListItem;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="w-full text-left flex items-center gap-3 px-4 py-3 hover:bg-muted/40 active:bg-muted/60 transition-colors"
    >
      <InitialsAvatar name={customer.full_name} />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <p className="font-medium text-sm truncate">
            {customer.full_name || '(no name)'}
          </p>
          <StatusBadge tone={customerStatusTone(customer.status)} className="shrink-0">
            {customer.status}
          </StatusBadge>
        </div>
        <div className="flex items-center gap-3 text-xs text-muted-foreground mt-1 truncate">
          {customer.email ? (
            <span className="inline-flex items-center gap-1 truncate min-w-0">
              <Mail className="size-3 shrink-0" aria-hidden />
              <span className="truncate">{customer.email}</span>
            </span>
          ) : null}
          {customer.phone ? (
            <span className="inline-flex items-center gap-1 shrink-0">
              <Phone className="size-3" aria-hidden />
              {customer.phone}
            </span>
          ) : null}
          {!customer.email && !customer.phone ? <span>No contact info</span> : null}
        </div>
      </div>
      <ChevronRight className="size-4 text-muted-foreground/60 shrink-0" aria-hidden />
    </button>
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
