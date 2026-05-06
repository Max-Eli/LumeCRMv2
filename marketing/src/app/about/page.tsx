import Link from 'next/link';

import { PageHero } from '@/components/page-hero';
import { ScrollReveal } from '@/components/scroll-reveal';

import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'About',
  description:
    'Lumè is a HIPAA-compliant CRM built specifically for medical spas — designed by people who watched friends running medspas struggle with platforms built for someone else.',
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
        standfirst="Lumè is a HIPAA-compliant CRM built specifically for medspas — designed by people who watched friends running spas struggle with platforms built for haircuts, yoga classes, and general doctors' offices."
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
                businesses. Mindbody and Vagaro come from the salon and
                yoga studio world. Boulevard targets high-end salons.
                Zenoti is enterprise-built for spa chains with hundreds
                of locations. None of them were designed for the specific
                blend of medical compliance, treatment-cycle scheduling,
                consent versioning, and front-desk reconciliation that a
                modern medspa actually needs.
              </p>
              <p className="mt-4">
                We watched a friend's spa lose 45 minutes every Saturday
                morning to a platform that couldn't quite take a
                deposit, couldn't quite send a reminder, and couldn't
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
                Every Lumè customer is on the HIPAA-compliant
                architecture from day one because there's only one
                architecture. No "secure plan" upsell. The Business
                Associate Agreement is included in every contract.
              </p>
              <p className="mt-4">
                <strong className="text-foreground">Pricing without games.</strong>{' '}
                Lumè doesn't process payments and doesn't take a cut of
                card volume. Your existing terminal stays your terminal.
                We charge per location, not per seat, so adding a hire
                doesn't trigger a re-negotiation.
              </p>
              <p className="mt-4">
                <strong className="text-foreground">Your data stays yours.</strong>{' '}
                Every report exports to CSV. The audit log is queryable.
                If you ever leave Lumè, you leave with everything you
                put in — no tier-locked exports, no lawyer-required
                escrow.
              </p>
            </ScrollReveal>

            <ScrollReveal delay={240}>
              <h2 className="mt-12 font-serif text-3xl font-medium text-foreground">
                Where we are right now
              </h2>
              <p className="mt-4">
                Two medspas are migrating onto Lumè from existing
                platforms in 2026. The first goes live before end of
                quarter. We're taking on a small, deliberate number of
                additional customers this year so we can stay close to
                every onboarding and ship the right features in
                response to what we see.
              </p>
              <p className="mt-4">
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
