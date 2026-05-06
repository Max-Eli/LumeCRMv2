/**
 * Up / down delta arrow with a tone-aware color.
 *
 * The dashboard's KPI tiles use this to communicate "today's revenue
 * is +12% vs. last week" without taking up a second row. Tone is
 * dictated by the caller because the SAME percentage delta means
 * different things for different metrics (revenue up = good,
 * no-show rate up = bad).
 *
 * `null` delta renders as an em-dash placeholder — used when the
 * comparison window had zero (so we'd be dividing by zero) or the
 * data isn't available yet.
 */

import { ArrowDownRight, ArrowUpRight, Minus } from 'lucide-react';

import { cn } from '@/lib/utils';

export interface DeltaArrowProps {
  /** Percentage delta. `null` = no comparison available. */
  pct: number | null;
  /** Whether higher values are better for this metric.
   *  Drives the color: same +5% reads green for revenue, red for
   *  no-show rate. */
  tone: 'positive' | 'negative' | 'neutral';
  /** Optional text suffix shown after the percent (e.g. "vs. last week"). */
  hint?: string;
  className?: string;
}

export function DeltaArrow({ pct, tone, hint, className }: DeltaArrowProps) {
  if (pct === null) {
    return (
      <span
        className={cn(
          'inline-flex items-center gap-1 text-xs text-muted-foreground/70',
          className,
        )}
      >
        <Minus className="size-3" aria-hidden />
        <span>—</span>
        {hint ? <span className="text-muted-foreground/55">{hint}</span> : null}
      </span>
    );
  }

  const isFlat = Math.abs(pct) < 0.5;
  const isUp = pct > 0;
  const Icon = isFlat ? Minus : isUp ? ArrowUpRight : ArrowDownRight;

  const toneClass =
    tone === 'positive'
      ? 'text-emerald-700 dark:text-emerald-400'
      : tone === 'negative'
        ? 'text-rose-700 dark:text-rose-400'
        : 'text-muted-foreground';

  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 text-xs font-medium tabular-nums',
        toneClass,
        className,
      )}
    >
      <Icon className="size-3" aria-hidden />
      <span>{isFlat ? 'flat' : `${pct > 0 ? '+' : ''}${pct.toFixed(1)}%`}</span>
      {hint ? <span className="text-muted-foreground/70 font-normal">{hint}</span> : null}
    </span>
  );
}
