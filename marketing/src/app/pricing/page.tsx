/**
 * Pricing page.
 *
 * Three transparent tiers (Solo / Practice / Group) priced
 * deliberately between Mindbody's salon-grade entry and Zenoti's
 * enterprise tax. The Group tier is custom-quote because pricing
 * at 4+ locations depends on integration scope.
 *
 * The page's main competitive argument lives in the "What's not in
 * the bill" section, which names what Boulevard charges $65/mo extra
 * for (Forms), what Aesthetic Record charges to let you export your
 * own patient data ($1,120), and Aesthetic Record's $399 setup fee.
 * Each is a specific dollar number customers can verify on the
 * competitor's own site.
 *
 * Card processing: Lumè processes card payments through a licensed
 * third-party payment partner. Specific rates are quoted at
 * contracting; the marketing page intentionally doesn't publish a
 * rate because the deal structure depends on the customer's
 * card-present/card-not-present mix.
 */

import Link from 'next/link';

import { PageHero } from '@/components/page-hero';
import { ScrollReveal } from '@/components/scroll-reveal';

import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Pricing',
  description:
    'Three tiers from $249/mo per location. BAA included. Integrated payment processing. Memberships, marketing, e-signed consent forms, and all 22 reports at every level.',
};

interface Tier {
  name: string;
  annualPrice: string;
  monthlyPrice: string;
  unit: string;
  positioning: string;
  bestFor: string;
  cta: { href: string; label: string };
  features: string[];
  featured?: boolean;
}

const TIERS: Tier[] = [
  {
    name: 'Solo',
    annualPrice: '$249',
    monthlyPrice: '$279',
    unit: '/mo · per location',
    positioning: 'Annual billing. $279/mo billed monthly.',
    bestFor:
      'An independent medspa running out of one location with a small provider team.',
    cta: { href: '/demo', label: 'Get a demo' },
    features: [
      '1 location · up to 5 bookable providers',
      'Unlimited front-desk and manager seats',
      'Per-provider booking calendar with conflict detection',
      'Online booking with deposit',
      'Client charts with treatment history and provider notes',
      'E-signed consent forms (intake + per-treatment)',
      'Integrated card processing + cash/check tracking',
      'Invoicing, daily close-out, 60-day reopen window',
      'All 22 financial, staff, guest, and operations reports',
      'Retail product sales at checkout',
      'Waitlist on the public booking page',
      'Append-only audit log access',
      '200 SMS reminders / month included',
      'BAA included',
      'Email support (business hours)',
    ],
  },
  {
    name: 'Practice',
    annualPrice: '$449',
    monthlyPrice: '$499',
    unit: '/mo · per location',
    positioning: 'Annual billing. $499/mo billed monthly.',
    bestFor:
      'An established medspa scaling across two or three locations with an unlimited bookable team.',
    cta: { href: '/demo', label: 'Get a demo' },
    featured: true,
    features: [
      'Everything in Solo, plus:',
      'Up to 3 locations',
      'Unlimited bookable providers',
      'Org-level multi-location dashboard',
      'Memberships and pre-paid treatment packages',
      'Gift cards',
      'Provider commission tracking',
      'Staff time tracking (clock-in/out)',
      'Marketing automation (birthday, win-back, treatment-cycle)',
      'Customer email and SMS marketing campaigns',
      '1,000 SMS reminders / month included',
      'Priority onboarding',
      'Email and chat support',
    ],
  },
  {
    name: 'Group',
    annualPrice: 'Custom',
    monthlyPrice: '',
    unit: '4+ locations',
    positioning: 'Volume pricing and a dedicated onboarding manager.',
    bestFor:
      'Multi-location groups, franchised brands, and chains running across more than three sites.',
    cta: { href: '/demo', label: 'Talk to sales' },
    features: [
      'Everything in Practice, plus:',
      'Unlimited locations',
      'Dedicated onboarding manager',
      'Custom integrations (QuickBooks Online, Zapier, custom connectors)',
      'SOC 2 Type II attestation share on request',
      'Custom security review on request',
      'Volume SMS pricing',
      'Migration assistance for 3+ source platforms',
    ],
  },
];

const NOT_IN_BILL = [
  {
    label: 'A setup fee',
    body:
      "Aesthetic Record charges $399 just to get started. Lumè onboarding and migration from your current platform are part of the standard contract — no separate setup line on the invoice.",
  },
  {
    label: 'A premium tier for HIPAA',
    body:
      'The BAA is included at every level. Lumè runs on a single compliant architecture because there isn\'t a second one.',
  },
  {
    label: 'Forms as an add-on',
    body:
      'Boulevard charges $65/mo per location for Forms. E-signed consent is the most-used feature in a medspa CRM. It\'s included.',
  },
  {
    label: 'A fee to export your own data',
    body:
      "Aesthetic Record charges $1,120 to export patient data. CSV export is one click on every report in Lumè, every month, no fee. The audit log is queryable too.",
  },
  {
    label: 'An annual contract lock-in',
    body:
      'Monthly is monthly. Annual is a 10% discount on monthly. Cancel for convenience with thirty days\' notice and we will not bill the following month.',
  },
];

const INCLUDED = [
  'Unlimited staff seats per location',
  'Unlimited client records',
  'Unlimited form submissions',
  'Unlimited invoices',
  'All 22 reports',
  'CSV export on every report',
  'Audit log queryable on request',
  'HIPAA Business Associate Agreement',
  'Integrated card payment processing',
  'Implementation + onboarding',
  'Migration from your current platform',
  'Email support, business hours',
];

export default function PricingPage() {
  return (
    <>
      <PageHero
        eyebrow="Pricing"
        headline={
          <>
            From $249/mo per location.{' '}
            <span className="accent-italic">Nothing hidden underneath.</span>
          </>
        }
        standfirst="Three tiers, all priced per location instead of per seat. BAA included at every level. Integrated payment processing through a licensed partner. The features Boulevard sells as add-ons are included here."
      />

      <PricingGrid />
      <NotInBill />
      <IncludedEverywhere />
      <PricingFaq />
      <PricingCta />
    </>
  );
}

// ── Tier grid ───────────────────────────────────────────────────────

function PricingGrid() {
  return (
    <section className="border-b border-border">
      <div className="mx-auto max-w-7xl px-6 lg:px-10 py-20 lg:py-28">
        <div className="grid gap-8 lg:grid-cols-3 lg:gap-6">
          {TIERS.map((tier, i) => (
            <ScrollReveal key={tier.name} delay={i * 100}>
              <TierCard tier={tier} />
            </ScrollReveal>
          ))}
        </div>

        <p className="mt-12 text-center text-sm text-foreground/60">
          All prices in USD. Annual billing is a 10% discount on monthly.
          SMS overage at telecom pass-through cost; no per-message
          platform fee.
        </p>
      </div>
    </section>
  );
}

function TierCard({ tier }: { tier: Tier }) {
  const isCustom = tier.annualPrice === 'Custom';
  return (
    <div
      className={`flex h-full flex-col border ${
        tier.featured
          ? 'border-foreground bg-foreground/[0.02]'
          : 'border-foreground/20'
      } p-8 lg:p-9`}
    >
      <div className="flex items-baseline justify-between">
        <h2 className="font-serif text-2xl font-medium text-foreground">
          {tier.name}
        </h2>
        {tier.featured ? (
          <span className="eyebrow text-accent">Most chosen</span>
        ) : null}
      </div>

      <div className="mt-6">
        {isCustom ? (
          <p className="font-display text-5xl text-foreground">
            {tier.annualPrice}
          </p>
        ) : (
          <p className="font-display text-5xl text-foreground">
            {tier.annualPrice}
            <span className="ml-1 text-xl text-foreground/60">{tier.unit}</span>
          </p>
        )}
        <p className="mt-3 text-sm text-foreground/60">{tier.positioning}</p>
      </div>

      <p className="mt-6 text-sm leading-relaxed text-foreground/75">
        {tier.bestFor}
      </p>

      <ul className="mt-8 space-y-2.5 text-sm text-foreground/80">
        {tier.features.map((feature) => (
          <li key={feature} className="flex items-start gap-2.5">
            <span
              aria-hidden
              className="mt-2 inline-block size-1 shrink-0 rounded-full bg-accent"
            />
            <span>{feature}</span>
          </li>
        ))}
      </ul>

      <Link
        href={tier.cta.href}
        className={`mt-10 inline-flex h-12 items-center justify-center rounded-full px-6 text-sm font-medium uppercase tracking-[0.16em] transition-colors ${
          tier.featured
            ? 'bg-foreground text-background hover:bg-foreground/90'
            : 'border border-foreground text-foreground hover:bg-foreground hover:text-background'
        }`}
      >
        {tier.cta.label}
      </Link>
    </div>
  );
}

// ── What's not in the bill ──────────────────────────────────────────

function NotInBill() {
  return (
    <section className="border-b border-border bg-foreground/[0.02]">
      <div className="mx-auto max-w-7xl px-6 lg:px-10 py-20 lg:py-28">
        <ScrollReveal>
          <p className="eyebrow text-foreground/60">What's not in the bill</p>
          <h2 className="mt-4 font-display text-4xl text-foreground sm:text-5xl">
            Five things other platforms{' '}
            <span className="accent-italic">charge for that we don't.</span>
          </h2>
        </ScrollReveal>

        <ol className="mt-16 grid gap-x-12 gap-y-10 lg:grid-cols-2">
          {NOT_IN_BILL.map((item, i) => (
            <ScrollReveal as="li" key={item.label} delay={i * 80}>
              <div className="border-l-2 border-accent/40 pl-5">
                <div className="flex items-baseline gap-3">
                  <span className="font-display text-2xl text-accent">
                    {String(i + 1).padStart(2, '0')}
                  </span>
                  <h3 className="font-serif text-xl font-medium text-foreground">
                    {item.label}
                  </h3>
                </div>
                <p className="mt-3 text-base leading-relaxed text-foreground/75">
                  {item.body}
                </p>
              </div>
            </ScrollReveal>
          ))}
        </ol>
      </div>
    </section>
  );
}

// ── Included everywhere ─────────────────────────────────────────────

function IncludedEverywhere() {
  return (
    <section className="border-b border-border">
      <div className="mx-auto max-w-7xl px-6 lg:px-10 py-20 lg:py-28">
        <ScrollReveal>
          <p className="eyebrow text-foreground/60">Included at every level</p>
          <h2 className="mt-4 font-display text-3xl text-foreground sm:text-4xl">
            No add-ons.{' '}
            <span className="accent-italic">No tier-locked features.</span>
          </h2>
          <ul className="mt-10 grid gap-x-8 gap-y-4 sm:grid-cols-2 lg:grid-cols-3">
            {INCLUDED.map((item) => (
              <li
                key={item}
                className="flex items-start gap-2 text-sm text-foreground/80"
              >
                <span
                  aria-hidden
                  className="mt-2 inline-block size-1 shrink-0 rounded-full bg-accent"
                />
                {item}
              </li>
            ))}
          </ul>
        </ScrollReveal>
      </div>
    </section>
  );
}

// ── FAQ ─────────────────────────────────────────────────────────────

const FAQS = [
  {
    q: 'What happens if I add a location mid-term?',
    a: "New locations are added to the next monthly invoice at the per-location rate of your tier. Close a location and it drops off the following invoice. No contract amendment needed.",
  },
  {
    q: 'Is the BAA actually included?',
    a: "Yes. The Business Associate Agreement is part of the standard customer contract at every tier — not a paid add-on, not a Premier-tier feature. See /baa for what it covers.",
  },
  {
    q: 'What do you charge for card processing?',
    a: "Card payments process through Lumè's licensed payment partner inside the appointment flow. Specific rates are quoted at contracting based on your card-present and card-not-present mix. There is no separate platform-percentage fee outside the rates set out in your Order Form.",
  },
  {
    q: 'What about SMS overage?',
    a: "Each tier includes a monthly SMS allocation. Beyond that, you pay telecom pass-through cost — typically under a cent per message, with no Lumè markup or per-message platform fee.",
  },
  {
    q: 'Do you offer a free trial?',
    a: "No free trial because every customer goes through implementation and a signed BAA before a tenant is provisioned. The 30-minute demo runs on your real service menu and provider list, so you see the product configured for your spa before signing.",
  },
  {
    q: 'Can I migrate from another platform?',
    a: "Yes. We migrate from Zenoti, Mindbody, Boulevard, Vagaro, Aesthetic Record, and spreadsheets. Migration is scoped on the export shape during your demo and typically completes in 2-4 weeks.",
  },
  {
    q: 'What if I want to leave?',
    a: "You leave with everything you put in. CSV export is one click on every report. The audit log is queryable. Patient data export is free, every time. No data-hostage fee.",
  },
];

function PricingFaq() {
  return (
    <section className="border-b border-border bg-foreground/[0.02]">
      <div className="mx-auto max-w-7xl px-6 lg:px-10 py-20 lg:py-28">
        <ScrollReveal>
          <p className="eyebrow text-foreground/60">Questions we hear</p>
          <h2 className="mt-4 font-display text-3xl text-foreground sm:text-4xl">
            Pricing FAQ
          </h2>
        </ScrollReveal>

        <dl className="mt-12 max-w-4xl space-y-0">
          {FAQS.map((faq, i) => (
            <ScrollReveal
              key={faq.q}
              delay={i * 50}
              className={i === 0 ? 'border-t border-foreground/15' : ''}
            >
              <div className="border-b border-foreground/15 py-6 lg:py-7">
                <dt className="font-serif text-lg font-medium text-foreground">
                  {faq.q}
                </dt>
                <dd className="mt-3 text-base leading-relaxed text-foreground/75">
                  {faq.a}
                </dd>
              </div>
            </ScrollReveal>
          ))}
        </dl>

        {/* FAQPage structured data — eligible for SERP rich-result
            treatment in Google. */}
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{
            __html: JSON.stringify({
              '@context': 'https://schema.org',
              '@type': 'FAQPage',
              mainEntity: FAQS.map((faq) => ({
                '@type': 'Question',
                name: faq.q,
                acceptedAnswer: { '@type': 'Answer', text: faq.a },
              })),
            }),
          }}
        />
      </div>
    </section>
  );
}

// ── CTA ─────────────────────────────────────────────────────────────

function PricingCta() {
  return (
    <section>
      <div className="mx-auto max-w-7xl px-6 lg:px-10 py-20 lg:py-28">
        <ScrollReveal>
          <div className="flex flex-col items-start gap-6 border-t border-foreground/15 pt-12 lg:flex-row lg:items-center lg:justify-between">
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
  );
}
