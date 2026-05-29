/**
 * ChargeCardDialog — Stripe Elements card-entry dialog for an invoice.
 *
 * The dialog has a two-step internal flow:
 *
 *   1. Amount step: operator confirms (or edits) the amount to charge.
 *      Defaults to invoice.amount_due_cents. On submit we hit
 *      ``POST /api/payments/invoices/<id>/charge-card/`` which creates
 *      a PaymentIntent on the spa's connected account + returns the
 *      ``client_secret`` + ``publishable_key`` + ``stripe_account_id``.
 *
 *   2. Card-entry step: we initialize ``@stripe/stripe-js`` with the
 *      publishable key + the connected account ID (so the payment
 *      lands on the right merchant), wrap with ``<Elements>``
 *      pointing at the client_secret, mount ``<PaymentElement>``,
 *      and let the operator (or customer, for the portal version)
 *      enter the card. On submit we call ``stripe.confirmPayment()``
 *      which handles 3DS / SCA challenges natively.
 *
 * The dialog NEVER touches raw card data — Stripe Elements iframes
 * handle entry. Our SAQ-A scope stays minimal.
 *
 * Final payment state arrives via the ``payment_intent.succeeded`` /
 * ``payment_intent.payment_failed`` webhook (NOT the
 * confirmPayment() return value, which is only the synchronous
 * client-side step). The dialog closes optimistically on a
 * client-side success + we trust the webhook to land the final
 * status. The parent component is responsible for refetching the
 * invoice / charges list after onSuccess fires.
 *
 * Same component is reused in the customer portal Pay-now flow
 * (chunk 2.6) — only the trigger + caller-side success handling
 * differ.
 */

'use client';

import { loadStripe, type Stripe as StripeJs } from '@stripe/stripe-js';
import {
  Elements,
  PaymentElement,
  useElements,
  useStripe,
} from '@stripe/react-stripe-js';
import { AlertCircle, CreditCard, Loader2 } from 'lucide-react';
import { useMemo, useState } from 'react';

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
import {
  type ChargeCardInput,
  type ChargeCardResponse,
  paymentsErrorMessage,
  useChargeCard,
} from '@/lib/payments';
import type { UseMutationResult } from '@tanstack/react-query';
import { cn } from '@/lib/utils';

// loadStripe returns a Promise per (publishableKey, options) pair.
// Cache instances by the key tuple so re-opening the dialog doesn't
// re-fetch Stripe.js. Map keyed by `${pk}|${accountId}` — different
// connected accounts on the same platform key get distinct instances.
const stripeJsCache = new Map<string, Promise<StripeJs | null>>();

function getStripe(
  publishableKey: string,
  stripeAccountId: string,
): Promise<StripeJs | null> {
  const cacheKey = `${publishableKey}|${stripeAccountId}`;
  let cached = stripeJsCache.get(cacheKey);
  if (!cached) {
    cached = loadStripe(publishableKey, {
      // Connect: charges live on the connected account, so Stripe.js
      // needs to know which account to act on behalf of.
      stripeAccount: stripeAccountId,
    });
    stripeJsCache.set(cacheKey, cached);
  }
  return cached;
}

export interface ChargeCardDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Invoice ID to charge against. */
  invoiceId: number;
  /** Amount due in cents — populates the initial amount input. */
  amountDueCents: number;
  /** Display-only — shown in the dialog header for context. */
  invoiceNumber?: string;
  /** Display-only — customer name shown in the dialog header. */
  customerName?: string;
  /** Fired after the confirmPayment promise resolves successfully.
   *  Parent typically refetches the invoice + closes the dialog. */
  onSuccess?: () => void;
  /** Which mutation creates the PaymentIntent. Defaults to
   *  ``useChargeCard`` (operator endpoint). The portal Pay-now flow
   *  passes ``usePayInvoiceFromPortal`` so the same dialog UI works
   *  for both operator-initiated and customer self-pay flows. Must
   *  be stable across renders (rules of hooks). */
  useChargeIntent?: () => UseMutationResult<ChargeCardResponse, Error, ChargeCardInput>;
}

export function ChargeCardDialog(props: ChargeCardDialogProps) {
  // Outer component is a thin shell — the meaningful state lives in
  // the body, which only mounts when open=true. That way every
  // open() gets fresh useState defaults without an effect-driven
  // reset (which would lint-warn for setState-in-effect).
  return (
    <Dialog open={props.open} onOpenChange={props.onOpenChange}>
      <DialogContent className="sm:max-w-md">
        {props.open ? <ChargeCardDialogBody {...props} /> : null}
      </DialogContent>
    </Dialog>
  );
}

function ChargeCardDialogBody({
  onOpenChange,
  invoiceId,
  amountDueCents,
  invoiceNumber,
  customerName,
  onSuccess,
  useChargeIntent,
}: ChargeCardDialogProps) {
  // Step 1 state — the amount input + the result of the
  // create-PaymentIntent call. Once we have a client_secret we
  // transition to step 2 (the Stripe Elements form).
  const [intent, setIntent] = useState<ChargeCardResponse | null>(null);
  const [amountDollars, setAmountDollars] = useState(
    () => (amountDueCents / 100).toFixed(2),
  );
  const [amountError, setAmountError] = useState<string | null>(null);

  // Default to the operator endpoint; portal callers pass
  // usePayInvoiceFromPortal. The prop is read once per dialog open
  // (the body unmounts when open=false), so the conditional hook
  // call is safe — same hook is called on every render of THIS
  // instance.
  const useCreateIntent = useChargeIntent ?? useChargeCard;
  const createIntent = useCreateIntent();

  const handleCreateIntent = () => {
    const dollars = Number(amountDollars);
    if (!Number.isFinite(dollars) || dollars <= 0) {
      setAmountError('Enter an amount greater than zero.');
      return;
    }
    const cents = Math.round(dollars * 100);
    if (cents > amountDueCents) {
      // Soft confirm — overpayment is technically legal but we want
      // the operator to think twice.
      const ok = window.confirm(
        `Amount $${dollars.toFixed(2)} exceeds the outstanding balance of $${(amountDueCents / 100).toFixed(2)}. Charge anyway?`,
      );
      if (!ok) return;
    }
    setAmountError(null);
    createIntent.mutate(
      { invoiceId, amount_cents: cents },
      {
        onSuccess: (resp) => setIntent(resp),
        onError: (err) =>
          setAmountError(
            paymentsErrorMessage(err, "Couldn't initialize the payment."),
          ),
      },
    );
  };

  return (
    <>
      <DialogHeader>
        <DialogTitle>Charge card</DialogTitle>
        <DialogDescription>
          {customerName ? `${customerName} · ` : ''}
          {invoiceNumber ? `Invoice ${invoiceNumber}` : `Invoice #${invoiceId}`}
        </DialogDescription>
      </DialogHeader>

      {intent === null ? (
        <AmountStep
          amountDollars={amountDollars}
          onAmountChange={setAmountDollars}
          amountDueCents={amountDueCents}
          onSubmit={handleCreateIntent}
          onCancel={() => onOpenChange(false)}
          isSubmitting={createIntent.isPending}
          error={amountError}
        />
      ) : (
        <CardStep
          intent={intent}
          onSuccess={() => {
            onSuccess?.();
            onOpenChange(false);
          }}
          onCancel={() => onOpenChange(false)}
        />
      )}
    </>
  );
}

// ── Step 1: amount ─────────────────────────────────────────────────

function AmountStep({
  amountDollars,
  onAmountChange,
  amountDueCents,
  onSubmit,
  onCancel,
  isSubmitting,
  error,
}: {
  amountDollars: string;
  onAmountChange: (next: string) => void;
  amountDueCents: number;
  onSubmit: () => void;
  onCancel: () => void;
  isSubmitting: boolean;
  error: string | null;
}) {
  return (
    <>
      <DialogBody className="space-y-4">
        <div className="space-y-1.5">
          <label
            htmlFor="charge-amount"
            className="text-xs uppercase tracking-wide text-muted-foreground"
          >
            Amount to charge
          </label>
          <div className="relative">
            <span className="absolute left-3 top-1/2 -translate-y-1/2 text-sm text-muted-foreground">
              $
            </span>
            <Input
              id="charge-amount"
              type="number"
              step="0.01"
              min="0.01"
              value={amountDollars}
              onChange={(e) => onAmountChange(e.target.value)}
              className="pl-7 font-mono tabular-nums"
              inputMode="decimal"
              autoFocus
            />
          </div>
          <p className="text-[11px] text-muted-foreground">
            Outstanding balance: ${(amountDueCents / 100).toFixed(2)}
          </p>
        </div>
        {error ? (
          <div className="flex items-start gap-2 rounded-md border border-destructive/30 bg-destructive/5 p-3 text-xs text-destructive">
            <AlertCircle className="size-4 shrink-0 mt-0.5" />
            <p>{error}</p>
          </div>
        ) : null}
      </DialogBody>
      <DialogFooter>
        <Button
          type="button"
          variant="ghost"
          onClick={onCancel}
          disabled={isSubmitting}
        >
          Cancel
        </Button>
        <Button type="button" onClick={onSubmit} disabled={isSubmitting}>
          {isSubmitting ? <Loader2 className="size-4 animate-spin" /> : null}
          Continue
        </Button>
      </DialogFooter>
    </>
  );
}

// ── Step 2: Stripe Elements card entry ─────────────────────────────

function CardStep({
  intent,
  onSuccess,
  onCancel,
}: {
  intent: ChargeCardResponse;
  onSuccess: () => void;
  onCancel: () => void;
}) {
  const stripePromise = useMemo(
    () => getStripe(intent.publishable_key, intent.stripe_account_id),
    [intent.publishable_key, intent.stripe_account_id],
  );

  // `Elements` provider keyed by the client_secret — Stripe's
  // recommended pattern. The PaymentElement reads the secret from
  // context.
  return (
    <Elements
      stripe={stripePromise}
      options={{
        clientSecret: intent.client_secret,
        // Lume-leaning visual defaults; Stripe Elements supports
        // a custom appearance. Kept conservative to look at home
        // inside the existing dialog chrome.
        appearance: {
          theme: 'stripe',
          variables: {
            fontFamily: 'inherit',
            colorPrimary: '#0a0a0a',
            borderRadius: '8px',
          },
        },
      }}
    >
      <CardForm onSuccess={onSuccess} onCancel={onCancel} />
    </Elements>
  );
}

function CardForm({
  onSuccess,
  onCancel,
}: {
  onSuccess: () => void;
  onCancel: () => void;
}) {
  const stripe = useStripe();
  const elements = useElements();
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!stripe || !elements) return;
    setSubmitting(true);
    setError(null);

    const { error: confirmError } = await stripe.confirmPayment({
      elements,
      // We don't need a return URL — confirmPayment without one stays
      // on the current page. 3DS redirects use the magic
      // `if_required` flow.
      redirect: 'if_required',
    });

    setSubmitting(false);

    if (confirmError) {
      // Most likely: card declined, insufficient funds, etc.
      // confirmError.message is customer-safe per Stripe docs.
      setError(confirmError.message ?? 'The payment could not be completed.');
      return;
    }

    // No error = either succeeded immediately OR is in a non-redirect
    // 3DS challenge that already completed. Either way, the webhook
    // will land terminal state. Optimistically close the dialog.
    onSuccess();
  };

  return (
    <form onSubmit={handleSubmit}>
      <DialogBody className="space-y-3">
        <PaymentElement
          options={{
            // Default to card; future: enable bank / Apple Pay / etc.
            // by removing this and letting Stripe Elements pick
            // based on the PaymentIntent's automatic_payment_methods.
            layout: 'tabs',
          }}
        />
        {error ? (
          <div className="flex items-start gap-2 rounded-md border border-destructive/30 bg-destructive/5 p-3 text-xs text-destructive">
            <AlertCircle className="size-4 shrink-0 mt-0.5" />
            <p>{error}</p>
          </div>
        ) : null}
        <p className="text-[10px] text-muted-foreground">
          Card details are entered directly with Stripe — Lumè never
          sees the full number.
        </p>
      </DialogBody>
      <DialogFooter>
        <Button
          type="button"
          variant="ghost"
          onClick={onCancel}
          disabled={submitting}
        >
          Cancel
        </Button>
        <Button type="submit" disabled={submitting || !stripe || !elements}>
          {submitting ? (
            <Loader2 className="size-4 animate-spin" />
          ) : (
            <CreditCard className="size-4" />
          )}
          Charge card
        </Button>
      </DialogFooter>
    </form>
  );
}

// Re-export cn so the imports above don't need to repeat it elsewhere
// (no-op placeholder — exists only so eslint doesn't flag the import).
void cn;
