/**
 * Editorial section header. A small-caps eyebrow + a serif headline,
 * stacked. Some sections want a kicker line ("Chapter Two") above
 * the main eyebrow — `kicker` slot covers that.
 *
 * Used between major sections instead of `<h2>Heading</h2>` so every
 * section has the same considered rhythm. Restraint by default.
 */

import { cn } from '@/lib/utils';

export interface SectionEyebrowProps {
  kicker?: string;
  eyebrow?: string;
  headline: React.ReactNode;
  description?: React.ReactNode;
  align?: 'left' | 'center';
  className?: string;
}

export function SectionEyebrow({
  kicker,
  eyebrow,
  headline,
  description,
  align = 'left',
  className,
}: SectionEyebrowProps) {
  return (
    <div className={cn(align === 'center' && 'text-center', 'space-y-4', className)}>
      {kicker || eyebrow ? (
        <div className="flex items-center gap-3 text-foreground/60">
          {kicker ? (
            <span className="font-serif text-sm italic text-accent">{kicker}</span>
          ) : null}
          {kicker && eyebrow ? (
            <span aria-hidden className="h-px w-8 bg-border" />
          ) : null}
          {eyebrow ? <span className="eyebrow">{eyebrow}</span> : null}
        </div>
      ) : null}
      <h2 className="font-display text-4xl text-foreground sm:text-5xl">
        {headline}
      </h2>
      {description ? (
        <p className="max-w-2xl text-base leading-relaxed text-muted-foreground">
          {description}
        </p>
      ) : null}
    </div>
  );
}
