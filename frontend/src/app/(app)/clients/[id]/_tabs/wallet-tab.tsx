/**
 * `WalletTab` — invoice + outstanding-balance view for a customer.
 *
 * Top of the tab: the at-a-glance balance ("$X open across N
 * invoices"). Below that, a table of invoices grouped by status —
 * Open invoices first (operator's actionable list), then Paid, then
 * Voided.
 *
 * Each invoice row links to the full invoice detail page where the
 * operator can close / reopen / void per Phase 1E semantics. This
 * tab is the read-side; mutations live on the dedicated invoice
 * page.
 */

'use client';

import {
  ChevronRight,
  CircleDollarSign,
  Clock,
  Receipt,
} from 'lucide-react';
import { useMemo } from 'react';

import {
  type Invoice,
  type InvoiceStatus,
  formatMoneyCents,
  openInvoiceWindow,
  openStandaloneInvoiceWindow,
  PAYMENT_METHOD_LABELS,
  useCustomerInvoices,
} from '@/lib/invoices';
import { cn } from '@/lib/utils';

const STATUS_TONE: Record<InvoiceStatus, 'open' | 'paid' | 'void'> = {
  open: 'open',
  paid: 'paid',
  void: 'void',
};

const STATUS_LABELS: Record<InvoiceStatus, string> = {
  open: 'Open',
  paid: 'Paid',
  void: 'Voided',
};

export function WalletTab({ customerId }: { customerId: number }) {
  const { data: invoices, isLoading, error } = useCustomerInvoices(customerId);

  const stats = useMemo(() => deriveStats(invoices ?? []), [invoices]);
  const grouped = useMemo(() => groupByStatus(invoices ?? []), [invoices]);

  if (isLoading) {
    return (
      <div className="rounded-md border bg-card p-6 text-sm text-muted-foreground max-w-3xl">
        Loading wallet…
      </div>
    );
  }
  if (error) {
    return (
      <div className="rounded-md border border-destructive/40 bg-destructive/[0.04] p-4 text-sm text-destructive max-w-3xl">
        Could not load invoices.
      </div>
    );
  }

  if ((invoices ?? []).length === 0) {
    return <EmptyState />;
  }

  return (
    <div className="space-y-8 max-w-3xl">
      <BalanceSummary
        openCents={stats.openCents}
        openCount={stats.openCount}
        lifetimePaidCents={stats.lifetimePaidCents}
        lifetimeInvoiceCount={stats.lifetimeInvoiceCount}
      />

      {grouped.open.length > 0 ? (
        <Section title="Open" count={grouped.open.length}>
          <InvoiceList items={grouped.open} />
        </Section>
      ) : null}

      {grouped.paid.length > 0 ? (
        <Section title="Paid" count={grouped.paid.length}>
          <InvoiceList items={grouped.paid} />
        </Section>
      ) : null}

      {grouped.void.length > 0 ? (
        <Section title="Voided" count={grouped.void.length}>
          <InvoiceList items={grouped.void} />
        </Section>
      ) : null}
    </div>
  );
}

// ── Sub-components ───────────────────────────────────────────────────

function BalanceSummary({
  openCents,
  openCount,
  lifetimePaidCents,
  lifetimeInvoiceCount,
}: {
  openCents: number;
  openCount: number;
  lifetimePaidCents: number;
  lifetimeInvoiceCount: number;
}) {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
      {/* Open balance — primary, owner-eye-catching emerald accent
          when zero, amber when there's actually something owed. */}
      <div
        className={cn(
          'rounded-lg border bg-card overflow-hidden',
          openCents > 0 ? 'border-amber-200' : 'border-border',
        )}
      >
        <div
          className={cn(
            'px-4 py-3 border-b',
            openCents > 0
              ? 'bg-amber-50/60 border-amber-200'
              : 'bg-emerald-50/40 border-border',
          )}
        >
          <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-medium inline-flex items-center gap-1">
            <CircleDollarSign className="size-3" aria-hidden />
            Open balance
          </p>
          <p
            className={cn(
              'text-2xl font-semibold tracking-tight tabular-nums mt-1',
              openCents > 0 ? 'text-amber-900' : 'text-foreground',
            )}
          >
            {formatMoneyCents(openCents)}
          </p>
          <p className="text-[11px] text-muted-foreground mt-0.5 tabular-nums">
            {openCount === 0
              ? 'No outstanding invoices.'
              : `${openCount} ${openCount === 1 ? 'invoice' : 'invoices'} awaiting payment`}
          </p>
        </div>
      </div>

      {/* Lifetime spend — context for VIP / spend-tier decisions. */}
      <div className="rounded-lg border border-border bg-card overflow-hidden">
        <div className="px-4 py-3 border-b border-border bg-muted/30">
          <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-medium inline-flex items-center gap-1">
            <Receipt className="size-3" aria-hidden />
            Lifetime paid
          </p>
          <p className="text-2xl font-semibold tracking-tight tabular-nums mt-1 text-foreground">
            {formatMoneyCents(lifetimePaidCents)}
          </p>
          <p className="text-[11px] text-muted-foreground mt-0.5 tabular-nums">
            Across {lifetimeInvoiceCount} {lifetimeInvoiceCount === 1 ? 'invoice' : 'invoices'}
          </p>
        </div>
      </div>
    </div>
  );
}

function Section({
  title,
  count,
  children,
}: {
  title: string;
  count: number;
  children: React.ReactNode;
}) {
  return (
    <section>
      <header className="flex items-baseline gap-2 mb-3">
        <h2 className="font-serif text-base font-semibold tracking-tight text-foreground">
          {title}
        </h2>
        <span className="text-xs tabular-nums text-muted-foreground">
          {count}
        </span>
      </header>
      {children}
    </section>
  );
}

function EmptyState() {
  return (
    <div className="rounded-lg border border-dashed bg-muted/20 p-8 text-center max-w-2xl">
      <div className="inline-flex size-10 items-center justify-center rounded-full bg-card text-muted-foreground border mb-3">
        <Receipt className="size-4" />
      </div>
      <h3 className="font-serif text-base font-semibold tracking-tight">
        No invoices yet
      </h3>
      <p className="text-xs text-muted-foreground mt-1.5 leading-relaxed">
        Invoices auto-generate when this customer books an appointment.
        Their balance + payment history will live here.
      </p>
    </div>
  );
}

function InvoiceList({ items }: { items: Invoice[] }) {
  return (
    <ul className="divide-y divide-border rounded-lg border bg-card overflow-hidden">
      {items.map((inv) => (
        <li key={inv.id}>
          <InvoiceRow invoice={inv} />
        </li>
      ))}
    </ul>
  );
}

function InvoiceRow({ invoice }: { invoice: Invoice }) {
  const dateLabel = formatDate(
    invoice.status === 'paid' && invoice.closed_at
      ? invoice.closed_at
      : invoice.created_at,
  );
  // Invoice detail opens in a separate popup window so the operator's
  // checkout context lives outside the CRM dashboard chrome. An
  // appointment invoice opens by appointment id; a standalone invoice
  // (custom package — no appointment) opens by its own invoice id.
  const appointmentId = invoice.appointment?.id ?? null;
  const openDetail = () =>
    appointmentId !== null
      ? openInvoiceWindow(appointmentId)
      : openStandaloneInvoiceWindow(invoice.id);

  const sharedClasses = cn(
    'flex items-center gap-4 px-4 py-3 transition-colors group w-full text-left',
    'hover:bg-muted/40 cursor-pointer',
  );

  const inner = (
    <>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="font-mono text-xs text-foreground/80">
            {invoice.invoice_number || `#${invoice.id}`}
          </span>
          <StatusPill status={invoice.status} />
          {invoice.appointment ? (
            <span className="text-xs text-muted-foreground truncate">
              {invoice.appointment.service_name}
            </span>
          ) : null}
        </div>
        <div className="flex items-center gap-3 text-xs text-muted-foreground mt-1 tabular-nums flex-wrap">
          <span className="inline-flex items-center gap-1">
            <Clock className="size-3" />
            {invoice.status === 'paid' ? 'Paid' : 'Created'} {dateLabel}
          </span>
          {invoice.status === 'paid' && invoice.payment_method ? (
            <span>{PAYMENT_METHOD_LABELS[invoice.payment_method]}</span>
          ) : null}
        </div>
      </div>
      <div className="text-right shrink-0">
        <div className="text-sm font-semibold tabular-nums text-foreground">
          {formatMoneyCents(invoice.total_cents)}
        </div>
        {invoice.tax_cents > 0 ? (
          <div className="text-[10px] text-muted-foreground tabular-nums mt-0.5">
            incl. {formatMoneyCents(invoice.tax_cents)} tax
          </div>
        ) : null}
      </div>
      <ChevronRight className="size-4 text-muted-foreground/60 group-hover:text-foreground transition-colors shrink-0" />
    </>
  );

  return (
    <button type="button" onClick={openDetail} className={sharedClasses}>
      {inner}
    </button>
  );
}

function StatusPill({ status }: { status: InvoiceStatus }) {
  const tone = STATUS_TONE[status];
  return (
    <span
      className={cn(
        'inline-flex items-center rounded-full px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wider',
        tone === 'open' && 'bg-amber-50 text-amber-800',
        tone === 'paid' && 'bg-emerald-50 text-emerald-700',
        tone === 'void' && 'bg-stone-100 text-stone-600',
      )}
    >
      {STATUS_LABELS[status]}
    </span>
  );
}

// ── Helpers ─────────────────────────────────────────────────────────

function deriveStats(invoices: Invoice[]) {
  let openCents = 0;
  let openCount = 0;
  let lifetimePaidCents = 0;
  let lifetimeInvoiceCount = 0;
  for (const inv of invoices) {
    if (inv.status === 'open') {
      openCents += inv.total_cents;
      openCount += 1;
    } else if (inv.status === 'paid') {
      lifetimePaidCents += inv.total_cents;
      lifetimeInvoiceCount += 1;
    }
  }
  return { openCents, openCount, lifetimePaidCents, lifetimeInvoiceCount };
}

function groupByStatus(invoices: Invoice[]) {
  const open: Invoice[] = [];
  const paid: Invoice[] = [];
  const voided: Invoice[] = [];
  for (const inv of invoices) {
    if (inv.status === 'open') open.push(inv);
    else if (inv.status === 'paid') paid.push(inv);
    else voided.push(inv);
  }
  // Newest first within each bucket. Open uses created_at; paid uses
  // closed_at; voided uses updated_at as the relevant ordering field.
  open.sort((a, b) => b.created_at.localeCompare(a.created_at));
  paid.sort((a, b) => (b.closed_at ?? '').localeCompare(a.closed_at ?? ''));
  voided.sort((a, b) => b.updated_at.localeCompare(a.updated_at));
  return { open, paid, void: voided };
}

function formatDate(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });
}
