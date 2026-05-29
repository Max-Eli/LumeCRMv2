/**
 * `/portal/invoices` — the customer's invoice list + Pay-now flow.
 *
 * Two sections:
 *   - Outstanding (invoice.status === 'open' AND amount_due_cents > 0)
 *     Each row gets a "Pay now" CTA that opens the Stripe Elements
 *     dialog. Reuses ``ChargeCardDialog`` from the operator side,
 *     swapping in the portal-flavored ``usePayInvoiceFromPortal``
 *     hook so the PaymentIntent gets created via the portal endpoint
 *     (Charge row carries created_by=None + initiated_via='customer_portal').
 *   - History (everything else — paid, voided, or zero-balance)
 *     Read-only summary with optional payment history.
 *
 * Designed for the same portal shell as other pages — minimal chrome,
 * tenant branding via primary_color where applicable, friendly copy.
 *
 * Once the customer pays, the Stripe webhook fires + invoice closes
 * automatically (the auto-close service handles the
 * created_by=None case). The ``onSuccess`` callback on the dialog
 * just invalidates the portal-invoices query so the freshly-paid
 * invoice moves from Outstanding → History after the next webhook
 * sync (typically within seconds).
 */

'use client';

import {
  CheckCircle2,
  CreditCard,
  FileText,
  Loader2,
  Receipt,
} from 'lucide-react';
import { useMemo, useState } from 'react';

import { Button } from '@/components/ui/button';
import { ChargeCardDialog } from '@/components/payments/charge-card-dialog';
import { PaymentHistory } from '@/components/payments/payment-history';
import { formatMoneyCents } from '@/lib/invoices';
import { usePayInvoiceFromPortal } from '@/lib/payments';
import { type PortalInvoice, usePortalInvoices } from '@/lib/portal';
import { cn } from '@/lib/utils';

export default function PortalInvoicesPage() {
  const { data: invoices, isLoading } = usePortalInvoices();

  const { outstanding, history } = useMemo(() => {
    const list = invoices ?? [];
    const outstanding: PortalInvoice[] = [];
    const history: PortalInvoice[] = [];
    for (const inv of list) {
      // "Outstanding" = open AND there's a balance to pay. An open
      // invoice with $0 due (rare — gift card covered it, etc.)
      // belongs in History so the operator's manual "Close" action
      // is the only path forward, not a customer Pay-now.
      if (inv.status === 'open' && inv.amount_due_cents > 0) {
        outstanding.push(inv);
      } else {
        history.push(inv);
      }
    }
    return { outstanding, history };
  }, [invoices]);

  return (
    <div className="max-w-4xl mx-auto w-full px-6 py-10">
      <header className="mb-8">
        <h1 className="font-serif text-3xl font-semibold tracking-tight">
          Invoices
        </h1>
        <p className="text-sm text-muted-foreground mt-1.5">
          Pay outstanding balances and review your billing history.
        </p>
      </header>

      {isLoading ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : (
        <div className="space-y-8">
          <Section
            title="Outstanding"
            count={outstanding.length}
            empty="You don't have any outstanding invoices right now."
            emptyIcon={CheckCircle2}
          >
            {outstanding.map((inv) => (
              <InvoiceRow key={inv.id} invoice={inv} isOutstanding />
            ))}
          </Section>
          <Section
            title="History"
            count={history.length}
            empty="No previous invoices yet. Future bills will show here after they're paid or closed."
            emptyIcon={FileText}
          >
            {history.map((inv) => (
              <InvoiceRow key={inv.id} invoice={inv} isOutstanding={false} />
            ))}
          </Section>
        </div>
      )}
    </div>
  );
}

// ── Section shell ─────────────────────────────────────────────────

function Section({
  title,
  count,
  empty,
  emptyIcon: EmptyIcon,
  children,
}: {
  title: string;
  count: number;
  empty: string;
  emptyIcon: typeof CheckCircle2;
  children: React.ReactNode;
}) {
  return (
    <section>
      <div className="flex items-baseline justify-between mb-3">
        <h2 className="font-serif text-xl font-semibold tracking-tight">
          {title}
        </h2>
        {count > 0 ? (
          <span className="text-[11px] uppercase tracking-wide text-muted-foreground">
            {count} {count === 1 ? 'invoice' : 'invoices'}
          </span>
        ) : null}
      </div>
      {count === 0 ? (
        <div className="rounded-lg border border-dashed bg-muted/20 px-4 py-8 text-center">
          <EmptyIcon className="size-6 mx-auto text-muted-foreground/60" aria-hidden />
          <p className="text-sm text-muted-foreground mt-2 max-w-md mx-auto">
            {empty}
          </p>
        </div>
      ) : (
        <ul className="space-y-3">{children}</ul>
      )}
    </section>
  );
}

// ── Invoice row ───────────────────────────────────────────────────

function InvoiceRow({
  invoice,
  isOutstanding,
}: {
  invoice: PortalInvoice;
  isOutstanding: boolean;
}) {
  const [payOpen, setPayOpen] = useState(false);

  return (
    <li>
      <div
        className={cn(
          'rounded-lg border bg-card overflow-hidden',
          isOutstanding && 'border-amber-500/30 bg-amber-50/30 dark:bg-amber-950/15',
        )}
      >
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 p-4">
          <div className="min-w-0 flex items-start gap-3">
            <Receipt className="size-5 text-muted-foreground mt-0.5" aria-hidden />
            <div className="min-w-0">
              <p className="font-medium">
                {invoice.invoice_number || `Invoice #${invoice.id}`}
                <span className="text-muted-foreground font-normal">
                  {' '}· {formatLongDate(invoice.created_at)}
                </span>
              </p>
              <p className="text-sm text-muted-foreground mt-0.5">
                {invoice.line_items.length}{' '}
                {invoice.line_items.length === 1 ? 'item' : 'items'}
                {invoice.appointment?.service_name ? (
                  <>
                    {' '}· {invoice.appointment.service_name}
                  </>
                ) : null}
              </p>
            </div>
          </div>

          <div className="flex items-center justify-between sm:justify-end gap-4">
            <div className="text-right">
              <p className="font-mono tabular-nums text-base font-semibold">
                {isOutstanding
                  ? formatMoneyCents(invoice.amount_due_cents)
                  : formatMoneyCents(invoice.total_cents)}
              </p>
              <p className="text-[11px] uppercase tracking-wide text-muted-foreground">
                {isOutstanding ? 'Due' : invoice.status}
              </p>
            </div>
            {isOutstanding ? (
              <Button
                type="button"
                size="sm"
                onClick={() => setPayOpen(true)}
              >
                <CreditCard className="size-4" />
                Pay now
              </Button>
            ) : null}
          </div>
        </div>

        {/* Payment history (charges + refunds) — read-only here. The
            same component is reused from the operator surface; we
            pass canRefund=false because customers never refund their
            own charges through the portal (only operators can). */}
        {invoice.charges && invoice.charges.length > 0 ? (
          <div className="border-t bg-background/50">
            <PaymentHistory charges={invoice.charges} canRefund={false} />
          </div>
        ) : null}
      </div>

      {isOutstanding ? (
        <ChargeCardDialog
          open={payOpen}
          onOpenChange={setPayOpen}
          invoiceId={invoice.id}
          amountDueCents={invoice.amount_due_cents}
          invoiceNumber={invoice.invoice_number}
          customerName={invoice.customer?.full_name}
          // Portal flavor: use the portal-specific create-intent
          // hook so the backend attributes the Charge to self-pay
          // (created_by=None, initiated_via='customer_portal').
          useChargeIntent={usePayInvoiceFromPortal}
          onSuccess={() => {
            // The webhook drives the authoritative state change
            // (invoice → paid). The query invalidation inside the
            // hook covers refresh; no extra refetch needed here.
          }}
        />
      ) : null}
    </li>
  );
}

// ── Helpers ───────────────────────────────────────────────────────

function formatLongDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });
}

// Used only for the rare loading state; surfaced here so the import
// stays declared at the top.
void Loader2;
