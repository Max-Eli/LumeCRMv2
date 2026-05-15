/**
 * `/portal/packages` — customer's purchased packages with sessions
 * remaining per service line.
 *
 * Active packages first (the customer's actionable inventory),
 * then pending, then voided/expired for history. Each package
 * card shows the per-service balance + expiry; the data layer
 * (`apps.packages`) tracks redemption automatically when an
 * invoice line redeems against it, so the numbers shown here
 * are always live.
 */

'use client';

import {
  CalendarDays,
  CheckCircle2,
  Clock,
  Package as PackageIcon,
  XCircle,
} from 'lucide-react';
import { useMemo } from 'react';

import { dollarsFromCents } from '@/lib/packages';
import {
  type PortalPackage,
  type PortalPackageStatus,
  usePortalPackages,
} from '@/lib/portal';
import { cn } from '@/lib/utils';

export default function PortalPackagesPage() {
  const { data: packages, isLoading } = usePortalPackages();

  return (
    <div className="max-w-4xl mx-auto w-full px-6 py-10">
      <header className="mb-8">
        <h1 className="font-serif text-3xl font-semibold tracking-tight">
          Packages
        </h1>
        <p className="text-sm text-muted-foreground mt-1.5">
          Sessions you&apos;ve purchased and how many remain.
        </p>
      </header>

      {isLoading ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : (packages?.length ?? 0) === 0 ? (
        <EmptyState />
      ) : (
        <ul className="space-y-3">
          {packages!.map((p) => (
            <PackageCard key={p.id} pkg={p} />
          ))}
        </ul>
      )}
    </div>
  );
}

function PackageCard({ pkg }: { pkg: PortalPackage }) {
  const isActive = pkg.status === 'active' && !pkg.is_expired;
  const isPending = pkg.status === 'pending';

  const expiringSoon = useMemo(() => {
    if (!pkg.expires_at || pkg.is_expired) return false;
    const days = (new Date(pkg.expires_at).getTime() - Date.now()) / (1000 * 60 * 60 * 24);
    return days >= 0 && days <= 30;
  }, [pkg.expires_at, pkg.is_expired]);

  return (
    <article
      className={cn(
        'rounded-xl border bg-card shadow-sm overflow-hidden',
        isActive && 'ring-1 ring-[var(--portal-brand,#1f2937)]/20',
      )}
    >
      {isActive ? (
        <div
          className="h-1 w-full"
          style={{ background: 'var(--portal-brand, #1f2937)' }}
          aria-hidden
        />
      ) : null}
      <div className="p-5">
        <div className="flex items-start justify-between gap-3 mb-3">
          <div className="min-w-0 flex-1">
            <h2 className="text-lg font-medium tracking-tight truncate">
              {pkg.name}
            </h2>
            <p className="text-xs text-muted-foreground mt-1">
              ${dollarsFromCents(pkg.price_cents)}
              {pkg.purchased_at ? (
                <> · Purchased {formatDate(pkg.purchased_at)}</>
              ) : null}
            </p>
          </div>
          <StatusBadge status={pkg.status} isExpired={pkg.is_expired} />
        </div>

        {pkg.items.length > 0 ? (
          <ul className="rounded-lg border divide-y bg-background">
            {pkg.items.map((item, idx) => {
              const remaining = item.quantity_remaining;
              const purchased = item.quantity_purchased;
              const depleted = remaining <= 0;
              return (
                <li
                  key={`${pkg.id}-${idx}`}
                  className="flex items-center justify-between gap-3 px-3 py-2 text-sm"
                >
                  <span
                    className={cn(
                      'truncate',
                      depleted && 'text-muted-foreground line-through',
                    )}
                  >
                    {item.service_name}
                  </span>
                  <span
                    className={cn(
                      'shrink-0 font-mono tabular-nums text-xs',
                      depleted
                        ? 'text-muted-foreground'
                        : remaining <= 1
                          ? 'text-amber-700 font-semibold'
                          : 'text-foreground font-medium',
                    )}
                  >
                    {remaining} of {purchased} left
                  </span>
                </li>
              );
            })}
          </ul>
        ) : null}

        <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-[11px] text-muted-foreground">
          {pkg.expires_at ? (
            <span
              className={cn(
                'inline-flex items-center gap-1',
                expiringSoon && 'text-amber-700 font-medium',
              )}
            >
              <CalendarDays className="size-3" />
              {pkg.is_expired
                ? `Expired ${formatDate(pkg.expires_at)}`
                : `Expires ${formatDate(pkg.expires_at)}`}
              {expiringSoon ? ' · soon' : null}
            </span>
          ) : (
            <span>No expiration</span>
          )}
          {isPending ? (
            <span className="inline-flex items-center gap-1 text-amber-700">
              <Clock className="size-3" />
              Activates once the invoice is paid
            </span>
          ) : null}
        </div>
      </div>
    </article>
  );
}

function StatusBadge({
  status,
  isExpired,
}: {
  status: PortalPackageStatus;
  isExpired: boolean;
}) {
  if (isExpired) {
    return (
      <span className="shrink-0 inline-flex items-center gap-1 text-[10px] uppercase tracking-wide font-medium px-2 py-1 rounded-full border bg-muted text-muted-foreground border-muted-foreground/20 whitespace-nowrap">
        <Clock className="size-3" />
        Expired
      </span>
    );
  }
  const tone =
    status === 'active'
      ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
      : status === 'pending'
        ? 'bg-amber-50 text-amber-800 border-amber-200'
        : 'bg-muted text-muted-foreground border-muted-foreground/20';
  const Icon =
    status === 'active' ? CheckCircle2 : status === 'voided' ? XCircle : null;
  const label =
    status === 'active' ? 'Active' : status === 'pending' ? 'Pending' : 'Voided';
  return (
    <span
      className={cn(
        'shrink-0 inline-flex items-center gap-1 text-[10px] uppercase tracking-wide font-medium px-2 py-1 rounded-full border whitespace-nowrap',
        tone,
      )}
    >
      {Icon ? <Icon className="size-3" /> : null}
      {label}
    </span>
  );
}

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center text-center px-10 py-16 gap-3 rounded-xl border border-dashed bg-card">
      <div className="inline-flex size-12 items-center justify-center rounded-full bg-muted">
        <PackageIcon className="size-5 text-muted-foreground" />
      </div>
      <p className="font-medium">No packages yet</p>
      <p className="text-sm text-muted-foreground max-w-md">
        Packages save you money when you buy several sessions at once. Ask the
        front desk about current bundles.
      </p>
    </div>
  );
}

function formatDate(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });
}
