/**
 * Reusable feature deep-dive page template.
 *
 * Sections (top → bottom):
 *
 *   1. Hero            — eyebrow + serif headline + functional standfirst + CTA
 *   2. Hero mock       — full-width product mockup of the feature in action
 *   3. Highlights      — 3 short value-prop bullets with concrete claims
 *   4. Detail sections — N stacked sections, each with a copy block + a
 *                        smaller product mock or list of capabilities
 *   5. Cross-links     — 2 related features
 *   6. CTA             — direct demo request
 *
 * Designed so each feature page reads like a Boulevard / Zenoti
 * product page: scannable, specific, no literary affectation. The
 * reusability also means six pages stay visually consistent without
 * me writing six bespoke layouts.
 */

import Link from 'next/link';
import type { ReactNode } from 'react';

import { ProductFrame } from '@/components/product-frame';
import { ScrollReveal } from '@/components/scroll-reveal';
import { breadcrumbJsonLd, jsonLd } from '@/lib/seo';

export interface FeatureDetail {
  eyebrow: string;
  title: string;
  body: ReactNode;
  bullets?: string[];
}

export interface FeaturePageProps {
  eyebrow: string;
  headline: ReactNode;
  standfirst: string;
  heroMock: ReactNode;
  heroMockUrl: string;
  /** Three short claims shown immediately under the hero mock. */
  highlights: { value: string; label: string }[];
  /** Long-form detail sections — alternate left/right with optional mocks. */
  details: (FeatureDetail & { mock?: ReactNode; mockUrl?: string })[];
  /** Cross-link cards at the bottom (usually 2 sibling features). */
  related: { href: string; label: string; title: string }[];
  /** The path this page renders at, e.g. `/features/booking`. Used to
   *  emit a correct `BreadcrumbList` JSON-LD record. Optional: when
   *  omitted, we still render the page but skip the breadcrumb
   *  payload. */
  path?: string;
  /** Human-readable breadcrumb label for this feature, e.g. "Booking
   *  calendar". Defaults to `eyebrow` when omitted. */
  breadcrumbLabel?: string;
}

export function FeaturePage({
  eyebrow,
  headline,
  standfirst,
  heroMock,
  heroMockUrl,
  highlights,
  details,
  related,
  path,
  breadcrumbLabel,
}: FeaturePageProps) {
  const breadcrumb = path
    ? breadcrumbJsonLd([
        { name: 'Home', path: '/' },
        { name: 'Features', path: '/features' },
        { name: breadcrumbLabel ?? eyebrow, path },
      ])
    : null;

  return (
    <>
      {breadcrumb ? (
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{ __html: jsonLd(breadcrumb) }}
        />
      ) : null}
      {/* Hero */}
      <section className="border-b border-border">
        <div className="mx-auto max-w-7xl px-6 lg:px-10 pt-20 pb-12 lg:pt-28 lg:pb-16">
          <p className="eyebrow text-foreground/60">{eyebrow}</p>
          <h1 className="mt-6 max-w-4xl font-display text-5xl text-foreground sm:text-6xl lg:text-7xl">
            {headline}
          </h1>
          <p className="mt-8 max-w-3xl text-lg leading-relaxed text-foreground/80 sm:text-xl">
            {standfirst}
          </p>
          <div className="mt-10 flex flex-wrap items-center gap-6">
            <Link
              href="/demo"
              className="inline-flex h-12 items-center rounded-full bg-foreground px-7 text-sm font-medium uppercase tracking-[0.16em] text-background hover:bg-foreground/90 transition-colors"
            >
              Get a demo
            </Link>
            <Link
              href="/features"
              className="text-sm font-medium text-foreground/70 hover:text-foreground transition-colors"
            >
              <span className="link-underline decoration-accent">All features →</span>
            </Link>
          </div>
        </div>
      </section>

      {/* Hero mock + highlights */}
      <section className="border-b border-border bg-foreground/[0.02]">
        <div className="mx-auto max-w-7xl px-6 lg:px-10 py-14 lg:py-20">
          <ScrollReveal>
            <ProductFrame url={heroMockUrl} aspect="aspect-[16/9]">
              {heroMock}
            </ProductFrame>
          </ScrollReveal>

          <ul className="mt-12 grid gap-8 border-t border-foreground/15 pt-10 sm:grid-cols-3">
            {highlights.map((h, i) => (
              <ScrollReveal as="li" key={h.label} delay={i * 80}>
                <p className="font-display text-3xl text-foreground sm:text-4xl">
                  {h.value}
                </p>
                <p className="mt-2 text-sm text-foreground/70">{h.label}</p>
              </ScrollReveal>
            ))}
          </ul>
        </div>
      </section>

      {/* Detail sections — alternate left/right */}
      <section>
        <div className="mx-auto max-w-7xl px-6 lg:px-10 py-24 lg:py-32 space-y-24 lg:space-y-32">
          {details.map((d, i) => {
            const flip = i % 2 === 1;
            return (
              <div key={d.title} className="grid items-center gap-12 lg:grid-cols-12 lg:gap-16">
                <ScrollReveal
                  className={flip ? 'lg:col-span-5 lg:col-start-8 lg:order-2' : 'lg:col-span-5'}
                >
                  <p className="eyebrow text-foreground/60">{d.eyebrow}</p>
                  <h2 className="mt-3 font-serif text-3xl font-medium text-foreground sm:text-4xl">
                    {d.title}
                  </h2>
                  <div className="mt-5 space-y-4 text-base leading-relaxed text-foreground/75 sm:text-lg">
                    {d.body}
                  </div>
                  {d.bullets ? (
                    <ul className="mt-6 space-y-2 text-sm text-foreground/75">
                      {d.bullets.map((b) => (
                        <li key={b} className="flex items-start gap-2">
                          <span aria-hidden className="mt-2 inline-block size-1 shrink-0 rounded-full bg-accent" />
                          {b}
                        </li>
                      ))}
                    </ul>
                  ) : null}
                </ScrollReveal>

                <ScrollReveal
                  delay={140}
                  className={flip ? 'lg:col-span-7 lg:col-start-1 lg:order-1' : 'lg:col-span-7 lg:col-start-6'}
                >
                  {d.mock ? (
                    <ProductFrame url={d.mockUrl ?? '/'}>
                      {d.mock}
                    </ProductFrame>
                  ) : null}
                </ScrollReveal>
              </div>
            );
          })}
        </div>
      </section>

      {/* Related features */}
      <section className="border-y border-border bg-foreground/[0.02]">
        <div className="mx-auto max-w-7xl px-6 lg:px-10 py-16 lg:py-20">
          <p className="eyebrow text-foreground/60">Related capabilities</p>
          <div className="mt-6 grid gap-8 lg:grid-cols-2">
            {related.map((r) => (
              <Link
                key={r.href}
                href={r.href}
                className="group flex items-baseline justify-between gap-6 border-t border-foreground/15 py-6 transition-colors hover:border-accent"
              >
                <div>
                  <p className="eyebrow text-foreground/60">{r.label}</p>
                  <p className="mt-2 font-serif text-xl font-medium text-foreground sm:text-2xl">
                    {r.title}
                  </p>
                </div>
                <span className="text-foreground/55 transition-colors group-hover:text-accent" aria-hidden>→</span>
              </Link>
            ))}
          </div>
        </div>
      </section>

      {/* CTA */}
      <section className="border-t border-border bg-foreground text-background">
        <div className="mx-auto max-w-7xl px-6 lg:px-10 py-20 lg:py-24">
          <div className="grid gap-8 lg:grid-cols-12 lg:items-center">
            <div className="lg:col-span-8">
              <p className="eyebrow text-background/60">See it in 30 minutes</p>
              <h2 className="mt-3 font-display text-3xl sm:text-4xl lg:text-5xl">
                See {eyebrow.toLowerCase()} running on your spa's data.
              </h2>
            </div>
            <div className="lg:col-span-4 lg:text-right">
              <Link
                href="/demo"
                className="inline-flex h-12 items-center rounded-full bg-background px-8 text-sm font-medium uppercase tracking-[0.16em] text-foreground hover:bg-background/90 transition-colors"
              >
                Get a demo
              </Link>
            </div>
          </div>
        </div>
      </section>
    </>
  );
}
