/**
 * Scroll-driven reveal primitive.
 *
 * Wraps any subtree and fades it up (`opacity 0 → 1`,
 * `translateY 24px → 0`) the first time it intersects the viewport.
 * Uses native IntersectionObserver — no Framer Motion, no Lottie, no
 * 200KB animation library. The motion is intentional editorial:
 * 700ms with a slow exponential ease, no bounce, no spring.
 *
 * Stagger is supported via the `delay` prop — supply per-row delays
 * to make a list of items reveal sequentially. The first row should
 * use 0ms; each subsequent row adds 60-100ms.
 *
 * Accessibility: respects `prefers-reduced-motion` automatically via
 * the `motion-reduce:` Tailwind variant on the transition utility.
 *
 * Performance: a single observer per element is fine at the scale of
 * a marketing page (~30 reveals on the home). If we ever shipped a
 * 200-card directory we'd swap for a shared root observer; today
 * the cost is invisible.
 */

'use client';

import { useEffect, useRef, useState } from 'react';

import { cn } from '@/lib/utils';

export interface ScrollRevealProps {
  children: React.ReactNode;
  /** Delay before the reveal animation starts, in ms. Use 0 for immediate
   *  (the most important call-to-action) and small offsets (60-100ms each)
   *  for staggered lists. */
  delay?: number;
  /** Optional additional class names on the wrapper. */
  className?: string;
  /** Render as a different element (e.g. `as="li"` inside an ordered list).
   *  Default: `div`. */
  as?: 'div' | 'section' | 'li' | 'span' | 'article';
  /** Trigger threshold (0-1). 0.15 by default — element starts revealing
   *  when ~15% has scrolled into view, which feels right for editorial
   *  pacing (the eye isn't startled by a sudden mid-screen pop). */
  threshold?: number;
}

export function ScrollReveal({
  children,
  delay = 0,
  className,
  as: Tag = 'div',
  threshold = 0.15,
}: ScrollRevealProps) {
  const ref = useRef<HTMLElement | null>(null);
  const [revealed, setRevealed] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    // If reduced motion is on, skip the observer entirely — render in
    // the final state immediately.
    if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) {
      setRevealed(true);
      return;
    }

    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            setRevealed(true);
            observer.disconnect();
            break;
          }
        }
      },
      { threshold },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [threshold]);

  // Tag is one of the allowed strings; cast to keep TS happy across the
  // five element types we accept.
  const ElementTag = Tag as 'div';

  return (
    <ElementTag
      ref={ref as React.RefObject<HTMLDivElement>}
      style={{ transitionDelay: revealed ? `${delay}ms` : '0ms' }}
      className={cn(
        'transition-[opacity,transform] duration-700 ease-[cubic-bezier(0.16,1,0.3,1)] motion-reduce:transition-none will-change-[opacity,transform]',
        revealed ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-6',
        className,
      )}
    >
      {children}
    </ElementTag>
  );
}
