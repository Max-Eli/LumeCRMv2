/**
 * Client search input for the calendar workspace.
 *
 * Live-filters the customer list as the user types. Results dropdown surfaces
 * up to 8 matches; clicking one navigates to the client detail page in the
 * `(app)` shell. Escape clears the input; click-outside closes the dropdown.
 *
 * Design intent: this is the front desk's most-used affordance. Keep it
 * prominent (wide input), keyboard-friendly (Escape to clear, arrow keys to
 * navigate results — Phase 1C session 2 polish), and fast (debounced query).
 */

'use client';

import { Search, X } from 'lucide-react';
import { useRouter } from 'next/navigation';
import { useEffect, useRef, useState } from 'react';

import { InitialsAvatar } from '@/components/initials-avatar';
import { useCustomers } from '@/lib/customers';
import { cn } from '@/lib/utils';

const MAX_RESULTS = 8;

export function CalendarSearch() {
  const router = useRouter();
  const [value, setValue] = useState('');
  const [debounced, setDebounced] = useState('');
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  // Debounce the search query so we don't fetch on every keystroke.
  useEffect(() => {
    const id = setTimeout(() => setDebounced(value.trim()), 200);
    return () => clearTimeout(id);
  }, [value]);

  const { data: customers, isFetching } = useCustomers({ q: debounced });
  const results = (customers ?? []).slice(0, MAX_RESULTS);
  const showResults = open && debounced.length > 0;

  // Close on click outside.
  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (!containerRef.current?.contains(e.target as Node)) setOpen(false);
    };
    window.addEventListener('mousedown', onClick);
    return () => window.removeEventListener('mousedown', onClick);
  }, [open]);

  const choose = (id: number) => {
    setValue('');
    setDebounced('');
    setOpen(false);
    router.push(`/clients/${id}`);
  };

  return (
    <div ref={containerRef} className="relative w-full max-w-md">
      <Search className="size-4 absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground pointer-events-none" />
      <input
        type="text"
        value={value}
        onChange={(e) => {
          setValue(e.target.value);
          if (!open) setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={(e) => {
          if (e.key === 'Escape') {
            setValue('');
            setDebounced('');
            setOpen(false);
            (e.target as HTMLInputElement).blur();
          }
        }}
        placeholder="Search clients by name, email, or phone…"
        aria-label="Search clients"
        className="w-full h-9 rounded-md border bg-card pl-9 pr-9 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 placeholder:text-muted-foreground/70"
      />
      {value ? (
        <button
          type="button"
          onClick={() => {
            setValue('');
            setDebounced('');
          }}
          className="absolute right-2 top-1/2 -translate-y-1/2 inline-flex size-6 items-center justify-center rounded text-muted-foreground hover:bg-muted hover:text-foreground"
          aria-label="Clear search"
        >
          <X className="size-3.5" />
        </button>
      ) : null}

      {showResults ? (
        <div
          role="listbox"
          className="absolute left-0 right-0 mt-1 rounded-md border bg-popover shadow-lg z-30 overflow-hidden"
        >
          {isFetching && results.length === 0 ? (
            <p className="px-3 py-3 text-sm text-muted-foreground">Searching…</p>
          ) : results.length === 0 ? (
            <p className="px-3 py-3 text-sm text-muted-foreground">
              No clients match <span className="font-medium text-foreground">“{debounced}”</span>.
            </p>
          ) : (
            <ul className="max-h-80 overflow-y-auto py-1">
              {results.map((c) => (
                <li key={c.id}>
                  <button
                    type="button"
                    onClick={() => choose(c.id)}
                    role="option"
                    className={cn(
                      'w-full flex items-center gap-3 px-3 py-2 text-left',
                      'hover:bg-muted focus-visible:bg-muted outline-none',
                    )}
                  >
                    <InitialsAvatar name={c.full_name} size="sm" />
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium truncate">
                        {c.full_name || c.email || `Client #${c.id}`}
                      </p>
                      <p className="text-xs text-muted-foreground truncate">
                        {[c.email, c.phone].filter(Boolean).join(' · ') || 'No contact info'}
                      </p>
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          )}
          {results.length === MAX_RESULTS ? (
            <p className="px-3 py-2 text-[11px] uppercase tracking-wide text-muted-foreground border-t bg-muted/30">
              Showing first {MAX_RESULTS} matches — refine your search to narrow further.
            </p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
