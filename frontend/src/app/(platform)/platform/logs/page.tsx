/**
 * `/platform/logs` — cross-tenant audit log search.
 *
 * Every action on every tenant (CRUD on PHI, logins, exports,
 * permission grants, etc.) goes through `apps.audit.services.record()`
 * on the backend and lands in `AuditLog`. This page lets the
 * platform operator search that flat firehose by tenant, user,
 * action type, and free-text — primary use case is support ("who
 * deleted customer 12345 in tenant Acme at 3pm?").
 *
 * Layout:
 *   - Sticky header (title + sub-description + search input)
 *   - Filter row (tenant chips + action chips)
 *   - Result feed, infinite-scroll style: load 50 at a time, "Load
 *     more" button at the bottom that paginates via opaque cursors
 *   - Row expand → full JSON metadata view
 *
 * Mobile: same layout, narrower padding, single-column card per
 * audit entry instead of dense rows.
 */

'use client';

import {
  ChevronDown,
  ChevronUp,
  Filter,
  ScrollText,
  Search,
  X,
} from 'lucide-react';
import { useMemo, useState } from 'react';

import { Input } from '@/components/ui/input';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';
import {
  AUDIT_ACTION_LABELS,
  AUDIT_ACTION_TONE,
  type AuditAction,
  type AuditEntry,
  type AuditLogFilters,
  usePlatformAuditLog,
  usePlatformTenants,
} from '@/lib/platform';
import { cn } from '@/lib/utils';

const ALL_ACTIONS: AuditAction[] = [
  'create',
  'read',
  'update',
  'delete',
  'login',
  'logout',
  'login_failed',
  'export',
  'permission_granted',
  'permission_revoked',
];

export default function PlatformLogsPage() {
  const [search, setSearch] = useState('');
  const [tenantFilter, setTenantFilter] = useState<string[]>([]);
  const [actionFilter, setActionFilter] = useState<AuditAction[]>([]);

  // Debounce-lite: the filters object is what the query depends on,
  // so a typing-fast operator triggers refetches at each keystroke
  // — fine because the API is cheap, but we let TanStack's request
  // dedupe handle the rest.
  const filters: AuditLogFilters = useMemo(
    () => ({
      q: search.trim() || undefined,
      tenant: tenantFilter.length ? tenantFilter : undefined,
      action: actionFilter.length ? actionFilter : undefined,
      limit: 50,
    }),
    [search, tenantFilter, actionFilter],
  );

  const { data: tenants } = usePlatformTenants();
  const {
    data,
    isLoading,
    isFetchingNextPage,
    fetchNextPage,
    hasNextPage,
    error,
  } = usePlatformAuditLog(filters);

  const entries: AuditEntry[] = useMemo(
    () => data?.pages.flatMap((p: { results: AuditEntry[] }) => p.results) ?? [],
    [data],
  );

  const activeFilterCount =
    (search.trim() ? 1 : 0) + tenantFilter.length + actionFilter.length;

  const resetFilters = () => {
    setSearch('');
    setTenantFilter([]);
    setActionFilter([]);
  };

  return (
    <div className="px-4 sm:px-8 lg:px-10 py-6 sm:py-10">
      {/* ─── Sticky header ────────────────────────────────────────── */}
      <div className="sticky top-0 z-10 -mx-4 sm:-mx-8 lg:-mx-10 -mt-6 sm:-mt-10 px-4 sm:px-8 lg:px-10 pt-6 sm:pt-10 pb-4 bg-background border-b border-border">
        <header>
          <p className="text-[11px] uppercase tracking-[0.16em] text-muted-foreground">
            Platform Admin
          </p>
          <h1 className="mt-2 font-serif text-2xl sm:text-3xl font-semibold tracking-tight text-foreground">
            Audit log
          </h1>
          <p className="mt-2 text-sm text-muted-foreground">
            Every PHI read + write across every tenant. Append-only
            and searchable; supports "who did what when" investigations
            in seconds.
          </p>
        </header>

        <div className="relative mt-4 max-w-2xl">
          <Search
            className="size-4 absolute left-3.5 top-1/2 -translate-y-1/2 text-muted-foreground pointer-events-none"
            aria-hidden
          />
          <Input
            placeholder="Search by resource, user email, tenant…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-10 h-11"
          />
        </div>
      </div>

      {/* ─── Filter row ───────────────────────────────────────────── */}
      <div className="mt-6 flex flex-wrap items-center gap-2">
        <TenantFilter
          tenants={(tenants ?? []).map((t) => ({ slug: t.slug, name: t.name }))}
          value={tenantFilter}
          onChange={setTenantFilter}
        />
        <ActionFilter value={actionFilter} onChange={setActionFilter} />
        {activeFilterCount > 0 ? (
          <button
            type="button"
            onClick={resetFilters}
            className="inline-flex items-center gap-1.5 h-8 px-3 rounded-full border border-border bg-card text-xs text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
          >
            <X className="size-3.5" />
            Reset
          </button>
        ) : null}
        <div className="ml-auto text-xs text-muted-foreground tabular-nums">
          {isLoading
            ? 'Loading…'
            : `${entries.length} ${entries.length === 1 ? 'entry' : 'entries'}${hasNextPage ? '+' : ''}`}
        </div>
      </div>

      {/* ─── Result feed ──────────────────────────────────────────── */}
      <div className="mt-4">
        {error ? (
          <div className="rounded-lg border border-destructive/40 bg-destructive/10 p-6 text-sm text-destructive">
            Failed to load audit log.
          </div>
        ) : isLoading ? (
          <SkeletonFeed />
        ) : entries.length === 0 ? (
          <EmptyState />
        ) : (
          <ul className="rounded-lg border bg-card divide-y overflow-hidden">
            {entries.map((entry) => (
              <li key={entry.id}>
                <AuditRow entry={entry} />
              </li>
            ))}
          </ul>
        )}

        {hasNextPage ? (
          <div className="mt-4 flex justify-center">
            <button
              type="button"
              onClick={() => fetchNextPage()}
              disabled={isFetchingNextPage}
              className="inline-flex h-9 items-center gap-2 px-4 rounded-md border border-border bg-card text-sm font-medium text-foreground hover:bg-muted transition-colors disabled:opacity-50"
            >
              {isFetchingNextPage ? 'Loading…' : 'Load more'}
            </button>
          </div>
        ) : null}
      </div>
    </div>
  );
}

// ── Tenant filter (multi-select popover) ───────────────────────────

function TenantFilter({
  tenants,
  value,
  onChange,
}: {
  tenants: { slug: string; name: string }[];
  value: string[];
  onChange: (next: string[]) => void;
}) {
  const selected = new Set(value);
  const label =
    selected.size === 0
      ? 'All tenants'
      : selected.size === 1
        ? tenants.find((t) => t.slug === [...selected][0])?.name ?? '1 tenant'
        : `${selected.size} tenants`;

  const toggle = (slug: string) => {
    const next = new Set(selected);
    if (next.has(slug)) next.delete(slug);
    else next.add(slug);
    onChange([...next]);
  };

  return (
    <Popover>
      <PopoverTrigger
        render={(props) => (
          <button
            {...props}
            type="button"
            className="inline-flex items-center gap-1.5 h-8 px-3 rounded-full border border-border bg-card text-xs font-medium text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
          >
            <Filter className="size-3.5" />
            <span>{label}</span>
            <ChevronDown className="size-3" />
          </button>
        )}
      />
      <PopoverContent align="start" className="w-64 p-1.5">
        <div className="max-h-64 overflow-y-auto">
          {tenants.length === 0 ? (
            <p className="px-2 py-2 text-xs text-muted-foreground">
              No tenants.
            </p>
          ) : (
            tenants.map((t) => {
              const checked = selected.has(t.slug);
              return (
                <button
                  key={t.slug}
                  type="button"
                  onClick={() => toggle(t.slug)}
                  className={cn(
                    'w-full flex items-center justify-between gap-2 px-2 py-1.5 rounded text-sm hover:bg-muted',
                    checked && 'text-foreground font-medium',
                  )}
                >
                  <span className="truncate">{t.name}</span>
                  {checked ? <span className="text-xs">✓</span> : null}
                </button>
              );
            })
          )}
        </div>
      </PopoverContent>
    </Popover>
  );
}

// ── Action filter (multi-select popover) ───────────────────────────

function ActionFilter({
  value,
  onChange,
}: {
  value: AuditAction[];
  onChange: (next: AuditAction[]) => void;
}) {
  const selected = new Set(value);
  const label =
    selected.size === 0
      ? 'All actions'
      : selected.size === 1
        ? AUDIT_ACTION_LABELS[[...selected][0]]
        : `${selected.size} actions`;

  const toggle = (action: AuditAction) => {
    const next = new Set(selected);
    if (next.has(action)) next.delete(action);
    else next.add(action);
    onChange([...next]);
  };

  return (
    <Popover>
      <PopoverTrigger
        render={(props) => (
          <button
            {...props}
            type="button"
            className="inline-flex items-center gap-1.5 h-8 px-3 rounded-full border border-border bg-card text-xs font-medium text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
          >
            <Filter className="size-3.5" />
            <span>{label}</span>
            <ChevronDown className="size-3" />
          </button>
        )}
      />
      <PopoverContent align="start" className="w-56 p-1.5">
        {ALL_ACTIONS.map((a) => {
          const checked = selected.has(a);
          return (
            <button
              key={a}
              type="button"
              onClick={() => toggle(a)}
              className={cn(
                'w-full flex items-center justify-between gap-2 px-2 py-1.5 rounded text-sm hover:bg-muted',
                checked && 'text-foreground font-medium',
              )}
            >
              <span>{AUDIT_ACTION_LABELS[a]}</span>
              {checked ? <span className="text-xs">✓</span> : null}
            </button>
          );
        })}
      </PopoverContent>
    </Popover>
  );
}

// ── Single audit row (collapsible metadata) ────────────────────────

function AuditRow({ entry }: { entry: AuditEntry }) {
  const [expanded, setExpanded] = useState(false);
  const hasMetadata = entry.metadata && Object.keys(entry.metadata).length > 0;

  return (
    <div className="px-4 sm:px-5 py-3">
      <button
        type="button"
        onClick={() => hasMetadata && setExpanded((e) => !e)}
        className={cn(
          'w-full text-left',
          hasMetadata && 'hover:bg-muted/30 -mx-4 sm:-mx-5 px-4 sm:px-5 py-2 -my-2 rounded transition-colors',
        )}
      >
        <div className="flex items-start gap-3">
          <ActionPill action={entry.action} />
          <div className="min-w-0 flex-1">
            <div className="flex items-baseline flex-wrap gap-x-2 gap-y-1">
              {entry.user ? (
                <span className="text-sm font-medium text-foreground truncate">
                  {entry.user.email}
                </span>
              ) : (
                <span className="text-sm font-medium text-muted-foreground italic">
                  system
                </span>
              )}
              {entry.tenant ? (
                <span className="text-xs text-muted-foreground">
                  @ <span className="font-mono">{entry.tenant.slug}</span>
                </span>
              ) : (
                <span className="text-xs text-muted-foreground/70 italic">
                  (no tenant)
                </span>
              )}
              {entry.resource_type ? (
                <span className="text-xs text-muted-foreground">
                  · {entry.resource_type}
                  {entry.resource_id ? (
                    <span className="font-mono">#{entry.resource_id}</span>
                  ) : null}
                </span>
              ) : null}
            </div>
            <p className="mt-1 text-[11px] text-muted-foreground tabular-nums">
              {formatTimestamp(entry.timestamp)}
              {entry.ip_address ? ` · IP ${entry.ip_address}` : ''}
            </p>
          </div>
          {hasMetadata ? (
            <span className="text-muted-foreground shrink-0 mt-1">
              {expanded ? (
                <ChevronUp className="size-4" />
              ) : (
                <ChevronDown className="size-4" />
              )}
            </span>
          ) : null}
        </div>
      </button>

      {expanded && hasMetadata ? (
        <pre className="mt-3 rounded-md border bg-background p-3 text-[11px] text-muted-foreground overflow-x-auto font-mono leading-relaxed">
          {JSON.stringify(entry.metadata, null, 2)}
        </pre>
      ) : null}
    </div>
  );
}

function ActionPill({ action }: { action: AuditAction }) {
  return (
    <span
      className={cn(
        'inline-flex items-center h-5 px-2 mt-0.5 rounded text-[10px] uppercase tracking-wide font-medium ring-1 whitespace-nowrap shrink-0',
        AUDIT_ACTION_TONE[action],
      )}
    >
      {AUDIT_ACTION_LABELS[action]}
    </span>
  );
}

// ── Empty + skeleton ───────────────────────────────────────────────

function EmptyState() {
  return (
    <div className="rounded-lg border bg-card p-12 text-center">
      <ScrollText className="mx-auto size-8 text-muted-foreground/50 mb-4" aria-hidden />
      <p className="text-sm font-medium text-foreground">No entries match.</p>
      <p className="mt-1 text-xs text-muted-foreground">
        Try clearing some filters or broadening the search.
      </p>
    </div>
  );
}

function SkeletonFeed() {
  return (
    <ul className="rounded-lg border bg-card divide-y overflow-hidden">
      {Array.from({ length: 8 }, (_, i) => (
        <li key={i} className="px-4 sm:px-5 py-3.5">
          <div className="flex items-start gap-3">
            <div className="h-5 w-14 animate-pulse rounded bg-muted shrink-0" />
            <div className="flex-1">
              <div className="h-4 w-2/3 animate-pulse rounded bg-muted" />
              <div className="mt-2 h-3 w-1/3 animate-pulse rounded bg-muted/60" />
            </div>
          </div>
        </li>
      ))}
    </ul>
  );
}

function formatTimestamp(iso: string): string {
  return new Date(iso).toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
  });
}
