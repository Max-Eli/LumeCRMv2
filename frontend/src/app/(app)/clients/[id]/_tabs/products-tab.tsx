/**
 * `<ProductsTab>` — retail products this customer has purchased.
 *
 * Derived from the customer's invoices: any line item with `product`
 * set is a product purchase. Voided invoices are excluded; open and
 * paid invoices both count (open ones get a "Not yet paid" pill so
 * the operator can chase payment from here).
 *
 * Read-only history surface. To sell a new product, the operator
 * uses the calendar appointment → invoice flow (or, when standalone
 * POS ships in Phase 2A, a dedicated "Quick sale" surface).
 */

'use client';

import { Package as PackageIcon, ShoppingBag } from 'lucide-react';
import Link from 'next/link';
import { useMemo } from 'react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  type Invoice,
  formatMoneyCents,
  openInvoiceWindow,
  useCustomerInvoices,
} from '@/lib/invoices';
import { cn } from '@/lib/utils';

interface ProductPurchaseRow {
  invoice: Invoice;
  line_id: number;
  description: string;
  quantity: number;
  unit_price_cents: number;
  line_subtotal_cents: number;
  created_at: string;
}

export function ProductsTab({ customerId }: { customerId: number }) {
  const { data: invoices, isLoading, error } = useCustomerInvoices(customerId);

  const rows = useMemo<ProductPurchaseRow[]>(() => {
    if (!invoices) return [];
    const result: ProductPurchaseRow[] = [];
    for (const inv of invoices) {
      if (inv.status === 'void') continue;
      for (const line of inv.line_items) {
        if (line.product == null) continue;
        result.push({
          invoice: inv,
          line_id: line.id,
          description: line.description,
          quantity: line.quantity,
          unit_price_cents: line.unit_price_cents,
          line_subtotal_cents: line.line_subtotal_cents,
          created_at: line.created_at,
        });
      }
    }
    // Newest purchases first.
    result.sort((a, b) => (a.created_at < b.created_at ? 1 : -1));
    return result;
  }, [invoices]);

  const paidTotalCents = useMemo(() => {
    return rows
      .filter((r) => r.invoice.status === 'paid')
      .reduce((sum, r) => sum + r.line_subtotal_cents, 0);
  }, [rows]);

  if (isLoading) {
    return (
      <div className="rounded-xl border bg-card px-6 py-12 text-center text-sm text-muted-foreground">
        Loading product history…
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-xl border border-destructive/40 bg-destructive/[0.04] px-6 py-6 text-sm text-destructive">
        Could not load product history.
      </div>
    );
  }

  if (rows.length === 0) {
    return (
      <div className="rounded-xl border border-dashed bg-card px-6 py-16 text-center max-w-2xl">
        <div className="inline-flex size-12 items-center justify-center rounded-full bg-muted text-muted-foreground mb-3">
          <ShoppingBag className="size-5" />
        </div>
        <p className="font-medium">No products purchased yet</p>
        <p className="text-sm text-muted-foreground mt-1 max-w-sm mx-auto">
          Products sold to this customer through an invoice show up here.
          Add a product line to an open invoice from the take-payment window
          to record a retail sale.
        </p>
        <Button
          render={<Link href="/catalog/products" />}
          nativeButton={false}
          variant="outline"
          className="mt-5"
        >
          <PackageIcon className="size-4" />
          Manage product catalog
        </Button>
      </div>
    );
  }

  return (
    <div className="space-y-4 max-w-3xl">
      <header className="flex items-center justify-between gap-3">
        <p className="text-xs text-muted-foreground">
          {rows.length} purchase{rows.length === 1 ? '' : 's'} on file
          {paidTotalCents > 0 ? (
            <>
              {' · '}
              <span className="font-medium text-foreground tabular-nums">
                {formatMoneyCents(paidTotalCents)}
              </span>{' '}
              in paid revenue
            </>
          ) : null}
        </p>
      </header>

      <ul className="rounded-xl border bg-card overflow-hidden divide-y">
        {rows.map((row) => (
          <PurchaseRow key={`${row.invoice.id}-${row.line_id}`} row={row} />
        ))}
      </ul>
    </div>
  );
}

function PurchaseRow({ row }: { row: ProductPurchaseRow }) {
  const dateLabel = new Date(row.created_at).toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });
  const tone =
    row.invoice.status === 'paid'
      ? 'paid'
      : row.invoice.status === 'open'
        ? 'open'
        : 'neutral';

  const onOpenInvoice = () => {
    if (row.invoice.appointment) {
      openInvoiceWindow(row.invoice.appointment.id);
    }
  };

  return (
    <li>
      <button
        type="button"
        onClick={onOpenInvoice}
        disabled={!row.invoice.appointment}
        className={cn(
          'w-full flex items-start gap-4 px-4 sm:px-5 py-3.5 text-left transition-colors',
          row.invoice.appointment
            ? 'hover:bg-muted/40 cursor-pointer'
            : 'cursor-default',
        )}
      >
        <div className="inline-flex size-10 items-center justify-center rounded-md bg-amber-50 text-amber-700 shrink-0 mt-0.5">
          <PackageIcon className="size-4" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <p className="font-medium text-sm">{row.description}</p>
            {tone === 'open' ? (
              <Badge
                variant="outline"
                className="font-normal text-[10.5px] px-1.5 py-0 border-amber-400/50 text-amber-700"
              >
                Not yet paid
              </Badge>
            ) : null}
          </div>
          <p className="text-xs text-muted-foreground mt-1 tabular-nums">
            Qty {row.quantity}
            <span className="mx-1.5 text-muted-foreground/50">·</span>
            {formatMoneyCents(row.unit_price_cents)} each
            <span className="mx-1.5 text-muted-foreground/50">·</span>
            {dateLabel}
            {row.invoice.invoice_number ? (
              <>
                <span className="mx-1.5 text-muted-foreground/50">·</span>
                <span className="font-mono">{row.invoice.invoice_number}</span>
              </>
            ) : null}
          </p>
        </div>
        <div className="text-right shrink-0">
          <p className="text-sm font-semibold tabular-nums">
            {formatMoneyCents(row.line_subtotal_cents)}
          </p>
        </div>
      </button>
    </li>
  );
}
