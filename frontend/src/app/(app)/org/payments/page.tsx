/**
 * `/org/payments` — Stripe Connect onboarding for the spa.
 *
 * This page is how the spa connects their own Stripe account so
 * they can take card payments from THEIR customers (via the
 * invoice charge-card flow shipping next chunk). It is intentionally
 * distinct from `/org/billing`, which is where the spa manages
 * their Lumè subscription with Voxtro LLC.
 *
 * State machine the page renders:
 *
 *   1. Stripe not configured (env vars empty)
 *      → Info banner; controls disabled.
 *
 *   2. Grandfathered tenant
 *      → "Contact support" copy; no self-serve onboarding.
 *
 *   3. Provider = stripe_connect, no stripe_account_id yet
 *      → "Connect Stripe" CTA → starts Express onboarding.
 *
 *   4. Provider = stripe_connect, account exists, details_submitted=false
 *      → "Finish onboarding" CTA (resumes the Stripe-hosted flow).
 *
 *   5. Provider = stripe_connect, details_submitted=true but
 *      charges_enabled=false or payouts_enabled=false
 *      → "Stripe is reviewing your account" + Refresh status button.
 *
 *   6. is_ready_to_charge = true
 *      → Green "Ready to take payments" card + link to Stripe
 *      Express Dashboard for refunds / payouts / disputes.
 *
 *   7. disabled_at != null
 *      → Red "Connection revoked" + Reconnect CTA.
 *
 *   8. Provider = custom
 *      → "Custom merchant configured by support" read-only card.
 *
 * Permission: MANAGE_BILLING (owner-only).
 */

'use client';

import {
  AlertCircle,
  CheckCircle2,
  CreditCard,
  ExternalLink,
  Info,
  Loader2,
  RefreshCw,
} from 'lucide-react';
import { useSearchParams } from 'next/navigation';
import { useEffect } from 'react';
import { toast } from 'sonner';

import { PageHeader } from '@/components/page-header';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { ApiError } from '@/lib/api';
import { useCurrentMembership } from '@/lib/auth';
import {
  type PaymentsSummary,
  paymentsErrorMessage,
  usePaymentsSummary,
  useRefreshPaymentsStatus,
  useStartOnboarding,
} from '@/lib/payments';
import { cn } from '@/lib/utils';

export default function OrgPaymentsPage() {
  const searchParams = useSearchParams();
  const refresh = useRefreshPaymentsStatus();

  // When the spa returns from the Stripe-hosted onboarding flow,
  // Stripe redirects back with ?onboarded=1. Pull a fresh status
  // immediately so the page reflects the new state without the
  // 30-second cache delay or waiting on the webhook.
  useEffect(() => {
    if (searchParams.get('onboarded') === '1') {
      refresh.mutate();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const { data, isLoading, error } = usePaymentsSummary();

  if (isLoading) {
    return (
      <div className="px-10 py-10 max-w-5xl">
        <PageHeader title="Payment processing" description="Loading…" />
      </div>
    );
  }
  if (error) {
    if (error instanceof ApiError && error.status === 403) {
      return (
        <div className="px-10 py-10 max-w-5xl">
          <PageHeader title="Payment processing" />
          <Card>
            <CardContent className="py-8 text-center text-sm text-muted-foreground">
              Payment-processing settings are restricted to the account
              owner.
            </CardContent>
          </Card>
        </div>
      );
    }
    return (
      <div className="px-10 py-10 max-w-5xl">
        <PageHeader title="Payment processing" />
        <p className="text-sm text-destructive">
          Could not load payment-processing status.
        </p>
      </div>
    );
  }
  if (!data) return null;

  return <PaymentsBody summary={data} />;
}

function PaymentsBody({ summary }: { summary: PaymentsSummary }) {
  const membership = useCurrentMembership();
  const isGrandfathered =
    !!membership?.tenant && (membership.tenant as { grandfathered?: boolean }).grandfathered === true;

  return (
    <div className="px-6 sm:px-10 py-8 sm:py-10 space-y-6 max-w-5xl">
      <PageHeader
        title="Payment processing"
        description="Connect your Stripe account so your spa can take card payments from customers at checkout."
      />

      {isGrandfathered ? (
        <GrandfatheredCard />
      ) : !summary.stripe_configured ? (
        <NotConfiguredCard />
      ) : summary.provider === 'custom' ? (
        <CustomMerchantCard />
      ) : (
        <ConnectStateCard summary={summary} />
      )}

      <HelpBlock />
    </div>
  );
}

// ── State cards ──────────────────────────────────────────────────

function GrandfatheredCard() {
  return (
    <Card>
      <CardContent className="p-6">
        <div className="flex items-start gap-3">
          <Info className="size-5 shrink-0 text-blue-600 dark:text-blue-400 mt-0.5" />
          <div className="space-y-2">
            <h2 className="font-medium">Legacy account</h2>
            <p className="text-sm text-muted-foreground leading-relaxed">
              This account predates Lumè&apos;s self-serve payment
              processing. To configure card processing on a legacy
              tenant, email{' '}
              <a
                href="mailto:support@lume-crm.com"
                className="underline text-foreground"
              >
                support@lume-crm.com
              </a>{' '}
              — we&apos;ll wire it up manually.
            </p>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function NotConfiguredCard() {
  return (
    <Card>
      <CardContent className="p-6">
        <div className="flex items-start gap-3">
          <Info className="size-5 shrink-0 text-amber-600 dark:text-amber-400 mt-0.5" />
          <div className="space-y-2">
            <h2 className="font-medium">Payment processing not yet enabled</h2>
            <p className="text-sm text-muted-foreground leading-relaxed">
              Stripe integration isn&apos;t configured in this
              environment yet. Card-processing setup will appear here
              once the platform keys are wired up.
            </p>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function CustomMerchantCard() {
  return (
    <Card>
      <CardContent className="p-6 space-y-2">
        <div className="flex items-start gap-3">
          <CheckCircle2 className="size-5 shrink-0 text-emerald-600 dark:text-emerald-400 mt-0.5" />
          <div className="space-y-1">
            <h2 className="font-medium">Custom merchant configured</h2>
            <p className="text-sm text-muted-foreground leading-relaxed">
              Your spa is set up with a custom payment processor.
              Changes are handled by support — email{' '}
              <a
                href="mailto:support@lume-crm.com"
                className="underline text-foreground"
              >
                support@lume-crm.com
              </a>.
            </p>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function ConnectStateCard({ summary }: { summary: PaymentsSummary }) {
  // Three primary states + two edge states. Pick which to render.
  if (summary.disabled_at) {
    return <ReconnectCard summary={summary} />;
  }
  if (summary.is_ready_to_charge) {
    return <ReadyCard summary={summary} />;
  }
  if (summary.stripe_account_id && summary.details_submitted) {
    return <UnderReviewCard summary={summary} />;
  }
  if (summary.stripe_account_id) {
    return <ResumeOnboardingCard />;
  }
  return <NotConnectedCard />;
}

function NotConnectedCard() {
  const start = useStartOnboarding();
  return (
    <Card>
      <CardContent className="p-6 space-y-5">
        <div className="flex items-start gap-3">
          <CreditCard className="size-5 shrink-0 text-foreground mt-0.5" />
          <div className="space-y-1">
            <h2 className="font-medium">Connect Stripe to take card payments</h2>
            <p className="text-sm text-muted-foreground leading-relaxed">
              Set up a Stripe account through Lumè in about three
              minutes. Your customers&apos; cards charge directly to
              your Stripe account (we never touch the money). Standard
              Stripe rates apply: 2.9% + 30¢ per charge. No Lumè
              markup.
            </p>
          </div>
        </div>
        <div className="flex flex-wrap gap-3 items-center">
          <Button
            type="button"
            onClick={() => {
              start.mutate(undefined, {
                onError: (err) =>
                  toast.error(
                    paymentsErrorMessage(
                      err,
                      "Couldn't open the Stripe onboarding flow.",
                    ),
                  ),
              });
            }}
            disabled={start.isPending}
          >
            {start.isPending ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <CreditCard className="size-4" />
            )}
            Connect Stripe
            <ExternalLink className="size-3.5" />
          </Button>
          <span className="text-xs text-muted-foreground">
            You&apos;ll be redirected to Stripe to complete the
            business verification.
          </span>
        </div>
      </CardContent>
    </Card>
  );
}

function ResumeOnboardingCard() {
  const start = useStartOnboarding();
  return (
    <Card>
      <CardContent className="p-6 space-y-5">
        <div className="flex items-start gap-3">
          <Info className="size-5 shrink-0 text-amber-600 dark:text-amber-400 mt-0.5" />
          <div className="space-y-1">
            <h2 className="font-medium">Finish setting up Stripe</h2>
            <p className="text-sm text-muted-foreground leading-relaxed">
              Your Stripe account was created but the business
              verification isn&apos;t complete yet. Resume the
              onboarding flow to start taking card payments.
            </p>
          </div>
        </div>
        <Button
          type="button"
          onClick={() => {
            start.mutate(undefined, {
              onError: (err) =>
                toast.error(
                  paymentsErrorMessage(
                    err,
                    "Couldn't reopen the onboarding flow.",
                  ),
                ),
            });
          }}
          disabled={start.isPending}
        >
          {start.isPending ? (
            <Loader2 className="size-4 animate-spin" />
          ) : null}
          Resume Stripe onboarding
          <ExternalLink className="size-3.5" />
        </Button>
      </CardContent>
    </Card>
  );
}

function UnderReviewCard({ summary }: { summary: PaymentsSummary }) {
  const refresh = useRefreshPaymentsStatus();
  return (
    <Card>
      <CardContent className="p-6 space-y-5">
        <div className="flex items-start gap-3">
          <Loader2 className="size-5 shrink-0 text-amber-600 dark:text-amber-400 mt-0.5 animate-spin" />
          <div className="space-y-1">
            <h2 className="font-medium">Stripe is reviewing your account</h2>
            <p className="text-sm text-muted-foreground leading-relaxed">
              Your details have been submitted. Stripe typically
              approves within a few minutes; verification can take
              longer for some business types. We&apos;ll update this
              page automatically when approval comes through.
            </p>
          </div>
        </div>
        <StatusFlags summary={summary} />
        <div className="flex flex-wrap items-center gap-3 pt-1">
          <Button
            type="button"
            variant="outline"
            onClick={() => refresh.mutate()}
            disabled={refresh.isPending}
          >
            {refresh.isPending ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <RefreshCw className="size-4" />
            )}
            Refresh status
          </Button>
          <a
            href="https://dashboard.stripe.com/"
            target="_blank"
            rel="noopener noreferrer"
            className="text-xs text-muted-foreground hover:text-foreground transition-colors inline-flex items-center gap-1"
          >
            Open Stripe Express dashboard
            <ExternalLink className="size-3" />
          </a>
        </div>
      </CardContent>
    </Card>
  );
}

function ReadyCard({ summary }: { summary: PaymentsSummary }) {
  const refresh = useRefreshPaymentsStatus();
  return (
    <Card className="border-emerald-500/30 bg-emerald-50/20 dark:bg-emerald-950/20">
      <CardContent className="p-6 space-y-5">
        <div className="flex items-start gap-3">
          <CheckCircle2 className="size-5 shrink-0 text-emerald-600 dark:text-emerald-400 mt-0.5" />
          <div className="space-y-1">
            <h2 className="font-medium">
              Connected and ready to take payments
            </h2>
            <p className="text-sm text-muted-foreground leading-relaxed">
              Your Stripe account is fully set up. Card-charge controls
              are now available on every invoice. Refunds + payout
              schedule + disputes are managed in your Stripe Express
              dashboard.
            </p>
            {summary.connected_at ? (
              <p className="text-[11px] text-muted-foreground mt-2">
                Connected {formatRelative(summary.connected_at)}
              </p>
            ) : null}
          </div>
        </div>
        <StatusFlags summary={summary} />
        <div className="flex flex-wrap items-center gap-3 pt-1">
          <Button
            type="button"
            nativeButton={false}
            render={(props) => (
              <a
                {...props}
                href="https://dashboard.stripe.com/"
                target="_blank"
                rel="noopener noreferrer"
              >
                Open Stripe Express dashboard
                <ExternalLink className="size-3.5" />
              </a>
            )}
          />
          <Button
            type="button"
            variant="ghost"
            onClick={() => refresh.mutate()}
            disabled={refresh.isPending}
          >
            {refresh.isPending ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <RefreshCw className="size-4" />
            )}
            Refresh status
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

function ReconnectCard({ summary }: { summary: PaymentsSummary }) {
  const start = useStartOnboarding();
  return (
    <Card className="border-rose-500/30 bg-rose-50/20 dark:bg-rose-950/20">
      <CardContent className="p-6 space-y-5">
        <div className="flex items-start gap-3">
          <AlertCircle className="size-5 shrink-0 text-rose-600 dark:text-rose-400 mt-0.5" />
          <div className="space-y-1">
            <h2 className="font-medium">Stripe connection revoked</h2>
            <p className="text-sm text-muted-foreground leading-relaxed">
              The Stripe Connect link to Lumè has been deauthorized.
              Card processing is offline. Reconnect to resume taking
              card payments — your existing customer + invoice data
              is untouched.
            </p>
            {summary.disabled_at ? (
              <p className="text-[11px] text-muted-foreground mt-2">
                Disconnected {formatRelative(summary.disabled_at)}
              </p>
            ) : null}
          </div>
        </div>
        <Button
          type="button"
          onClick={() => {
            start.mutate(undefined, {
              onError: (err) =>
                toast.error(
                  paymentsErrorMessage(
                    err,
                    "Couldn't open the reconnect flow.",
                  ),
                ),
            });
          }}
          disabled={start.isPending}
        >
          {start.isPending ? (
            <Loader2 className="size-4 animate-spin" />
          ) : (
            <CreditCard className="size-4" />
          )}
          Reconnect Stripe
        </Button>
      </CardContent>
    </Card>
  );
}

// ── Status-flag list ────────────────────────────────────────────

function StatusFlags({ summary }: { summary: PaymentsSummary }) {
  const flags: { label: string; ok: boolean }[] = [
    { label: 'Business details submitted', ok: summary.details_submitted },
    { label: 'Card charges enabled', ok: summary.charges_enabled },
    { label: 'Payouts to bank enabled', ok: summary.payouts_enabled },
  ];
  return (
    <ul className="space-y-1.5 text-xs">
      {flags.map((flag) => (
        <li key={flag.label} className="flex items-center gap-2">
          <span
            className={cn(
              'inline-flex size-4 items-center justify-center rounded-full',
              flag.ok
                ? 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400'
                : 'bg-muted text-muted-foreground',
            )}
          >
            {flag.ok ? '✓' : '·'}
          </span>
          <span
            className={flag.ok ? 'text-foreground' : 'text-muted-foreground'}
          >
            {flag.label}
          </span>
        </li>
      ))}
    </ul>
  );
}

// ── Help block ──────────────────────────────────────────────────

function HelpBlock() {
  return (
    <Card className="border-dashed">
      <CardContent className="p-6 space-y-2">
        <h3 className="text-sm font-medium">How card processing works</h3>
        <p className="text-xs text-muted-foreground leading-relaxed">
          When your customer pays an invoice with a card, Stripe
          charges their card and deposits the funds (minus
          processing fees) into your Stripe account. Stripe pays out
          to your bank account on the schedule you configure in your
          Stripe Express dashboard — typically daily. Refunds and
          disputes are also handled through that dashboard.
        </p>
        <p className="text-xs text-muted-foreground leading-relaxed">
          Lumè doesn&apos;t take a markup on processing — you pay
          the standard Stripe rate (2.9% + 30¢ for cards) directly,
          with no platform fee added on top.
        </p>
      </CardContent>
    </Card>
  );
}

function formatRelative(iso: string): string {
  // Simple "X days ago" — good enough for connect/disconnect timing
  // copy. Sub-day timing is rare on this surface so we don't bother
  // with hours/minutes precision.
  const target = new Date(iso).getTime();
  const days = Math.round((Date.now() - target) / (24 * 60 * 60 * 1000));
  if (days <= 0) return 'just now';
  if (days === 1) return 'yesterday';
  if (days < 30) return `${days} days ago`;
  if (days < 365) return `${Math.round(days / 30)} months ago`;
  return `${Math.round(days / 365)} years ago`;
}
