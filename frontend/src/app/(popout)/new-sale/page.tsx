/**
 * `/new-sale` — standalone popout for a walk-in sale.
 *
 * Spawned by the calendar right-rail "New sale" tile. A walk-in wants
 * to buy a product, gift card, or membership with no appointment:
 *   1. Pick the client.
 *   2. A blank standalone invoice is opened for them.
 *   3. The popout hands off to the take-payment page, where the
 *      operator adds line items and takes payment.
 */

'use client';

import { Loader2, ShoppingBag } from 'lucide-react';
import { useRouter } from 'next/navigation';
import { useState } from 'react';

import { CustomerSearchPicker } from '@/components/customer-search-picker';
import type { CustomerListItem } from '@/lib/customers';
import { useCreateStandaloneInvoice } from '@/lib/invoices';

export default function NewSalePopoutPage() {
  const router = useRouter();
  const create = useCreateStandaloneInvoice();
  const [error, setError] = useState<string | null>(null);

  const onPick = async (customer: CustomerListItem) => {
    setError(null);
    try {
      const invoice = await create.mutateAsync({ customer_id: customer.id });
      // Hand off to the take-payment page in standalone mode. No
      // ?action=pay — the invoice is empty, so the operator adds line
      // items first and then takes payment.
      router.push(`/invoice/${invoice.id}?by=invoice`);
    } catch {
      setError('Couldn’t start the sale. Please try again.');
    }
  };

  return (
    <div className="flex flex-col h-screen bg-muted/30">
      <header className="shrink-0 border-b bg-card px-6 py-3 flex items-center gap-3">
        <div
          className="inline-flex size-8 items-center justify-center rounded-md bg-accent/15 text-accent-foreground"
          aria-hidden
        >
          <ShoppingBag className="size-4" />
        </div>
        <div className="leading-tight">
          <h1 className="text-sm font-serif font-semibold tracking-tight">
            New sale
          </h1>
          <p className="text-[10px] uppercase tracking-wide text-muted-foreground">
            Walk-in purchase — no appointment
          </p>
        </div>
      </header>

      <main className="flex-1 min-h-0 overflow-y-auto">
        {create.isPending ? (
          <div className="flex flex-col items-center justify-center gap-3 py-24 text-muted-foreground">
            <Loader2 className="size-5 animate-spin" />
            <p className="text-sm">Opening the sale…</p>
          </div>
        ) : (
          <>
            <CustomerSearchPicker
              onPick={onPick}
              title="Who is this sale for?"
              subtitle="Pick the client, then add products, gift cards, or memberships and take payment."
            />
            {error ? (
              <p className="-mt-6 pb-6 text-center text-sm text-destructive">
                {error}
              </p>
            ) : null}
          </>
        )}
      </main>
    </div>
  );
}
