import Link from 'next/link';

import { PageHero } from '@/components/page-hero';
import { ScrollReveal } from '@/components/scroll-reveal';

import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'About',
    description:
    'Lumè is a HIPAA-compliant CRM built specifically for medical spas. Designed by people who watched friends running spas struggle with platforms built for someone else.',
};

export default function AboutPage() {
  return (
    <>
      <PageHero
        eyebrow="About Lumè"
        headline={
          <>
            We build software for medical spas.{' '}
            <span className="accent-italic">That&apos;s it.</span>
          </>
        }
        standfirst="Lumè is a HIPAA-compliant CRM built for medspas. Designed by people who watched friends running spas struggle with platforms built for haircuts, yoga classes, and general doctors' offices."
      />

      <section>
        <div className="mx-auto max-w-3xl px-6 lg:px-10 py-20 lg:py-28">
          <article className="space-y-6 text-lg leading-[1.85] text-foreground/85">
            <ScrollReveal>
              <h2 className="font-serif text-3xl font-medium text-foreground">
                Why we exist
              </h2>
              <p className="mt-4">
                The medspa industry runs on software designed for other
                businesses. Mindbody and Vagaro for salons and yoga.
                Boulevard for high-end salons. Zenoti for spa chains
                with hundreds of locations. None of them are built
                around the blend of medical compliance, treatment-cycle
                scheduling, consent versioning, and front-desk
                reconciliation a medspa actually needs.
              </p>
              <p className="mt-4">
                We watched a friend's spa lose 45 minutes every
                Saturday morning to a platform that couldn't quite take
                a deposit, couldn't quite send a reminder, and couldn't
                quite show the front desk what time it was at the other
                location. So we built the alternative.
              </p>
            </ScrollReveal>

            <ScrollReveal delay={120}>
              <h2 className="mt-12 font-serif text-3xl font-medium text-foreground">
                What we believe
              </h2>
              <p className="mt-4">
                <strong className="text-foreground">HIPAA isn't a tier.</strong>{' '}
                Every customer runs on the same compliant architecture.
                No "secure plan" upsell because there's no other plan.
                The BAA is in every contract.
              </p>
              <p className="mt-4">
                <strong className="text-foreground">Pricing without games.</strong>{' '}
                Card processing runs through our licensed payment
                partner with rates quoted up front. We charge per
                location, not per seat, so a hire doesn't trigger a
                re-negotiation.
              </p>
              <p className="mt-4">
                <strong className="text-foreground">Your data stays yours.</strong>{' '}
                Every report exports to CSV. The audit log is
                queryable. If you ever leave Lumè, you leave with
                everything you put in. No tier-locked exports, no
                lawyer-required escrow.
              </p>
            </ScrollReveal>

            <ScrollReveal delay={240}>
              <h2 className="mt-12 font-serif text-3xl font-medium text-foreground">
                Where we are right now
              </h2>
              <p className="mt-4">
                Two medspas are migrating onto Lumè in 2026; the first
                goes live before end of quarter. We're taking on a
                small, deliberate number of additional customers this
                year so we stay close to every onboarding.
              </p>

              {/* A small typographic strip of brand-meaningful
                  numbers. Visual anchor for an otherwise pure-prose
                  page; same editorial vocabulary as the rest of the
                  site (numbered, accent burgundy, serif). */}
              <ul className="mt-10 grid gap-y-6 gap-x-8 border-y border-foreground/15 py-8 sm:grid-cols-3">
                <li>
                  <p className="font-display text-3xl text-accent">2</p>
                  <p className="mt-1 text-sm text-foreground/70">
                    Medspas migrating onto Lumè in 2026.
                  </p>
                </li>
                <li>
                  <p className="font-display text-3xl text-accent">22</p>
                  <p className="mt-1 text-sm text-foreground/70">
                    Reports across financial, staff, guests, and operations.
                  </p>
                </li>
                <li>
                  <p className="font-display text-3xl text-accent">1</p>
                  <p className="mt-1 text-sm text-foreground/70">
                    Architecture. No secure tier, no upsell.
                  </p>
                </li>
              </ul>

              <p className="mt-6">
                If you'd like to be one of them,{' '}
                <Link
                  href="/demo"
                  className="font-medium text-accent underline underline-offset-4 hover:text-foreground"
                >
                  request a demo
                </Link>
                . We respond within one business day.
              </p>
            </ScrollReveal>

            <ScrollReveal delay={360}>
              <p className="mt-12 text-sm text-muted-foreground">
                — The Lumè team
              </p>
            </ScrollReveal>
          </article>
        </div>
      </section>
    </>
  );
}
