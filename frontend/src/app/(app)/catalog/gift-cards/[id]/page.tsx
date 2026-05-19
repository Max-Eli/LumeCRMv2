/**
 * `/catalog/gift-cards/[id]` — gift card detail.
 *
 * Surface for looking up a specific issued card: balance, recipient,
 * purchase history (the source invoice line + close date), full
 * append-only ledger of every issue / redeem / reversal /
 * adjustment, and the void affordance for active cards.
 *
 * Read-only otherwise — gift cards are never edited after sale
 * (PI1.1 financial integrity); changes happen via ledger rows.
 */

'use client';

import {
  AlertCircle,
  Ban,
  Check,
  ClipboardCopy,
  Gift,
  Loader2,
  Repeat2,
  Sparkles,
  Trash2,
} from 'lucide-react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { use, useState } from 'react';
import { toast } from 'sonner';

import { PageHeader } from '@/components/page-header';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { ApiError } from '@/lib/api';
import { useCurrentMembership } from '@/lib/auth';
import {
  type GiftCard,
  type GiftCardLedgerKind,
  useGiftCard,
  useVoidGiftCard,
} from '@/lib/giftcards';
import { cn } from '@/lib/utils';

export default function GiftCardDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const cardId = Number(id);
  const me = useCurrentMembership();
  const canVoid = me?.role === 'owner' || me?.role === 'manager';
  const router = useRouter();

  const { data: card, isLoading, error } = useGiftCard(cardId);

  if (isLoading) {
    return (
      <div className="px-8 py-8">
        <PageHeader
          title=""
          back={{ href: '/catalog/gift-cards', label: 'All gift cards' }}
        />
        <div className="rounded-lg border bg-card p-12 text-center text-sm text-muted-foreground">
          Loading…
        </div>
      </div>
    );
  }
  if (error || !card) {
    return (
      <div className="px-8 py-8">
        <PageHeader
          title="Card not found"
          back={{ href: '/catalog/gift-cards', label: 'All gift cards' }}
        />
        <p className="text-sm text-destructive">
          Could not load this card.
        </p>
      </div>
    );
  }

  return (
    <div className="px-8 py-8 space-y-6">
      <PageHeader
        title={card.code}
        description={
          card.issued_to_customer_name
          || card.issued_to_name
          || 'Unknown recipient'
        }
        back={{ href: '/catalog/gift-cards', label: 'All gift cards' }}
        actions={
          canVoid && (card.status === 'active' || card.status === 'pending') ? (
            <VoidButton card={card} onSuccess={() => router.refresh()} />
          ) : null
        }
      />

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <SummaryCard card={card} />
        <RecipientCard card={card} />
        <PurchaserCard card={card} />
      </div>

      <LedgerCard card={card} />
    </div>
  );
}

// ── Summary card ────────────────────────────────────────────────────

function SummaryCard({ card }: { card: GiftCard }) {
  const [copied, setCopied] = useState(false);
  const onCopy = async () => {
    try {
      await navigator.clipboard.writeText(card.code);
      setCopied(true);
      toast.success('Code copied');
      setTimeout(() => setCopied(false), 1500);
    } catch {
      toast.error('Could not copy');
    }
  };

  return (
    <Card>
      <CardHeader className="flex-row items-start gap-3 space-y-0">
        <div className="inline-flex size-10 items-center justify-center rounded-md bg-emerald-50 text-emerald-700 shrink-0">
          <Gift className="size-5" />
        </div>
        <div className="min-w-0 flex-1">
          <CardTitle className="text-sm font-medium uppercase tracking-wide">
            At a glance
          </CardTitle>
        </div>
        <StatusBadge card={card} />
      </CardHeader>
      <CardContent className="space-y-3">
        <div>
          <p className="text-[11px] uppercase tracking-wider text-muted-foreground font-medium">
            Code
          </p>
          <button
            type="button"
            onClick={onCopy}
            className="mt-1 inline-flex items-center gap-2 font-mono text-lg tracking-wider hover:bg-muted rounded-md -mx-1 px-1 py-0.5 transition-colors"
            title="Copy code"
          >
            {card.code}
            {copied ? (
              <Check className="size-3.5 text-emerald-600" />
            ) : (
              <ClipboardCopy className="size-3.5 text-muted-foreground" />
            )}
          </button>
        </div>

        <Row label="Initial value" value={card.initial_value_dollars} mono />
        <Row
          label="Balance"
          value={card.balance_dollars}
          mono
          tone={
            card.balance_cents === 0 && card.status === 'active'
              ? 'muted'
              : undefined
          }
          large
        />
        {card.issued_at ? (
          <Row
            label="Issued"
            value={new Date(card.issued_at).toLocaleDateString()}
          />
        ) : null}
        {card.expires_at ? (
          <Row
            label="Expires"
            value={new Date(card.expires_at).toLocaleDateString()}
            tone={card.is_expired ? 'warn' : undefined}
          />
        ) : (
          <Row label="Expires" value="Never" muted />
        )}
        {card.status === 'voided' && card.void_reason ? (
          <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2">
            <p className="text-xs text-amber-900">
              <span className="font-medium">Voided:</span>{' '}
              {card.void_reason}
              {card.voided_at ? (
                <>
                  {' '}
                  ({new Date(card.voided_at).toLocaleDateString()})
                </>
              ) : null}
            </p>
          </div>
        ) : null}
        {card.is_expired && card.status === 'active' ? (
          <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 flex items-start gap-2">
            <AlertCircle className="size-4 text-amber-600 shrink-0 mt-0.5" />
            <p className="text-xs text-amber-900 leading-relaxed">
              Past expiration — redemption is rejected at checkout.
            </p>
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}

function RecipientCard({ card }: { card: GiftCard }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm font-medium uppercase tracking-wide">
          Recipient
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-2 text-sm">
        {card.issued_to_customer_name ? (
          <Row
            label="Customer"
            value={
              <Link
                href={`/clients/${card.issued_to_customer}`}
                className="text-foreground underline hover:no-underline"
              >
                {card.issued_to_customer_name}
              </Link>
            }
          />
        ) : (
          <Row
            label="Name"
            value={card.issued_to_name || '—'}
            muted={!card.issued_to_name}
          />
        )}
        {card.issued_to_email ? (
          <Row label="Email" value={card.issued_to_email} />
        ) : null}
      </CardContent>
    </Card>
  );
}

function PurchaserCard({ card }: { card: GiftCard }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm font-medium uppercase tracking-wide">
          Purchased by
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-2 text-sm">
        {card.purchaser_customer_name ? (
          <Row
            label="Customer"
            value={
              <Link
                href={`/clients/${card.purchaser_customer}`}
                className="text-foreground underline hover:no-underline"
              >
                {card.purchaser_customer_name}
              </Link>
            }
          />
        ) : (
          <Row label="Customer" value="—" muted />
        )}
        <p className="text-xs text-muted-foreground pt-1 leading-relaxed">
          The purchaser is the customer on the invoice that paid for
          this card. Often the same as the recipient; different when
          the card was bought as a gift for someone else.
        </p>
      </CardContent>
    </Card>
  );
}

// ── Ledger ──────────────────────────────────────────────────────────

const LEDGER_KIND_LABELS: Record<GiftCardLedgerKind, string> = {
  issue: 'Issued',
  redeem: 'Redeemed',
  reversal: 'Reversed',
  adjustment: 'Adjustment',
};

const LEDGER_KIND_ICONS: Record<
  GiftCardLedgerKind,
  React.ComponentType<{ className?: string }>
> = {
  issue: Sparkles,
  redeem: Trash2,
  reversal: Repeat2,
  adjustment: AlertCircle,
};

function LedgerCard({ card }: { card: GiftCard }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm font-medium uppercase tracking-wide">
          Ledger
        </CardTitle>
        <p className="text-xs text-muted-foreground mt-1">
          Append-only audit trail. Net of all rows equals the current
          balance ({card.balance_dollars}).
        </p>
      </CardHeader>
      <CardContent>
        {card.ledger_entries.length === 0 ? (
          <p className="text-sm text-muted-foreground italic py-2">
            No ledger entries yet — card is still pending.
          </p>
        ) : (
          <ul className="border rounded-md divide-y">
            {card.ledger_entries.map((entry) => {
              const Icon = LEDGER_KIND_ICONS[entry.kind];
              const isPositive = entry.amount_cents > 0;
              return (
                <li key={entry.id} className="px-4 py-3 flex items-start gap-3">
                  <div
                    className={cn(
                      'inline-flex size-7 items-center justify-center rounded-md shrink-0 mt-0.5',
                      isPositive
                        ? 'bg-emerald-50 text-emerald-700'
                        : 'bg-stone-100 text-stone-700',
                    )}
                  >
                    <Icon className="size-3.5" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium">
                      {LEDGER_KIND_LABELS[entry.kind]}
                      {entry.invoice ? (
                        <span className="ml-2 text-xs text-muted-foreground font-mono">
                          Invoice #{entry.invoice}
                        </span>
                      ) : null}
                    </p>
                    <p className="text-xs text-muted-foreground mt-0.5">
                      {new Date(entry.recorded_at).toLocaleString()}
                      {entry.by_user_email ? (
                        <> · by {entry.by_user_email}</>
                      ) : null}
                    </p>
                    {entry.note ? (
                      <p className="text-xs text-muted-foreground mt-1 italic">
                        {entry.note}
                      </p>
                    ) : null}
                  </div>
                  <span
                    className={cn(
                      'font-mono tabular-nums shrink-0 mt-0.5',
                      isPositive ? 'text-emerald-700' : 'text-stone-700',
                    )}
                  >
                    {isPositive ? '+' : ''}
                    {(entry.amount_cents / 100).toLocaleString(undefined, {
                      style: 'currency',
                      currency: 'USD',
                    })}
                  </span>
                </li>
              );
            })}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

// ── Void affordance ─────────────────────────────────────────────────

function VoidButton({
  card,
  onSuccess,
}: {
  card: GiftCard;
  onSuccess: () => void;
}) {
  const [confirming, setConfirming] = useState(false);
  const [reason, setReason] = useState('');
  const voidCard = useVoidGiftCard(card.id);

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!reason.trim()) {
      toast.error('A reason is required.');
      return;
    }
    voidCard.mutate(
      { reason: reason.trim() },
      {
        onSuccess: () => {
          toast.success('Card voided');
          setConfirming(false);
          setReason('');
          onSuccess();
        },
        onError: (err) => {
          if (err instanceof ApiError && err.body && typeof err.body === 'object') {
            const body = err.body as { detail?: string };
            if (body.detail) {
              toast.error(body.detail);
              return;
            }
          }
          toast.error('Could not void.');
        },
      },
    );
  };

  if (!confirming) {
    return (
      <Button variant="outline" onClick={() => setConfirming(true)}>
        <Ban className="size-4" />
        Void card
      </Button>
    );
  }
  return (
    <form onSubmit={onSubmit} className="flex items-center gap-2 flex-wrap">
      <Input
        value={reason}
        onChange={(e) => setReason(e.target.value)}
        placeholder="Reason"
        className="w-56"
        autoFocus
      />
      <Button type="submit" disabled={voidCard.isPending}>
        {voidCard.isPending ? (
          <Loader2 className="size-4 animate-spin" />
        ) : null}
        Void
      </Button>
      <Button
        type="button"
        variant="outline"
        onClick={() => {
          setConfirming(false);
          setReason('');
        }}
      >
        Cancel
      </Button>
    </form>
  );
}

// ── Status badge + helpers ──────────────────────────────────────────

function StatusBadge({ card }: { card: GiftCard }) {
  if (card.status === 'voided') {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-stone-100 text-stone-600 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider shrink-0">
        Voided
      </span>
    );
  }
  if (card.status === 'expired' || card.is_expired) {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-amber-50 text-amber-700 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider shrink-0">
        Expired
      </span>
    );
  }
  if (card.status === 'pending') {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-amber-50 text-amber-700 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider shrink-0">
        <span className="size-1.5 rounded-full bg-amber-500 animate-pulse" />
        Pending
      </span>
    );
  }
  if (card.is_fully_redeemed) {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-stone-100 text-stone-600 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider shrink-0">
        Used
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 text-emerald-700 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider shrink-0">
      <span className="size-1.5 rounded-full bg-emerald-500" />
      Active
    </span>
  );
}

function Row({
  label,
  value,
  mono,
  muted,
  tone,
  large,
}: {
  label: string;
  value: React.ReactNode;
  mono?: boolean;
  muted?: boolean;
  tone?: 'muted' | 'warn';
  large?: boolean;
}) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <dt
        className={cn(
          'text-xs uppercase tracking-wider text-muted-foreground font-medium',
          muted && 'text-muted-foreground/70',
        )}
      >
        {label}
      </dt>
      <dd
        className={cn(
          'tabular-nums text-right',
          mono && 'font-mono',
          large && 'text-xl font-semibold',
          tone === 'muted' && 'text-muted-foreground',
          tone === 'warn' && 'text-amber-700',
        )}
      >
        {value}
      </dd>
    </div>
  );
}
