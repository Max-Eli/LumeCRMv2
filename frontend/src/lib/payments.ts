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

// ── Charge a card on an invoice (Stripe Elements flow) ─────────────

export interface ChargeCardInput {
  /** Invoice ID to charge against. */
  invoiceId: number;
  /** Amount in cents. Caller is responsible for not exceeding
   *  invoice.amount_due_cents — backend re-validates only that it's
   *  positive (Stripe permits overpayment; we trust the operator UI
   *  not to send too much). */
  amount_cents: number;
}

/** What ``POST /api/payments/invoices/<id>/charge-card/`` returns.
 *  Everything the frontend Stripe Elements widget needs to confirm
 *  the payment is in this payload — no separate env-var dependency
 *  for the publishable key. */
export interface ChargeCardResponse {
  /** Local Charge row PK. Useful for the activity log + post-confirm
   *  refetches. */
  charge_id: number;
  /** Stripe PaymentIntent client secret. Pass this to
   *  ``stripe.confirmPayment()`` along with the Elements instance. */
  client_secret: string;
  /** Stripe publishable key — same Voxtro LLC account as the secret
   *  key in the backend. Echoed from backend env so rotation only
   *  requires updating the backend, not the frontend bundle. */
  publishable_key: string;
  /** The spa's Stripe Connect Account ID. Required to initialize
   *  Stripe.js against the right connected account (direct charges
   *  on the connected account need this). */
  stripe_account_id: string;
}

/** Create a PaymentIntent on the spa's connected account. The
 *  caller (typically a ChargeCardDialog) takes the returned client
 *  secret + initializes Stripe Elements to collect the card.
 *
 *  Mutation only — no cache invalidation here because the actual
 *  payment state lands via webhook + the dialog is the natural
 *  refetch trigger after a successful confirm. */
export function useChargeCard() {
  return useMutation<ChargeCardResponse, Error, ChargeCardInput>({
    mutationFn: ({ invoiceId, amount_cents }) =>
      api.post<ChargeCardResponse>(
        `/api/payments/invoices/${invoiceId}/charge-card/`,
        { amount_cents },
      ),
  });
}

// ── Refund a card charge ───────────────────────────────────────────

export interface RefundChargeInput {
  /** Charge row PK (NOT Stripe charge ID — the local one). */
  chargeId: number;
  /** Refund amount in cents. Must be > 0 and <= charge.refundable_cents. */
  amount_cents: number;
  /** Operator-typed reason (audit trail). Backend requires non-empty
   *  and ≤ 255 chars. */
  reason: string;
}

export interface RefundChargeResponse {
  refund_id: number;
  status: 'pending' | 'succeeded' | 'failed';
  amount_cents: number;
  /** New total refunded on the parent charge after this refund. */
  charge_refunded_cents: number;
}

/** Issue a Stripe refund + persist a local Refund row. Caller is
 *  responsible for invalidating any cached Charge list it's
 *  displaying. */
export function useRefundCharge() {
  const qc = useQueryClient();
  return useMutation<RefundChargeResponse, Error, RefundChargeInput>({
    mutationFn: ({ chargeId, amount_cents, reason }) =>
      api.post<RefundChargeResponse>(
        `/api/payments/charges/${chargeId}/refund/`,
        { amount_cents, reason },
      ),
    onSuccess: () => {
      // Refunds change invoice "fully paid" state in some UIs; broad
      // invalidation is cheap.
      qc.invalidateQueries({ queryKey: ['invoices'] });
    },
  });
}

// ── Customer-portal self-pay variant ──────────────────────────────
//
// Same wire shape as ``useChargeCard`` (returns ``ChargeCardResponse``)
// but hits ``POST /api/portal/invoices/<id>/pay/`` instead of the
// operator endpoint. Used by the portal Pay-now flow — same Stripe
// Elements UI on the frontend, different auth + backend attribution
// (Charge row carries ``created_by=None`` + ``initiated_via='customer_portal'``).
//
// Exposed with the same input + return shape as ``useChargeCard`` so
// a single ChargeCardDialog component can be reused across both
// surfaces by passing this hook as the ``useChargeIntent`` prop.

/** Customer-portal self-pay variant of {@link useChargeCard}. */
export function usePayInvoiceFromPortal() {
  const qc = useQueryClient();
  return useMutation<ChargeCardResponse, Error, ChargeCardInput>({
    mutationFn: ({ invoiceId, amount_cents }) =>
      api.post<ChargeCardResponse>(
        `/api/portal/invoices/${invoiceId}/pay/`,
        { amount_cents },
      ),
    onSuccess: () => {
      // Portal customer just kicked off a payment; their invoice list
      // will need to refresh once the webhook lands. Invalidate the
      // portal-invoices query so a returning user sees fresh state.
      qc.invalidateQueries({ queryKey: ['portal', 'invoices'] });
    },
  });
}
