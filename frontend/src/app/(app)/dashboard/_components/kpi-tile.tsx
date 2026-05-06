/**
 * Dashboard KPI tile.
 *
 * Layout (top → bottom):
 *   - small-caps label
 *   - large display value (font-serif tracking-tight tabular-nums)
 *   - optional delta arrow + comparison label
 *   - optional sub-line ("12 paid invoices today")
 *
 * Used in a 4-up grid at the top of the dashboard. Loading state
 * shows skeleton bars at the same heights so the grid doesn't jump.
 */

import type { ReactNode } from 'react';

import { cn } from '@/lib/utils';

import { DeltaArrow } from './delta-arrow';

export interface KpiTileProps {
  label: string;
  value: ReactNode;
  /** Optional sub-line shown beneath the value, before the delta. */
  subline?: ReactNode;
  /** Delta percentage vs. comparison window. `undefined` to omit the row. */
  deltaPct?: number | null;
  /** Tone for the delta arrow. Caller decides because semantics vary
   *  per metric (revenue up = good; no-show rate up = bad). */
  deltaTone?: 'positive' | 'negative' | 'neutral';
  /** Comparison-window label, e.g. "vs. last week". */
  deltaHint?: string;
  /** Loading state — render skeletons at the right heights so the
   *  grid doesn't jump on first paint. */
  loading?: boolean;
  className?: string;
}

export function KpiTile({
  label,
  value,
  subline,
  deltaPct,
  deltaTone = 'neutral',
  deltaHint,
  loading = false,
  className,
}: KpiTileProps) {
  return (
    <div
      className={cn(
        'rounded-lg border bg-card px-5 py-4 transition-colors hover:bg-muted/20',
        className,
      )}
    >
      <p className="text-[11px] uppercase tracking-wide text-muted-foreground/85 font-medium">
        {label}
      </p>
      {loading ? (
        <>
          <div className="mt-2 h-8 w-24 animate-pulse rounded bg-muted/60" />
          <div className="mt-2 h-3 w-32 animate-pulse rounded bg-muted/40" />
        </>
      ) : (
        <>
          <p className="mt-1.5 font-serif text-3xl font-medium tracking-tight tabular-nums text-foreground">
            {value}
          </p>
          {subline ? (
            <p className="mt-1 text-xs text-muted-foreground">{subline}</p>
          ) : null}
          {deltaPct !== undefined ? (
            <div className="mt-2">
              <DeltaArrow pct={deltaPct} tone={deltaTone} hint={deltaHint} />
            </div>
          ) : null}
        </>
      )}
    </div>
  );
}

export function KpiRow({ children }: { children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
      {children}
    </div>
  );
}
