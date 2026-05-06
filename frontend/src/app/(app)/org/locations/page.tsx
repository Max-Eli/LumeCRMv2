/**
 * `/org/locations` — manage the physical sites that make up the
 * business. Owner-only (gated by `MANAGE_TENANT_SETTINGS`; the
 * backend re-validates).
 *
 * Single-location tenants can use this page to add their second site;
 * multi-location tenants use it to add, rename, deactivate, and switch
 * the default location. The default location is the fallback the
 * `LocationMiddleware` resolves when no specific site has been picked
 * (e.g. fresh login, missing cookie). Exactly one default per tenant
 * at all times — enforced both at the DB layer (partial unique index)
 * and on the API write paths.
 *
 * Hard delete is intentionally not exposed — appointments / payroll /
 * audit records FK into Location in later sessions, so deletion would
 * either orphan or cascade them. Soft-delete via `is_active=false`
 * preserves the trail.
 */

'use client';

import {
  Building2,
  CheckCircle2,
  ChevronRight,
  Clock,
  MapPin,
  Plus,
  Star,
} from 'lucide-react';
import Link from 'next/link';
import { useMemo, useState } from 'react';

import { PageHeader } from '@/components/page-header';
import { Button } from '@/components/ui/button';
import { useCurrentMembership } from '@/lib/auth';
import { type Location, locationDisplayName, useLocations } from '@/lib/locations';
import { cn } from '@/lib/utils';

export default function OrgLocationsPage() {
  const me = useCurrentMembership();
  const canManage = me?.role === 'owner';

  const { data: locations, isLoading, error } = useLocations();
  const [showInactive, setShowInactive] = useState(false);

  const filtered = useMemo(() => {
    const all = locations ?? [];
    return showInactive ? all : all.filter((l) => l.is_active);
  }, [locations, showInactive]);

  const inactiveCount = useMemo(
    () => (locations ?? []).filter((l) => !l.is_active).length,
    [locations],
  );

  return (
    <div className="px-10 py-10 max-w-7xl space-y-6">
      <PageHeader
        title="Locations"
        description="Each physical site your business operates. Calendar, scheduling, and reports scope to whichever location your team picks. Exactly one location is the default fallback at all times."
        actions={
          <>
            {inactiveCount > 0 ? (
              <ShowInactiveToggle
                value={showInactive}
                onChange={setShowInactive}
                inactiveCount={inactiveCount}
              />
            ) : null}
            {canManage ? (
              <Link
                href="/org/locations/new"
                className="inline-flex items-center gap-1.5 h-8 px-3 rounded-md bg-foreground text-background text-xs font-medium hover:bg-foreground/90 transition-colors"
              >
                <Plus className="size-3.5" />
                Add location
              </Link>
            ) : null}
          </>
        }
      />

      {isLoading ? (
        <p className="text-sm text-muted-foreground">Loading locations…</p>
      ) : error ? (
        <p className="text-sm text-destructive">Could not load locations.</p>
      ) : filtered.length === 0 ? (
        <EmptyState showInactive={showInactive} hasAny={(locations ?? []).length > 0} />
      ) : (
        <ul className="border rounded-lg divide-y bg-card">
          {filtered.map((location) => (
            <LocationRow
              key={location.id}
              location={location}
              canOpen={canManage}
            />
          ))}
        </ul>
      )}

      {!canManage ? (
        <p className="text-[11px] text-muted-foreground/80 leading-relaxed">
          Only owners can add or edit locations. Contact your owner if you
          need a new site set up.
        </p>
      ) : null}
    </div>
  );
}

// ── Sub-components ──────────────────────────────────────────────────

function ShowInactiveToggle({
  value,
  onChange,
  inactiveCount,
}: {
  value: boolean;
  onChange: (next: boolean) => void;
  inactiveCount: number;
}) {
  return (
    <button
      type="button"
      onClick={() => onChange(!value)}
      aria-pressed={value}
      className={cn(
        'inline-flex items-center gap-1.5 h-8 px-2.5 rounded-md text-xs uppercase tracking-wide transition-colors border',
        value
          ? 'border-foreground/30 bg-foreground text-background'
          : 'border-border bg-card text-muted-foreground hover:bg-muted hover:text-foreground',
      )}
    >
      <Clock className="size-3.5" />
      {value ? 'Hide inactive' : `Show inactive (${inactiveCount})`}
    </button>
  );
}

function LocationRow({
  location,
  canOpen,
}: {
  location: Location;
  canOpen: boolean;
}) {
  const detailHref = `/org/locations/${location.id}`;
  const cityState = [location.city, location.state].filter(Boolean).join(', ');
  const summary = cityState || location.address_line1 || 'No address set';

  return (
    <li
      className={cn(
        'group relative flex items-center gap-4 px-4 py-3 transition-colors',
        !location.is_active && 'bg-muted/30',
        canOpen && 'hover:bg-muted/40',
      )}
    >
      {canOpen ? (
        <Link
          href={detailHref}
          className="absolute inset-0 z-0 rounded-md focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring/40"
          aria-label={`Open ${locationDisplayName(location)}`}
        >
          <span className="sr-only">Open</span>
        </Link>
      ) : null}

      <div
        className={cn(
          'inline-flex size-9 items-center justify-center rounded-md border bg-background',
          !location.is_active && 'opacity-60',
        )}
        aria-hidden
      >
        <Building2 className="size-4 text-muted-foreground" />
      </div>

      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <p
            className={cn(
              'text-sm font-medium truncate',
              !location.is_active && 'text-muted-foreground line-through',
            )}
          >
            {locationDisplayName(location)}
          </p>
          {location.is_default ? (
            <span
              title="Default location — used as the fallback when no specific site is selected"
              className="inline-flex items-center gap-0.5 text-[10px] uppercase tracking-wide px-1.5 py-px rounded bg-accent/15 text-accent"
            >
              <Star className="size-3" />
              Default
            </span>
          ) : null}
          {!location.is_active ? (
            <span className="text-[10px] uppercase tracking-wide px-1.5 py-px rounded bg-muted text-muted-foreground">
              Inactive
            </span>
          ) : null}
        </div>
        <p className="text-xs text-muted-foreground truncate flex items-center gap-1 mt-0.5">
          <MapPin className="size-3" />
          {summary}
          <span className="text-muted-foreground/60"> · </span>
          {trimSeconds(location.business_open_time)}–{trimSeconds(location.business_close_time)}
          <span className="text-muted-foreground/60"> · </span>
          {location.timezone}
        </p>
      </div>

      <div className="relative z-10 flex items-center gap-2">
        <span className="text-[11px] uppercase tracking-wide text-muted-foreground font-mono">
          {location.slug}
        </span>
        {canOpen ? (
          <ChevronRight className="size-4 text-muted-foreground/60 group-hover:text-muted-foreground transition-colors" />
        ) : null}
      </div>
    </li>
  );
}

function EmptyState({
  showInactive,
  hasAny,
}: {
  showInactive: boolean;
  hasAny: boolean;
}) {
  return (
    <div className="border rounded-lg bg-card px-6 py-12 text-center">
      <CheckCircle2 className="size-6 mx-auto mb-3 text-muted-foreground/60" />
      <p className="text-sm text-foreground font-medium">
        {!hasAny
          ? 'No locations yet'
          : showInactive
            ? 'No matching locations'
            : 'No active locations'}
      </p>
      <p className="text-xs text-muted-foreground mt-1">
        {!hasAny
          ? 'Onboarding always seeds a default location, so this is unusual — check Django admin.'
          : 'Toggle Show inactive to see deactivated sites.'}
      </p>
    </div>
  );
}

function trimSeconds(time: string): string {
  // Backend returns 'HH:MM:SS'; UI shows 'HH:MM'.
  const match = /^(\d{1,2}:\d{2})/.exec(time);
  return match ? match[1] : time;
}
