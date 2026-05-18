/**
 * `/platform` — index dashboard.
 *
 * Layout (top → bottom):
 *
 *   1. Sticky header — title + cross-tenant search + New tenant CTA
 *   2. Status row — 4 KPI tiles with status accent
 *   3. Two-column body
 *        Left  (2/3) — Recent signups
 *        Right (1/3) — Recent platform-audit activity
 *
 * All numbers come from `/api/platform/summary/`. Recent activity
 * pulls from the audit log filtered to `resource_type='platform_tenant'`
 * — gives at-a-glance visibility into recent platform-side actions
 * (suspends, creates, reactivations). Search jumps to the tenants list
 * with the same query pre-applied via `?q=`.
 */

'use client';

import { Building2, Plus, Search } from 'lucide-react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useState } from 'react';

import { Input } from '@/components/ui/input';
import {
  STATUS_LABELS,
  STATUS_TONE,
  type PlatformTenantStatus,
  usePlatformSummary,
} from '@/lib/platform';
import { cn } from '@/lib/utils';

export default function PlatformDashboardPage() {
  const router = useRouter();
  const { data: summary, isLoading, error } = usePlatformSummary();
  const [search, setSearch] = useState('');

  const submitSearch = (e: React.FormEvent) => {
    e.preventDefault();
    const q = search.trim();
    router.push(`/platform/tenants${q ? `?q=${encodeURIComponent(q)}` : ''}`);
  };

  return (
    <div className="px-4 sm:px-8 lg:px-10 py-6 sm:py-10 space-y-6 sm:space-y-8">
      {/* ─── Header strip ─────────────────────────────────────────── */}
      <header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div className="min-w-0">
          <p className="text-[11px] uppercase tracking-[0.16em] text-muted-foreground">
            Platform Admin
          </p>
          <h1 className="mt-2 font-serif text-2xl sm:text-3xl font-semibold tracking-tight text-foreground">
            Lumè platform overview
          </h1>
          <p className="mt-2 text-sm text-muted-foreground">
            Cross-tenant view of every customer running on Lumè.
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

      {/* ─── Cross-tenant search ─────────────────────────────────── */}
      <form onSubmit={submitSearch} className="relative max-w-2xl">
        <Search
          className="size-4 absolute left-3.5 top-1/2 -translate-y-1/2 text-muted-foreground pointer-events-none"
          aria-hidden
        />
        <Input
          placeholder="Search tenants by name, slug, or owner email…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="pl-10 h-11"
        />
      </form>

      {error ? (
        <div className="rounded-lg border border-destructive/40 bg-destructive/10 px-4 py-3 text-sm text-destructive">
          Failed to load platform summary.
        </div>
      ) : null}

      {/* ─── KPI tiles ───────────────────────────────────────────── */}
      <div className="grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-4">
        <Tile
          label="Total tenants"
          value={isLoading ? '—' : String(summary?.total_tenants ?? 0)}
          loading={isLoading}
        />
        <Tile
          label="Active"
          value={isLoading ? '—' : String(summary?.by_status.active ?? 0)}
          tone="active"
          loading={isLoading}
        />
        <Tile
          label="Trial"
          value={isLoading ? '—' : String(summary?.by_status.trial ?? 0)}
          tone="trial"
          loading={isLoading}
        />
        <Tile
          label="Suspended"
          value={isLoading ? '—' : String(summary?.by_status.suspended ?? 0)}
          tone="suspended"
          loading={isLoading}
        />
      </div>

      {/* ─── Two-column body ─────────────────────────────────────── */}
      <div className="grid gap-4 lg:grid-cols-3 lg:gap-6">
        {/* Recent signups */}
        <section className="lg:col-span-2 rounded-lg border bg-card overflow-hidden">
          <header className="flex items-baseline justify-between gap-4 border-b px-4 sm:px-5 py-4">
            <div>
              <p className="text-[11px] uppercase tracking-wide text-muted-foreground/85 font-medium">
                Recent signups
              </p>
              <p className="mt-1 font-serif text-base font-medium text-foreground">
                Last 30 days
              </p>
            </div>
            <Link
              href="/platform/tenants"
              className="text-xs font-medium uppercase tracking-[0.16em] text-foreground/70 hover:text-accent transition-colors whitespace-nowrap"
            >
              All tenants →
            </Link>
          </header>
          {isLoading ? (
            <SkeletonRows rows={4} />
          ) : !summary || summary.recent_signups.length === 0 ? (
            <div className="px-5 py-12 text-center">
              <Building2 className="mx-auto size-6 text-muted-foreground/60 mb-3" aria-hidden />
              <p className="text-sm text-muted-foreground">
                No tenants signed up in the last 30 days.
              </p>
            </div>
          ) : (
            <ul className="divide-y">
              {summary.recent_signups.map((t) => (
                <li key={t.slug}>
                  <Link
                    href={`/platform/tenants/${t.slug}`}
                    className="flex items-center justify-between gap-3 px-4 sm:px-5 py-3 transition-colors hover:bg-muted/30"
                  >
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium text-foreground truncate">{t.name}</p>
                      <p className="text-xs text-muted-foreground truncate">
                        {t.slug} · {t.owner_email ?? '—'}
                      </p>
                    </div>
                    <div className="flex items-center gap-3 shrink-0">
                      <StatusPill status={t.status} />
                      <span className="hidden sm:inline text-xs text-muted-foreground tabular-nums whitespace-nowrap">
                        {formatDate(t.created_at)}
                      </span>
                    </div>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </section>

        {/* Recent activity */}
        <section className="rounded-lg border bg-card overflow-hidden">
          <header className="border-b px-4 sm:px-5 py-4">
            <p className="text-[11px] uppercase tracking-wide text-muted-foreground/85 font-medium">
              Recent activity
            </p>
            <p className="mt-1 font-serif text-base font-medium text-foreground">
              Platform audit log
            </p>
          </header>
          {isLoading ? (
            <SkeletonRows rows={4} />
          ) : !summary || summary.recent_activity.length === 0 ? (
            <div className="px-5 py-12 text-center">
              <p className="text-sm text-muted-foreground">No platform activity yet.</p>
            </div>
          ) : (
            <ul className="divide-y">
              {summary.recent_activity.map((a, i) => (
                <li key={i} className="px-4 sm:px-5 py-3">
                  <p className="text-sm text-foreground">{eventLabel(a.event, a.tenant_slug)}</p>
                  <p className="mt-1 text-[11px] text-muted-foreground tabular-nums">
                    {a.user_email ?? 'system'} · {formatTimestamp(a.timestamp)}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </div>
  );
}

// ── Tile ────────────────────────────────────────────────────────────

function Tile({
  label,
  value,
  tone,
  loading,
}: {
  label: string;
  value: string;
  tone?: PlatformTenantStatus;
  loading?: boolean;
}) {
  return (
    <div
      className={cn(
        'rounded-lg border bg-card px-4 sm:px-5 py-4 transition-colors relative overflow-hidden',
        tone && 'border-l-4',
      )}
      style={
        tone === 'active'
          ? { borderLeftColor: 'var(--color-emerald, #10b981)' }
          : tone === 'trial'
            ? { borderLeftColor: 'var(--color-emphasis, #FF9408)' }
            : tone === 'suspended'
              ? { borderLeftColor: 'var(--color-destructive, #CA3F16)' }
              : undefined
      }
    >
      <p className="text-[11px] uppercase tracking-wide text-muted-foreground/85 font-medium">
        {label}
      </p>
      {loading ? (
        <div className="mt-2 h-9 w-16 animate-pulse rounded bg-muted" />
      ) : (
        <p className="mt-1.5 font-serif text-2xl sm:text-3xl font-semibold tracking-tight tabular-nums text-foreground">
          {value}
        </p>
      )}
    </div>
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

function SkeletonRows({ rows }: { rows: number }) {
  return (
    <ul className="divide-y">
      {Array.from({ length: rows }, (_, i) => (
        <li key={i} className="px-5 py-3">
          <div className="h-4 w-2/3 animate-pulse rounded bg-muted" />
          <div className="mt-2 h-3 w-1/3 animate-pulse rounded bg-muted/60" />
        </li>
      ))}
    </ul>
  );
}

function eventLabel(event: string | null, tenantSlug: string | null): string {
  const slug = tenantSlug ?? '—';
  switch (event) {
    case 'tenant_created':
      return `Created tenant "${slug}"`;
    case 'tenant_suspended':
      return `Suspended tenant "${slug}"`;
    case 'tenant_reactivated':
      return `Reactivated tenant "${slug}"`;
    case 'tenant_updated':
      return `Updated tenant "${slug}"`;
    default:
      return event ? `${event} · ${slug}` : slug;
  }
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

function formatTimestamp(iso: string): string {
  const d = new Date(iso);
  const now = Date.now();
  const diffSec = Math.floor((now - d.getTime()) / 1000);
  if (diffSec < 60) return 'just now';
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`;
  if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h ago`;
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}
