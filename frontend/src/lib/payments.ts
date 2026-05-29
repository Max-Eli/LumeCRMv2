/**
 * Payments data hooks — drives /org/payments.
 *
 * Wraps ``/api/payments/*`` (apps.payments). Stripe Connect Express
 * onboarding lives here; the spa-customer charge / refund flow comes
 * in the next chunk along with the matching backend endpoints.
 *
 * Distinct from ``lib/billing.ts``:
 *   - billing = how Lumè charges the spa for the SaaS subscription
 *   - payments = how the spa charges THEIR customers for treatments
 *
 * Both use Stripe under the same Voxtro LLC account, but they're
 * different integrations with different webhook secrets + different
 * permission stories — keeping the client surfaces split keeps the
 * concerns clear in the code.
 */

'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { ApiError, api } from './api';

export type MerchantProvider = 'stripe_connect' | 'custom';

/** What ``GET /api/payments/summary/`` returns. Drives the entire
 *  /org/payments page state. */
export interface PaymentsSummary {
  provider: MerchantProvider;
  /** Stripe Connected Account ID (acct_...). Empty before onboarding starts. */
  stripe_account_id: string;
  /** Mirrored from Stripe via account.updated webhook. */
  charges_enabled: boolean;
  payouts_enabled: boolean;
  details_submitted: boolean;
  /** ISO; null before first Express account create. */
  connected_at: string | null;
  /** ISO; null if not disabled. Set when the spa deauthorizes the app
   *  from their Stripe account (or Stripe disables for compliance). */
  disabled_at: string | null;
  /** Single intent-named predicate the page uses to gate the
   *  "ready to take payments" UI state. True only when all four
   *  Stripe flags + the disabled_at=null all line up. */
  is_ready_to_charge: boolean;
  /** True when STRIPE_SECRET_KEY is set on the backend. False in
   *  environments where Stripe isn't wired up yet. */
  stripe_configured: boolean;
}

const PAYMENTS_SUMMARY_KEY = ['payments', 'summary'] as const;

/** Owner-only. Hits the summary endpoint; safe even before any
 *  MerchantAccount row exists (the backend lazy-creates a default
 *  row on first read so the UI always has a useful shape). */
export function usePaymentsSummary() {
  return useQuery<PaymentsSummary>({
    queryKey: PAYMENTS_SUMMARY_KEY,
    queryFn: () => api.get<PaymentsSummary>('/api/payments/summary/'),
    // 30 seconds — short enough that the page reflects state quickly
    // after a webhook fires, long enough that idle owners don't burn
    // API calls. Manual refresh is a separate hook below.
    staleTime: 30 * 1000,
  });
}

/** Force-pull the latest state from Stripe before returning. Used by
 *  the "Refresh status" button — most syncs come through the
 *  webhook, but a manual refresh is the right escape hatch when the
 *  operator wants to verify state immediately. */
export function useRefreshPaymentsStatus() {
  const qc = useQueryClient();
  return useMutation<PaymentsSummary, Error, void>({
    mutationFn: () =>
      api.get<PaymentsSummary>('/api/payments/summary/?refresh=1'),
    onSuccess: (data) => {
      // Replace the cache entry directly so the UI updates without
      // a second roundtrip.
      qc.setQueryData(PAYMENTS_SUMMARY_KEY, data);
    },
  });
}

/** Start (or restart) the Stripe-hosted Express onboarding flow.
 *
 *  Same-tab redirect — the spa fills out KYC + bank account on
 *  Stripe's hosted pages, then Stripe redirects them back to the
 *  configured return URL on /org/payments (with ?onboarded=1).
 *
 *  AccountLinks expire quickly; always call fresh per click.
 */
export function useStartOnboarding() {
  return useMutation<{ url: string }, Error, void>({
    mutationFn: () =>
      api.post<{ url: string }>('/api/payments/onboarding-link/', {}),
    onSuccess: ({ url }) => {
      if (typeof window !== 'undefined') {
        window.location.href = url;
      }
    },
  });
}

/** Pull a human error message from an ApiError body. Mirrors the
 *  shape returned by payments endpoints (detail + code). */
export function paymentsErrorMessage(err: unknown, fallback: string): string {
  if (err instanceof ApiError && typeof err.body === 'object' && err.body) {
    const body = err.body as { detail?: string };
    if (typeof body.detail === 'string' && body.detail) return body.detail;
  }
  return fallback;
}
