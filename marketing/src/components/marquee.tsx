/**
 * Slow horizontal typographic ticker. Use once per page max.
 *
 * Renders the supplied phrases twice in sequence so the CSS keyframe
 * can translate `-50%` and seamlessly loop. Pure CSS animation, no
 * JS — runs on the GPU compositor, costs nothing. Pauses on hover
 * (gives the operator a moment to read a phrase).
 *
 * Editorial use: phrases should be brand stances or ethos lines, not
 * feature names or product copy. The eye drifts past, catches one
 * line, moves on. Restraint by design.
 */

import { cn } from '@/lib/utils';

export interface MarqueeProps {
  phrases: string[];
  /** Visual style. `display` = large serif italic. `eyebrow` = small caps. */
  variant?: 'display' | 'eyebrow';
  className?: string;
}

export function Marquee({ phrases, variant = 'display', className }: MarqueeProps) {
  // Render the phrase set twice so the CSS animation's -50% loop
  // looks seamless. Mark the duplicate as aria-hidden — screen
  // readers should hear the phrases once.
  const items = (
    <div className="marquee-track">
      {phrases.map((p, i) => (
        <span key={i} className="flex items-center gap-16 shrink-0">
          {variant === 'display' ? (
            <span className="font-display text-5xl text-foreground/85 sm:text-6xl lg:text-7xl">
              {p}
            </span>
          ) : (
            <span className="eyebrow text-foreground/65">{p}</span>
          )}
          <span className="text-2xl text-accent" aria-hidden>·</span>
        </span>
      ))}
    </div>
  );
  return (
    <div className={cn('marquee-host overflow-hidden', className)}>
      <div className="marquee">
        {items}
        <div aria-hidden>{items}</div>
      </div>
    </div>
  );
}
