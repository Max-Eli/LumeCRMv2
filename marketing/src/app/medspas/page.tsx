import Link from 'next/link';

import { PageHero } from '@/components/page-hero';
import { ScrollReveal } from '@/components/scroll-reveal';
import { SectionEyebrow } from '@/components/section-eyebrow';
import { ProductFrame } from '@/components/product-frame';
import { CalendarMock, ChartMock, ReportsMock } from '@/components/product-mocks';

import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'For medspas',
  description:
    'Why Lumè is built for medical spas — the clinical workflows, compliance demands, and operational realities that general-purpose CRMs miss.',
};

const FAILURE_MODES = [
  {
    title: 'Salon platforms.',
    body:
      "Mindbody, Vagaro, Booker — built for haircuts and yoga classes, then patched to handle injectables. They lack treatment-cycle scheduling, per-service consent recurrence, and the medical-grade audit trail a state board expects.",
  },
  {
    title: 'High-end salon platforms.',
    body:
      "Boulevard targets the high-end salon market. The booking experience is excellent; the medical workflows aren't there. No consent-versioning, no per-treatment audit trail, no medical-spa-specific reporting like consent-expiration tracking.",
  },
  {
    title: 'Enterprise spa software.',
    body:
      "Zenoti is built for spa chains with hundreds of locations. Powerful, but priced and configured for that scale — most independent and small-chain medspas spend twelve months in implementation and never use 30% of the surface.",
  },
  {
    title: "General doctor's office EMRs.",
    body:
      "Athena, Epic, Practice Fusion — designed for medical visits, not retail aesthetics. They handle charting and ICD coding well; they fail at booking with deposits, retail product sales, and the customer-facing polish a medspa client expects.",
  },
];

const WORKFLOW_FITS = [
  {
    eyebrow: 'Treatment-cycle scheduling',
    title: 'Schedule the next visit at the right interval, automatically.',
    body:
      "Botox at 12-14 weeks. Filler at 6-12 months depending on product. Laser series at 4-6 weeks. Lumè knows the recommended interval for each service in your menu and surfaces the next-visit suggestion at checkout — not as a calendar invite the client never opens, but as a deposit-on-book flow that converts.",
  },
  {
    eyebrow: 'Consent that follows the treatment',
    title: 'Per-treatment consent forms, signed at the visit.',
    body:
      "A general intake form gets signed once per client. Per-treatment consent (Botox, filler, lasers) signs every visit because the risk profile is per-procedure. Lumè handles both rules: lifetime intake on first visit, per-visit consent auto-assigned when the appointment books.",
  },
  {
    eyebrow: 'Pricing that respects the chair',
    title: 'No platform fee on card volume.',
    body:
      "Most spa platforms take 1-3% of card volume on top of your processor fees. On a $2M annual book that's $20-60K a year going to the software vendor for the privilege of letting you take payments. Lumè doesn't process payments and doesn't charge for them — your existing terminal, your existing processor, your existing rate.",
  },
  {
    eyebrow: 'Medical-grade audit trail',
    title: 'Every PHI access logged, every state change traceable.',
    body:
      "If your medical board asks who viewed Sarah Chen's chart on May 12th, you can answer. Lumè writes an audit log entry on every PHI read — append-only, immutable in production, queryable by date range, user, or resource. SOC 2 CC 6.1 + HIPAA §164.312(b) satisfied by architecture, not by retrofit.",
  },
];

export default function ForMedspasPage() {
  return (
    <>
      <PageHero
        eyebrow="For medical spas"
        headline={
          <>
            Built for medspas.{' '}
            <span className="accent-italic">Not a salon tool with extras.</span>
          </>
        }
        standfirst="Most CRMs medspas use today were designed for haircuts, yoga classes, or general doctors' offices, then patched to handle injectables. Lumè was built for medical spa workflows from day one — clinical compliance, treatment-cycle scheduling, per-service consent recurrence, and the financial reconciliation the front desk actually does."
      />

      {/* Why other tools fall short */}
      <section className="border-b border-border">
        <div className="mx-auto max-w-7xl px-6 lg:px-10 py-20 lg:py-28">
          <ScrollReveal>
            <SectionEyebrow
              eyebrow="The platforms most medspas are using"
              headline={
                <>
                  Four categories of tools.{' '}
                  <span className="accent-italic">All built for someone else.</span>
                </>
              }
              description="Medspas have spent the last decade adapting platforms designed for other industries. Each comes with specific compromises."
            />
          </ScrollReveal>

          <div className="mt-16 grid gap-x-12 gap-y-10 lg:grid-cols-2">
            {FAILURE_MODES.map((f, i) => (
              <ScrollReveal key={f.title} delay={i * 80} className="border-t border-foreground/15 pt-6">
                <h3 className="font-serif text-xl font-medium text-foreground">{f.title}</h3>
                <p className="mt-3 text-base leading-relaxed text-foreground/75">{f.body}</p>
              </ScrollReveal>
            ))}
          </div>
        </div>
      </section>

      {/* Workflow fits — the actual product fit */}
      <section>
        <div className="mx-auto max-w-7xl px-6 lg:px-10 py-24 lg:py-32">
          <ScrollReveal>
            <SectionEyebrow
              eyebrow="Built for medspa workflows"
              headline={
                <>
                  Four workflows{' '}
                  <span className="accent-italic">other platforms get wrong.</span>
                </>
              }
              description="The specific operational realities of running a medical spa, and how Lumè handles each one."
            />
          </ScrollReveal>

          <div className="mt-20 space-y-20 lg:space-y-28">
            {WORKFLOW_FITS.map((w, i) => (
              <div key={w.title} className="grid items-start gap-10 lg:grid-cols-12 lg:gap-14">
                <ScrollReveal className="lg:col-span-1">
                  <span className="font-display text-3xl text-accent/80">
                    {String(i + 1).padStart(2, '0')}
                  </span>
                </ScrollReveal>
                <ScrollReveal delay={80} className="lg:col-span-11 lg:col-start-2">
                  <p className="eyebrow text-foreground/60">{w.eyebrow}</p>
                  <h3 className="mt-3 max-w-3xl font-serif text-2xl font-medium text-foreground sm:text-3xl">
                    {w.title}
                  </h3>
                  <p className="mt-4 max-w-3xl text-base leading-relaxed text-foreground/75 sm:text-lg">
                    {w.body}
                  </p>
                </ScrollReveal>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* The day-of-business view */}
      <section className="border-y border-border bg-foreground/[0.02]">
        <div className="mx-auto max-w-7xl px-6 lg:px-10 py-20 lg:py-28">
          <ScrollReveal>
            <SectionEyebrow
              eyebrow="A day in the front desk's hands"
              headline={
                <>
                  How Lumè runs the{' '}
                  <span className="accent-italic">day-to-day.</span>
                </>
              }
            />
          </ScrollReveal>

          <div className="mt-12 grid gap-8 lg:grid-cols-3">
            <ScrollReveal>
              <ProductFrame url="/calendar" aspect="aspect-[4/3]">
                <CalendarMock />
              </ProductFrame>
              <p className="mt-4 eyebrow text-foreground/60">9:00 am</p>
              <p className="mt-2 font-serif text-lg font-medium text-foreground">Open the calendar</p>
              <p className="mt-1 text-sm leading-relaxed text-foreground/70">
                Per-provider columns show the day, scoped to your location. Coffee in hand, you can see who's booked, who's confirmed, and which appointments need the consent form sent before arrival.
              </p>
            </ScrollReveal>

            <ScrollReveal delay={120}>
              <ProductFrame url="/clients/sarah-chen" aspect="aspect-[4/3]">
                <ChartMock />
              </ProductFrame>
              <p className="mt-4 eyebrow text-foreground/60">11:30 am</p>
              <p className="mt-2 font-serif text-lg font-medium text-foreground">Check in a returning client</p>
              <p className="mt-1 text-sm leading-relaxed text-foreground/70">
                Sarah's been here twelve times. The chart loads in under a second with her allergies, last visit, and the pending Botox consent ready to sign on the iPad before the provider sees her.
              </p>
            </ScrollReveal>

            <ScrollReveal delay={240}>
              <ProductFrame url="/reports/financial/daily-close-out" aspect="aspect-[4/3]">
                <ReportsMock />
              </ProductFrame>
              <p className="mt-4 eyebrow text-foreground/60">7:30 pm</p>
              <p className="mt-2 font-serif text-lg font-medium text-foreground">Close out the day</p>
              <p className="mt-1 text-sm leading-relaxed text-foreground/70">
                Daily close-out report breaks gross by payment method. Cash matches the drawer, card matches the terminal. Export to CSV for the bookkeeper. Lock up.
              </p>
            </ScrollReveal>
          </div>
        </div>
      </section>

      {/* CTA */}
      <section className="border-t border-border bg-foreground text-background">
        <div className="mx-auto max-w-7xl px-6 lg:px-10 py-20 lg:py-24">
          <ScrollReveal>
            <div className="grid gap-8 lg:grid-cols-12 lg:items-center">
              <div className="lg:col-span-8">
                <p className="eyebrow text-background/60">See it in 30 minutes</p>
                <h2 className="mt-3 font-display text-3xl sm:text-4xl lg:text-5xl">
                  See Lumè configured for your medspa.
                </h2>
                <p className="mt-4 max-w-2xl text-base leading-relaxed text-background/80">
                  We'll set up a private walkthrough with the product
                  configured for your service menu, your providers, and
                  your locations. Coming from another platform? We scope
                  the migration during the call.
                </p>
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
          </ScrollReveal>
        </div>
      </section>
    </>
  );
}
