/**
 * `/platform` — index dashboard.
 *
 * Layout (top → bottom):
 *
 *   1. Header   — page title + "Create tenant" CTA
 *   2. Status row — 4 KPI tiles for total / active / trial / suspended
 *   3. Two-column body
 *      - Recent signups table (left, 2/3)
 *      - Recent platform activity feed (right, 1/3)
 *
 * All numbers come from `/api/platform/summary/`. Recent activity
 * pulls from the audit log filtered to `resource_type='platform_tenant'`
 * — gives at-a-glance visibility into recent platform-side actions
 * (suspends, creates, reactivations).
 */

'use client';

import { Building2, Plus } from 'lucide-react';
import Link from 'next/link';

import {
  STATUS_LABELS,
  STATUS_TONE,
  type PlatformTenantStatus,
  usePlatformSummary,
} from '@/lib/platform';
import { cn } from '@/lib/utils';

export default function PlatformDashboardPage() {
  const { data: summary, isLoading, error } = usePlatformSummary();

  return (
    <div className="px-10 py-10 max-w-7xl space-y-8">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-[11px] uppercase tracking-[0.16em] text-muted-foreground">
            Platform Admin
          </p>
          <h1 className="mt-2 font-serif text-3xl font-semibold tracking-tight text-foreground">
            Lumè platform overview
          </h1>
          <p className="mt-2 text-sm text-muted-foreground">
            Cross-tenant view of every customer running on Lumè today.
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

      {error ? (
        <div className="rounded-lg border border-destructive/40 bg-destructive/10 px-4 py-3 text-sm text-destructive">
          Failed to load platform summary.
        </div>
      ) : null}

      {/* Status tiles */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
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

      <div className="grid gap-6 lg:grid-cols-3">
        {/* Recent signups */}
        <section className="lg:col-span-2 rounded-lg border bg-card overflow-hidden">
          <header className="flex items-baseline justify-between gap-4 border-b px-5 py-4">
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
              className="text-xs font-medium uppercase tracking-[0.16em] text-foreground/70 hover:text-accent transition-colors"
            >
              All tenants →
            </Link>
          </header>
          {isLoading ? (
            <div className="px-5 py-10 text-center text-sm text-muted-foreground">Loading…</div>
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
                    className="grid grid-cols-[1fr_auto_auto] items-baseline gap-4 px-5 py-3 transition-colors hover:bg-muted/30"
                  >
                    <div className="min-w-0">
                      <p className="text-sm font-medium text-foreground truncate">{t.name}</p>
                      <p className="text-xs text-muted-foreground truncate">
                        {t.slug}.xn--lumcrm-5ua.com · {t.owner_email ?? '—'}
                      </p>
                    </div>
                    <StatusPill status={t.status} />
                    <span className="text-xs text-muted-foreground tabular-nums">
                      {formatDate(t.created_at)}
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </section>

        {/* Recent activity */}
        <section className="rounded-lg border bg-card overflow-hidden">
          <header className="border-b px-5 py-4">
            <p className="text-[11px] uppercase tracking-wide text-muted-foreground/85 font-medium">
              Recent activity
            </p>
            <p className="mt-1 font-serif text-base font-medium text-foreground">
              Platform audit log
            </p>
          </header>
          {isLoading ? (
            <div className="px-5 py-10 text-center text-sm text-muted-foreground">Loading…</div>
          ) : !summary || summary.recent_activity.length === 0 ? (
            <div className="px-5 py-12 text-center">
              <p className="text-sm text-muted-foreground">No platform activity yet.</p>
            </div>
          ) : (
            <ul className="divide-y">
              {summary.recent_activity.map((a, i) => (
                <li key={i} className="px-5 py-3">
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
        'rounded-lg border bg-card px-5 py-4 transition-colors',
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
        <div className="mt-2 h-8 w-16 animate-pulse rounded bg-muted" />
      ) : (
        <p className="mt-1.5 font-serif text-3xl font-semibold tracking-tight tabular-nums text-foreground">
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
        'inline-flex items-center h-5 px-2 rounded text-[10px] uppercase tracking-wide font-medium ring-1',
        STATUS_TONE[status],
      )}
    >
      {STATUS_LABELS[status]}
    </span>
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
