/**
 * `/org/dashboard` — organization-level rollup view.
 *
 * For owners + managers of multi-location businesses: a single screen
 * showing every site at a glance. Read-only — editing locations
 * happens at `/org/locations/[id]` (owner gate). Single-location
 * tenants can still visit, they'll just see one card.
 *
 * v1 content is intentionally narrow: per-location card with hours,
 * address, default flag. Cross-location KPIs (revenue rollup, today's
 * appointment count per site) light up when reporting lands in
 * Phase 1G — at that point the page grows from "locations overview"
 * into a real org-rollup dashboard. Today, this gives owners somewhere
 * meaningful to land when they click "Org → Dashboard" rather than a
 * placeholder.
 */

'use client';

import {
  ArrowRight,
  Building2,
  ChartLine,
  Clock,
  Globe,
  MapPin,
  Phone,
  Plus,
  Star,
} from 'lucide-react';
import Link from 'next/link';

import { PageHeader } from '@/components/page-header';
import { useCurrentMembership } from '@/lib/auth';
import {
  type Location,
  locationDisplayName,
  useLocations,
} from '@/lib/locations';
import { cn } from '@/lib/utils';

export default function OrgDashboardPage() {
  const me = useCurrentMembership();
  const canManage = me?.role === 'owner';

  if (me && me.role !== 'owner' && me.role !== 'manager') {
    return (
      <div className="px-10 py-10 max-w-7xl">
        <PageHeader
          title="Organization dashboard"
          description="Owners and managers only."
        />
        <p className="text-sm text-destructive">
          You don&apos;t have access to the organization view.
        </p>
      </div>
    );
  }

  return <OrgDashboardContent canManage={canManage} />;
}

function OrgDashboardContent({ canManage }: { canManage: boolean }) {
  const { data: locations, isLoading, error } = useLocations();

  const all = locations ?? [];
  const activeCount = all.filter((l) => l.is_active).length;
  const inactiveCount = all.length - activeCount;

  return (
    <div className="px-10 py-10 max-w-7xl space-y-6">
      <PageHeader
        title="Organization"
        description="Your business across every location. Site-specific work happens on each location's dashboard; this is the rollup view."
        actions={
          canManage ? (
            <Link
              href="/org/locations/new"
              className="inline-flex items-center gap-1.5 h-8 px-3 rounded-md bg-foreground text-background text-xs font-medium hover:bg-foreground/90 transition-colors"
            >
              <Plus className="size-3.5" />
              Add location
            </Link>
          ) : null
        }
      />

      <SummaryRow activeCount={activeCount} inactiveCount={inactiveCount} />

      {isLoading ? (
        <p className="text-sm text-muted-foreground">Loading locations…</p>
      ) : error ? (
        <p className="text-sm text-destructive">Could not load locations.</p>
      ) : all.length === 0 ? (
        <EmptyState />
      ) : (
        <section>
          <SectionHeader>Locations</SectionHeader>
          <ul className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
            {all
              .filter((l) => l.is_active)
              .map((location) => (
                <LocationCard
                  key={location.id}
                  location={location}
                  canOpen={canManage}
                />
              ))}
            {inactiveCount > 0 ? (
              <li
                className="border rounded-lg bg-muted/30 px-4 py-6 flex items-center justify-center text-xs text-muted-foreground"
                title="Inactive locations are hidden from this view; manage them at /org/locations"
              >
                {inactiveCount} inactive site{inactiveCount === 1 ? '' : 's'} hidden ·{' '}
                {canManage ? (
                  <Link
                    href="/org/locations"
                    className="ml-1 underline-offset-2 hover:underline text-foreground"
                  >
                    Manage
                  </Link>
                ) : (
                  <span>Ask an owner to manage</span>
                )}
              </li>
            ) : null}
          </ul>
        </section>
      )}

      <FuturePanelsHint />
    </div>
  );
}

// ── Sub-components ──────────────────────────────────────────────────

function SummaryRow({
  activeCount,
  inactiveCount,
}: {
  activeCount: number;
  inactiveCount: number;
}) {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
      <SummaryCard
        label="Active locations"
        value={String(activeCount)}
        icon={<Building2 className="size-4" />}
      />
      <SummaryCard
        label="Inactive"
        value={String(inactiveCount)}
        icon={<Building2 className="size-4 opacity-60" />}
        muted
      />
      <SummaryCard
        label="Cross-location reports"
        value="—"
        hint="Available with Phase 1G reporting"
        icon={<ChartLine className="size-4 opacity-60" />}
        muted
      />
    </div>
  );
}

function SummaryCard({
  icon,
  label,
  value,
  hint,
  muted,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  hint?: string;
  muted?: boolean;
}) {
  return (
    <div
      className={cn(
        'border rounded-lg bg-card px-4 py-3',
        muted && 'bg-muted/20',
      )}
    >
      <div className="flex items-center gap-2 text-[11px] uppercase tracking-wide text-muted-foreground">
        {icon}
        {label}
      </div>
      <p className="font-serif text-2xl tracking-tight mt-1">{value}</p>
      {hint ? (
        <p className="text-[11px] text-muted-foreground mt-0.5">{hint}</p>
      ) : null}
    </div>
  );
}

function LocationCard({
  location,
  canOpen,
}: {
  location: Location;
  canOpen: boolean;
}) {
  const cityState = [location.city, location.state].filter(Boolean).join(', ');
  const fullAddress = [location.address_line1, cityState, location.zip_code]
    .filter(Boolean)
    .join(' · ');
  const hours = `${trimSeconds(location.business_open_time)} – ${trimSeconds(location.business_close_time)}`;

  return (
    <li
      className={cn(
        'group relative border rounded-lg bg-card p-4 space-y-3 transition-colors',
        canOpen && 'hover:border-foreground/20',
      )}
    >
      {canOpen ? (
        <Link
          href={`/org/locations/${location.id}`}
          className="absolute inset-0 z-0 rounded-lg focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring/40"
          aria-label={`Open ${locationDisplayName(location)}`}
        >
          <span className="sr-only">Open</span>
        </Link>
      ) : null}

      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <h3 className="font-serif text-base font-semibold tracking-tight truncate">
              {locationDisplayName(location)}
            </h3>
            {location.is_default ? (
              <span
                title="Default location — fallback when no specific site is selected"
                className="inline-flex items-center gap-0.5 text-[10px] uppercase tracking-wide px-1.5 py-px rounded bg-accent/15 text-accent"
              >
                <Star className="size-3" />
                Default
              </span>
            ) : null}
          </div>
          <p className="text-[11px] text-muted-foreground font-mono mt-0.5">
            {location.slug}
          </p>
        </div>
        {canOpen ? (
          <ArrowRight className="size-4 text-muted-foreground/60 group-hover:text-foreground transition-colors relative z-10" />
        ) : null}
      </div>

      <dl className="space-y-1.5 text-xs text-muted-foreground">
        <DetailRow icon={<MapPin className="size-3.5" />}>
          {fullAddress || <em className="not-italic text-muted-foreground/70">No address set</em>}
        </DetailRow>
        <DetailRow icon={<Clock className="size-3.5" />}>{hours}</DetailRow>
        <DetailRow icon={<Globe className="size-3.5" />}>{location.timezone}</DetailRow>
        {location.phone ? (
          <DetailRow icon={<Phone className="size-3.5" />}>{location.phone}</DetailRow>
        ) : null}
      </dl>
    </li>
  );
}

function DetailRow({
  icon,
  children,
}: {
  icon: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-center gap-1.5 truncate">
      <span className="text-muted-foreground/70 shrink-0" aria-hidden>
        {icon}
      </span>
      <span className="truncate">{children}</span>
    </div>
  );
}

function SectionHeader({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="text-[11px] uppercase tracking-wide text-muted-foreground font-medium mb-3">
      {children}
    </h2>
  );
}

function EmptyState() {
  return (
    <div className="border rounded-lg bg-card px-6 py-12 text-center">
      <Building2 className="size-6 mx-auto mb-3 text-muted-foreground/60" />
      <p className="text-sm text-foreground font-medium">No locations yet</p>
      <p className="text-xs text-muted-foreground mt-1">
        Onboarding always seeds a default location, so this is unusual — check
        Django admin.
      </p>
    </div>
  );
}

function FuturePanelsHint() {
  return (
    <div className="rounded-md border border-dashed border-border/80 px-4 py-3 text-[11px] text-muted-foreground leading-relaxed">
      <span className="font-medium text-foreground">Coming next:</span>{' '}
      cross-location revenue + appointments rollup with Phase 1G reporting; the
      online booking portal config (Phase 1I); third-party integrations.
    </div>
  );
}

function trimSeconds(time: string): string {
  const match = /^(\d{1,2}:\d{2})/.exec(time);
  return match ? match[1] : time;
}
