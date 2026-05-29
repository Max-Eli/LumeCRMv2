/**
 * `/platform/tenants` — list of every customer tenant on Lumè.
 *
 * Layout (desktop):
 *   - Sticky header (page title + New tenant CTA + search bar)
 *   - Status-filter chip row (All / Active / Trial / Suspended)
 *   - Table with 5 columns (tenant / owner / status / members / signed up)
 *
 * Layout (mobile):
 *   - Same sticky header, compressed
 *   - Same chips, scroll horizontally if cramped
 *   - Card list instead of table — each tenant becomes a tappable card
 *
 * Search syncs to `?q=` so the dashboard's search bar can deep-link
 * filtered results.
 */

'use client';

import { Plus, Search } from 'lucide-react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { useCallback, useEffect, useMemo, useState } from 'react';

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
  PLAN_LABELS,
  STATUS_LABELS,
  STATUS_TONE,
  type PlatformPlan,
  type PlatformTenantListItem,
  type PlatformTenantStatus,
  usePlatformTenants,
} from '@/lib/platform';
import { cn } from '@/lib/utils';

type StatusFilter = 'all' | PlatformTenantStatus;

const STATUS_FILTERS: { id: StatusFilter; label: string }[] = [
  { id: 'all', label: 'All' },
  { id: 'active', label: 'Active' },
  { id: 'trial', label: 'Trial' },
  // Past-due was added when self-serve billing landed — payment
  // failed but workspace not yet suspended. Operationally critical to
  // see at a glance because these tenants are 7 days from suspension.
  { id: 'past_due', label: 'Past due' },
  { id: 'suspended', label: 'Suspended' },
  { id: 'cancelled', label: 'Cancelled' },
];

export default function PlatformTenantsListPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { data: tenants, isLoading, error } = usePlatformTenants();

  // URL-driven state: ?q=... and ?status=active
  const initialSearch = searchParams.get('q') ?? '';
  const initialStatus = (searchParams.get('status') as StatusFilter | null) ?? 'all';
  const [search, setSearch] = useState(initialSearch);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>(initialStatus);

  // Sync URL ⇆ state. Debounced (effectively, since URL replace is fast).
  useEffect(() => {
    const params = new URLSearchParams(searchParams.toString());
    if (search) params.set('q', search);
    else params.delete('q');
    if (statusFilter !== 'all') params.set('status', statusFilter);
    else params.delete('status');
    const next = params.toString();
    router.replace(`/platform/tenants${next ? `?${next}` : ''}`, { scroll: false });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search, statusFilter]);

  const counts = useMemo(() => {
    const c: Record<StatusFilter, number> = {
      all: 0,
      active: 0,
      trial: 0,
      past_due: 0,
      suspended: 0,
      cancelled: 0,
    };
    for (const t of tenants ?? []) {
      c.all += 1;
      c[t.status] = (c[t.status] ?? 0) + 1;
    }
    return c;
  }, [tenants]);

  const filtered = useMemo(() => {
    if (!tenants) return [];
    const q = search.trim().toLowerCase();
    return tenants.filter((t) => {
      if (statusFilter !== 'all' && t.status !== statusFilter) return false;
      if (!q) return true;
      return (
        t.name.toLowerCase().includes(q) ||
        t.slug.toLowerCase().includes(q) ||
        (t.owner_email ?? '').toLowerCase().includes(q) ||
        // Billing email often differs from the owner email (finance
        // dept). Ops searches by it to reconcile against Stripe.
        t.billing_email.toLowerCase().includes(q)
      );
    });
  }, [tenants, search, statusFilter]);

  const goToDetail = useCallback(
    (slug: string) => router.push(`/platform/tenants/${slug}`),
    [router],
  );

  return (
    <div className="px-4 sm:px-8 lg:px-10 py-6 sm:py-10">
      {/* ─── Sticky header strip ────────────────────────────────── */}
      <div className="sticky top-0 z-10 -mx-4 sm:-mx-8 lg:-mx-10 -mt-6 sm:-mt-10 px-4 sm:px-8 lg:px-10 pt-6 sm:pt-10 pb-4 bg-background border-b border-border">
        <header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
          <div className="min-w-0">
            <p className="text-[11px] uppercase tracking-[0.16em] text-muted-foreground">
              Platform Admin
            </p>
            <h1 className="mt-2 font-serif text-2xl sm:text-3xl font-semibold tracking-tight text-foreground">
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
            className="inline-flex h-10 items-center justify-center gap-2 rounded-md bg-foreground px-4 text-sm font-medium text-background hover:bg-foreground/90 transition-colors shrink-0"
          >
            <Plus className="size-4" />
            New tenant
          </Link>
        </header>

        <div className="relative max-w-md mt-4">
          <Search
            className="size-4 absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground pointer-events-none"
            aria-hidden
          />
          <Input
            placeholder="Search by name, slug, owner or billing email…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-9"
          />
        </div>
      </div>

      {/* ─── Filter chips ───────────────────────────────────────── */}
      <div className="mt-6 -mx-4 sm:mx-0 overflow-x-auto">
        <div className="px-4 sm:px-0 flex items-center gap-2 whitespace-nowrap">
          {STATUS_FILTERS.map((f) => {
            const active = f.id === statusFilter;
            const n = counts[f.id] ?? 0;
            return (
              <button
                key={f.id}
                type="button"
                onClick={() => setStatusFilter(f.id)}
                className={cn(
                  'inline-flex items-center gap-1.5 h-8 px-3 rounded-full border text-xs font-medium transition-colors',
                  active
                    ? 'bg-foreground text-background border-foreground'
                    : 'bg-card text-muted-foreground border-border hover:bg-muted hover:text-foreground',
                )}
              >
                <span>{f.label}</span>
                <span
                  className={cn(
                    'tabular-nums text-[10px] px-1.5 py-0.5 rounded-full',
                    active
                      ? 'bg-background/20 text-background'
                      : 'bg-muted text-muted-foreground',
                  )}
                >
                  {n}
                </span>
              </button>
            );
          })}
        </div>
      </div>

      {/* ─── Body ───────────────────────────────────────────────── */}
      <div className="mt-4">
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
            {search || statusFilter !== 'all'
              ? 'No tenants match the current filter.'
              : 'No tenants yet.'}
          </div>
        ) : (
          <>
            {/* Desktop table */}
            <div className="hidden md:block rounded-lg border bg-card overflow-hidden">
              <Table>
                <TableHeader>
                  <TableRow className="bg-muted/30 hover:bg-muted/30">
                    <TableHead className="w-[28%]">Tenant</TableHead>
                    <TableHead>Owner</TableHead>
                    <TableHead className="w-[110px]">Plan</TableHead>
                    <TableHead className="w-[130px]">Status</TableHead>
                    <TableHead className="w-[90px] text-right">Members</TableHead>
                    <TableHead className="w-[120px]">Signed up</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filtered.map((t) => (
                    <TenantRow key={t.slug} tenant={t} onClick={() => goToDetail(t.slug)} />
                  ))}
                </TableBody>
              </Table>
            </div>

            {/* Mobile card list */}
            <ul className="md:hidden space-y-2">
              {filtered.map((t) => (
                <li key={t.slug}>
                  <button
                    type="button"
                    onClick={() => goToDetail(t.slug)}
                    className="w-full text-left rounded-lg border bg-card px-4 py-3.5 transition-colors hover:bg-muted/30 active:bg-muted/50"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2 min-w-0">
                          <p className="font-medium text-foreground truncate">{t.name}</p>
                          {t.grandfathered ? <LegacyBadge /> : null}
                        </div>
                        <p className="text-xs text-muted-foreground font-mono truncate mt-0.5">
                          {t.slug}
                        </p>
                        <p className="text-xs text-muted-foreground/85 truncate mt-1">
                          {t.owner_email ?? 'No owner'}
                        </p>
                      </div>
                      <div className="flex flex-col items-end gap-1 shrink-0">
                        <StatusPill status={t.status} />
                        <PlanPill plan={t.plan} />
                      </div>
                    </div>
                    <div className="mt-3 pt-3 border-t border-border flex items-center justify-between gap-4 text-xs text-muted-foreground tabular-nums">
                      <span>
                        {t.member_count} {t.member_count === 1 ? 'member' : 'members'}
                      </span>
                      {t.status === 'trial' && t.trial_days_remaining !== null ? (
                        <TrialCountdown days={t.trial_days_remaining} />
                      ) : (
                        <span>Joined {formatDate(t.created_at)}</span>
                      )}
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          </>
        )}
      </div>
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
          <div className="flex items-center gap-2 min-w-0">
            <p className="font-medium text-foreground truncate">{tenant.name}</p>
            {tenant.grandfathered ? <LegacyBadge /> : null}
          </div>
          <p className="text-xs text-muted-foreground font-mono truncate">
            {tenant.slug}.xn--lumcrm-5ua.com
          </p>
        </div>
      </TableCell>
      <TableCell className="text-foreground/80 text-sm truncate max-w-[260px]">
        {tenant.owner_email ?? '—'}
      </TableCell>
      <TableCell>
        <PlanPill plan={tenant.plan} />
      </TableCell>
      <TableCell>
        <div className="flex flex-col gap-1 items-start">
          <StatusPill status={tenant.status} />
          {tenant.status === 'trial' && tenant.trial_days_remaining !== null ? (
            <TrialCountdown days={tenant.trial_days_remaining} />
          ) : null}
        </div>
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
        'inline-flex items-center h-5 px-2 rounded text-[10px] uppercase tracking-wide font-medium ring-1 whitespace-nowrap',
        STATUS_TONE[status],
      )}
    >
      {STATUS_LABELS[status]}
    </span>
  );
}

/** Compact plan-tier badge. Visual hierarchy: Pro stands out (most
 *  common upgrade target), Enterprise gets a subtle premium tone,
 *  Trial signals "not yet on a paid tier so be patient with them." */
function PlanPill({ plan }: { plan: PlatformPlan }) {
  const tone: Record<PlatformPlan, string> = {
    trial: 'bg-amber-500/10 text-amber-300 ring-amber-500/20',
    starter: 'bg-foreground/8 text-foreground/85 ring-foreground/15',
    pro: 'bg-blue-500/15 text-blue-300 ring-blue-500/30',
    enterprise: 'bg-purple-500/15 text-purple-300 ring-purple-500/30',
  };
  return (
    <span
      className={cn(
        'inline-flex items-center h-5 px-2 rounded text-[10px] uppercase tracking-wide font-medium ring-1 whitespace-nowrap',
        tone[plan],
      )}
    >
      {PLAN_LABELS[plan]}
    </span>
  );
}

/** Trial countdown that nudges toward urgent tones as the trial ends.
 *  Operators scan this column for "who's about to churn unless we
 *  intervene" — the colors do the triage automatically. */
function TrialCountdown({ days }: { days: number }) {
  const tone =
    days <= 1
      ? 'text-rose-300'
      : days <= 7
        ? 'text-orange-300'
        : 'text-muted-foreground';
  return (
    <span
      className={cn(
        'inline-flex items-center text-[10px] tabular-nums whitespace-nowrap',
        tone,
      )}
    >
      {days === 0
        ? 'Ends today'
        : days === 1
          ? '1 day left'
          : `${days} days left`}
    </span>
  );
}

/** "Legacy" badge for the 2 launch spas that predate self-serve
 *  pricing. Ops MUST see this on every list/detail surface — it's the
 *  signal not to attempt billing changes (they're grandfathered into
 *  Pro with no Stripe enrollment). Wrong call here breaks live spas. */
function LegacyBadge() {
  return (
    <span
      className="inline-flex items-center h-4 px-1.5 rounded text-[9px] uppercase tracking-wide font-medium ring-1 ring-yellow-500/30 bg-yellow-500/10 text-yellow-300 whitespace-nowrap"
      title="Grandfathered launch spa — no Stripe enrollment. Contact founder before changing billing."
    >
      Legacy
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
