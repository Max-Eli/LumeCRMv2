/**
 * Customer profile · Gift cards tab.
 *
 * Two sections:
 *   - Cards received   — issued TO this customer (or via free-text
 *                        recipient name when this customer is the
 *                        purchaser; surface the link both ways).
 *   - Cards purchased  — bought BY this customer (often as gifts).
 *
 * No edit affordances inline; void / detail open the catalog
 * detail page for the card.
 */

'use client';

import { Gift, Loader2 } from 'lucide-react';
import Link from 'next/link';

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  type GiftCard,
  useCustomerGiftCards,
} from '@/lib/giftcards';
import { cn } from '@/lib/utils';

export function GiftCardsTab({ customerId }: { customerId: number }) {
  const { received, purchased } = useCustomerGiftCards(customerId);

  if (received.isLoading || purchased.isLoading) {
    return (
      <Card>
        <CardContent className="py-8 text-center text-sm text-muted-foreground">
          <Loader2 className="size-4 animate-spin inline mr-2" />
          Loading gift cards…
        </CardContent>
      </Card>
    );
  }
  if (received.error || purchased.error) {
    return (
      <Card>
        <CardContent className="py-8 text-center text-sm text-destructive">
          Could not load gift cards.
        </CardContent>
      </Card>
    );
  }

  const receivedCards = received.data ?? [];
  const purchasedCards = purchased.data ?? [];

  if (receivedCards.length === 0 && purchasedCards.length === 0) {
    return <EmptyState />;
  }

  return (
    <div className="space-y-8">
      {receivedCards.length > 0 ? (
        <Section
          title="Received"
          subtitle="Cards issued to this customer."
        >
          <CardsList cards={receivedCards} />
        </Section>
      ) : null}
      {purchasedCards.length > 0 ? (
        <Section
          title="Purchased"
          subtitle="Cards this customer bought (often gifted to someone else)."
          tone="muted"
        >
          <CardsList cards={purchasedCards} />
        </Section>
      ) : null}
    </div>
  );
}

function EmptyState() {
  return (
    <Card className="border-dashed">
      <CardContent className="py-12 text-center">
        <div className="inline-flex size-12 items-center justify-center rounded-full bg-emerald-50 text-emerald-700 mb-4">
          <Gift className="size-5" />
        </div>
        <p className="text-sm text-foreground font-medium">
          No gift cards yet
        </p>
        <p className="text-xs text-muted-foreground mt-1.5 max-w-md mx-auto leading-relaxed">
          Gift cards land here when this customer either buys a card
          on an invoice (as a gift or for themselves) or is the
          recipient of a card someone else purchased.
        </p>
      </CardContent>
    </Card>
  );
}

function Section({
  title,
  subtitle,
  tone,
  children,
}: {
  title: string;
  subtitle?: string;
  tone?: 'muted';
  children: React.ReactNode;
}) {
  return (
    <section>
      <header className="mb-3">
        <h2
          className={cn(
            'text-[11px] uppercase tracking-wide font-medium',
            tone === 'muted' ? 'text-muted-foreground/80' : 'text-foreground',
          )}
        >
          {title}
        </h2>
        {subtitle ? (
          <p className="text-xs text-muted-foreground/80 mt-0.5">{subtitle}</p>
        ) : null}
      </header>
      {children}
    </section>
  );
}

function CardsList({ cards }: { cards: GiftCard[] }) {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
      {cards.map((c) => (
        <CardTile key={c.id} card={c} />
      ))}
    </div>
  );
}

function CardTile({ card }: { card: GiftCard }) {
  return (
    <Card>
      <CardHeader className="flex-row items-start gap-3 space-y-0">
        <div className="inline-flex size-10 items-center justify-center rounded-md bg-emerald-50 text-emerald-700 shrink-0">
          <Gift className="size-5" />
        </div>
        <div className="min-w-0 flex-1">
          <CardTitle className="text-sm font-mono tracking-wider">
            {card.code}
          </CardTitle>
          <p className="text-xs text-muted-foreground mt-0.5">
            {card.issued_at
              ? `Issued ${new Date(card.issued_at).toLocaleDateString()}`
              : 'Pending payment'}
            {card.expires_at ? (
              <> · expires {new Date(card.expires_at).toLocaleDateString()}</>
            ) : null}
          </p>
        </div>
        <StatusPill card={card} />
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex items-baseline justify-between">
          <span className="text-xs uppercase tracking-wider text-muted-foreground">
            Balance
          </span>
          <span
            className={cn(
              'font-mono tabular-nums text-xl font-semibold',
              card.balance_cents === 0
                && card.status === 'active'
                && 'text-muted-foreground',
            )}
          >
            {card.balance_dollars}
            {card.initial_value_cents !== card.balance_cents ? (
              <span className="text-xs font-normal text-muted-foreground ml-2">
                of {card.initial_value_dollars}
              </span>
            ) : null}
          </span>
        </div>
        <Link
          href={`/catalog/gift-cards/${card.id}`}
          className="text-xs text-foreground underline hover:no-underline"
        >
          View details →
        </Link>
      </CardContent>
    </Card>
  );
}

function StatusPill({ card }: { card: GiftCard }) {
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
