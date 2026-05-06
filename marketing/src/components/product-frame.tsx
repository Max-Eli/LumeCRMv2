/**
 * Browser-style frame for product UI mockups.
 *
 * Wraps a child (the mock UI) in a clean window chrome — three soft
 * traffic-light dots, a hairline tab/URL bar with the page name in
 * monospace, and a subtle drop shadow under the frame. The wrapper
 * stays editorial: no glass effect, no gradient, no glow.
 *
 * The mock UIs (calendar, chart, form, etc.) are intentionally
 * built with real-looking HTML/CSS rather than stock illustrations —
 * they reflect the actual product surface, so when a customer
 * arrives in their tenant subdomain after a demo, what they saw on
 * the marketing site matches what they're now using.
 */

import { cn } from '@/lib/utils';

export interface ProductFrameProps {
  /** Path shown in the URL bar — e.g. `/calendar`, `/clients/Sarah-Chen`. */
  url?: string;
  /** Inner content — the mock UI. Should fill the frame. */
  children: React.ReactNode;
  /** Optional aspect ratio for the inner viewport. Default: `aspect-[16/10]`. */
  aspect?: string;
  className?: string;
  /** When true, drops the subtle shadow + ring (use inside dark sections). */
  flat?: boolean;
}

export function ProductFrame({
  url = '/calendar',
  children,
  aspect = 'aspect-[16/10]',
  className,
  flat = false,
}: ProductFrameProps) {
  return (
    <div
      className={cn(
        'relative overflow-hidden rounded-xl border border-foreground/10 bg-background',
        !flat && 'shadow-[0_30px_80px_-40px_rgba(16,12,8,0.35),_0_8px_24px_-12px_rgba(16,12,8,0.18)]',
        className,
      )}
    >
      {/* Window chrome — three soft dots + a URL "tab" with the page name. */}
      <div className="flex items-center gap-3 border-b border-foreground/10 bg-foreground/[0.025] px-4 py-2.5">
        <div className="flex items-center gap-1.5">
          <span className="block size-2.5 rounded-full bg-foreground/15" />
          <span className="block size-2.5 rounded-full bg-foreground/15" />
          <span className="block size-2.5 rounded-full bg-foreground/15" />
        </div>
        <div className="ml-2 flex items-center gap-2 rounded-md bg-foreground/5 px-3 py-1 text-[11px] font-mono text-foreground/55">
          <span aria-hidden>◆</span>
          <span>acmespa.lumècrm.com</span>
          <span className="text-foreground/30">{url}</span>
        </div>
      </div>

      <div className={cn('relative bg-background', aspect)}>{children}</div>
    </div>
  );
}
