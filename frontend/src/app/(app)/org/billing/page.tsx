/**
 * `/org/billing` — subscription + add-on management for the owner.
 *
 * What this page does:
 *   - Shows the active plan (Starter / Pro / Enterprise / Trial), the
 *     billing cycle, status, trial-end / next-renewal dates.
 *   - Surfaces current usage against caps: staff seats used / max,
 *     locations used / max, SMS sent / quota, emails sent / quota.
 *   - Lets the owner adjust add-on quantities (staff seats, locations
 *     [Pro only], email packs). Each change round-trips to Stripe
 *     immediately with prorated billing.
 *   - "Manage payment + invoices" button opens the Stripe-hosted
 *     billing portal in the same tab.
 *
 * Special states:
 *   - **Grandfathered tenants** (the original launch spas) get a
 *     "Contact support for billing changes" message instead of the
 *     self-serve controls. Their workspace is untouched by tier limits
 *     so nothing here gates them — this page is purely informational
 *     for them.
 *   - **Stripe not configured** (env vars empty in this deploy) shows
 *     a yellow callout + disables the buttons. Read-only state still
 *     works so onboarding can preview the page before keys are wired.
 *   - **Trial / Past-due / Suspended status**: status-specific banner
 *     at the top with a clear next action.
 *
 * Permission: ``MANAGE_BILLING`` (owner-only by default; locked
 * against per-user override in the permission catalog).
 */

'use client';

import {
  AlertTriangle,
  CreditCard,
  ExternalLink,
  Info,
  Loader2,
  Minus,
  Plus,
} from 'lucide-react';
import { useState } from 'react';
import { toast } from 'sonner';

import { PageHeader } from '@/components/page-header';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { ApiError } from '@/lib/api';
import {
  type AddonKey,
  type BillingSummary,
  billingErrorMessage,
  useBillingSummary,
  useOpenStripePortal,
  useUpdateAddonQuantity,
} from '@/lib/billing';
import { cn } from '@/lib/utils';

const PLAN_LABEL: Record<string, string> = {
  trial: 'Trial',
  starter: 'Starter',
  pro: 'Pro',
  enterprise: 'Enterprise',
};

const STATUS_TONE: Record<
  string,
  { label: string; bg: string; text: string }
> = {
  trial: { label: 'Trial', bg: 'bg-blue-50', text: 'text-blue-800' },
  active: { label: 'Active', bg: 'bg-emerald-50', text: 'text-emerald-800' },
  past_due: { label: 'Past due', bg: 'bg-amber-50', text: 'text-amber-800' },
  suspended: { label: 'Suspended', bg: 'bg-red-50', text: 'text-red-800' },
  cancelled: { label: 'Cancelled', bg: 'bg-muted', text: 'text-muted-foreground' },
};

// Friendly labels per add-on key. Keep in sync with backend `plans.py`.
const ADDON_LABEL: Record<AddonKey, { name: string; unit: string }> = {
  staff: { name: 'Extra staff seats', unit: 'seat' },
  location: { name: 'Extra locations', unit: 'location' },
  email_5k: { name: 'Email packs (5,000)', unit: 'pack' },
  email_10k: { name: 'Email packs (10,000)', unit: 'pack' },
};

export default function OrgBillingPage() {
  const { data, isLoading, error } = useBillingSummary();

  if (isLoading) {
    return (
      <div className="px-10 py-10 max-w-5xl">
        <PageHeader title="Billing" description="Loading…" />
      </div>
    );
  }
  if (error) {
    if (error instanceof ApiError && error.status === 403) {
      return (
        <div className="px-10 py-10 max-w-5xl">
          <PageHeader title="Billing" />
          <Card>
            <CardContent className="py-8 text-center text-sm text-muted-foreground">
              Billing settings are restricted to the account owner.
            </CardContent>
          </Card>
        </div>
      );
    }
    return (
      <div className="px-10 py-10 max-w-5xl">
        <PageHeader title="Billing" />
        <p className="text-sm text-destructive">Could not load billing details.</p>
      </div>
    );
  }
  if (!data) return null;

  return <BillingBody summary={data} />;
}

function BillingBody({ summary }: { summary: BillingSummary }) {
  const status = STATUS_TONE[summary.status] ?? STATUS_TONE.active;

  return (
    <div className="px-6 sm:px-10 py-8 sm:py-10 space-y-6 max-w-5xl">
      <PageHeader
        title="Billing"
        description="Manage your subscription, add-ons, and payment method."
      />

      <StatusBanner summary={summary} />

      <Card>
        <CardContent className="p-6 space-y-6">
          <div className="flex items-start justify-between gap-4 flex-wrap">
            <div className="space-y-1">
              <p className="text-[11px] uppercase tracking-wide text-muted-foreground">
                Current plan
              </p>
              <div className="flex items-baseline gap-3">
                <h2 className="text-2xl font-semibold font-serif">
                  {PLAN_LABEL[summary.plan] ?? summary.plan}
                </h2>
                <span
                  className={cn(
                    'inline-flex items-center px-2 py-0.5 rounded text-[11px] font-medium uppercase tracking-wide',
                    status.bg,
                    status.text,
                  )}
                >
                  {status.label}
                </span>
              </div>
              <p className="text-xs text-muted-foreground">
                Billed {summary.billing_cycle}
                {summary.grandfathered ? ' · Legacy account' : null}
              </p>
            </div>
            <PortalButton summary={summary} />
          </div>

          <DatesLine summary={summary} />
        </CardContent>
      </Card>

      <UsageBlock summary={summary} />

      <AddonsBlock summary={summary} />

      <ContactBlock />
    </div>
  );
}

// ── Status banner ────────────────────────────────────────────────

function StatusBanner({ summary }: { summary: BillingSummary }) {
  if (summary.grandfathered) {
    return (
      <Banner tone="info" icon={<Info className="size-4" />}>
        This account is on a <strong>legacy plan</strong>. Capacity caps
        don&apos;t apply and add-on management is handled by support — email{' '}
        <a href="mailto:support@lume-crm.com" className="underline">support@lume-crm.com</a>{' '}
        for any billing changes.
      </Banner>
    );
  }
  if (summary.status === 'past_due') {
    return (
      <Banner tone="warning" icon={<AlertTriangle className="size-4" />}>
        Your last payment didn&apos;t go through. Update your card to keep
        your workspace active — we&apos;ll automatically retry within a
        few days.
      </Banner>
    );
  }
  if (summary.status === 'suspended') {
    return (
      <Banner tone="danger" icon={<AlertTriangle className="size-4" />}>
        Your workspace is suspended for non-payment. Update your card to
        restore access immediately.
      </Banner>
    );
  }
  if (summary.status === 'trial' && summary.trial_ends_at) {
    const daysLeft = daysUntil(summary.trial_ends_at);
    return (
      <Banner tone="info" icon={<Info className="size-4" />}>
        {daysLeft > 1 ? `${daysLeft} days left in your trial.` : 'Your trial ends today.'}{' '}
        Your card will be charged automatically when the trial ends.
      </Banner>
    );
  }
  if (!summary.stripe_configured) {
    return (
      <Banner tone="info" icon={<Info className="size-4" />}>
        Stripe billing isn&apos;t configured in this environment yet.
        The page is read-only until the keys are wired up.
      </Banner>
    );
  }
  return null;
}

function Banner({
  tone,
  icon,
  children,
}: {
  tone: 'info' | 'warning' | 'danger';
  icon: React.ReactNode;
  children: React.ReactNode;
}) {
  const palette = {
    info: 'bg-blue-50 border-blue-200 text-blue-900',
    warning: 'bg-amber-50 border-amber-200 text-amber-900',
    danger: 'bg-red-50 border-red-200 text-red-900',
  }[tone];
  return (
    <div className={cn('flex items-start gap-3 rounded-lg border px-4 py-3 text-sm', palette)}>
      <span className="shrink-0 mt-0.5">{icon}</span>
      <div className="leading-relaxed">{children}</div>
    </div>
  );
}

// ── Portal button ────────────────────────────────────────────────

function PortalButton({ summary }: { summary: BillingSummary }) {
  const open = useOpenStripePortal();

  const disabled =
    summary.grandfathered
    || !summary.stripe_configured
    || !summary.has_stripe_subscription;

  const onClick = () => {
    open.mutate(
      { returnUrl: window.location.href },
      {
        onError: (err) =>
          toast.error(
            billingErrorMessage(err, "Couldn't open the billing portal."),
          ),
      },
    );
  };

  return (
    <Button
      type="button"
      variant="outline"
      disabled={disabled || open.isPending}
      onClick={onClick}
    >
      {open.isPending ? (
        <Loader2 className="size-4 animate-spin" />
      ) : (
        <CreditCard className="size-4" />
      )}
      Manage payment + invoices
      <ExternalLink className="size-3.5 ml-1" />
    </Button>
  );
}

// ── Dates ────────────────────────────────────────────────────────

function DatesLine({ summary }: { summary: BillingSummary }) {
  const pieces: { label: string; value: string }[] = [];
  if (summary.trial_ends_at) {
    pieces.push({ label: 'Trial ends', value: formatDate(summary.trial_ends_at) });
  }
  if (summary.current_period_end) {
    pieces.push({
      label: summary.status === 'trial' ? 'First charge' : 'Next renewal',
      value: formatDate(summary.current_period_end),
    });
  }
  if (summary.billing_email) {
    pieces.push({ label: 'Billing email', value: summary.billing_email });
  }
  if (pieces.length === 0) return null;
  return (
    <dl className="grid grid-cols-2 sm:grid-cols-3 gap-x-6 gap-y-3 text-xs">
      {pieces.map((piece) => (
        <div key={piece.label}>
          <dt className="text-muted-foreground uppercase tracking-wide text-[10px]">
            {piece.label}
          </dt>
          <dd className="text-sm mt-0.5">{piece.value}</dd>
        </div>
      ))}
    </dl>
  );
}

// ── Usage ────────────────────────────────────────────────────────

function UsageBlock({ summary }: { summary: BillingSummary }) {
  const rows: Array<{ label: string; used: number; cap: number | null }> = [
    {
      label: 'Staff seats',
      used: summary.usage.staff_count,
      cap: summary.capacity.max_staff,
    },
    {
      label: 'Locations',
      used: summary.usage.location_count,
      cap: summary.capacity.max_locations,
    },
    {
      label: 'SMS this period',
      used: summary.usage.sms_used,
      cap: summary.capacity.sms_quota,
    },
    {
      label: 'Emails this period',
      used: summary.usage.email_used,
      cap: summary.capacity.email_quota,
    },
  ];
  return (
    <Card>
      <CardContent className="p-6 space-y-4">
        <h3 className="text-sm font-medium">Usage</h3>
        <div className="space-y-3">
          {rows.map((row) => (
            <UsageRow key={row.label} {...row} />
          ))}
        </div>
        {summary.status === 'trial' ? (
          <p className="text-[11px] text-muted-foreground">
            SMS overage during the trial is reported but not billed
            until your card is charged at trial end.
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}

function UsageRow({
  label,
  used,
  cap,
}: {
  label: string;
  used: number;
  cap: number | null;
}) {
  // Null cap = unlimited (grandfathered / enterprise). Show ∞.
  const isUnlimited = cap === null;
  const percent =
    isUnlimited || cap === 0
      ? 0
      : Math.min(100, Math.round((used / cap) * 100));
  const overBudget = !isUnlimited && cap !== null && used > cap;

  return (
    <div className="space-y-1">
      <div className="flex items-baseline justify-between text-xs">
        <span className="text-muted-foreground">{label}</span>
        <span className="font-mono tabular-nums">
          {used.toLocaleString()}{' '}
          <span className="text-muted-foreground">
            / {isUnlimited ? '∞' : cap?.toLocaleString()}
          </span>
        </span>
      </div>
      <div className="h-1.5 rounded-full bg-muted overflow-hidden">
        {!isUnlimited ? (
          <div
            className={cn(
              'h-full transition-all',
              overBudget
                ? 'bg-red-500'
                : percent >= 80
                  ? 'bg-amber-500'
                  : 'bg-foreground',
            )}
            style={{ width: `${percent}%` }}
          />
        ) : null}
      </div>
    </div>
  );
}

// ── Add-ons ──────────────────────────────────────────────────────

function AddonsBlock({ summary }: { summary: BillingSummary }) {
  const allowedKeys = Object.keys(summary.allowed_addons) as AddonKey[];
  if (allowedKeys.length === 0) {
    return null; // grandfathered or no allowed add-ons on this plan
  }

  return (
    <Card>
      <CardContent className="p-6 space-y-4">
        <div>
          <h3 className="text-sm font-medium">Add-ons</h3>
          <p className="text-xs text-muted-foreground mt-1">
            Scale up your plan with metered add-ons. Changes are
            prorated to your current billing period.
          </p>
        </div>
        <div className="space-y-3">
          {allowedKeys.map((key) => (
            <AddonRow
              key={key}
              addonKey={key}
              current={summary.addons[key] ?? 0}
              maxQuantity={summary.allowed_addons[key].max_quantity}
              disabled={
                !summary.stripe_configured
                || !summary.has_stripe_subscription
              }
            />
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

function AddonRow({
  addonKey,
  current,
  maxQuantity,
  disabled,
}: {
  addonKey: AddonKey;
  current: number;
  maxQuantity: number | null;
  disabled: boolean;
}) {
  const update = useUpdateAddonQuantity();
  // Optimistic UI: track the desired quantity locally so the buttons
  // don't lag a roundtrip behind the user's click.
  const [pendingValue, setPendingValue] = useState<number | null>(null);

  const value = pendingValue ?? current;
  const label = ADDON_LABEL[addonKey];
  const atMax = maxQuantity !== null && value >= maxQuantity;
  const atMin = value <= 0;

  const set = (next: number) => {
    if (next < 0) return;
    if (maxQuantity !== null && next > maxQuantity) return;
    setPendingValue(next);
    update.mutate(
      { addon_key: addonKey, quantity: next },
      {
        onSuccess: () => {
          toast.success(
            next === 0
              ? `Removed ${label.name.toLowerCase()}`
              : `${label.name}: ${next}`,
          );
          setPendingValue(null);
        },
        onError: (err) => {
          toast.error(billingErrorMessage(err, "Couldn't update add-on."));
          setPendingValue(null);
        },
      },
    );
  };

  return (
    <div className="flex items-center justify-between gap-4">
      <div className="min-w-0 flex-1">
        <p className="text-sm">{label.name}</p>
        <p className="text-[11px] text-muted-foreground">
          {value} {value === 1 ? label.unit : `${label.unit}s`} active
          {maxQuantity !== null ? ` · up to ${maxQuantity}` : null}
        </p>
      </div>
      <div className="inline-flex items-center rounded-md border bg-card overflow-hidden">
        <button
          type="button"
          onClick={() => set(value - 1)}
          disabled={disabled || atMin || update.isPending}
          className="inline-flex size-9 items-center justify-center text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-30 disabled:hover:bg-card transition-colors"
          aria-label={`Decrease ${label.name}`}
        >
          <Minus className="size-4" />
        </button>
        <span className="inline-flex min-w-[2.5rem] h-9 items-center justify-center text-sm font-mono tabular-nums border-x">
          {value}
        </span>
        <button
          type="button"
          onClick={() => set(value + 1)}
          disabled={disabled || atMax || update.isPending}
          className="inline-flex size-9 items-center justify-center text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-30 disabled:hover:bg-card transition-colors"
          aria-label={`Increase ${label.name}`}
        >
          <Plus className="size-4" />
        </button>
      </div>
    </div>
  );
}

// ── Contact / upgrade-tier rail ─────────────────────────────────

function ContactBlock() {
  return (
    <Card className="border-dashed">
      <CardContent className="p-6 flex items-start gap-4 flex-wrap">
        <div className="flex-1 min-w-0">
          <h3 className="text-sm font-medium">Need a different tier?</h3>
          <p className="text-xs text-muted-foreground mt-1 leading-relaxed">
            Upgrading to Pro (more locations, marketing campaigns,
            commissions, white-label) or Enterprise (custom volume + SSO
            + multi-location reporting + dedicated support) is a
            quick conversation — we&apos;ll walk through what makes
            sense and migrate you the same day.
          </p>
        </div>
        <Button
          nativeButton={false}
          render={(props) => (
            <a
              {...props}
              href="https://lume-crm.com/demo"
              target="_blank"
              rel="noopener noreferrer"
            >
              Book a demo
              <ExternalLink className="size-3.5 ml-1" />
            </a>
          )}
        />
      </CardContent>
    </Card>
  );
}

// ── Helpers ──────────────────────────────────────────────────────

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });
}

function daysUntil(iso: string): number {
  const target = new Date(iso).getTime();
  const now = Date.now();
  return Math.max(0, Math.ceil((target - now) / (24 * 60 * 60 * 1000)));
}
