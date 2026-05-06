/**
 * Subtle parallax wrapper. Translates the child opposite the scroll
 * direction at a small fraction of scroll speed (default `speed=0.15`),
 * giving editorial layouts a slight depth cue without theme-park
 * "everything is moving" effects.
 *
 * Pure scroll listener (no rAF queue, no GSAP) — at this site's
 * scale it's invisible cost. Respects `prefers-reduced-motion` by
 * disabling the translation entirely.
 *
 * Use it for accents only (a single pull-quote number, a hero side
 * panel). Don't apply it to body copy — small text drifting against
 * scroll is hard to read.
 */

'use client';

import { useEffect, useRef, useState } from 'react';

import { cn } from '@/lib/utils';

export interface ParallaxProps {
  children: React.ReactNode;
  /** Fraction of scroll distance to translate. 0.15 ≈ subtle drift,
   *  0.4 = noticeable, > 0.5 = obvious. Editorial restraint: stay ≤ 0.2. */
  speed?: number;
  className?: string;
}

export function Parallax({ children, speed = 0.15, className }: ParallaxProps) {
  const ref = useRef<HTMLDivElement | null>(null);
  const [offset, setOffset] = useState(0);

  useEffect(() => {
    if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return;

    const update = () => {
      const el = ref.current;
      if (!el) return;
      const rect = el.getBoundingClientRect();
      const viewportCenter = window.innerHeight / 2;
      // Distance of the element's center from the viewport center,
      // negative when above. This makes the parallax symmetric: it
      // drifts up when below the viewport center and down when above.
      const distance = rect.top + rect.height / 2 - viewportCenter;
      setOffset(-distance * speed);
    };

    update();
    window.addEventListener('scroll', update, { passive: true });
    window.addEventListener('resize', update, { passive: true });
    return () => {
      window.removeEventListener('scroll', update);
      window.removeEventListener('resize', update);
    };
  }, [speed]);

  return (
    <div
      ref={ref}
      style={{ transform: `translate3d(0, ${offset}px, 0)` }}
      className={cn('will-change-transform', className)}
    >
      {children}
    </div>
  );
}
