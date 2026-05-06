/**
 * Customer profile · Packages tab.
 *
 * Lists every PurchasedPackage (active first, then voided) with
 * per-service balance bars and a recent-redemption history per
 * package. No edit affordances here — sale + redemption happen on
 * invoices, not on the customer profile.
 */

'use client';

import {
  AlertCircle,
  CheckCircle2,
  Layers,
  Package as PackageIcon,
} from 'lucide-react';

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  type PurchasedPackage,
  useCustomerPurchasedPackages,
} from '@/lib/packages';
import { cn } from '@/lib/utils';

export function PackagesTab({ customerId }: { customerId: number }) {
  const { data, isLoading, error } = useCustomerPurchasedPackages(customerId);

  if (isLoading) {
    return (
      <Card>
        <CardContent className="py-8 text-center text-sm text-muted-foreground">
          Loading packages…
        </CardContent>
      </Card>
    );
  }
  if (error) {
    return (
      <Card>
        <CardContent className="py-8 text-center text-sm text-destructive">
          Could not load packages.
        </CardContent>
      </Card>
    );
  }

  const all = data ?? [];
  if (all.length === 0) {
    return <EmptyState />;
  }

  // Group by status — active first, pending mid (rare display state),
  // voided last. Within a group, newest purchases first.
  const active = all.filter((p) => p.status === 'active');
  const pending = all.filter((p) => p.status === 'pending');
  const voided = all.filter((p) => p.status === 'voided');

  return (
    <div className="space-y-8">
      {active.length > 0 ? (
        <Section title="Active" subtitle="Available to redeem at checkout.">
          <div className="space-y-4">
            {active.map((p) => (
              <PackageCard key={p.id} pkg={p} />
            ))}
          </div>
        </Section>
      ) : null}
      {pending.length > 0 ? (
        <Section
          title="Pending"
          subtitle="Sold but invoice hasn't closed yet — credits become available on payment."
          tone="muted"
        >
          <div className="space-y-4">
            {pending.map((p) => (
              <PackageCard key={p.id} pkg={p} />
            ))}
          </div>
        </Section>
      ) : null}
      {voided.length > 0 ? (
        <Section
          title="Voided"
          subtitle="Invoice was voided or the package was manually voided."
          tone="muted"
        >
          <div className="space-y-4">
            {voided.map((p) => (
              <PackageCard key={p.id} pkg={p} />
            ))}
          </div>
        </Section>
      ) : null}
    </div>
  );
}

function EmptyState() {
  return (
    <Card className="border-dashed">
      <CardContent className="py-12 text-center">
        <div className="inline-flex size-12 items-center justify-center rounded-full bg-emerald-50 text-emerald-700 mb-4">
          <Layers className="size-5" />
        </div>
        <p className="text-sm text-foreground font-medium">No packages yet</p>
        <p className="text-xs text-muted-foreground mt-1.5 max-w-md mx-auto leading-relaxed">
          Packages get created when this customer buys a bundle on an
          invoice. Each visit afterward, the front desk can redeem
          credits at checkout.
        </p>
      </CardContent>
    </Card>
  );
}

function Section({
  title,
  subtitle,
  tone,
  children,
}: {
  title: string;
  subtitle?: string;
  tone?: 'muted';
  children: React.ReactNode;
}) {
  return (
    <section>
      <header className="mb-3">
        <h2
          className={cn(
            'text-[11px] uppercase tracking-wide font-medium',
            tone === 'muted' ? 'text-muted-foreground/80' : 'text-foreground',
          )}
        >
          {title}
        </h2>
        {subtitle ? (
          <p className="text-xs text-muted-foreground/80 mt-0.5">{subtitle}</p>
        ) : null}
      </header>
      {children}
    </section>
  );
}

function PackageCard({ pkg }: { pkg: PurchasedPackage }) {
  const expiresLabel = pkg.expires_at
    ? new Date(pkg.expires_at).toLocaleDateString()
    : 'Never';

  return (
    <Card>
      <CardHeader className="flex-row items-start gap-3 space-y-0">
        <div className="inline-flex size-10 items-center justify-center rounded-md bg-emerald-50 text-emerald-700 shrink-0">
          <Layers className="size-5" />
        </div>
        <div className="min-w-0 flex-1">
          <CardTitle className="text-base font-medium">{pkg.name}</CardTitle>
          <p className="text-xs text-muted-foreground mt-0.5">
            ${(pkg.price_cents / 100).toFixed(2)}
            {pkg.purchased_at ? (
              <>
                {' '}
                · purchased{' '}
                {new Date(pkg.purchased_at).toLocaleDateString()}
              </>
            ) : (
              ' · pending payment'
            )}
            {pkg.expires_at ? <> · expires {expiresLabel}</> : null}
          </p>
        </div>
        <StatusPill pkg={pkg} />
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="space-y-2.5">
          {pkg.items.map((it) => {
            const usedCount = it.quantity_purchased - it.quantity_remaining;
            const pct =
              it.quantity_purchased === 0
                ? 0
                : (usedCount / it.quantity_purchased) * 100;
            return (
              <div key={it.id}>
                <div className="flex items-baseline justify-between text-sm mb-1">
                  <span className="font-medium">{it.service_name}</span>
                  <span className="text-muted-foreground tabular-nums">
                    {it.quantity_remaining} of {it.quantity_purchased} left
                  </span>
                </div>
                <div className="h-1.5 rounded-full bg-muted overflow-hidden">
                  <div
                    className={cn(
                      'h-full transition-[width]',
                      it.quantity_remaining === 0
                        ? 'bg-stone-300'
                        : 'bg-emerald-500',
                    )}
                    style={{ width: `${pct}%` }}
                  />
                </div>
              </div>
            );
          })}
        </div>

        {pkg.is_expired && pkg.status === 'active' ? (
          <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 flex items-start gap-2">
            <AlertCircle className="size-4 text-amber-600 shrink-0 mt-0.5" />
            <p className="text-xs text-amber-900 leading-relaxed">
              This package has expired. Remaining credits cannot be redeemed.
            </p>
          </div>
        ) : null}

        {pkg.redemptions.length > 0 ? (
          <div className="pt-2 border-t">
            <p className="text-[11px] uppercase tracking-wide text-muted-foreground font-medium mb-2">
              Recent redemptions
            </p>
            <ul className="space-y-1">
              {pkg.redemptions.slice(0, 5).map((r) => (
                <li
                  key={r.id}
                  className="flex items-baseline justify-between text-xs text-muted-foreground"
                >
                  <span>
                    {r.quantity > 0 ? '−' : '+'}
                    {Math.abs(r.quantity)} {r.service_name}
                  </span>
                  <span className="tabular-nums">
                    {new Date(r.redeemed_at).toLocaleDateString()}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}

function StatusPill({ pkg }: { pkg: PurchasedPackage }) {
  if (pkg.status === 'voided') {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-stone-100 text-stone-600 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider shrink-0">
        Voided
      </span>
    );
  }
  if (pkg.status === 'pending') {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-amber-50 text-amber-700 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider shrink-0">
        <span className="size-1.5 rounded-full bg-amber-500 animate-pulse" />
        Pending
      </span>
    );
  }
  if (pkg.is_expired) {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-amber-50 text-amber-700 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider shrink-0">
        Expired
      </span>
    );
  }
  if (pkg.total_credits_remaining === 0) {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-stone-100 text-stone-600 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider shrink-0">
        <PackageIcon className="size-2.5" />
        Used
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 text-emerald-700 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider shrink-0">
      <CheckCircle2 className="size-2.5" />
      Active
    </span>
  );
}
