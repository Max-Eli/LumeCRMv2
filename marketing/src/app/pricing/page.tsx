import Link from 'next/link';

import { PageHero } from '@/components/page-hero';
import { ScrollReveal } from '@/components/scroll-reveal';

import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Pricing',
  description:
    'Custom pricing based on locations, providers, SMS volume, and migration scope. No platform fee on card volume. BAA included. We respond within one business day.',
};

const VARIABLES = [
  {
    label: 'Locations',
    body:
      'How many physical locations you operate. The first location is included; each additional location adds to the monthly bill.',
  },
  {
    label: 'Active providers',
    body:
      'Bookable providers on your team. Front-desk and bookkeeping seats are included at every plan level — pricing scales with bookable revenue, not headcount.',
  },
  {
    label: 'Migration scope',
    body:
      'If you\'re moving from Zenoti, Mindbody, Boulevard, or another platform, we scope a one-time migration based on the export shape. Most migrations complete in 2-4 weeks.',
  },
  {
    label: 'SMS / email volume',
    body:
      'Reminder cadence and marketing sends sit downstream of the seat fee. Pass-through at telecom cost — no markup, no per-message platform fee.',
  },
];

const INCLUDED = [
  'Unlimited staff seats per location',
  'Unlimited client records',
  'Unlimited form submissions',
  'Unlimited invoices and payments',
  'All 22 reports',
  'CSV export on every report',
  'HIPAA Business Associate Agreement',
  'Email + chat support, business hours',
  'Implementation + onboarding',
  'No card-volume fee',
  'No annual contract lock-in',
  'No tier upgrade required for new features',
];

export default function PricingPage() {
  return (
    <>
      <PageHero
        eyebrow="Pricing"
        headline={
          <>
            Custom pricing,{' '}
            <span className="accent-italic">scaled to your spa.</span>
          </>
        }
        standfirst="Every medspa runs differently. Tell us about your operation and we'll send a quote within one business day. The Business Associate Agreement, onboarding, and unlimited staff seats are included at every level."
      />

      <section>
        <div className="mx-auto max-w-7xl px-6 lg:px-10 py-20 lg:py-28">
          <div className="grid gap-16 lg:grid-cols-12">
            <ScrollReveal className="lg:col-span-5">
              <p className="eyebrow text-foreground/60">What we ask about</p>
              <h2 className="mt-4 font-display text-4xl text-foreground sm:text-5xl">
                Four variables.
                <br />
                <span className="accent-italic">No surprise items.</span>
              </h2>
              <p className="mt-6 text-base leading-relaxed text-foreground/80">
                The quote you receive is the quote that goes on the
                contract. Setup is included. The BAA is included.
                There's no annual contract lock-in — we earn the
                renewal with the product, not a clause.
              </p>
            </ScrollReveal>

            <ol className="space-y-0 lg:col-span-7">
              {VARIABLES.map((v, i) => (
                <ScrollReveal as="li" key={v.label} delay={i * 80} className={i === 0 ? 'border-t border-foreground/15' : ''}>
                  <div className="grid gap-4 border-b border-foreground/15 py-8 lg:grid-cols-12 lg:gap-8 lg:py-10">
                    <div className="lg:col-span-3">
                      <span className="font-display text-2xl text-accent/80">
                        {String(i + 1).padStart(2, '0')}
                      </span>
                      <p className="mt-2 eyebrow text-foreground/60">{v.label}</p>
                    </div>
                    <p className="text-base leading-relaxed text-foreground/80 lg:col-span-9">
                      {v.body}
                    </p>
                  </div>
                </ScrollReveal>
              ))}
            </ol>
          </div>

          {/* What's included */}
          <ScrollReveal>
            <div className="mt-24 border-t border-foreground/15 pt-16">
              <p className="eyebrow text-foreground/60">Included at every level</p>
              <h2 className="mt-4 font-display text-3xl text-foreground sm:text-4xl">
                No tier upgrades.{' '}
                <span className="accent-italic">No add-ons.</span>
              </h2>
              <ul className="mt-10 grid gap-x-8 gap-y-4 sm:grid-cols-2 lg:grid-cols-3">
                {INCLUDED.map((item) => (
                  <li key={item} className="flex items-start gap-2 text-sm text-foreground/80">
                    <span aria-hidden className="mt-2 inline-block size-1 shrink-0 rounded-full bg-accent" />
                    {item}
                  </li>
                ))}
              </ul>
            </div>
          </ScrollReveal>

          <ScrollReveal>
            <div className="mt-20 flex flex-col items-start gap-6 border-t border-foreground/15 pt-12 lg:flex-row lg:items-center lg:justify-between">
              <div>
                <p className="eyebrow text-foreground/60">Ready for a number?</p>
                <p className="mt-3 font-serif text-2xl font-medium text-foreground">
                  We send the quote with the demo invitation.
                </p>
              </div>
              <Link
                href="/demo"
                className="inline-flex h-12 items-center rounded-full bg-foreground px-7 text-sm font-medium uppercase tracking-[0.16em] text-background hover:bg-foreground/90 transition-colors"
              >
                Get a demo + quote
              </Link>
            </div>
          </ScrollReveal>
        </div>
      </section>
    </>
  );
}
