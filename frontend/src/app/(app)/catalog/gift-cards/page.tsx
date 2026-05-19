/**
 * `/catalog/gift-cards` — list of issued gift cards.
 *
 * Gift cards aren't authored from this surface — they're sold on
 * an invoice via the "Sell a gift card" panel. This page is for
 * looking up issued cards: search by code or recipient name,
 * filter by status, void (with reason) when needed.
 *
 * Stat strip surfaces total outstanding liability (sum of ACTIVE
 * card balances) which is the number a tenant needs for accurate
 * P&L reporting once they're processing real volume.
 */

'use client';

import {
  AlertCircle,
  Ban,
  Gift,
  Loader2,
  Search,
} from 'lucide-react';
import { useRouter } from 'next/navigation';
import { useMemo, useState } from 'react';
import { toast } from 'sonner';

import { PageHeader } from '@/components/page-header';
import { Button } from '@/components/ui/button';
import { Field, FieldLabel } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { ApiError } from '@/lib/api';
import { useCurrentMembership } from '@/lib/auth';
import {
  type GiftCard,
  type GiftCardStatus,
  useGiftCardLookup,
  useGiftCards,
  useVoidGiftCard,
} from '@/lib/giftcards';
import { useDebounce } from '@/lib/use-debounce';
import { cn } from '@/lib/utils';

type StateFilter = 'all' | GiftCardStatus;

export default function GiftCardsListPage() {
  const me = useCurrentMembership();
  const canVoid = me?.role === 'owner' || me?.role === 'manager';
  const router = useRouter();
  const [search, setSearch] = useState('');
  const debouncedSearch = useDebounce(search, 250);
  const [filter, setFilter] = useState<StateFilter>('all');

  const { data, isLoading, error } = useGiftCards({
    q: debouncedSearch || undefined,
    status: filter === 'all' ? undefined : filter,
  });

  // Aggregate stats off an unfiltered fetch so the strip is stable.
  const all = useGiftCards();
  const allRows = all.data ?? [];
  const cards = data ?? [];
  const activeCount = allRows.filter((c) => c.status === 'active').length;
  const liabilityCents = useMemo(() => {
    const rows = all.data ?? [];
    return rows.reduce((s, c) => {
      if (c.status !== 'active') return s;
      return s + c.balance_cents;
    }, 0);
  }, [all.data]);

  return (
    <div className="px-4 sm:px-8 py-4 sm:py-8 space-y-4 sm:space-y-6">
      <PageHeader
        title="Gift cards"
        description="Issued cards. Sell new cards from an OPEN invoice (Sell a gift card panel). Look up balances at checkout via the redeem panel on the customer's invoice."
      />

      <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
        <Stat label="Cards issued" value={allRows.length} />
        <Stat label="Active" value={activeCount} tone="emerald" />
        <Stat
          label="Outstanding liability"
          value={`$${(liabilityCents / 100).toLocaleString(undefined, {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
          })}`}
          isCurrency
          sublabel="Sum of active card balances"
        />
      </div>

      <CodeLookupCard />

      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div className="inline-flex items-center gap-0.5 rounded-md border bg-muted/40 p-0.5">
          {(
            ['all', 'active', 'pending', 'voided', 'expired'] as const
          ).map((f) => (
            <button
              key={f}
              type="button"
              onClick={() => setFilter(f)}
              className={cn(
                'px-3 h-8 rounded-md text-sm transition-colors capitalize',
                filter === f
                  ? 'bg-card text-foreground shadow-sm font-medium'
                  : 'text-muted-foreground hover:text-foreground',
              )}
            >
              {f}
            </button>
          ))}
        </div>
        <div className="relative max-w-md flex-1 min-w-[240px]">
          <Search className="size-4 absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground pointer-events-none" />
          <Input
            placeholder="Search by code, recipient name, or email…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-9"
          />
        </div>
      </div>

      {error ? (
        <div className="rounded-lg border border-destructive/40 bg-destructive/5 p-6 text-sm text-destructive">
          Could not load gift cards.
        </div>
      ) : isLoading ? (
        <div className="rounded-lg border bg-card p-12 text-center text-sm text-muted-foreground">
          Loading gift cards…
        </div>
      ) : cards.length === 0 ? (
        allRows.length === 0 ? (
          <EmptyState />
        ) : (
          <div className="rounded-lg border bg-card p-12 text-center">
            <Search className="size-8 mx-auto text-muted-foreground/40 mb-3" />
            <p className="text-sm text-muted-foreground">
              No cards match the current filters.
            </p>
          </div>
        )
      ) : (
        <CardsTable
          rows={cards}
          canVoid={canVoid}
          onClick={(id) => router.push(`/catalog/gift-cards/${id}`)}
        />
      )}
    </div>
  );
}

// ── Code lookup card ────────────────────────────────────────────────

function CodeLookupCard() {
  const router = useRouter();
  const lookup = useGiftCardLookup();
  const [code, setCode] = useState('');

  const onLookup = () => {
    const trimmed = code.trim().toUpperCase();
    if (!trimmed) {
      toast.error('Enter a code first.');
      return;
    }
    lookup.mutate(
      { code: trimmed },
      {
        onSuccess: (card) => {
          router.push(`/catalog/gift-cards/${card.id}`);
        },
        onError: (err) => {
          if (err instanceof ApiError && err.status === 404) {
            toast.error('No card with that code.');
          } else {
            toast.error('Lookup failed.');
          }
        },
      },
    );
  };

  return (
    <div className="rounded-lg border bg-emerald-50/30 p-5 flex items-end gap-3 flex-wrap">
      <div className="flex-1 min-w-[280px]">
        <Field>
          <FieldLabel htmlFor="gc-lookup">
            Look up a card by code
          </FieldLabel>
          <Input
            id="gc-lookup"
            value={code}
            onChange={(e) => setCode(e.target.value)}
            placeholder="GC-XXXX-YYYY"
            className="font-mono uppercase"
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault();
                onLookup();
              }
            }}
          />
        </Field>
      </div>
      <Button type="button" onClick={onLookup} disabled={lookup.isPending}>
        {lookup.isPending ? (
          <Loader2 className="size-4 animate-spin" />
        ) : (
          <Search className="size-4" />
        )}
        Look up
      </Button>
    </div>
  );
}

// ── Cards table ─────────────────────────────────────────────────────

function CardsTable({
  rows,
  canVoid,
  onClick,
}: {
  rows: GiftCard[];
  canVoid: boolean;
  onClick: (id: number) => void;
}) {
  return (
    <div className="rounded-lg border bg-card overflow-x-auto">
      <Table className="min-w-[720px]">
        <TableHeader>
          <TableRow className="bg-muted/30 hover:bg-muted/30">
            <TableHead className="w-[160px]">Code</TableHead>
            <TableHead className="w-[26%]">Recipient</TableHead>
            <TableHead>Purchaser</TableHead>
            <TableHead className="text-right w-[120px]">Initial</TableHead>
            <TableHead className="text-right w-[120px]">Balance</TableHead>
            <TableHead className="w-[120px]">Issued</TableHead>
            <TableHead className="w-[110px]">Status</TableHead>
            {canVoid ? <TableHead className="w-[80px]" /> : null}
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((c) => (
            <CardRow
              key={c.id}
              card={c}
              canVoid={canVoid}
              onClick={() => onClick(c.id)}
            />
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

function CardRow({
  card,
  canVoid,
  onClick,
}: {
  card: GiftCard;
  canVoid: boolean;
  onClick: () => void;
}) {
  const recipientLabel =
    card.issued_to_customer_name
    || card.issued_to_name
    || 'Unknown recipient';

  return (
    <TableRow className="cursor-pointer group" onClick={onClick}>
      <TableCell className="py-3.5 font-mono text-xs">
        {card.code}
      </TableCell>
      <TableCell>
        <div className="flex items-center gap-3">
          <div className="inline-flex size-8 items-center justify-center rounded-md bg-emerald-50 text-emerald-700 shrink-0">
            <Gift className="size-4" />
          </div>
          <div className="min-w-0">
            <p className="font-medium truncate">{recipientLabel}</p>
            {card.issued_to_email ? (
              <p className="text-xs text-muted-foreground truncate">
                {card.issued_to_email}
              </p>
            ) : null}
          </div>
        </div>
      </TableCell>
      <TableCell className="text-sm text-muted-foreground">
        {card.purchaser_customer_name || (
          <span className="text-xs text-muted-foreground/70">—</span>
        )}
      </TableCell>
      <TableCell className="text-right font-mono tabular-nums">
        {card.initial_value_dollars}
      </TableCell>
      <TableCell className="text-right">
        <span
          className={cn(
            'font-mono tabular-nums font-medium',
            card.balance_cents === 0
              && card.status === 'active'
              && 'text-stone-500',
          )}
        >
          {card.balance_dollars}
        </span>
      </TableCell>
      <TableCell className="text-xs text-muted-foreground">
        {card.issued_at
          ? new Date(card.issued_at).toLocaleDateString()
          : '—'}
      </TableCell>
      <TableCell>
        <StatusPill card={card} />
      </TableCell>
      {canVoid ? (
        <TableCell
          // Stop click bubbling so the void affordance doesn't open
          // the detail page.
          onClick={(e) => e.stopPropagation()}
        >
          {card.status === 'active' || card.status === 'pending' ? (
            <VoidInlineButton card={card} />
          ) : null}
        </TableCell>
      ) : null}
    </TableRow>
  );
}

function StatusPill({ card }: { card: GiftCard }) {
  if (card.status === 'voided') {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-stone-100 text-stone-600 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider">
        Voided
      </span>
    );
  }
  if (card.status === 'expired' || card.is_expired) {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-amber-50 text-amber-700 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider">
        Expired
      </span>
    );
  }
  if (card.status === 'pending') {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-amber-50 text-amber-700 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider">
        <span className="size-1.5 rounded-full bg-amber-500 animate-pulse" />
        Pending
      </span>
    );
  }
  if (card.is_fully_redeemed) {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-stone-100 text-stone-600 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider">
        Used
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 text-emerald-700 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider">
      <span className="size-1.5 rounded-full bg-emerald-500" />
      Active
    </span>
  );
}

function VoidInlineButton({ card }: { card: GiftCard }) {
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
      <button
        type="button"
        onClick={() => setConfirming(true)}
        className="inline-flex size-7 items-center justify-center rounded-md text-muted-foreground/60 opacity-0 group-hover:opacity-100 hover:bg-muted hover:text-destructive transition-all"
        aria-label="Void this card"
        title="Void card"
      >
        <Ban className="size-3.5" />
      </button>
    );
  }
  return (
    <form
      onSubmit={onSubmit}
      className="inline-flex items-center gap-1.5"
      onClick={(e) => e.stopPropagation()}
    >
      <Input
        value={reason}
        onChange={(e) => setReason(e.target.value)}
        placeholder="Reason"
        className="h-7 text-xs w-32"
        autoFocus
      />
      <button
        type="submit"
        disabled={voidCard.isPending}
        className="inline-flex h-7 items-center px-2 rounded-md bg-destructive text-destructive-foreground text-xs font-medium hover:bg-destructive/90 disabled:opacity-60"
      >
        {voidCard.isPending ? (
          <Loader2 className="size-3 animate-spin" />
        ) : (
          'Void'
        )}
      </button>
      <button
        type="button"
        onClick={() => {
          setConfirming(false);
          setReason('');
        }}
        className="inline-flex h-7 items-center px-2 rounded-md text-xs text-muted-foreground hover:bg-muted"
      >
        Cancel
      </button>
    </form>
  );
}

function Stat({
  label,
  value,
  sublabel,
  tone,
  isCurrency,
}: {
  label: string;
  value: number | string;
  sublabel?: string;
  tone?: 'emerald';
  isCurrency?: boolean;
}) {
  return (
    <div className="rounded-lg border bg-card px-5 py-4">
      <p className="text-[11px] uppercase tracking-wider text-muted-foreground font-medium">
        {label}
      </p>
      <p
        className={cn(
          'font-semibold tabular-nums leading-tight mt-1',
          isCurrency ? 'text-xl font-mono' : 'text-2xl',
          tone === 'emerald' && 'text-emerald-700',
        )}
      >
        {typeof value === 'number' ? value.toLocaleString() : value}
      </p>
      {sublabel ? (
        <p className="text-[11px] text-muted-foreground mt-0.5 truncate">
          {sublabel}
        </p>
      ) : null}
    </div>
  );
}

function EmptyState() {
  return (
    <div className="rounded-lg border bg-card p-12 text-center">
      <div className="inline-flex size-12 items-center justify-center rounded-full bg-emerald-50 text-emerald-700 mb-4">
        <Gift className="size-6" />
      </div>
      <h3 className="font-serif text-xl font-semibold tracking-tight">
        No gift cards issued yet
      </h3>
      <p className="text-sm text-muted-foreground mt-2 max-w-md mx-auto leading-relaxed">
        Gift cards are sold from a customer&rsquo;s invoice — open
        any OPEN invoice and use the &quot;Sell a gift card&quot;
        panel. Issued cards land here with their codes for lookup
        at redemption time.
      </p>
      <div className="mt-4 inline-flex items-center gap-1.5 text-xs text-muted-foreground">
        <AlertCircle className="size-3.5" />
        <span>Custom amounts only — no preset denominations in v1.</span>
      </div>
    </div>
  );
}
