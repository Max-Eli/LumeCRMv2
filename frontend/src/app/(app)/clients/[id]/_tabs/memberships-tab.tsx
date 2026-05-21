/**
 * Customer profile · Memberships tab.
 *
 * Lists every Subscription (active first, then pending, expired,
 * cancelled). Each card shows the plan name, billing cycle,
 * current-period balance bars per service, and the recent
 * redemption ledger. Cancel button on active rows for owners /
 * managers.
 */

'use client';

import {
  AlertCircle,
  Ban,
  CheckCircle2,
  CreditCard,
  Loader2,
  Repeat,
} from 'lucide-react';
import { useState } from 'react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Field, FieldLabel } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { ApiError } from '@/lib/api';
import { useCurrentMembership } from '@/lib/auth';
import {
  type Subscription,
  BILLING_INTERVAL_LABELS,
  useCancelSubscription,
  useCustomerSubscriptions,
} from '@/lib/subscriptions';
import { cn } from '@/lib/utils';

export function MembershipsTab({ customerId }: { customerId: number }) {
  const { data, isLoading, error } = useCustomerSubscriptions(customerId);

  if (isLoading) {
    return (
      <Card>
        <CardContent className="py-8 text-center text-sm text-muted-foreground">
          Loading memberships…
        </CardContent>
      </Card>
    );
  }
  if (error) {
    return (
      <Card>
        <CardContent className="py-8 text-center text-sm text-destructive">
          Could not load memberships.
        </CardContent>
      </Card>
    );
  }

  const all = data ?? [];
  if (all.length === 0) {
    return <EmptyState />;
  }

  const active = all.filter((s) => s.status === 'active');
  const pending = all.filter((s) => s.status === 'pending');
  const expired = all.filter((s) => s.status === 'expired');
  const cancelled = all.filter((s) => s.status === 'cancelled');

  return (
    <div className="space-y-8">
      {active.length > 0 ? (
        <Section
          title="Active"
          subtitle="Available to redeem during the current billing period."
        >
          <div className="space-y-4">
            {active.map((s) => (
              <SubscriptionCard key={s.id} sub={s} />
            ))}
          </div>
        </Section>
      ) : null}
      {pending.length > 0 ? (
        <Section
          title="Pending"
          subtitle="Sold but invoice hasn't closed — credits become available on payment."
          tone="muted"
        >
          <div className="space-y-4">
            {pending.map((s) => (
              <SubscriptionCard key={s.id} sub={s} />
            ))}
          </div>
        </Section>
      ) : null}
      {expired.length > 0 ? (
        <Section
          title="Expired"
          subtitle="Past billing periods. Sell a fresh cycle to renew."
          tone="muted"
        >
          <div className="space-y-4">
            {expired.map((s) => (
              <SubscriptionCard key={s.id} sub={s} />
            ))}
          </div>
        </Section>
      ) : null}
      {cancelled.length > 0 ? (
        <Section
          title="Cancelled"
          subtitle="Voided subscriptions kept for the audit trail."
          tone="muted"
        >
          <div className="space-y-4">
            {cancelled.map((s) => (
              <SubscriptionCard key={s.id} sub={s} />
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
        <div className="inline-flex size-12 items-center justify-center rounded-full bg-violet-50 text-violet-700 mb-4">
          <CreditCard className="size-5" />
        </div>
        <p className="text-sm text-foreground font-medium">
          No memberships yet
        </p>
        <p className="text-xs text-muted-foreground mt-1.5 max-w-md mx-auto leading-relaxed">
          Memberships get created when this customer buys a plan on an
          invoice. Each cycle, the front desk can redeem included
          services + apply member-only pricing.
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

function SubscriptionCard({ sub }: { sub: Subscription }) {
  const me = useCurrentMembership();
  const canCancel = me?.role === 'owner' || me?.role === 'manager';
  const [confirmingCancel, setConfirmingCancel] = useState(false);
  const [reason, setReason] = useState('');
  const cancel = useCancelSubscription(sub.id);

  const periodEndsLabel = sub.current_period_ends_at
    ? new Date(sub.current_period_ends_at).toLocaleDateString()
    : null;

  const onCancel = () => {
    if (!reason.trim()) {
      toast.error('A reason is required.');
      return;
    }
    cancel.mutate(
      { reason: reason.trim() },
      {
        onSuccess: () => {
          toast.success('Subscription cancelled');
          setConfirmingCancel(false);
        },
        onError: (err) => {
          if (err instanceof ApiError && err.body && typeof err.body === 'object') {
            const body = err.body as { detail?: string };
            if (body.detail) {
              toast.error(body.detail);
              return;
            }
          }
          toast.error('Could not cancel.');
        },
      },
    );
  };

  return (
    <Card>
      <CardHeader className="flex-row items-start gap-3 space-y-0">
        <div className="inline-flex size-10 items-center justify-center rounded-md bg-violet-50 text-violet-700 shrink-0">
          <CreditCard className="size-5" />
        </div>
        <div className="min-w-0 flex-1">
          <CardTitle className="text-base font-medium">{sub.name}</CardTitle>
          <p className="text-xs text-muted-foreground mt-0.5 inline-flex items-center gap-1.5 flex-wrap">
            ${(sub.price_cents / 100).toFixed(2)}
            <span className="inline-flex items-center gap-1">
              <Repeat className="size-3" />
              {BILLING_INTERVAL_LABELS[sub.billing_interval]}
            </span>
            {sub.started_at ? (
              <>
                · started {new Date(sub.started_at).toLocaleDateString()}
              </>
            ) : (
              ' · pending payment'
            )}
            {periodEndsLabel && sub.status === 'active' ? (
              <> · period ends {periodEndsLabel}</>
            ) : null}
            {Number(sub.member_discount_percent) > 0 ? (
              <span className="text-emerald-700">
                · {sub.member_discount_percent}% member rate
              </span>
            ) : null}
          </p>
        </div>
        <StatusPill sub={sub} />
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="space-y-2.5">
          {sub.items.map((it) => {
            const used = it.quantity_per_cycle - it.quantity_remaining;
            const pct =
              it.quantity_per_cycle === 0
                ? 0
                : (used / it.quantity_per_cycle) * 100;
            return (
              <div key={it.id}>
                <div className="flex items-baseline justify-between text-sm mb-1">
                  <span className="font-medium">
                    {it.item_type === 'category'
                      ? `Any ${it.category_name}`
                      : it.service_name}
                  </span>
                  <span className="text-muted-foreground tabular-nums">
                    {it.quantity_remaining} of {it.quantity_per_cycle} this cycle
                  </span>
                </div>
                <div className="h-1.5 rounded-full bg-muted overflow-hidden">
                  <div
                    className={cn(
                      'h-full transition-[width]',
                      it.quantity_remaining === 0
                        ? 'bg-stone-300'
                        : 'bg-violet-500',
                    )}
                    style={{ width: `${pct}%` }}
                  />
                </div>
              </div>
            );
          })}
        </div>

        {sub.status === 'active' && !sub.is_in_period ? (
          <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 flex items-start gap-2">
            <AlertCircle className="size-4 text-amber-600 shrink-0 mt-0.5" />
            <p className="text-xs text-amber-900 leading-relaxed">
              This subscription is past its current period. Sell a renewal
              cycle to restore credits.
            </p>
          </div>
        ) : null}

        {sub.redemptions.length > 0 ? (
          <div className="pt-2 border-t">
            <p className="text-[11px] uppercase tracking-wide text-muted-foreground font-medium mb-2">
              Recent redemptions
            </p>
            <ul className="space-y-1">
              {sub.redemptions.slice(0, 5).map((r) => (
                <li
                  key={r.id}
                  className="flex items-baseline justify-between text-xs text-muted-foreground"
                >
                  <span>
                    {r.quantity > 0 ? '−' : '+'}
                    {Math.abs(r.quantity)} {r.service_name}
                    {r.credit_kind === 'category' && r.category_name ? (
                      <span className="text-muted-foreground/60">
                        {' '}
                        · {r.category_name} credit
                      </span>
                    ) : null}
                  </span>
                  <span className="tabular-nums">
                    {new Date(r.redeemed_at).toLocaleDateString()}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        {sub.status === 'cancelled' && sub.cancel_reason ? (
          <div className="text-xs text-muted-foreground pt-2 border-t">
            <span className="font-medium">Cancelled:</span> {sub.cancel_reason}
            {sub.cancelled_at ? (
              <> ({new Date(sub.cancelled_at).toLocaleDateString()})</>
            ) : null}
          </div>
        ) : null}

        {canCancel
        && (sub.status === 'active' || sub.status === 'pending')
        && !confirmingCancel ? (
          <div className="pt-2 border-t flex justify-end">
            <button
              type="button"
              onClick={() => setConfirmingCancel(true)}
              className="text-xs text-muted-foreground hover:text-destructive inline-flex items-center gap-1.5"
            >
              <Ban className="size-3.5" />
              Cancel subscription
            </button>
          </div>
        ) : null}

        {confirmingCancel ? (
          <div className="pt-3 border-t space-y-3">
            <Field>
              <FieldLabel htmlFor={`cancel-reason-${sub.id}`}>
                Cancellation reason
              </FieldLabel>
              <Input
                id={`cancel-reason-${sub.id}`}
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                placeholder="e.g. Customer request, moved away…"
              />
            </Field>
            <div className="flex items-center justify-end gap-2">
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => {
                  setConfirmingCancel(false);
                  setReason('');
                }}
              >
                Keep
              </Button>
              <Button
                type="button"
                size="sm"
                onClick={onCancel}
                disabled={cancel.isPending}
              >
                {cancel.isPending ? (
                  <Loader2 className="size-3.5 animate-spin" />
                ) : null}
                Cancel subscription
              </Button>
            </div>
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}

function StatusPill({ sub }: { sub: Subscription }) {
  if (sub.status === 'cancelled') {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-stone-100 text-stone-600 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider shrink-0">
        Cancelled
      </span>
    );
  }
  if (sub.status === 'expired') {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-stone-100 text-stone-600 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider shrink-0">
        Expired
      </span>
    );
  }
  if (sub.status === 'pending') {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-amber-50 text-amber-700 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider shrink-0">
        <span className="size-1.5 rounded-full bg-amber-500 animate-pulse" />
        Pending
      </span>
    );
  }
  // active
  if (!sub.is_in_period) {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-amber-50 text-amber-700 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider shrink-0">
        Period ended
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
