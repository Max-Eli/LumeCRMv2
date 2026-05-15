/**
 * `/portal/memberships` — customer's subscription history.
 *
 * Active cycles first, then pending (paid invoice opened but not
 * yet flipped to active), then expired/cancelled for history.
 * Read-only — subscription changes (cancel, renew) flow through
 * staff so refunds + proration are handled deliberately.
 */

'use client';

import {
  Award,
  BadgeCheck,
  CalendarDays,
  Clock,
  XCircle,
} from 'lucide-react';

import { dollarsFromCents } from '@/lib/packages';
import {
  type PortalSubscription,
  type SubscriptionStatus,
  usePortalMemberships,
} from '@/lib/portal';
import { cn } from '@/lib/utils';

export default function PortalMembershipsPage() {
  const { data: subscriptions, isLoading } = usePortalMemberships();

  return (
    <div className="max-w-4xl mx-auto w-full px-6 py-10">
      <header className="mb-8">
        <h1 className="font-serif text-3xl font-semibold tracking-tight">
          Memberships
        </h1>
        <p className="text-sm text-muted-foreground mt-1.5">
          Your plan, member benefits, and history.
        </p>
      </header>

      {isLoading ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : (subscriptions?.length ?? 0) === 0 ? (
        <EmptyState />
      ) : (
        <ul className="space-y-3">
          {subscriptions!.map((s) => (
            <SubscriptionCard key={s.id} subscription={s} />
          ))}
        </ul>
      )}
    </div>
  );
}

function SubscriptionCard({ subscription }: { subscription: PortalSubscription }) {
  const isActive = subscription.status === 'active';
  const isCancelled = subscription.status === 'cancelled';
  const isPending = subscription.status === 'pending';

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
            <h2 className="text-lg font-medium tracking-tight">
              {subscription.name}
            </h2>
            {subscription.description ? (
              <p className="text-sm text-muted-foreground mt-1 line-clamp-2">
                {subscription.description}
              </p>
            ) : null}
          </div>
          <StatusBadge status={subscription.status} display={subscription.status_display} />
        </div>

        <dl className="grid grid-cols-2 gap-3 text-sm">
          <div>
            <dt className="text-[11px] uppercase tracking-wide text-muted-foreground font-medium">
              Price
            </dt>
            <dd className="mt-0.5 font-medium">
              ${dollarsFromCents(subscription.price_cents)}
              <span className="text-xs text-muted-foreground font-normal ml-1">
                / {subscription.billing_interval.replace('_', ' ')}
              </span>
            </dd>
          </div>
          {Number(subscription.member_discount_percent) > 0 ? (
            <div>
              <dt className="text-[11px] uppercase tracking-wide text-muted-foreground font-medium">
                Member discount
              </dt>
              <dd className="mt-0.5 font-medium inline-flex items-center gap-1">
                <BadgeCheck className="size-3.5 text-emerald-600" />
                {subscription.member_discount_percent}% off
              </dd>
            </div>
          ) : null}
          {subscription.current_period_starts_at && subscription.current_period_ends_at && !isCancelled ? (
            <div className="col-span-2">
              <dt className="text-[11px] uppercase tracking-wide text-muted-foreground font-medium">
                Current period
              </dt>
              <dd className="mt-0.5 text-sm flex items-center gap-1.5">
                <CalendarDays className="size-3.5 text-muted-foreground" />
                {formatDate(subscription.current_period_starts_at)} —{' '}
                {formatDate(subscription.current_period_ends_at)}
              </dd>
            </div>
          ) : null}
          {isCancelled && subscription.cancelled_at ? (
            <div className="col-span-2">
              <dt className="text-[11px] uppercase tracking-wide text-muted-foreground font-medium">
                Cancelled
              </dt>
              <dd className="mt-0.5 text-sm inline-flex items-center gap-1.5">
                <Clock className="size-3.5 text-muted-foreground" />
                {formatDate(subscription.cancelled_at)}
              </dd>
            </div>
          ) : null}
        </dl>

        {isPending ? (
          <p className="mt-4 text-[11px] text-muted-foreground border-t pt-3">
            Activates once the invoice is paid.
          </p>
        ) : null}
      </div>
    </article>
  );
}

function StatusBadge({
  status,
  display,
}: {
  status: SubscriptionStatus;
  display: string;
}) {
  const tone =
    status === 'active'
      ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
      : status === 'pending'
        ? 'bg-amber-50 text-amber-800 border-amber-200'
        : status === 'cancelled'
          ? 'bg-muted text-muted-foreground border-muted-foreground/20'
          : 'bg-muted text-muted-foreground border-muted-foreground/20';

  const Icon =
    status === 'active' ? BadgeCheck : status === 'cancelled' ? XCircle : null;

  return (
    <span
      className={cn(
        'shrink-0 inline-flex items-center gap-1 text-[10px] uppercase tracking-wide font-medium px-2 py-1 rounded-full border whitespace-nowrap',
        tone,
      )}
    >
      {Icon ? <Icon className="size-3" /> : null}
      {display}
    </span>
  );
}

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center text-center px-10 py-16 gap-3 rounded-xl border border-dashed bg-card">
      <div className="inline-flex size-12 items-center justify-center rounded-full bg-muted">
        <Award className="size-5 text-muted-foreground" />
      </div>
      <p className="font-medium">No memberships yet</p>
      <p className="text-sm text-muted-foreground max-w-md">
        Ask the front desk about our membership plans — members get exclusive
        pricing on services.
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
