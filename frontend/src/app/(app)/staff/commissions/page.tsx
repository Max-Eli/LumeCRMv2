/**
 * `/staff/commissions` — your earnings (everyone) + tenant totals (managers).
 *
 * Mobile-first because most providers will check this on their phone
 * between appointments. Hero card shows the date-range net total in
 * big numerals; below it, recent ledger entries with signed amounts
 * (reversals show as negative).
 *
 * Managers also see a "Team this period" section underneath: one row
 * per staff member with their net earnings for the same window. Tap a
 * row to drill into that person's ledger via `?member=<id>`.
 */

'use client';

import {
  ArrowDownRight,
  ArrowUpRight,
  Loader2,
  ReceiptText,
  Settings2,
  X,
} from 'lucide-react';
import Link from 'next/link';
import { useMemo, useState } from 'react';

import { PageHeader } from '@/components/page-header';
import { useCurrentMembership, useUser } from '@/lib/auth';
import {
  type CommissionEntry,
  type CommissionTotalRow,
  formatCents,
  useCommissionEntries,
  useCommissionTotals,
} from '@/lib/commissions';
import { useAllMemberships } from '@/lib/tenant';
import { cn } from '@/lib/utils';

type RangePreset = '30d' | '90d' | 'mtd' | 'ytd';

const RANGE_OPTIONS: { id: RangePreset; label: string }[] = [
  { id: '30d', label: 'Last 30 days' },
  { id: '90d', label: 'Last 90 days' },
  { id: 'mtd', label: 'This month' },
  { id: 'ytd', label: 'This year' },
];

export default function CommissionsPage() {
  const me = useCurrentMembership();
  const { data: user } = useUser();
  const isManager = me?.role === 'owner' || me?.role === 'manager';

  const [preset, setPreset] = useState<RangePreset>('30d');
  const [focusedMemberId, setFocusedMemberId] = useState<number | null>(null);

  // Lazy useState init so React Compiler doesn't see Date.now() in
  // render. The reference time is fixed once at mount; the user can
  // refresh the page if they want a fresher window.
  const [refMs] = useState<number>(() => Date.now());

  const { from, to } = useMemo(
    () => rangeForPreset(preset, refMs),
    [preset, refMs],
  );

  // Resolve own membership id by matching email — useUser() is the
  // session user; useAllMemberships() lists staff at the active tenant.
  // We need this for two reasons:
  //   1. Filter "Your earnings" + "Recent activity" to the requesting
  //      user explicitly (so managers viewing their own page don't
  //      accidentally see the whole team's entries).
  //   2. Surface the focused-staff drill-in via ?member=<id> for
  //      managers without losing the navigation back to the tenant view.
  const memberships = useAllMemberships();
  const ownMembershipId = useMemo(() => {
    if (!user) return null;
    const match = (memberships.data ?? []).find(
      (m) => m.user_email === user.email,
    );
    return match?.id ?? null;
  }, [memberships.data, user]);

  // When a manager clicks a row in the team table, the focused-staff
  // ledger pulls that person's entries instead of the manager's own.
  const focusedMember = useMemo(() => {
    if (!focusedMemberId) return null;
    return (
      (memberships.data ?? []).find((m) => m.id === focusedMemberId) ?? null
    );
  }, [memberships.data, focusedMemberId]);

  // The "Your earnings" totals card — uses /totals/ for the headline
  // figure and /entries/ for the recent activity list.
  const ownTotals = useCommissionTotals({
    membershipId: focusedMemberId ?? ownMembershipId ?? undefined,
    from,
    to,
  });
  const ownEntries = useCommissionEntries({
    membershipId: focusedMemberId ?? ownMembershipId ?? undefined,
    from,
    to,
  });

  // Manager view: tenant-wide totals (no membership filter). For non-
  // managers the backend auto-scopes to their own membership, so this
  // call is harmless (we just don't render it below).
  const teamTotals = useCommissionTotals({ from, to });

  if (!me || !user) {
    return (
      <div className="px-4 py-10 sm:px-8 sm:py-8 mx-auto max-w-3xl">
        <p className="text-sm text-muted-foreground text-center">
          Sign in to see your commissions.
        </p>
      </div>
    );
  }

  const ownRow = ownTotals.data?.[0] ?? null;
  const focusedName = focusedMember
    ? `${focusedMember.user_first_name} ${focusedMember.user_last_name}`.trim()
      || focusedMember.user_email
    : null;

  return (
    <div className="px-4 py-6 sm:px-8 sm:py-8 space-y-6 max-w-5xl mx-auto w-full">
      <PageHeader
        title={focusedName ? `${focusedName}'s commissions` : 'Commissions'}
        description={
          focusedName
            ? 'Manager view of this staff member.'
            : 'Your earnings on services rendered. Updates the moment an invoice is paid.'
        }
        actions={
          isManager ? (
            <Link
              href="/staff/commissions/rules"
              className="inline-flex items-center gap-1.5 h-9 px-3 rounded-md text-sm font-medium border bg-card hover:bg-muted transition-colors"
            >
              <Settings2 className="size-3.5" />
              Rules
            </Link>
          ) : null
        }
      />

      {focusedMember ? (
        <button
          type="button"
          onClick={() => setFocusedMemberId(null)}
          className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground"
        >
          <X className="size-3.5" />
          Back to my view
        </button>
      ) : null}

      <RangePicker preset={preset} onChange={setPreset} />

      <EarningsHero
        row={ownRow}
        loading={ownTotals.isLoading}
        label={
          focusedName
            ? `${focusedName}${focusedName.endsWith('s') ? "'" : "'s"} earnings`
            : `${user.first_name ? `${user.first_name}'s` : 'Your'} earnings`
        }
      />

      <RecentEntries
        entries={ownEntries.data ?? []}
        loading={ownEntries.isLoading}
      />

      {isManager && !focusedMember ? (
        <TeamTotals
          rows={teamTotals.data ?? []}
          loading={teamTotals.isLoading}
          ownMembershipId={ownMembershipId}
          onFocusMember={setFocusedMemberId}
        />
      ) : null}
    </div>
  );
}

// ── Date range ──────────────────────────────────────────────────────

function rangeForPreset(
  preset: RangePreset,
  nowMs: number,
): { from: string; to: string } {
  const now = new Date(nowMs);
  const to = now.toISOString();
  if (preset === 'mtd') {
    const start = new Date(now.getFullYear(), now.getMonth(), 1, 0, 0, 0);
    return { from: start.toISOString(), to };
  }
  if (preset === 'ytd') {
    const start = new Date(now.getFullYear(), 0, 1, 0, 0, 0);
    return { from: start.toISOString(), to };
  }
  const days = preset === '30d' ? 30 : 90;
  const from = new Date(nowMs - days * 24 * 60 * 60 * 1000).toISOString();
  return { from, to };
}

function RangePicker({
  preset,
  onChange,
}: {
  preset: RangePreset;
  onChange: (next: RangePreset) => void;
}) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {RANGE_OPTIONS.map((opt) => (
        <button
          key={opt.id}
          type="button"
          onClick={() => onChange(opt.id)}
          className={cn(
            'h-8 px-3 rounded-full text-xs font-medium border transition-colors',
            preset === opt.id
              ? 'bg-foreground text-background border-foreground'
              : 'bg-card hover:bg-muted',
          )}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}

// ── Hero card ───────────────────────────────────────────────────────

function EarningsHero({
  row,
  loading,
  label,
}: {
  row: CommissionTotalRow | null;
  loading: boolean;
  label: string;
}) {
  const net = row?.net_cents ?? 0;
  const accrued = row?.accrual_total_cents ?? 0;
  const reversed = row?.reversal_total_cents ?? 0;

  return (
    <section className="rounded-2xl border bg-card px-5 py-6 sm:px-7 sm:py-8 space-y-5">
      <div>
        <p className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground font-medium">
          {label}
        </p>
        <p className="font-mono text-4xl sm:text-5xl font-semibold tabular-nums tracking-tight mt-2">
          {loading ? (
            <span className="inline-flex items-center gap-2 text-muted-foreground/50">
              <Loader2 className="size-6 animate-spin" />
            </span>
          ) : (
            formatCents(net)
          )}
        </p>
      </div>
      <div className="grid grid-cols-2 gap-3 pt-4 border-t">
        <div>
          <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-medium">
            Earned
          </p>
          <p className="font-mono text-lg tabular-nums mt-0.5">
            {formatCents(accrued)}
          </p>
        </div>
        <div>
          <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-medium">
            Reversed
          </p>
          <p
            className={cn(
              'font-mono text-lg tabular-nums mt-0.5',
              reversed < 0 ? 'text-destructive' : 'text-muted-foreground/70',
            )}
          >
            {formatCents(reversed)}
          </p>
        </div>
      </div>
    </section>
  );
}

// ── Recent entries ──────────────────────────────────────────────────

function RecentEntries({
  entries,
  loading,
}: {
  entries: CommissionEntry[];
  loading: boolean;
}) {
  if (loading) {
    return (
      <section>
        <h2 className="text-[11px] uppercase tracking-wider text-muted-foreground font-medium mb-3">
          Recent activity
        </h2>
        <div className="rounded-xl border bg-card p-10 text-center text-sm text-muted-foreground">
          <Loader2 className="size-5 animate-spin mx-auto mb-2" />
          Loading…
        </div>
      </section>
    );
  }
  if (entries.length === 0) {
    return (
      <section>
        <h2 className="text-[11px] uppercase tracking-wider text-muted-foreground font-medium mb-3">
          Recent activity
        </h2>
        <div className="rounded-xl border border-dashed bg-muted/20 p-8 text-center">
          <ReceiptText className="size-5 mx-auto text-muted-foreground/50 mb-2" />
          <p className="text-sm text-muted-foreground">
            No commission activity in this window.
          </p>
        </div>
      </section>
    );
  }
  return (
    <section>
      <header className="flex items-baseline justify-between mb-3">
        <h2 className="text-[11px] uppercase tracking-wider text-muted-foreground font-medium">
          Recent activity
        </h2>
        <p className="text-[11px] text-muted-foreground/70">
          {entries.length} {entries.length === 1 ? 'entry' : 'entries'}
        </p>
      </header>
      <ul className="rounded-xl border bg-card overflow-hidden divide-y">
        {entries.map((entry) => (
          <EntryRow key={entry.id} entry={entry} />
        ))}
      </ul>
    </section>
  );
}

function EntryRow({ entry }: { entry: CommissionEntry }) {
  const isReversal = entry.kind === 'reversal';
  return (
    <li className="px-4 py-3 flex items-center gap-3">
      <div
        className={cn(
          'inline-flex size-8 items-center justify-center rounded-md shrink-0',
          isReversal
            ? 'bg-rose-50 text-rose-700'
            : 'bg-emerald-50 text-emerald-700',
        )}
      >
        {isReversal ? (
          <ArrowDownRight className="size-4" />
        ) : (
          <ArrowUpRight className="size-4" />
        )}
      </div>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium truncate">
          {entry.line_description || 'Service line'}
        </p>
        <p className="text-xs text-muted-foreground">
          Invoice {entry.invoice_number}
          {' · '}
          {Number(entry.rate_percent).toFixed(2)}% of{' '}
          {formatCents(entry.line_subtotal_cents)}
          {' · '}
          {new Date(entry.accrued_at).toLocaleDateString(undefined, {
            month: 'short',
            day: 'numeric',
          })}
        </p>
      </div>
      <p
        className={cn(
          'font-mono tabular-nums text-sm font-medium shrink-0',
          isReversal ? 'text-destructive' : 'text-emerald-700',
        )}
      >
        {formatCents(entry.amount_cents)}
      </p>
    </li>
  );
}

// ── Manager: team totals ────────────────────────────────────────────

function TeamTotals({
  rows,
  loading,
  ownMembershipId,
  onFocusMember,
}: {
  rows: CommissionTotalRow[];
  loading: boolean;
  ownMembershipId: number | null;
  onFocusMember: (id: number) => void;
}) {
  const others = rows.filter((r) => r.membership_id !== ownMembershipId);
  const sorted = [...others].sort((a, b) => b.net_cents - a.net_cents);
  const teamNet = others.reduce((acc, r) => acc + r.net_cents, 0);

  if (loading) {
    return (
      <section>
        <h2 className="text-[11px] uppercase tracking-wider text-muted-foreground font-medium mb-3">
          Team this period
        </h2>
        <div className="rounded-xl border bg-card p-10 text-center text-sm text-muted-foreground">
          <Loader2 className="size-5 animate-spin mx-auto mb-2" />
          Loading…
        </div>
      </section>
    );
  }

  return (
    <section>
      <header className="flex items-baseline justify-between mb-3">
        <h2 className="text-[11px] uppercase tracking-wider text-muted-foreground font-medium">
          Team this period
        </h2>
        {others.length > 0 ? (
          <p className="text-[11px] text-muted-foreground">
            Team net{' '}
            <span className="font-mono font-medium tabular-nums text-foreground">
              {formatCents(teamNet)}
            </span>
          </p>
        ) : null}
      </header>
      {sorted.length === 0 ? (
        <div className="rounded-xl border border-dashed bg-muted/20 p-8 text-center text-sm text-muted-foreground">
          No teammates have commission accruals in this window.
        </div>
      ) : (
        <ul className="rounded-xl border bg-card overflow-hidden divide-y">
          {sorted.map((row) => {
            const fullName =
              `${row.first_name ?? ''} ${row.last_name ?? ''}`.trim()
              || row.email;
            return (
              <li key={row.membership_id}>
                <button
                  type="button"
                  onClick={() => onFocusMember(row.membership_id)}
                  className="w-full px-4 py-3 flex items-center gap-3 hover:bg-muted/40 transition-colors text-left"
                >
                  <div className="size-8 rounded-full bg-muted text-foreground/80 flex items-center justify-center text-xs font-medium uppercase shrink-0">
                    {(row.first_name?.[0] ?? row.email[0] ?? '?')}
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium truncate">{fullName}</p>
                    <p className="text-xs text-muted-foreground capitalize">
                      {row.role.replace('_', ' ')}
                    </p>
                  </div>
                  <p className="font-mono tabular-nums text-sm font-medium shrink-0">
                    {formatCents(row.net_cents)}
                  </p>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
