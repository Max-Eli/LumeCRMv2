/**
 * Invoice data. Pairs with `apps.invoices` at `/api/invoices/`. One
 * invoice is auto-created per appointment; closing it records payment
 * and (per ADR 0007) moves the appointment to `completed`.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { useAuth } from './auth';

export type InvoiceStatus = 'open' | 'paid' | 'void';

export type PaymentMethod =
  | 'cash'
  | 'check'
  | 'card_external'
  | 'gift_card'
  | 'other';

export const PAYMENT_METHODS: { value: PaymentMethod; label: string }[] = [
  { value: 'cash', label: 'Cash' },
  { value: 'check', label: 'Check' },
  { value: 'card_external', label: 'Card (external terminal)' },
  { value: 'gift_card', label: 'Gift card' },
  { value: 'other', label: 'Other' },
];

export interface InvoiceLineItem {
  id: number;
  description: string;
  quantity: number;
  unit_price_cents: number;
  line_subtotal_cents: number;
  line_tax_cents: number;
}

export interface Invoice {
  id: number;
  invoice_number: string;
  status: InvoiceStatus;
  subtotal_cents: number;
  tax_cents: number;
  total_cents: number;
  amount_due_cents: number;
  payment_method: PaymentMethod | '';
  closed_at: string | null;
  line_items: InvoiceLineItem[];
  is_reopen_window_open: boolean;
}

/** "$120.00" from a cents amount. */
export function formatMoney(cents: number): string {
  return `$${(cents / 100).toFixed(2)}`;
}

/** The invoice attached to an appointment (one per appointment). */
export function useInvoiceForAppointment(appointmentId: number) {
  const { authedFetch } = useAuth();
  return useQuery({
    queryKey: ['invoices', 'appointment', appointmentId],
    queryFn: async () => {
      const list = await authedFetch<Invoice[]>(
        `/api/invoices/?appointment=${appointmentId}`,
      );
      return list[0] ?? null;
    },
    enabled: Number.isFinite(appointmentId) && appointmentId > 0,
  });
}

/** Close an open invoice — records payment. Also flips the linked
 *  appointment to completed, so appointment caches are invalidated. */
export function useCloseInvoice(invoiceId: number) {
  const { authedFetch } = useAuth();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (method: PaymentMethod) =>
      authedFetch<Invoice>(`/api/invoices/${invoiceId}/close/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ payment_method: method }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['invoices'] });
      queryClient.invalidateQueries({ queryKey: ['appointments'] });
    },
  });
}

/** Reopen a paid invoice. */
export function useReopenInvoice(invoiceId: number) {
  const { authedFetch } = useAuth();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (reason: string) =>
      authedFetch<Invoice>(`/api/invoices/${invoiceId}/reopen/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reason }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['invoices'] });
      queryClient.invalidateQueries({ queryKey: ['appointments'] });
    },
  });
}
