/**
 * Gift card hooks.
 *
 * Pairs with `apps.giftcards` at `/api/gift-cards/` (read + lookup +
 * void) plus the invoice action endpoints for sale + redemption +
 * reversal.
 *
 * Gift cards aren't a "catalog" in the usual sense — there's no
 * predefined denomination row to create or edit. Each card is
 * issued at a custom dollar value through the invoice's
 * `add-gift-card-sale` action. The `/catalog/gift-cards` page is a
 * list of *issued* cards with code lookup + status filter +
 * voiding.
 */

'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from './api';

// ── Types ───────────────────────────────────────────────────────────

export type GiftCardStatus = 'pending' | 'active' | 'voided' | 'expired';

export type GiftCardLedgerKind =
  | 'issue'
  | 'redeem'
  | 'reversal'
  | 'adjustment';

export interface GiftCardLedgerRow {
  id: number;
  gift_card: number;
  kind: GiftCardLedgerKind;
  amount_cents: number;
  invoice: number | null;
  by_user_email: string | null;
  note: string;
  recorded_at: string;
}

export interface GiftCard {
  id: number;
  code: string;
  issued_to_customer: number | null;
  issued_to_customer_name: string | null;
  issued_to_name: string;
  issued_to_email: string;
  purchaser_customer: number | null;
  purchaser_customer_name: string | null;
  source_invoice_line: number;
  initial_value_cents: number;
  initial_value_dollars: string;
  balance_cents: number;
  balance_dollars: string;
  status: GiftCardStatus;
  issued_at: string | null;
  expires_at: string | null;
  voided_at: string | null;
  voided_by_email: string | null;
  void_reason: string;
  notes: string;
  is_redeemable: boolean;
  is_expired: boolean;
  is_fully_redeemed: boolean;
  ledger_entries: GiftCardLedgerRow[];
  created_at: string;
  updated_at: string;
}

// ── Query keys ──────────────────────────────────────────────────────

const GIFT_CARDS_KEY = ['gift-cards'] as const;
const giftCardKey = (id: number) => [...GIFT_CARDS_KEY, id] as const;

// ── Read hooks ──────────────────────────────────────────────────────

export interface GiftCardListFilter {
  /** Free-text search across code, issued_to_name, email, notes. */
  q?: string;
  customerId?: number;
  purchaserId?: number;
  status?: GiftCardStatus;
  /** Exact code lookup (case-insensitive). */
  code?: string;
}

export function useGiftCards(opts: GiftCardListFilter = {}) {
  const params = new URLSearchParams();
  if (opts.q) params.set('q', opts.q);
  if (opts.customerId) params.set('customer', String(opts.customerId));
  if (opts.purchaserId) params.set('purchaser', String(opts.purchaserId));
  if (opts.status) params.set('status', opts.status);
  if (opts.code) params.set('code', opts.code);
  const qs = params.toString();
  const path = qs ? `/api/gift-cards/?${qs}` : '/api/gift-cards/';

  return useQuery<GiftCard[]>({
    queryKey: [
      ...GIFT_CARDS_KEY,
      opts.q ?? '',
      opts.customerId ?? 0,
      opts.purchaserId ?? 0,
      opts.status ?? '',
      opts.code ?? '',
    ],
    queryFn: () => api.get<GiftCard[]>(path),
  });
}

export function useGiftCard(id: number | undefined) {
  return useQuery<GiftCard>({
    queryKey: id ? giftCardKey(id) : ['gift-cards', 'disabled'],
    queryFn: () => api.get<GiftCard>(`/api/gift-cards/${id}/`),
    enabled: typeof id === 'number' && id > 0,
  });
}

/** Customer profile gift cards section: cards received OR purchased
 *  by this customer. The backend doesn't OR-filter natively; we
 *  fetch each side and merge. */
export function useCustomerGiftCards(customerId: number | undefined) {
  const received = useQuery<GiftCard[]>({
    queryKey: [...GIFT_CARDS_KEY, 'received', customerId ?? 0],
    queryFn: () =>
      api.get<GiftCard[]>(`/api/gift-cards/?customer=${customerId}`),
    enabled: typeof customerId === 'number' && customerId > 0,
  });
  const purchased = useQuery<GiftCard[]>({
    queryKey: [...GIFT_CARDS_KEY, 'purchased', customerId ?? 0],
    queryFn: () =>
      api.get<GiftCard[]>(`/api/gift-cards/?purchaser=${customerId}`),
    enabled: typeof customerId === 'number' && customerId > 0,
  });
  return { received, purchased };
}

// ── Code-based lookup (used at checkout) ────────────────────────────

export interface GiftCardLookupInput {
  code: string;
}

export function useGiftCardLookup() {
  return useMutation<GiftCard, Error, GiftCardLookupInput>({
    mutationFn: (input) =>
      api.post<GiftCard>('/api/gift-cards/lookup/', input),
  });
}

// ── Void ────────────────────────────────────────────────────────────

export interface VoidGiftCardInput {
  reason: string;
}

export function useVoidGiftCard(id: number) {
  const qc = useQueryClient();
  return useMutation<GiftCard, Error, VoidGiftCardInput>({
    mutationFn: (input) =>
      api.post<GiftCard>(`/api/gift-cards/${id}/void/`, input),
    onSuccess: (updated) => {
      qc.setQueryData(giftCardKey(updated.id), updated);
      qc.invalidateQueries({ queryKey: GIFT_CARDS_KEY });
    },
  });
}

// ── Money helpers ───────────────────────────────────────────────────

export function centsFromDollars(input: string | number): number {
  if (input === '' || input == null) return 0;
  const n = typeof input === 'string' ? Number(input) : input;
  if (Number.isNaN(n)) return 0;
  return Math.round(n * 100);
}

export function dollarsFromCents(cents: number): string {
  return (cents / 100).toFixed(2);
}
