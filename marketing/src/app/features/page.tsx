import Link from 'next/link';

import { PageHero } from '@/components/page-hero';
import { ScrollReveal } from '@/components/scroll-reveal';

import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Features',
  description:
    'Six core capabilities purpose-built for medical spas: booking, client charts, consent forms, payments, reporting, and multi-location management.',
};

const FEATURES = [
  {
    n: '01',
    kicker: 'Booking',
    title: 'Multi-provider calendar with online booking.',
    standfirst:
      'Per-provider columns, per-location scoping, working-hours awareness. Clients can self-book online with a deposit; the system blocks double-bookings and flags missing consent before check-in.',
    href: '/features/booking',
  },
  {
    n: '02',
    kicker: 'Client charts',
    title: 'Complete client records, searchable across all locations.',
    standfirst:
      "Contact info, treatment history, allergies, signed consent forms, outstanding paperwork, and provider-only notes — accessible from the calendar in two taps. Searches across every chart your spa has, regardless of location.",
    href: '/features/charts',
  },
  {
    n: '03',
    kicker: 'Consent forms',
    title: 'E-signed consent that holds up under audit.',
    standfirst:
      "Schema-versioned templates for intake and per-treatment consent. Sent as tokenized links, signed on a tablet, snapshotted at the moment of signing. Audit trail captures IP, user-agent, and timestamp on every signature.",
    href: '/features/forms',
  },
  {
    n: '04',
    kicker: 'Payments',
    title: 'Invoicing built for end-of-day reconciliation.',
    standfirst:
      "Cash, check, card-on-terminal, and other methods recorded with payment reference. Owner-only sixty-day reopen window. Daily close-out matches the cash drawer at end of shift. No platform fee on card volume.",
    href: '/features/payments',
  },
  {
    n: '05',
    kicker: 'Reports',
    title: 'Twenty-two reports across financial, staff, guests, and operations.',
    standfirst:
      "Daily close-out, AR aging, revenue by service / provider / location, schedule utilization, no-show rates, top spenders, booking lead time. All running against live data; CSV export with HIPAA confirmation; audit-logged on every run.",
    href: '/features/reports',
  },
  {
    n: '06',
    kicker: 'Multi-location',
    title: 'One brand, multiple locations, one bill.',
    standfirst:
      "Per-location calendars, pricing, staff schedules, and reports. Org-level dashboard rolls up revenue, appointments, and utilization across every site. Single sign-on; the location switcher only appears when there's more than one to switch between.",
    href: '/features/multi-location',
  },
];

export default function FeaturesIndexPage() {
  return (
    <>
      <PageHero
        eyebrow="Platform features"
        headline={
          <>
            Six core capabilities,{' '}
            <span className="accent-italic">built for medspas.</span>
          </>
        }
        standfirst="Each one designed for the actual workflows medical spas run every day. Click through to see how each feature works."
      />

      <section>
        <div className="mx-auto max-w-7xl px-6 lg:px-10 py-20 lg:py-28">
          <ol className="space-y-0">
            {FEATURES.map((f, i) => (
              <ScrollReveal
                as="li"
                key={f.n}
                delay={i * 60}
                className={i === 0 ? 'border-t border-foreground/15' : ''}
              >
                <Link
                  href={f.href}
                  className="group grid gap-4 border-b border-foreground/15 py-10 transition-colors hover:border-accent lg:grid-cols-12 lg:gap-12 lg:py-14"
                >
                  <div className="lg:col-span-2">
                    <p className="font-display text-3xl text-accent/80 transition-colors group-hover:text-accent">
                      {f.n}
                    </p>
                    <p className="mt-2 eyebrow text-foreground/60">{f.kicker}</p>
                  </div>
                  <div className="lg:col-span-9">
                    <h2 className="font-serif text-2xl font-medium text-foreground sm:text-3xl lg:text-4xl">
                      {f.title}
                    </h2>
                    <p className="mt-4 max-w-2xl text-base leading-relaxed text-foreground/75 sm:text-lg">
                      {f.standfirst}
                    </p>
                    <span className="mt-6 inline-flex items-center text-xs font-medium uppercase tracking-[0.16em] text-foreground/70 transition-colors group-hover:text-accent">
                      Learn more
                      <span className="ml-2" aria-hidden>→</span>
                    </span>
                  </div>
                </Link>
              </ScrollReveal>
            ))}
          </ol>
        </div>
      </section>
    </>
  );
}
