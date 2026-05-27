/**
 * Invoice data hooks.
 *
 * Pairs with `apps.invoices` at `/api/invoices/`. Per ADR 0007:
 *
 *   - Every appointment has an invoice (1:1, auto-created on booking).
 *     Standalone invoices (POS) land in Phase 2A — same shape, with
 *     `appointment` = null.
 *   - The only path to `Appointment.status = 'completed'` is closing the
 *     invoice via `useCloseInvoice`. The serializer rejects direct
 *     `PATCH status=completed` on appointments with a guidance message.
 *   - Owners and managers may reopen a paid invoice within 60 days of
 *     `closed_at` (the FIRST close — re-closes don't extend the window).
 *
 * Money everywhere is in cents — divide by 100 only at the display edge.
 */

'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { ApiError, api } from './api';

// ── Take-payment window ──────────────────────────────────────────────────

/** Open the invoice / take-payment surface in a true popup window
 *  (not a new tab). Operators expect a focused checkout context,
 *  not another tab buried in their existing stack.
 *
 *  Browsers vary in how they honor `popup`: Chrome reliably opens a
 *  bare window; Firefox + Safari may still render a tab if the user
 *  has set their preferences that way. Mobile browsers always open
 *  it as a tab — there's no concept of a window on a phone — which
 *  is the right behavior there anyway. */
const INVOICE_WINDOW_FEATURES = [
  'popup=yes',
  'width=1080',
  'height=920',
  'resizable=yes',
  'scrollbars=yes',
].join(',');

function openInvoicePath(path: string): void {
  // `_blank` so each open invoice gets its own window — using a
  // named target would reuse one window and clobber the operator's
  // existing checkout.
  window.open(path, '_blank', INVOICE_WINDOW_FEATURES);
}

export function openInvoiceWindow(appointmentId: number, action?: 'pay' | 'reopen' | 'void'): void {
  const path = action
    ? `/invoice/${appointmentId}?action=${action}`
    : `/invoice/${appointmentId}`;
  openInvoicePath(path);
}

/** Open a standalone invoice (no appointment — e.g. a custom package)
 *  in the take-payment window. Routes to the `?by=invoice` mode of the
 *  invoice page, which loads by invoice id rather than appointment id. */
export function openStandaloneInvoiceWindow(
  invoiceId: number,
  action?: 'pay' | 'reopen' | 'void',
): void {
  const path = action
    ? `/invoice/${invoiceId}?by=invoice&action=${action}`
    : `/invoice/${invoiceId}?by=invoice`;
  openInvoicePath(path);
}

// ── Types ────────────────────────────────────────────────────────────────

export type InvoiceStatus = 'open' | 'paid' | 'void';

export type PaymentMethod =
  | 'cash'
  | 'check'
  | 'card_external'
  | 'gift_card'
  | 'other';

export const PAYMENT_METHOD_LABELS: Record<PaymentMethod, string> = {
  cash: 'Cash',
  check: 'Check',
  card_external: 'Card (external terminal)',
  gift_card: 'Gift card (full coverage)',
  other: 'Other',
};

/** A discount specified either as a flat cents-off ('amount') or
 *  a percent-off ('percent'). Operator picks the kind per line / per
 *  invoice; the input is what they typed (e.g. 10.00 = $10 OR 10%
 *  depending on kind). */
export type DiscountKind = 'amount' | 'percent';

export interface InvoiceLineItem {
  id: number;
  service: number | null;
  product: number | null;
  package: number | null;
  membership_plan: number | null;
  description: string;
  quantity: number;
  unit_price_cents: number;
  tax_rate_percent: string; // Decimal as string from DRF
  line_subtotal_cents: number;
  line_tax_cents: number;
  /** Per-line discount fields. `discount_input` is whatever the
   *  operator typed (dollars off when kind=amount, percent when
   *  kind=percent); `discount_cents` is the derived cents. */
  discount_kind: DiscountKind;
  discount_input: string;
  discount_cents: number;
  discount_reason: string;
  /** This line's share of the invoice-level discount, distributed
   *  pro-rata across lines by the server's `recalculate_totals`. */
  invoice_discount_share_cents: number;
  created_at: string;
}

/** Body for `POST /api/invoices/<id>/add-gift-card-sale/`. Sells a
 *  gift card on this OPEN invoice. Caller supplies value + recipient
 *  (either an existing customer FK or a free-text name). */
export interface AddGiftCardSaleInput {
  value_cents: number;
  recipient_customer_id?: number;
  recipient_name?: string;
  recipient_email?: string;
  expires_at?: string;
  notes?: string;
}

/** Body for `POST /api/invoices/<id>/apply-gift-card/`. Applies a
 *  portion of a card's balance to this invoice. Backend validates
 *  active + not expired + balance covers + ≤ amount due. */
export interface ApplyGiftCardInput {
  code: string;
  amount_cents: number;
}

export interface InvoiceCustomerSummary {
  id: number;
  first_name: string;
  last_name: string;
  full_name: string;
  email: string;
  phone: string;
}

export interface InvoiceAppointmentSummary {
  id: number;
  status: string;
  start_time: string;
  end_time: string;
  service_name: string;
  provider_name: string | null;
}

export interface Invoice {
  id: number;
  /** Human-readable invoice number, format `INV-YYYY-NNNN`. Per-tenant
   *  sequential, resets on Jan 1. Always present on rows created
   *  after the 0003 migration; backfilled retroactively on existing
   *  rows. Defensive empty-string fallback only for pre-migration
   *  test fixtures. */
  invoice_number: string;
  customer: InvoiceCustomerSummary;
  appointment: InvoiceAppointmentSummary | null;
  status: InvoiceStatus;
  subtotal_cents: number;
  tax_cents: number;
  total_cents: number;
  /** Invoice-level discount (layers on top of any per-line discounts
   *  and is distributed pro-rata across lines by the server). The
   *  display formula is:
   *    total = subtotal − line_discounts_total − invoice_discount + tax
   */
  invoice_discount_kind: DiscountKind;
  invoice_discount_input: string;
  invoice_discount_cents: number;
  invoice_discount_reason: string;
  /** Sum of every line's per-line discount cents — kept denormalized
   *  on the invoice header so the totals box doesn't have to sum line
   *  by line and the DB-level constraint can verify the rollup. */
  line_discounts_total_cents: number;
  /** Total of gift card credits applied toward this invoice.
   *  Reduces `amount_due_cents`. Mutated by the apply-gift-card /
   *  reverse-gift-card-redemption actions. */
  gift_card_credits_cents: number;
  /** What `payment_method` covers at close: `total - gift_card_credits`,
   *  clamped at 0. Server-computed. */
  amount_due_cents: number;
  payment_method: PaymentMethod | '';
  payment_reference: string;
  notes: string;
  closed_at: string | null;
  closed_by_email: string | null;
  reopened_at: string | null;
  reopened_by_email: string | null;
  reopen_count: number;
  voided_at: string | null;
  voided_by_email: string | null;
  void_reason: string;
  created_at: string;
  updated_at: string;
  created_by_email: string | null;
  line_items: InvoiceLineItem[];
  is_reopen_window_open: boolean;
  reopen_deadline: string | null;
}

export interface CloseInvoiceInput {
  payment_method: PaymentMethod;
  payment_reference?: string;
  notes?: string;
}

export interface ReopenInvoiceInput {
  reason: string;
}

export interface VoidInvoiceInput {
  reason: string;
}

/** Body for `POST /api/invoices/<id>/add-line/`. Caller supplies
 *  exactly one of `service_id` / `product_id` / `package_id` /
 *  `membership_plan_id`; backend rejects more or fewer with a 400. */
export interface AddInvoiceLineInput {
  service_id?: number;
  product_id?: number;
  package_id?: number;
  membership_plan_id?: number;
  quantity?: number;
  /** Optional override for member discounts / comp pricing. */
  unit_price_cents?: number;
  /** Optional override for the snapshot description. */
  description?: string;
}

/** Body for `POST /api/invoices/<id>/redeem-from-package/`. Backend
 *  validates the package is ACTIVE, not expired, customer-matched,
 *  and has remaining credit for the chosen service. */
export interface RedeemFromPackageInput {
  purchased_package_id: number;
  service_id: number;
  note?: string;
}

/** Body for `POST /api/invoices/<id>/redeem-from-membership/`.
 *  Backend validates the subscription is ACTIVE + in-period,
 *  customer-matched, and has remaining credit for the service. */
export interface RedeemFromMembershipInput {
  subscription_id: number;
  service_id: number;
  note?: string;
}

/** One row in the custom-package builder. */
export interface CustomPackageItemInput {
  service_id: number;
  quantity: number;
}

/** Body for `POST /api/invoices/<id>/add-custom-package/`. Builds
 *  a one-off bundle for this customer (not from the catalog) and
 *  adds it to the invoice as a single line. Same lifecycle as a
 *  catalog package: PENDING until invoice close, then ACTIVE. */
export interface AddCustomPackageInput {
  name: string;
  description?: string;
  price_cents: number;
  tax_rate_percent?: string | number;
  validity_days?: number | null;
  items: CustomPackageItemInput[];
}

// ── Query keys ───────────────────────────────────────────────────────────

const INVOICES_KEY = ['invoices'] as const;

const invoiceDetailKey = (id: number) => [...INVOICES_KEY, id] as const;
const invoiceByAppointmentKey = (appointmentId: number) =>
  [...INVOICES_KEY, 'appointment', appointmentId] as const;

// ── Hooks ────────────────────────────────────────────────────────────────

/** Fetch a single invoice by ID. */
export function useInvoice(id: number | undefined) {
  return useQuery<Invoice>({
    queryKey: invoiceDetailKey(id ?? 0),
    queryFn: () => api.get<Invoice>(`/api/invoices/${id}/`),
    enabled: typeof id === 'number' && id > 0,
  });
}

/** All invoices for a single customer, newest first.
 *
 *  Drives the customer profile's Wallet tab — open balance + payment
 *  history at a glance. Hits `/api/invoices/?customer=<id>`; tenant
 *  scoping handled by middleware. */
export function useCustomerInvoices(customerId: number | undefined) {
  return useQuery<Invoice[]>({
    queryKey: [...INVOICES_KEY, 'customer', customerId ?? 0],
    queryFn: () => api.get<Invoice[]>(`/api/invoices/?customer=${customerId}`),
    enabled: typeof customerId === 'number' && customerId > 0,
  });
}

/**
 * Fetch the (single) invoice for an appointment. The list endpoint is
 * filtered server-side; we unwrap the array to return the first hit (or
 * null) so callers that know "this appointment has at most one invoice"
 * (per ADR 0007) get a clean shape.
 */
export function useInvoiceForAppointment(appointmentId: number | undefined) {
  return useQuery<Invoice | null>({
    queryKey: invoiceByAppointmentKey(appointmentId ?? 0),
    queryFn: async () => {
      const list = await api.get<Invoice[] | { results: Invoice[] }>(
        `/api/invoices/?appointment=${appointmentId}`,
      );
      const items = Array.isArray(list) ? list : list.results;
      return items[0] ?? null;
    },
    enabled: typeof appointmentId === 'number' && appointmentId > 0,
  });
}

/**
 * Open a blank standalone invoice for a walk-in sale (no appointment).
 * Backs the calendar "New sale" tool — the operator picks a customer,
 * this creates an empty OPEN invoice, and the UI hands off to the
 * take-payment page where lines are added and payment is taken.
 */
export function useCreateStandaloneInvoice() {
  const qc = useQueryClient();
  return useMutation<Invoice, Error, { customer_id: number }>({
    mutationFn: (input) =>
      api.post<Invoice>('/api/invoices/create-standalone/', input),
    onSuccess: (created) => {
      qc.setQueryData(invoiceDetailKey(created.id), created);
      qc.invalidateQueries({
        queryKey: [...INVOICES_KEY, 'customer', created.customer.id],
      });
    },
  });
}

/**
 * Close (take payment). Throws an `ApiError` on permission failure
 * (typically 403) or state-machine conflict (409 — invoice already
 * paid / voided / appointment cancelled).
 */
export function useCloseInvoice(invoiceId: number) {
  const qc = useQueryClient();
  return useMutation<Invoice, Error, CloseInvoiceInput>({
    mutationFn: (input) => api.post<Invoice>(`/api/invoices/${invoiceId}/close/`, input),
    onSuccess: (updated) => {
      qc.setQueryData(invoiceDetailKey(updated.id), updated);
      // The appointment side also changed (status → completed); blow the
      // appointments cache so the calendar reflects it without a manual
      // refetch.
      if (updated.appointment) {
        qc.invalidateQueries({
          queryKey: invoiceByAppointmentKey(updated.appointment.id),
        });
      }
      qc.invalidateQueries({ queryKey: ['appointments'] });
    },
  });
}

/** Server response from POST /api/invoices/{id}/email/. */
export interface EmailInvoiceResponse {
  recipient: string;
}

/**
 * Email the invoice (PDF attached) to the customer of record. 403
 * if the caller lacks PROCESS_PAYMENT (owner / manager / front desk);
 * 400 if the customer has no email on file (the operator should fix
 * the profile first). Each call sends a fresh email — no
 * deduplication.
 */
export function useEmailInvoice(invoiceId: number) {
  return useMutation<EmailInvoiceResponse, Error, void>({
    mutationFn: () => api.post<EmailInvoiceResponse>(`/api/invoices/${invoiceId}/email/`, undefined),
  });
}

/**
 * Reopen a paid invoice. 403 if the caller lacks `REOPEN_INVOICE`
 * (owner / manager only), 409 if the 60-day window has passed
 * (response body includes `window_expired: true`).
 */
export function useReopenInvoice(invoiceId: number) {
  const qc = useQueryClient();
  return useMutation<Invoice, Error, ReopenInvoiceInput>({
    mutationFn: (input) => api.post<Invoice>(`/api/invoices/${invoiceId}/reopen/`, input),
    onSuccess: (updated) => {
      qc.setQueryData(invoiceDetailKey(updated.id), updated);
      if (updated.appointment) {
        qc.invalidateQueries({
          queryKey: invoiceByAppointmentKey(updated.appointment.id),
        });
      }
      qc.invalidateQueries({ queryKey: ['appointments'] });
    },
  });
}

/** Body for `PATCH /api/invoices/<id>/lines/<line_id>/edit/` — edit a
 *  line's unit price and/or per-line discount. Only the fields you
 *  provide are changed. `authorized_by_email` + `authorized_by_password`
 *  are required when the acting user lacks `EDIT_INVOICE_PRICE`; an
 *  owner / manager's credentials authorize the change and the audit
 *  log captures both the acting user and the authorizer. */
export interface EditInvoiceLineInput {
  unit_price_cents?: number;
  discount_kind?: DiscountKind;
  /** Operator-typed value (dollars off when kind=amount, percent
   *  when kind=percent). Send 0 to clear. */
  discount_input?: string;
  discount_reason?: string;
  authorized_by_email?: string;
  authorized_by_password?: string;
}

export function useEditInvoiceLine(invoiceId: number) {
  const qc = useQueryClient();
  return useMutation<
    Invoice,
    Error,
    { line_id: number; payload: EditInvoiceLineInput }
  >({
    mutationFn: ({ line_id, payload }) =>
      api.patch<Invoice>(
        `/api/invoices/${invoiceId}/lines/${line_id}/edit/`, payload,
      ),
    onSuccess: (updated) => {
      qc.setQueryData(invoiceDetailKey(updated.id), updated);
      if (updated.appointment) {
        qc.invalidateQueries({
          queryKey: invoiceByAppointmentKey(updated.appointment.id),
        });
      }
    },
  });
}

/** Body for `PATCH /api/invoices/<id>/discount/` — set or clear the
 *  invoice-level discount. Same manager-override shape as
 *  `EditInvoiceLineInput`. Send `invoice_discount_input: '0'` to
 *  clear an existing discount. */
export interface SetInvoiceDiscountInput {
  invoice_discount_kind?: DiscountKind;
  invoice_discount_input?: string;
  invoice_discount_reason?: string;
  authorized_by_email?: string;
  authorized_by_password?: string;
}

export function useSetInvoiceDiscount(invoiceId: number) {
  const qc = useQueryClient();
  return useMutation<Invoice, Error, SetInvoiceDiscountInput>({
    mutationFn: (payload) =>
      api.patch<Invoice>(`/api/invoices/${invoiceId}/discount/`, payload),
    onSuccess: (updated) => {
      qc.setQueryData(invoiceDetailKey(updated.id), updated);
      if (updated.appointment) {
        qc.invalidateQueries({
          queryKey: invoiceByAppointmentKey(updated.appointment.id),
        });
      }
    },
  });
}

/** Add a service or product line to an OPEN invoice. 409 if the
 *  invoice is PAID or VOID; 400 if the catalog item is inactive or
 *  cross-tenant. Stock decrement happens at close time, not here. */
export function useAddInvoiceLine(invoiceId: number) {
  const qc = useQueryClient();
  return useMutation<Invoice, Error, AddInvoiceLineInput>({
    mutationFn: (input) =>
      api.post<Invoice>(`/api/invoices/${invoiceId}/add-line/`, input),
    onSuccess: (updated) => {
      qc.setQueryData(invoiceDetailKey(updated.id), updated);
      if (updated.appointment) {
        qc.invalidateQueries({
          queryKey: invoiceByAppointmentKey(updated.appointment.id),
        });
      }
    },
  });
}

/** Remove a line from an OPEN invoice. 404 if the line isn't on
 *  this invoice; 409 if the invoice is PAID or VOID. The endpoint
 *  returns the recalculated invoice. */
export function useRemoveInvoiceLine(invoiceId: number) {
  const qc = useQueryClient();
  return useMutation<Invoice, Error, number>({
    mutationFn: (lineId) =>
      api.delete<Invoice>(`/api/invoices/${invoiceId}/lines/${lineId}/`),
    onSuccess: (updated) => {
      qc.setQueryData(invoiceDetailKey(updated.id), updated);
      if (updated.appointment) {
        qc.invalidateQueries({
          queryKey: invoiceByAppointmentKey(updated.appointment.id),
        });
      }
    },
  });
}

/** Build a one-off package per customer + add it as a line on
 *  the invoice. `source_template` on the resulting PurchasedPackage
 *  is null. Same lifecycle as catalog packages: PENDING until
 *  the invoice closes. */
export function useAddCustomPackage(invoiceId: number) {
  const qc = useQueryClient();
  return useMutation<Invoice, Error, AddCustomPackageInput>({
    mutationFn: (input) =>
      api.post<Invoice>(
        `/api/invoices/${invoiceId}/add-custom-package/`,
        input,
      ),
    onSuccess: (updated) => {
      qc.setQueryData(invoiceDetailKey(updated.id), updated);
      if (updated.appointment) {
        qc.invalidateQueries({
          queryKey: invoiceByAppointmentKey(updated.appointment.id),
        });
      }
      qc.invalidateQueries({ queryKey: ['purchased-packages'] });
    },
  });
}

/** Redeem a credit from a customer's purchased package. The
 *  endpoint atomically: decrements the per-service balance,
 *  creates a $0 invoice line tagged with the source package,
 *  and writes a `PackageRedemption` ledger row. Returns the
 *  recalculated invoice. */
export function useRedeemFromPackage(invoiceId: number) {
  const qc = useQueryClient();
  return useMutation<Invoice, Error, RedeemFromPackageInput>({
    mutationFn: (input) =>
      api.post<Invoice>(
        `/api/invoices/${invoiceId}/redeem-from-package/`,
        input,
      ),
    onSuccess: (updated) => {
      qc.setQueryData(invoiceDetailKey(updated.id), updated);
      if (updated.appointment) {
        qc.invalidateQueries({
          queryKey: invoiceByAppointmentKey(updated.appointment.id),
        });
      }
      qc.invalidateQueries({ queryKey: ['purchased-packages'] });
    },
  });
}

/** Redeem a credit from a customer's active Subscription. Same
 *  contract as `useRedeemFromPackage` but on the membership side.
 *  Returns the recalculated invoice. */
export function useRedeemFromMembership(invoiceId: number) {
  const qc = useQueryClient();
  return useMutation<Invoice, Error, RedeemFromMembershipInput>({
    mutationFn: (input) =>
      api.post<Invoice>(
        `/api/invoices/${invoiceId}/redeem-from-membership/`,
        input,
      ),
    onSuccess: (updated) => {
      qc.setQueryData(invoiceDetailKey(updated.id), updated);
      if (updated.appointment) {
        qc.invalidateQueries({
          queryKey: invoiceByAppointmentKey(updated.appointment.id),
        });
      }
      qc.invalidateQueries({ queryKey: ['subscriptions'] });
    },
  });
}

/** Sell a gift card on an OPEN invoice. Creates a positive line +
 *  PENDING `GiftCard` (flips ACTIVE on invoice close). */
export function useAddGiftCardSale(invoiceId: number) {
  const qc = useQueryClient();
  return useMutation<Invoice, Error, AddGiftCardSaleInput>({
    mutationFn: (input) =>
      api.post<Invoice>(
        `/api/invoices/${invoiceId}/add-gift-card-sale/`,
        input,
      ),
    onSuccess: (updated) => {
      qc.setQueryData(invoiceDetailKey(updated.id), updated);
      if (updated.appointment) {
        qc.invalidateQueries({
          queryKey: invoiceByAppointmentKey(updated.appointment.id),
        });
      }
      qc.invalidateQueries({ queryKey: ['gift-cards'] });
    },
  });
}

/** Apply some of a gift card's balance toward this OPEN invoice.
 *  Decrements card balance + bumps `gift_card_credits_cents`. */
export function useApplyGiftCard(invoiceId: number) {
  const qc = useQueryClient();
  return useMutation<Invoice, Error, ApplyGiftCardInput>({
    mutationFn: (input) =>
      api.post<Invoice>(
        `/api/invoices/${invoiceId}/apply-gift-card/`,
        input,
      ),
    onSuccess: (updated) => {
      qc.setQueryData(invoiceDetailKey(updated.id), updated);
      if (updated.appointment) {
        qc.invalidateQueries({
          queryKey: invoiceByAppointmentKey(updated.appointment.id),
        });
      }
      qc.invalidateQueries({ queryKey: ['gift-cards'] });
    },
  });
}

/** Reverse a previously-applied gift card credit. The original
 *  REDEEM ledger row is preserved; a REVERSAL row is appended. */
export function useReverseGiftCardRedemption(invoiceId: number) {
  const qc = useQueryClient();
  return useMutation<Invoice, Error, number>({
    mutationFn: (ledgerId) =>
      api.delete<Invoice>(
        `/api/invoices/${invoiceId}/gift-card-redemptions/${ledgerId}/`,
      ),
    onSuccess: (updated) => {
      qc.setQueryData(invoiceDetailKey(updated.id), updated);
      if (updated.appointment) {
        qc.invalidateQueries({
          queryKey: invoiceByAppointmentKey(updated.appointment.id),
        });
      }
      qc.invalidateQueries({ queryKey: ['gift-cards'] });
    },
  });
}

/** Void an open invoice. 409 if invoice is paid (must reopen first). */
export function useVoidInvoice(invoiceId: number) {
  const qc = useQueryClient();
  return useMutation<Invoice, Error, VoidInvoiceInput>({
    mutationFn: (input) => api.post<Invoice>(`/api/invoices/${invoiceId}/void/`, input),
    onSuccess: (updated) => {
      qc.setQueryData(invoiceDetailKey(updated.id), updated);
      if (updated.appointment) {
        qc.invalidateQueries({
          queryKey: invoiceByAppointmentKey(updated.appointment.id),
        });
      }
      qc.invalidateQueries({ queryKey: ['appointments'] });
    },
  });
}

// ── Display helpers ──────────────────────────────────────────────────────

export const INVOICE_STATUS_LABELS: Record<InvoiceStatus, string> = {
  open: 'Open',
  paid: 'Paid',
  void: 'Void',
};

export const INVOICE_STATUS_TONE: Record<
  InvoiceStatus,
  'neutral' | 'success' | 'destructive'
> = {
  open: 'neutral',
  paid: 'success',
  void: 'destructive',
};

/** Format cents as a USD currency string. */
export function formatMoneyCents(cents: number): string {
  return (cents / 100).toLocaleString(undefined, {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

/** Pull a human error message from an ApiError body, falling back to a default. */
export function invoiceErrorMessage(err: unknown, fallback: string): string {
  if (err instanceof ApiError && typeof err.body === 'object' && err.body) {
    const body = err.body as { detail?: string };
    if (typeof body.detail === 'string' && body.detail) return body.detail;
  }
  return fallback;
}
