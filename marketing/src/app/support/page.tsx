/**
 * /support — Customer support page.
 *
 * Structure:
 *   1. Hero — direct, no fluff. "We respond." with the SLA by tier.
 *   2. Contact channels — email by category (support, security, billing)
 *   3. Support by plan — what each tier gets
 *   4. Common questions — self-serve answers to the most frequent asks
 *   5. Closing CTA — demo for prospects, support email for customers
 *
 * SEO targets:
 *   - "Lumè CRM support"
 *   - "medspa CRM support"
 *   - "Lumè contact"
 *
 * FAQ schema for AI search engines — common operational questions
 * with direct answers.
 */

import Link from 'next/link';
import type { Metadata } from 'next';

import { PageHero } from '@/components/page-hero';
import { ScrollReveal } from '@/components/scroll-reveal';
import { SITE_URL_ASCII, jsonLd } from '@/lib/seo';

export const metadata: Metadata = {
  title: 'Support',
  description:
    'Contact Lumè CRM support. Email response within one business day for all plans. Priority email and chat for Pro. Named support channel for Enterprise. BAA and security questions answered directly.',
};

const FAQ_SCHEMA = {
  '@context': 'https://schema.org',
  '@type': 'FAQPage',
  mainEntity: [
    {
      '@type': 'Question',
      name: 'How do I contact Lumè CRM support?',
      acceptedAnswer: {
        '@type': 'Answer',
        text: 'Email support@lumècrm.com for product support. For security and HIPAA questions, email security@lumècrm.com. For billing, email billing@lumècrm.com. All plans receive a response within one business day. Pro plans receive priority email and chat support.',
      },
    },
    {
      '@type': 'Question',
      name: 'What is Lumè CRM\'s support response time?',
      acceptedAnswer: {
        '@type': 'Answer',
        text: 'All plans receive a response within one business day (Monday–Friday, 9am–6pm ET). Pro plans receive priority support with faster response times and access to live chat during business hours. Enterprise plans have a dedicated customer success manager and a 99.9% SLA.',
      },
    },
    {
      '@type': 'Question',
      name: 'How do I migrate from Mindbody, Boulevard, or Vagaro to Lumè?',
      acceptedAnswer: {
        '@type': 'Answer',
        text: 'Migration support is included in the Pro annual plan. Email support@lumècrm.com with your current platform and we will scope the migration and provide a timeline. Typical migrations from Mindbody, Boulevard, Vagaro, or Aesthetic Record take 2–4 weeks. We import your service catalog, client records, and appointment history.',
      },
    },
    {
      '@type': 'Question',
      name: 'Where do I send HIPAA or BAA questions?',
      acceptedAnswer: {
        '@type': 'Answer',
        text: 'Email security@lumècrm.com for all HIPAA compliance questions, BAA inquiries, audit documentation, and vendor questionnaires. We respond within one business day and can share architecture documentation and control mappings for your compliance team.',
      },
    },
    {
      '@type': 'Question',
      name: 'How do I cancel my Lumè subscription?',
      acceptedAnswer: {
        '@type': 'Answer',
        text: 'Email billing@lumècrm.com to cancel. We do not require a phone call or a lengthy offboarding process. Your data is available for export at any time before and after cancellation — CSV export is included at every tier at no charge.',
      },
    },
  ],
};

const CONTACT_CHANNELS = [
  {
    label: 'Product support',
    email: 'support@lumècrm.com',
    emailAscii: 'support@xn--lumcrm-5ua.com',
    description: 'Questions about features, configuration, billing, onboarding, and migration.',
  },
  {
    label: 'Security & compliance',
    email: 'security@lumècrm.com',
    emailAscii: 'security@xn--lumcrm-5ua.com',
    description: 'HIPAA documentation, BAA requests, vendor questionnaires, audit scope.',
  },
  {
    label: 'Billing',
    email: 'billing@lumècrm.com',
    emailAscii: 'billing@xn--lumcrm-5ua.com',
    description: 'Plan changes, invoices, cancellation, payment methods.',
  },
];

const PLAN_SUPPORT = [
  {
    tier: 'Starter',
    price: 'from $79/mo',
    sla: 'Response within 1 business day',
    channels: 'Email (support@lumècrm.com)',
    hours: 'Monday–Friday, 9am–6pm ET',
    extras: [],
  },
  {
    tier: 'Pro',
    price: 'from $199/mo',
    sla: 'Priority response · typically same business day',
    channels: 'Priority email + live chat during business hours',
    hours: 'Monday–Friday, 9am–6pm ET',
    extras: [
      'Migration support included',
      'Onboarding call with your team',
      'Priority queue for urgent issues',
    ],
    featured: true,
  },
  {
    tier: 'Enterprise',
    price: 'Custom',
    sla: '99.9% uptime SLA · named support contact',
    channels: 'Named channel · dedicated CSM · priority queue',
    hours: 'Extended hours, negotiated per contract',
    extras: [
      'Dedicated customer success manager',
      'White-glove migration and onboarding',
      'Architecture review and compliance documentation',
      'Custom SLA negotiation',
    ],
  },
];

const COMMON_QUESTIONS = [
  {
    q: 'How do I get my data out of my current platform?',
    a: 'Most platforms (Mindbody, Vagaro, Boulevard, Aesthetic Record) allow CSV export of client records, service catalogs, and appointment history through their reporting or admin section. Export those before your migration call — we will tell you exactly which files to download. If your platform charges for export, document that cost; it is worth knowing before you sign.',
  },
  {
    q: 'How long does onboarding take?',
    a: 'A typical medspa onboarding takes two to four weeks from contract signature to go-live. Week one: service catalog and staff setup. Week two: client import and consent form configuration. Weeks three to four: staff training and parallel-run testing. Enterprise onboardings with multi-platform migration take four to eight weeks.',
  },
  {
    q: 'Can I bring my own card processor?',
    a: 'Yes — Pro and Enterprise plans support custom merchant account integration. Worldpay, Square, Heartland, Authorize.net, and others are supported. Starter uses Stripe Connect (2.9% + 30¢, standard Stripe rates, no Lumè markup).',
  },
  {
    q: 'How does the AI SMS agent work?',
    a: 'The AI SMS agent (Pro and Enterprise) responds to inbound texts on your spa\'s toll-free number around the clock. It checks real-time availability, matches the service to an eligible provider, proposes appointment times, and books on the customer\'s confirmation. Staff can pause it per-conversation from the inbox at any time. It escalates to staff immediately for clinical questions, payment disputes, or any conversation that needs a human.',
  },
  {
    q: 'Where do I find my BAA?',
    a: 'Your Business Associate Agreement is included in your standard contract and is countersigned at time of signup. If you need a copy for a compliance audit or your legal team, email security@lumècrm.com and we will provide a signed copy within one business day.',
  },
  {
    q: 'What happens to my data if I cancel?',
    a: 'You leave with everything. CSV export is one click on every report at every tier — no fee, no request required, no waiting period. We retain data for 90 days after cancellation in case you need to export anything you missed. After 90 days, data is deleted per our retention policy.',
  },
];

export default function SupportPage() {
  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: jsonLd(FAQ_SCHEMA) }}
      />

      <PageHero
        eyebrow="Support"
        headline={
          <>
            We respond within{' '}
            <span className="accent-italic">one business day.</span>
          </>
        }
        standfirst="Every plan includes email support. Pro gets priority response and live chat. Enterprise gets a dedicated contact and a 99.9% SLA. Send us a specific question and we'll send back a specific answer."
      />

      {/* Contact channels */}
      <section className="border-b border-border">
        <div className="mx-auto max-w-7xl px-6 lg:px-10 py-16 lg:py-20">
          <ScrollReveal>
            <div className="grid gap-6 sm:grid-cols-3">
              {CONTACT_CHANNELS.map((c) => (
                <div
                  key={c.label}
                  className="rounded-lg border border-border bg-card p-6"
                >
                  <p className="eyebrow text-foreground/60 text-xs">{c.label}</p>
                  <a
                    href={`mailto:${c.emailAscii}`}
                    className="mt-2 block font-medium text-accent hover:text-foreground transition-colors text-sm break-all"
                  >
                    {c.email}
                  </a>
                  <p className="mt-3 text-sm leading-relaxed text-foreground/70">
                    {c.description}
                  </p>
                </div>
              ))}
            </div>
          </ScrollReveal>
        </div>
      </section>

      {/* Support by plan */}
      <section className="border-b border-border">
        <div className="mx-auto max-w-7xl px-6 lg:px-10 py-16 lg:py-24">
          <ScrollReveal>
            <p className="eyebrow text-foreground/60">By plan</p>
            <h2 className="mt-3 font-serif text-3xl font-medium text-foreground">
              What your tier includes.
            </h2>
          </ScrollReveal>

          <div className="mt-10 grid gap-6 lg:grid-cols-3">
            {PLAN_SUPPORT.map((p, i) => (
              <ScrollReveal key={p.tier} delay={i * 80}>
                <div className={`h-full rounded-lg border p-6 ${
                  p.featured
                    ? 'border-foreground/30 bg-card ring-1 ring-foreground/10'
                    : 'border-border bg-card'
                }`}>
                  <div className="flex items-baseline gap-2">
                    <p className="font-serif text-xl font-medium text-foreground">{p.tier}</p>
                    {p.featured && (
                      <span className="rounded-full bg-foreground px-2 py-0.5 text-[9px] font-medium uppercase tracking-wide text-background">
                        Most chosen
                      </span>
                    )}
                  </div>
                  <p className="mt-0.5 text-xs text-foreground/50">{p.price}</p>

                  <div className="mt-5 space-y-3 text-sm">
                    <div>
                      <span className="text-[10px] uppercase tracking-wide text-foreground/50">SLA</span>
                      <p className="mt-1 text-foreground/85">{p.sla}</p>
                    </div>
                    <div>
                      <span className="text-[10px] uppercase tracking-wide text-foreground/50">Channels</span>
                      <p className="mt-1 text-foreground/85">{p.channels}</p>
                    </div>
                    <div>
                      <span className="text-[10px] uppercase tracking-wide text-foreground/50">Hours</span>
                      <p className="mt-1 text-foreground/85">{p.hours}</p>
                    </div>
                    {p.extras.length > 0 && (
                      <div>
                        <span className="text-[10px] uppercase tracking-wide text-foreground/50">Included</span>
                        <ul className="mt-1 space-y-1">
                          {p.extras.map((e) => (
                            <li key={e} className="flex items-start gap-1.5 text-foreground/80">
                              <span className="mt-1.5 size-1 shrink-0 rounded-full bg-accent" aria-hidden />
                              {e}
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </div>
                </div>
              </ScrollReveal>
            ))}
          </div>
        </div>
      </section>

      {/* Common questions */}
      <section className="border-b border-border">
        <div className="mx-auto max-w-3xl px-6 lg:px-10 py-16 lg:py-24">
          <ScrollReveal>
            <p className="eyebrow text-foreground/60">Common questions</p>
            <h2 className="mt-3 font-serif text-3xl font-medium text-foreground">
              Quick answers.
            </h2>
          </ScrollReveal>

          <div className="mt-10 space-y-10">
            {COMMON_QUESTIONS.map((item, i) => (
              <ScrollReveal key={item.q} delay={i * 60}>
                <div>
                  <h3 className="text-base font-semibold text-foreground">{item.q}</h3>
                  <p className="mt-2 text-sm leading-relaxed text-foreground/75">{item.a}</p>
                </div>
              </ScrollReveal>
            ))}
          </div>
        </div>
      </section>

      {/* Closing CTA */}
      <section>
        <div className="mx-auto max-w-7xl px-6 lg:px-10 py-16 lg:py-24">
          <ScrollReveal>
            <div className="lg:grid lg:grid-cols-12 lg:gap-8 lg:items-center">
              <div className="lg:col-span-7">
                <p className="eyebrow text-foreground/60">Still have questions?</p>
                <h2 className="mt-3 font-serif text-4xl font-medium text-foreground">
                  Send us a specific question.
                </h2>
                <p className="mt-4 text-base leading-relaxed text-foreground/75 max-w-xl">
                  We don&apos;t route to a bot first. Email goes to the team.
                  If your question is about onboarding, migration, compliance, or
                  a feature you can&apos;t find — just ask.
                </p>
              </div>
              <div className="mt-10 lg:col-span-5 lg:mt-0 lg:text-right space-y-3">
                <a
                  href="mailto:support@xn--lumcrm-5ua.com"
                  className="inline-flex h-12 items-center rounded-full bg-foreground px-8 text-sm font-medium uppercase tracking-[0.16em] text-background hover:bg-foreground/90 transition-colors"
                >
                  Email support
                </a>
                <p className="text-xs text-foreground/50 block">
                  Or{' '}
                  <Link
                    href="/demo"
                    className="text-accent hover:text-foreground underline underline-offset-2 transition-colors"
                  >
                    request a demo
                  </Link>{' '}
                  if you&apos;re evaluating Lumè for the first time.
                </p>
              </div>
            </div>
          </ScrollReveal>
        </div>
      </section>
    </>
  );
}
