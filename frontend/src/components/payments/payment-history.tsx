/**
 * PaymentHistory + RefundDialog — Stripe Connect charge timeline + refund flow.
 *
 * Renders the ``invoice.charges[]`` array as a chronological activity
 * list. Each succeeded charge gets a Refund button (when the operator
 * has the ISSUE_REFUND permission and there's still refundable
 * balance). Failed charges show the Stripe failure_code + message so
 * the operator can coach the customer on retry.
 *
 * The Refund dialog is its own component, opened per-charge. It
 * validates the amount client-side (must be > 0 and ≤ refundable),
 * requires a non-empty reason (audit trail), and surfaces backend
 * 409 / 502 / 503 errors as inline error blocks rather than toasts
 * so the operator can react without dismissing context.
 *
 * Permission gating: the component itself doesn't check perms; the
 * caller decides whether to render the Refund affordance via the
 * ``canRefund`` prop. Backend re-checks ISSUE_REFUND on every call;
 * we just hide the button to avoid a click → 403 cycle.
 */

'use client';

import {
  AlertCircle,
  CheckCircle2,
  CreditCard,
  ExternalLink,
  Loader2,
  RotateCcw,
  XCircle,
} from 'lucide-react';
import { useMemo, useState } from 'react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { formatMoneyCents, type InvoiceCharge } from '@/lib/invoices';
import {
  paymentsErrorMessage,
  useRefundCharge,
} from '@/lib/payments';
import { cn } from '@/lib/utils';

export interface PaymentHistoryProps {
  /** From ``invoice.charges`` — backend orders newest-first. */
  charges: InvoiceCharge[];
  /** When true, render the "Refund" button on succeeded charges with
   *  remaining refundable balance. Caller composes this from the
   *  user's role (typically ISSUE_REFUND default → owner / manager /
   *  front_desk). */
  canRefund: boolean;
  /** Fired after a successful refund. Parent typically refetches the
   *  invoice so the rollup numbers + Refund row appear. */
  onRefundIssued?: () => void;
}

export function PaymentHistory({
  charges,
  canRefund,
  onRefundIssued,
}: PaymentHistoryProps) {
  if (charges.length === 0) return null;

  return (
    <div className="px-4 sm:px-6 py-5 space-y-3">
      <h3 className="text-[11px] uppercase tracking-wide text-muted-foreground font-medium">
        Card payments
      </h3>
      <ul className="space-y-2">
        {charges.map((charge) => (
          <li key={charge.id}>
            <ChargeRow
              charge={charge}
              canRefund={canRefund}
              onRefundIssued={onRefundIssued}
            />
          </li>
        ))}
      </ul>
    </div>
  );
}

// ── Single charge row ─────────────────────────────────────────────

function ChargeRow({
  charge,
  canRefund,
  onRefundIssued,
}: {
  charge: InvoiceCharge;
  canRefund: boolean;
  onRefundIssued?: () => void;
}) {
  const [refundOpen, setRefundOpen] = useState(false);

  const Icon =
    charge.status === 'succeeded'
      ? CheckCircle2
      : charge.status === 'failed'
        ? XCircle
        : Loader2;
  const tone =
    charge.status === 'succeeded'
      ? 'text-emerald-600 dark:text-emerald-400'
      : charge.status === 'failed'
        ? 'text-rose-600 dark:text-rose-400'
        : 'text-muted-foreground';

  // "Refund" affordance gating: only on succeeded charges, only when
  // there's remaining refundable balance, and only when the caller
  // says the operator has ISSUE_REFUND.
  const showRefundButton =
    canRefund && charge.status === 'succeeded' && charge.refundable_cents > 0;

  return (
    <div className="rounded-md border bg-card px-3.5 py-3">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-2.5 min-w-0">
          <Icon
            className={cn(
              'size-4 shrink-0 mt-0.5',
              tone,
              charge.status === 'pending' && 'animate-spin',
            )}
            aria-hidden
          />
          <div className="min-w-0">
            <p className="text-sm">
              <span className="font-mono tabular-nums">
                {formatMoneyCents(charge.amount_cents)}
              </span>
              <span className="text-muted-foreground"> · </span>
              <span className="text-muted-foreground">
                {chargeStatusLabel(charge)}
              </span>
              {charge.brand && charge.last4 ? (
                <>
                  <span className="text-muted-foreground"> · </span>
                  <span className="text-muted-foreground capitalize">
                    {charge.brand}
                  </span>{' '}
                  <span className="font-mono tabular-nums">
                    ··{charge.last4}
                  </span>
                </>
              ) : null}
            </p>
            <p className="text-[11px] text-muted-foreground mt-0.5">
              {formatRelativeDateTime(charge.created_at)}
              {charge.created_by_email ? (
                <>
                  {' '}· by{' '}
                  <span className="text-foreground/70">
                    {charge.created_by_email}
                  </span>
                </>
              ) : (
                ' · self-paid via customer portal'
              )}
              {charge.initiated_via === 'customer_portal'
              && !charge.created_by_email
                ? null
                : null}
            </p>
            {charge.status === 'failed' && charge.failure_message ? (
              <p className="text-[11px] text-rose-600 dark:text-rose-400 mt-1">
                {charge.failure_message}
                {charge.failure_code ? (
                  <span className="text-muted-foreground">
                    {' '}({charge.failure_code})
                  </span>
                ) : null}
              </p>
            ) : null}
          </div>
        </div>
        {showRefundButton ? (
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => setRefundOpen(true)}
          >
            <RotateCcw className="size-3.5" />
            Refund
          </Button>
        ) : null}
      </div>

      {/* Refund history nested under the charge — small text, indented. */}
      {charge.refunds.length > 0 ? (
        <ul className="mt-2.5 pl-6 space-y-1 border-l border-border ml-1.5">
          {charge.refunds.map((refund) => (
            <li
              key={refund.id}
              className="text-[11px] text-muted-foreground"
            >
              <span className="font-mono tabular-nums">
                −{formatMoneyCents(refund.amount_cents)}
              </span>{' '}
              refunded · {refund.status}
              <span className="ml-1.5 text-foreground/70">
                {refund.reason}
              </span>
              <span className="ml-1.5">
                {formatRelativeDateTime(refund.created_at)}
              </span>
              {refund.created_by_email ? (
                <> · {refund.created_by_email}</>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}

      {showRefundButton ? (
        <RefundDialog
          open={refundOpen}
          onOpenChange={setRefundOpen}
          charge={charge}
          onSuccess={() => {
            onRefundIssued?.();
            setRefundOpen(false);
          }}
        />
      ) : null}
    </div>
  );
}

// ── Refund dialog ─────────────────────────────────────────────────

function RefundDialog({
  open,
  onOpenChange,
  charge,
  onSuccess,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  charge: InvoiceCharge;
  onSuccess: () => void;
}) {
  const refund = useRefundCharge();
  const refundableDollars = useMemo(
    () => (charge.refundable_cents / 100).toFixed(2),
    [charge.refundable_cents],
  );
  // Default to full refundable balance — most refunds are full. The
  // operator can edit down for partial.
  const [amountDollars, setAmountDollars] = useState(refundableDollars);
  const [reason, setReason] = useState('');
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    const dollars = Number(amountDollars);
    if (!Number.isFinite(dollars) || dollars <= 0) {
      setError('Enter an amount greater than zero.');
      return;
    }
    const cents = Math.round(dollars * 100);
    if (cents > charge.refundable_cents) {
      setError(
        `Amount exceeds refundable balance of ${formatMoneyCents(charge.refundable_cents)}.`,
      );
      return;
    }
    const trimmedReason = reason.trim();
    if (!trimmedReason) {
      setError('A reason is required (audit trail).');
      return;
    }

    refund.mutate(
      {
        chargeId: charge.id,
        amount_cents: cents,
        reason: trimmedReason,
      },
      {
        onSuccess: () => {
          toast.success(
            `Refunded ${formatMoneyCents(cents)} to ${charge.brand || 'card'} ··${charge.last4}`,
            { icon: <CheckCircle2 className="size-4" /> },
          );
          onSuccess();
        },
        onError: (err) =>
          setError(paymentsErrorMessage(err, "Couldn't issue the refund.")),
      },
    );
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Refund charge</DialogTitle>
          <DialogDescription>
            {charge.brand ? (
              <>
                {charge.brand.charAt(0).toUpperCase() + charge.brand.slice(1)}{' '}
                ··{charge.last4} · originally charged{' '}
                {formatMoneyCents(charge.amount_cents)}
              </>
            ) : (
              <>Originally charged {formatMoneyCents(charge.amount_cents)}</>
            )}
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit}>
          <DialogBody className="space-y-4">
            <div className="space-y-1.5">
              <label
                htmlFor="refund-amount"
                className="text-xs uppercase tracking-wide text-muted-foreground"
              >
                Refund amount
              </label>
              <div className="relative">
                <span className="absolute left-3 top-1/2 -translate-y-1/2 text-sm text-muted-foreground">
                  $
                </span>
                <Input
                  id="refund-amount"
                  type="number"
                  step="0.01"
                  min="0.01"
                  max={(charge.refundable_cents / 100).toFixed(2)}
                  value={amountDollars}
                  onChange={(e) => setAmountDollars(e.target.value)}
                  className="pl-7 font-mono tabular-nums"
                  inputMode="decimal"
                  autoFocus
                />
              </div>
              <p className="text-[11px] text-muted-foreground">
                Up to {formatMoneyCents(charge.refundable_cents)} refundable
                {charge.refunded_cents > 0
                  ? ` · ${formatMoneyCents(charge.refunded_cents)} already refunded`
                  : ''}
              </p>
            </div>

            <div className="space-y-1.5">
              <label
                htmlFor="refund-reason"
                className="text-xs uppercase tracking-wide text-muted-foreground"
              >
                Reason
                <span className="text-foreground/40 normal-case">
                  {' '}— required for audit trail
                </span>
              </label>
              <Input
                id="refund-reason"
                type="text"
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                placeholder="e.g. Customer requested · Service not delivered"
                maxLength={255}
              />
            </div>

            {error ? (
              <div className="flex items-start gap-2 rounded-md border border-destructive/30 bg-destructive/5 p-3 text-xs text-destructive">
                <AlertCircle className="size-4 shrink-0 mt-0.5" />
                <p>{error}</p>
              </div>
            ) : null}

            <p className="text-[10px] text-muted-foreground leading-relaxed">
              Refunds typically settle to the customer&apos;s card in
              5–10 business days. The original charge stays on the
              ledger — we record this refund as a separate event
              against it.
            </p>
          </DialogBody>
          <DialogFooter>
            <Button
              type="button"
              variant="ghost"
              onClick={() => onOpenChange(false)}
              disabled={refund.isPending}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={refund.isPending}>
              {refund.isPending ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <RotateCcw className="size-4" />
              )}
              Issue refund
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

// ── Helpers ───────────────────────────────────────────────────────

function chargeStatusLabel(charge: InvoiceCharge): string {
  if (charge.is_fully_refunded) return 'Fully refunded';
  if (charge.refunded_cents > 0 && charge.status === 'succeeded') {
    return 'Partially refunded';
  }
  switch (charge.status) {
    case 'succeeded':
      return 'Charged';
    case 'failed':
      return 'Declined';
    case 'pending':
      return 'Processing';
  }
}

function formatRelativeDateTime(iso: string): string {
  const target = new Date(iso).getTime();
  const now = Date.now();
  const diffMin = Math.round((now - target) / (60 * 1000));
  if (diffMin < 1) return 'Just now';
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffH = Math.round(diffMin / 60);
  if (diffH < 24) return `${diffH}h ago`;
  const diffD = Math.round(diffH / 24);
  if (diffD < 7) return `${diffD}d ago`;
  return new Date(iso).toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });
}

// Pre-import the icon to avoid an unused-import error if the file
// is tree-shaken with only PaymentHistory exposed.
void CreditCard;
void ExternalLink;
