/**
 * Inner-page hero. Smaller register than the home page hero — a
 * small-caps eyebrow above a single serif headline, optional
 * standfirst paragraph below, and a fine ruled line to set off the
 * page body.
 *
 * Used at the top of /features, /security, /pricing, /demo, /about
 * so every inner page opens with the same considered rhythm.
 */

import { cn } from '@/lib/utils';

export interface PageHeroProps {
  eyebrow: string;
  headline: React.ReactNode;
  standfirst?: React.ReactNode;
  className?: string;
}

export function PageHero({ eyebrow, headline, standfirst, className }: PageHeroProps) {
  return (
    <section className={cn('border-b border-border', className)}>
      <div className="mx-auto max-w-7xl px-6 lg:px-10 pt-20 pb-16 lg:pt-28 lg:pb-20">
        <p className="eyebrow text-foreground/60">{eyebrow}</p>
        <h1 className="mt-6 max-w-4xl font-display text-5xl text-foreground sm:text-6xl lg:text-7xl">
          {headline}
        </h1>
        {standfirst ? (
          <p className="mt-8 max-w-3xl text-lg leading-relaxed text-foreground/80 sm:text-xl">
            {standfirst}
          </p>
        ) : null}
      </div>
    </section>
  );
}
