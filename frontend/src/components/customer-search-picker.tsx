/**
 * Shared customer search-and-pick step.
 *
 * A debounced search box over `/api/customers/?q=` with tappable
 * result rows. Used by any popout flow that starts with "which client
 * is this for?" — the build-package and new-sale popouts both reuse
 * it, so the search behaviour stays identical across them.
 */

'use client';

import { ArrowUpRight, Loader2, Search, UserRound } from 'lucide-react';
import { useEffect, useState } from 'react';

import { InitialsAvatar } from '@/components/initials-avatar';
import { Input } from '@/components/ui/input';
import { useCustomers, type CustomerListItem } from '@/lib/customers';

export function CustomerSearchPicker({
  onPick,
  title = 'Who is this for?',
  subtitle = 'Find the client to get started.',
}: {
  onPick: (customer: CustomerListItem) => void;
  /** Heading shown above the search box. */
  title?: string;
  /** Supporting line under the heading. */
  subtitle?: string;
}) {
  const [search, setSearch] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');

  useEffect(() => {
    const t = window.setTimeout(() => setDebouncedSearch(search.trim()), 200);
    return () => window.clearTimeout(t);
  }, [search]);

  const { data: customers, isFetching } = useCustomers({ q: debouncedSearch });
  const showResults = debouncedSearch.length >= 2;
  const results = showResults ? (customers ?? []) : [];

  return (
    <div className="max-w-xl mx-auto px-6 py-12 space-y-5">
      <div className="text-center space-y-2">
        <div
          className="size-12 mx-auto inline-flex items-center justify-center rounded-full bg-card border"
          aria-hidden
        >
          <UserRound className="size-5 text-muted-foreground" />
        </div>
        <h2 className="text-lg font-medium tracking-tight">{title}</h2>
        <p className="text-sm text-muted-foreground">{subtitle}</p>
      </div>

      <div className="relative">
        <Search className="size-4 absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground pointer-events-none" />
        <Input
          autoFocus
          placeholder="Search by name, email, or phone…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="pl-9"
        />
      </div>

      {!showResults ? (
        <p className="text-xs text-muted-foreground text-center">
          Start typing a client&apos;s name.
        </p>
      ) : isFetching && results.length === 0 ? (
        <div className="flex items-center justify-center py-4 text-muted-foreground">
          <Loader2 className="size-4 animate-spin" />
        </div>
      ) : results.length === 0 ? (
        <p className="text-sm text-muted-foreground text-center py-4">
          No clients matching “{debouncedSearch}”.
        </p>
      ) : (
        <ul className="rounded-xl border bg-card divide-y overflow-hidden">
          {results.map((c) => {
            const name = c.full_name || `${c.first_name} ${c.last_name}`;
            return (
              <li key={c.id}>
                <button
                  type="button"
                  onClick={() => onPick(c)}
                  className="w-full text-left px-4 py-3 hover:bg-muted transition-colors flex items-center gap-3"
                >
                  <InitialsAvatar name={name} size="sm" />
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium truncate">{name}</p>
                    <p className="text-xs text-muted-foreground truncate">
                      {c.email || c.phone || 'No contact'}
                    </p>
                  </div>
                  <ArrowUpRight className="size-3.5 text-muted-foreground/60 shrink-0" />
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
