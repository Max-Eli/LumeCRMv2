/**
 * `<BrandLoader>` — full-viewport branded loading screen.
 *
 * The brand monogram with a subtle pulse + a thin progress accent.
 * Used as the fallback for every Suspense boundary in the app shell
 * (root + per-route-group `loading.tsx` files), so route-change
 * transitions feel branded instead of falling back to a blank
 * screen.
 *
 * Two variants:
 *   - `full` (default): viewport-tall splash. For root + route-
 *     group loaders.
 *   - `inline`: stretches to its parent container. For embedded
 *     suspense regions (e.g. inside the dashboard content area
 *     while the route data is fetching).
 */

import { BrandMark } from './brand-mark';
import { cn } from '@/lib/utils';

export interface BrandLoaderProps {
  variant?: 'full' | 'inline';
  /** Optional caption rendered below the mark. Use for context-
   *  specific loaders (e.g. "Loading appointments…"). */
  caption?: string;
  className?: string;
}

export function BrandLoader({
  variant = 'full',
  caption,
  className,
}: BrandLoaderProps) {
  return (
    <div
      role="status"
      aria-live="polite"
      aria-label={caption ?? 'Loading'}
      className={cn(
        'flex flex-col items-center justify-center gap-5 bg-muted/30 text-muted-foreground',
        variant === 'full' ? 'min-h-screen w-full' : 'h-full w-full py-16',
        className,
      )}
    >
      <div className="relative">
        {/* Subtle expanding ring — pulses to suggest activity without
            being noisy. Tailwind's `animate-ping` cycle is well-tuned
            for this. */}
        <span
          aria-hidden
          className="absolute inset-0 inline-flex size-full rounded-full bg-foreground/10 animate-ping"
        />
        <span className="relative inline-flex size-12 items-center justify-center rounded-full bg-card border shadow-sm">
          <BrandMark variant="icon" size={28} />
        </span>
      </div>
      {caption ? (
        <p className="text-xs uppercase tracking-[0.18em] text-muted-foreground">
          {caption}
        </p>
      ) : null}
      <span className="sr-only">Loading…</span>
    </div>
  );
}
