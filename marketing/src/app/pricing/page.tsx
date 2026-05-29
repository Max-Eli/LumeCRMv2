/**
 * Pricing page.
 *
 * Three tiers, priced flat per workspace (NOT per location anymore —
 * that was the model on the pre-self-serve pricing). Starter +
 * Pro list a public price; Enterprise is custom. Add-ons cover
 * scale-up between tiers so a Starter that hires their fourth staffer
 * doesn't have to jump to Pro to keep operating.
 *
 * Tier shape mirrors the backend ``apps.tenants.plans`` catalog. Any
 * change here must propagate there (and to the receipts + Stripe
 * Products in the dashboard). Self-serve signup is shipping in a
 * later phase — for now every tier's CTA is "Book a demo" because
 * that's the entry path we can actually deliver.
 *
 * The page's main competitive argument lives in the "What's not in
 * the bill" section, which names what Boulevard charges $65/mo extra
 * for (Forms), what Aesthetic Record charges to let you export your
 * own patient data ($1,120), and Aesthetic Record's $399 setup fee.
 * Each is a specific dollar number customers can verify on the
 * competitor's own site.
 *
 * Card processing: Lumè processes card payments through Stripe
 * Connect (Starter tier) or a custom merchant integration (Pro /
 * Enterprise — Worldpay / Square / Heartland / Authorize.net etc.).
 * Specific Stripe rates are public (2.9% + 30¢, pass-through); custom
 * merchant rates depend on the spa's existing relationship.
 */

import Link from 'next/link';

import { PageHero } from '@/components/page-hero';
import { ScrollReveal } from '@/components/scroll-reveal';

import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Pricing',
  description:
    'Three tiers from $99/mo. BAA included. Clinical chart notes, packages, memberships, and gift cards at every level. Stripe card processing for Starter, custom merchant integration for Pro and Enterprise.',
};

interface Tier {
  name: string;
  /** Annual-billed monthly price, e.g. "$79". The annual discount is
   *  the headline number — most customers land on annual. */
  annualPrice: string;
  /** Month-to-month price, displayed underneath as the fallback. */
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
    name: 'Starter',
    annualPrice: '$79',
    monthlyPrice: '$99',
    unit: '/mo · billed annually',
    positioning: 'Annual billing. $99/mo billed monthly. Cancel anytime.',
    bestFor:
      'A solo injector, a two-chair shop, or any spa that just opened. The full medspa CRM at the lowest entry point.',
    cta: { href: '/demo', label: 'Get a demo' },
    features: [
      '1 location · 2 staff seats (add more for $20/mo each)',
      'Per-provider booking calendar with conflict detection',
      'Public online booking page',
      'Client records + tags + segmentation + notes',
      'Clinical chart notes (provider role only, HIPAA-grade audit)',
      'Intake + per-treatment consent forms, e-signed',
      'Packages, memberships, and gift cards (sell + redeem)',
      'Auto-invoicing with cash / check / Stripe card processing',
      '7 core reports (sales, no-show, AR aging, daily close-out, more)',
      'Customer portal (book, fill forms, view receipts)',
      'Audit log on every PHI read',
      '500 SMS reminders / month included',
      '2,000 emails / month included',
      'BAA included',
      'Email support, business hours',
    ],
  },
  {
    name: 'Pro',
    annualPrice: '$199',
    monthlyPrice: '$249',
    unit: '/mo · billed annually',
    positioning: 'Annual billing. $249/mo billed monthly. Migration included.',
    bestFor:
      'An established medspa with a full clinical team and a marketing motion. The tier most spas land on.',
    cta: { href: '/demo', label: 'Get a demo' },
    featured: true,
    features: [
      'Everything in Starter, plus:',
      '3 locations · 10 staff seats (add more for $20/mo each)',
      'Multi-provider day view + per-provider weekly schedules',
      'All 23+ reports across Financial / Staff / Guests / Operations',
      '2-way SMS inbox with saved replies + automated templates',
      'Email marketing — campaigns, audiences, automations',
      'Provider commissions tracking + payroll export',
      'Line-item discounts with manager-override credentials',
      'White-label branding on the booking page + login',
      'Per-tenant Twilio sender number (your own caller ID)',
      'Custom merchant account integration available',
      '1,500 SMS reminders / month included',
      '20,000 emails / month included',
      'Migration support included (Zenoti, Boulevard, Mindbody CSV)',
      'Priority email + chat support',
    ],
  },
  {
    name: 'Enterprise',
    annualPrice: 'Custom',
    monthlyPrice: '',
    unit: 'from $599/mo · custom contract',
    positioning: 'Annual billing. Volume + multi-location discounts.',
    bestFor:
      'Multi-location chains, franchise groups, and anyone whose needs don\'t fit a public tier.',
    cta: { href: '/demo', label: 'Talk to sales' },
    features: [
      'Everything in Pro, plus:',
      'Unlimited locations + staff',
      'Dedicated customer success manager + 99.9% SLA',
      'Named support channel + priority queue',
      'White-glove migration (multiple source platforms)',
      'White-glove custom merchant integration (any processor)',
      'Custom contract + DPA negotiation',
      '5,000 SMS + 100,000 emails / month included',
      'Custom integration work (priced per project)',
    ],
  },
];

const ADDONS = [
  { label: 'Extra staff seat', price: '+$20/mo', scope: 'Starter & Pro' },
  { label: 'Extra location', price: '+$75/mo', scope: 'Pro (up to +2)' },
  { label: 'Email pack — 5,000', price: '+$20/mo', scope: 'Starter' },
  { label: 'Email pack — 10,000', price: '+$15/mo', scope: 'Pro' },
  { label: 'SMS overage', price: '$0.04 / msg (Starter)', scope: 'Pay as you go, no monthly minimum' },
  { label: 'SMS overage', price: '$0.03 / msg (Pro)', scope: 'Pay as you go, no monthly minimum' },
];

const NOT_IN_BILL = [
  {
    label: 'A setup fee',
    body:
      "Aesthetic Record charges $399 just to get started. Standard Lumè onboarding is part of the contract — Pro tier additionally includes migration support from your current platform at no extra cost.",
  },
  {
    label: 'A premium tier for HIPAA',
    body:
      'The BAA is included at every level. Lumè runs on a single compliant architecture because there isn\'t a second one. Audit log on every PHI read, tenant isolation at the database, AWS under a signed BAA.',
  },
  {
    label: 'Forms or clinical notes as add-ons',
    body:
      "Boulevard charges $65/mo per location for Forms. Some platforms gate clinical chart notes to a top tier. Both ship in the $99 Starter — gating the engine of a medspa CRM is a tax on the customers who can least afford it.",
  },
  {
    label: 'A fee to export your own data',
    body:
      "Aesthetic Record charges $1,120 to export patient data. CSV export is one click on every report in Lumè, every month, no fee. The audit log is queryable too.",
  },
  {
    label: 'Per-seat pricing surprises',
    body:
      'Vagaro charges $10 per staff per month on top of base. Lumè is flat per workspace. Hiring another front-desk costs $20/mo with one click in /org/billing — no contract amendment, no sales call, prorated to your current period.',
  },
];

const INCLUDED = [
  'Clinical chart notes (provider-only, HIPAA-grade)',
  'Packages, memberships, gift cards (sell + redeem)',
  'E-signed intake + consent forms',
  'Online booking on a public page',
  'Customer portal (book, fill forms, pay)',
  'CSV export on every report',
  'Audit log queryable on request',
  'HIPAA Business Associate Agreement',
  'Stripe card processing on Starter; bring-your-own on Pro+',
  'Migration help (free on annual Pro)',
  'Cancel anytime — no annual lock-in',
  'Email support at every level',
];

export default function PricingPage() {
  return (
    <>
      <PageHero
        eyebrow="Pricing"
        headline={
          <>
            From $79/mo, billed annually.{' '}
            <span className="accent-italic">Nothing hidden underneath.</span>
          </>
        }
        standfirst="Three tiers, flat per workspace — never per seat. BAA included at every level. Clinical chart notes, packages, memberships, and gift cards ship at $99. Stripe card processing for Starter; bring your own merchant for Pro and above."
      />

      <PricingGrid />
      <AddonsBlock />
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
          All prices in USD. Annual billing is a 20% discount on monthly.
          Self-serve signup launching soon — for now every tier starts
          with a 30-minute demo on your real service menu.
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

// ── Add-ons (transparent line-item pricing) ────────────────────────

function AddonsBlock() {
  return (
    <section className="border-b border-border bg-foreground/[0.02]">
      <div className="mx-auto max-w-7xl px-6 lg:px-10 py-20 lg:py-28">
        <ScrollReveal>
          <p className="eyebrow text-foreground/60">Scale-up add-ons</p>
          <h2 className="mt-4 font-display text-3xl text-foreground sm:text-4xl">
            Grow into the next tier{' '}
            <span className="accent-italic">without crossing the next tier.</span>
          </h2>
          <p className="mt-4 max-w-2xl text-base leading-relaxed text-foreground/75">
            Buy a single extra staff seat, an extra location, or another
            5,000 emails — prorated to your current period and managed
            in /org/billing without a sales call.
          </p>
        </ScrollReveal>

        <ul className="mt-12 grid gap-x-8 gap-y-5 sm:grid-cols-2 lg:grid-cols-3">
          {ADDONS.map((addon, i) => (
            <ScrollReveal as="li" key={`${addon.label}-${addon.scope}`} delay={i * 60}>
              <div className="border-l-2 border-accent/40 pl-5">
                <p className="font-serif text-lg font-medium text-foreground">
                  {addon.label}
                </p>
                <p className="mt-1 font-mono tabular-nums text-sm text-accent">
                  {addon.price}
                </p>
                <p className="mt-1 text-xs text-foreground/60">
                  {addon.scope}
                </p>
              </div>
            </ScrollReveal>
          ))}
        </ul>
      </div>
    </section>
  );
}

// ── What's not in the bill ──────────────────────────────────────────

function NotInBill() {
  return (
    <section className="border-b border-border">
      <div className="mx-auto max-w-7xl px-6 lg:px-10 py-20 lg:py-28">
        <ScrollReveal>
          <p className="eyebrow text-foreground/60">What&apos;s not in the bill</p>
          <h2 className="mt-4 font-display text-4xl text-foreground sm:text-5xl">
            Five things other platforms{' '}
            <span className="accent-italic">charge for that we don&apos;t.</span>
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
    <section className="border-b border-border bg-foreground/[0.02]">
      <div className="mx-auto max-w-7xl px-6 lg:px-10 py-20 lg:py-28">
        <ScrollReveal>
          <p className="eyebrow text-foreground/60">Included at every level</p>
          <h2 className="mt-4 font-display text-3xl text-foreground sm:text-4xl">
            The engine of a medspa CRM.{' '}
            <span className="accent-italic">Ungated.</span>
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
    q: 'Is there a free trial?',
    a: "Self-serve trial signup is launching soon. For now every tier starts with a 30-minute demo on your real service menu and provider list, so you see the product configured for your spa before signing. When self-serve goes live, Starter will offer a 14-day trial with a credit card on file and the full Pro feature set during the trial period.",
  },
  {
    q: 'Can I add or remove staff mid-month?',
    a: "Yes. Add a staff seat for $20/mo in /org/billing — prorated to your current period and live within seconds. Remove a seat and the next invoice credits the unused time. No contract amendment, no sales call.",
  },
  {
    q: 'What happens if I add a location mid-term?',
    a: "Pro can add up to 2 extra locations at $75/mo each, prorated to your period and managed in /org/billing. Past 5 total locations, you're in Enterprise territory — that's a sales conversation about volume pricing and dedicated support.",
  },
  {
    q: 'Is the BAA actually included?',
    a: "Yes. The Business Associate Agreement is part of the standard customer contract at every tier — not a paid add-on, not a Premier-tier feature. See /baa for what it covers.",
  },
  {
    q: 'What do you charge for card processing?',
    a: "Starter: Stripe card processing at the standard pass-through rate (2.9% + 30¢ per charge), with no Lumè markup. Pro + Enterprise: choose Stripe OR bring your own merchant account (Worldpay, Square, Heartland, Authorize.net) — we integrate it for you as part of onboarding.",
  },
  {
    q: 'What about SMS overage?',
    a: "Starter includes 500/mo, Pro includes 1,500/mo, Enterprise includes 5,000/mo. Beyond that you pay per message: $0.04 on Starter, $0.03 on Pro, $0.025 on Enterprise. Email overage isn't a per-send fee — you buy more email packs ($20/5k on Starter; $15/10k on Pro) when you need them.",
  },
  {
    q: 'Can I migrate from another platform?',
    a: "Yes. We migrate from Zenoti, Mindbody, Boulevard, Vagaro, Aesthetic Record, and spreadsheets. Migration is scoped during your demo and typically completes in 2-4 weeks. Pro tier includes the migration; Enterprise includes white-glove migration across multiple source platforms.",
  },
  {
    q: 'What if I want to leave?',
    a: "You leave with everything you put in. CSV export is one click on every report. The audit log is queryable. Patient data export is free, every time. Cancel anytime with thirty days' notice — we won't bill the following month.",
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
