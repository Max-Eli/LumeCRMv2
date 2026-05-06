/**
 * Functional tool panel — quick service price lookup.
 *
 * Front desk's "what does X cost?" affordance during phone calls and walk-ins.
 * Type any service / category / code → live results with price + duration +
 * tax-aware total. Uses the existing `useServices` API with the standard
 * `?q=` filter.
 *
 * Memberships and products land here in later phases (2C / 2A); for now the
 * panel only covers services.
 */

'use client';

import { Receipt, Search } from 'lucide-react';
import Link from 'next/link';
import { useEffect, useState } from 'react';

import { Badge } from '@/components/ui/badge';
import { useServices } from '@/lib/services';

export function PriceCheckPanel() {
  const [value, setValue] = useState('');
  const [debounced, setDebounced] = useState('');

  useEffect(() => {
    const id = setTimeout(() => setDebounced(value.trim()), 200);
    return () => clearTimeout(id);
  }, [value]);

  const { data: services, isFetching } = useServices({
    q: debounced,
    activeOnly: true,
  });
  const results = (services ?? []).slice(0, 25);

  return (
    <div className="flex flex-col h-full">
      <div className="p-4 border-b">
        <p className="text-xs text-muted-foreground mb-2">
          Search by name, code, or category. Returns active services.
        </p>
        <div className="relative">
          <Search className="size-4 absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground pointer-events-none" />
          <input
            type="text"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder="Botox, BTX20, facial…"
            aria-label="Search services for price check"
            autoFocus
            className="w-full h-9 rounded-md border bg-background pl-9 pr-3 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
          />
        </div>
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto">
        {!debounced ? (
          <EmptyHint />
        ) : isFetching && results.length === 0 ? (
          <p className="px-4 py-3 text-sm text-muted-foreground">Searching…</p>
        ) : results.length === 0 ? (
          <p className="px-4 py-3 text-sm text-muted-foreground">
            No services match <span className="font-medium text-foreground">“{debounced}”</span>.
          </p>
        ) : (
          <ul className="divide-y">
            {results.map((s) => {
              const tax = Number(s.tax_rate_percent || 0);
              const total = s.price_cents * (1 + tax / 100);
              return (
                <li key={s.id}>
                  <Link
                    href={`/services/${s.id}`}
                    className="block px-4 py-3 hover:bg-muted/50 transition-colors"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0 flex-1">
                        <p className="font-medium text-sm truncate">{s.name}</p>
                        <div className="flex items-center gap-2 mt-1">
                          <code className="text-[11px] font-mono text-muted-foreground tracking-wider">
                            {s.code}
                          </code>
                          {s.category ? (
                            <Badge
                              variant="outline"
                              className="font-normal text-[10px] py-0"
                              style={{
                                borderColor: `${s.category.color}66`,
                                color: s.category.color,
                              }}
                            >
                              {s.category.name}
                            </Badge>
                          ) : null}
                          <span className="text-[11px] text-muted-foreground tabular-nums">
                            {s.duration_minutes}m
                          </span>
                        </div>
                      </div>
                      <div className="text-right shrink-0">
                        <p className="font-mono text-sm font-semibold tabular-nums">
                          {s.price_dollars}
                        </p>
                        {tax > 0 ? (
                          <p className="text-[11px] text-muted-foreground tabular-nums">
                            +{tax.toFixed(3)}% tax · ${(total / 100).toFixed(2)}
                          </p>
                        ) : (
                          <p className="text-[11px] text-muted-foreground/70">No tax</p>
                        )}
                      </div>
                    </div>
                  </Link>
                </li>
              );
            })}
          </ul>
        )}
      </div>

      <footer className="shrink-0 px-4 py-3 border-t text-[11px] text-muted-foreground">
        Memberships and retail products land in this panel in Phases 2C and 2A.
      </footer>
    </div>
  );
}

function EmptyHint() {
  return (
    <div className="px-4 py-12 text-center">
      <div className="inline-flex size-10 items-center justify-center rounded-full bg-muted text-muted-foreground mb-3">
        <Receipt className="size-4" />
      </div>
      <p className="text-sm text-muted-foreground">
        Start typing to look up service prices.
      </p>
    </div>
  );
}
