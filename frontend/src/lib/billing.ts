/**
 * Billing data hooks — drives /org/billing.
 *
 * Wraps the backend ``/api/billing/*`` endpoints (``apps.billing``).
 * Two integrations are intentionally distinct in the API + here too:
 *
 *   - Stripe Billing (this file) — the SaaS subscription Lumè charges
 *     the spa for. Owner-only surface; gated by ``MANAGE_BILLING``.
 *   - Stripe Connect (Phase 2, not built yet) — the spa charging their
 *     own customers. Will live in `lib/payments.ts` when it ships.
 *
 * The summary endpoint is safe to fetch for any owner — even
 * grandfathered tenants who have no Stripe subscription get a useful
 * shape back (capacity nulls = unlimited, ``allowed_addons`` empty,
 * ``has_stripe_subscription`` false). The UI uses those flags to switch
 * between "self-serve add-on controls" and "talk to support" copy.
 */

'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { ApiError, api } from './api';

export type Plan = 'trial' | 'starter' | 'pro' | 'enterprise';
export type BillingCycle = 'monthly' | 'annual';
export type TenantBillingStatus =
  | 'trial'
  | 'active'
  | 'past_due'
  | 'suspended'
  | 'cancelled';

export type AddonKey = 'staff' | 'location' | 'email_5k' | 'email_10k';

/** What ``GET /api/billing/summary/`` returns. Drives the entire
 *  /org/billing page. */
export interface BillingSummary {
  plan: Plan;
  billing_cycle: BillingCycle;
  status: TenantBillingStatus;
  grandfathered: boolean;
  /** ISO datetime; null when the tenant never went through a trial
   *  (grandfathered / enterprise sales-onboarded). */
  trial_ends_at: string | null;
  /** ISO datetime mirrored from Stripe. Null pre-trial-end. */
  current_period_end: string | null;
  billing_email: string;

  /** Plan baseline + add-ons. ``null`` for any limit means unlimited
   *  (grandfathered or enterprise). Frontend renders ∞. */
  capacity: {
    max_staff: number | null;
    max_locations: number | null;
    sms_quota: number | null;
    email_quota: number | null;
  };
  /** What they're currently using against the caps. */
  usage: {
    staff_count: number;
    location_count: number;
    sms_used: number;
    email_used: number;
  };
  /** Active add-on quantities, keyed by add-on identifier. */
  addons: Partial<Record<AddonKey, number>>;
  /** Add-ons this tenant's plan is allowed to buy. Empty for
   *  grandfathered tenants ("contact support"). Each value has
   *  delta, capacity_key, allowed_plans, max_quantity. */
  allowed_addons: Record<
    string,
    {
      delta: number;
      capacity_key: string;
      allowed_plans: string[];
      max_quantity: number | null;
    }
  >;
  /** True when STRIPE_SECRET_KEY is present in the backend env.
   *  Frontend disables billing-portal + add-on buttons when false
   *  (with a clear "Stripe not configured" hint). */
  stripe_configured: boolean;
  /** True when this tenant has a Stripe Subscription on file.
   *  False for grandfathered tenants (and during the brief window
   *  between signup and Stripe Customer create). */
  has_stripe_subscription: boolean;
}

const BILLING_SUMMARY_KEY = ['billing', 'summary'] as const;

/** Owner-only. Returns null while the user is being loaded; 403 is
 *  surfaced as an ApiError the page handles via the standard error
 *  path. */
export function useBillingSummary() {
  return useQuery<BillingSummary>({
    queryKey: BILLING_SUMMARY_KEY,
    queryFn: () => api.get<BillingSummary>('/api/billing/summary/'),
    staleTime: 60 * 1000, // 1 min — usage counters move slowly
  });
}

export interface UpdateAddonQuantityInput {
  addon_key: AddonKey;
  quantity: number;
}

/** Update a single add-on's quantity. Backend calls Stripe + mirrors
 *  the new state locally; we refetch the summary on success so the
 *  capacity / cost line refreshes. Errors surface as ``ApiError``
 *  with the structured body the backend returns:
 *    400 ``invalid_addon_request`` — plan doesn't allow it / over max
 *    503 ``stripe_not_configured``
 *    502 ``stripe_error``  — Stripe API call failed
 *    409 ``grandfathered_no_self_serve_billing`` */
export function useUpdateAddonQuantity() {
  const qc = useQueryClient();
  return useMutation<
    { addon_key: AddonKey; quantity: number; addons: Partial<Record<AddonKey, number>> },
    Error,
    UpdateAddonQuantityInput
  >({
    mutationFn: (input) =>
      api.post('/api/billing/addon-quantity/', input),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: BILLING_SUMMARY_KEY });
    },
  });
}

/** Pop the Stripe-hosted billing portal in a new window. The window
 *  isn't a tab — `noreferrer` is set so it can't reach back into our
 *  origin via window.opener.
 *
 *  Two-step: hit the backend for the portal URL, then redirect. If
 *  the backend returns 503 / 502, surface the message via the
 *  passed-in onError callback (typically a toast). */
export function useOpenStripePortal() {
  return useMutation<{ url: string }, Error, { returnUrl?: string }>({
    mutationFn: (input) =>
      api.post('/api/billing/portal-session/', { return_url: input.returnUrl }),
    onSuccess: ({ url }) => {
      // Same-tab redirect — the operator is expected to come back
      // through Stripe's "Return to ..." button.
      if (typeof window !== 'undefined') {
        window.location.href = url;
      }
    },
  });
}

/** Pull a human error message from an ApiError body. Mirrors the
 *  shape returned by the billing endpoints (detail + code). */
export function billingErrorMessage(err: unknown, fallback: string): string {
  if (err instanceof ApiError && typeof err.body === 'object' && err.body) {
    const body = err.body as { detail?: string };
    if (typeof body.detail === 'string' && body.detail) return body.detail;
  }
  return fallback;
}
