/**
 * Home page.
 *
 * Voice: confident product-marketing, modeled on Boulevard, Zenoti,
 * Podium. Direct value props, specific feature claims, no literary
 * affectation. Every section earns its place by adding business
 * substance — not magazine vibe.
 *
 * Sections (top → bottom):
 *
 *   1. Hero          — direct headline, one-line subhead, CTA, calendar mock
 *   2. Capabilities  — six feature rows, each paired with a product mock
 *   3. Why Lumè      — three concrete reasons we exist (vs. competitors)
 *   4. Compliance    — HIPAA / SOC 2 strip linking to /security
 *   5. Demo CTA      — direct, action-oriented closing
 */

import Link from 'next/link';

import { Marquee } from '@/components/marquee';
import { Parallax } from '@/components/parallax';
import { ProductFrame } from '@/components/product-frame';
import {
  CalendarMock,
  ChartMock,
  FormMock,
  InvoiceMock,
  LocationsMock,
  ReportsMock,
} from '@/components/product-mocks';
import { ScrollReveal } from '@/components/scroll-reveal';
import { SectionEyebrow } from '@/components/section-eyebrow';
import { jsonLd, softwareApplicationJsonLd } from '@/lib/seo';

export default function HomePage() {
  return (
    <>
      {/* Home-page structured data: tells search engines this is a
          medspa-vertical B2B SaaS product, not a generic website.
          Eligible for Google's product knowledge-graph treatment. */}
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: jsonLd(softwareApplicationJsonLd()) }}
      />
      <Hero />
      <CapabilityStrip />
      <Capabilities />
      <WhyLume />
      <Compliance />
      <DemoCta />
    </>
  );
}

// ── 1. Hero ─────────────────────────────────────────────────────────────

function Hero() {
  return (
    <section className="relative overflow-hidden border-b border-border">
      <div className="mx-auto max-w-7xl px-6 lg:px-10 pt-16 pb-20 lg:pt-24 lg:pb-28">
        <div className="grid gap-14 lg:grid-cols-12 lg:gap-12">
          <div className="lg:col-span-7">
            <p className="hero-rise eyebrow text-foreground/60" style={{ animationDelay: '0ms' }}>
              The CRM for medical spas
            </p>
            <h1
              className="hero-rise mt-6 font-display text-5xl text-foreground sm:text-6xl lg:text-7xl xl:text-[5.25rem]"
              style={{ animationDelay: '120ms' }}
            >
              Run your medspa from{' '}
              <span className="accent-italic">one platform.</span>
            </h1>
            <p
              className="hero-rise mt-8 max-w-2xl text-lg leading-relaxed text-foreground/80 sm:text-xl"
              style={{ animationDelay: '260ms' }}
            >
              Booking, charts, consent, integrated payments, and
              twenty-two live reports. HIPAA-compliant. BAA included.
              Implementation in two to four weeks.
            </p>
            <div
              className="hero-rise mt-10 flex flex-wrap items-center gap-6"
              style={{ animationDelay: '380ms' }}
            >
              <Link
                href="/demo"
                className="inline-flex h-12 items-center rounded-full bg-foreground px-7 text-sm font-medium uppercase tracking-[0.16em] text-background hover:bg-foreground/90 transition-colors"
              >
                Start 30-day free trial
              </Link>
              <Link
                href="/pricing"
                className="text-sm font-medium uppercase tracking-[0.16em] text-foreground/75 hover:text-foreground transition-colors"
              >
                See pricing →
              </Link>
            </div>
            {/* Single short line under the CTA so prospects know
                what the trial actually means before they click. */}
            <p
              className="hero-rise mt-5 text-sm text-foreground/60"
              style={{ animationDelay: '440ms' }}
            >
              Full Pro features for 30 days. No charge until day 31. Cancel anytime.
            </p>

            {/* Three differentiators a medspa owner will scan in
                a single second. Each is a fact, not a turn of phrase. */}
            <ul
              className="hero-rise mt-12 grid grid-cols-1 gap-4 text-sm text-foreground/75 sm:grid-cols-3"
              style={{ animationDelay: '500ms' }}
            >
              <li className="border-l-2 border-accent/50 pl-4">
                <span className="block font-serif text-base font-medium text-foreground">BAA in every contract</span>
                HIPAA isn't an upgrade tier.
              </li>
              <li className="border-l-2 border-accent/50 pl-4">
                <span className="block font-serif text-base font-medium text-foreground">Integrated payments</span>
                Card, cash, and check inside the appointment flow.
              </li>
              <li className="border-l-2 border-accent/50 pl-4">
                <span className="block font-serif text-base font-medium text-foreground">Built for medspas</span>
                Not a salon platform with extras bolted on.
              </li>
            </ul>
          </div>

          <div className="hero-rise lg:col-span-5" style={{ animationDelay: '600ms' }}>
            <Parallax speed={0.06}>
              <ProductFrame url="/calendar" aspect="aspect-[5/6] sm:aspect-[16/12] lg:aspect-[5/6]">
                <CalendarMock />
              </ProductFrame>
              <p className="mt-4 text-center text-[11px] uppercase tracking-[0.18em] text-foreground/55">
                Multi-provider booking · Manhattan location
              </p>
            </Parallax>
          </div>
        </div>
      </div>
    </section>
  );
}

// ── 2. Capability strip (was: literary marquee) ─────────────────────────

const CAPABILITY_PHRASES = [
  'Booking',
  'Client charts',
  'Consent forms',
  'Payments',
  '22 reports',
  'Multi-location',
  'HIPAA-compliant',
  'Tenant isolation',
  'Audit logging',
  'No card-processing markup',
];

function CapabilityStrip() {
  return (
    <section className="border-b border-border bg-foreground/[0.02] py-8 lg:py-10">
      <Marquee phrases={CAPABILITY_PHRASES} variant="display" />
    </section>
  );
}

// ── 3. Capabilities ────────────────────────────────────────────────────

interface CapabilityRow {
  n: string;
  label: string;
  title: string;
  body: string;
  bullets: string[];
  href: string;
  url: string;
  Mock: React.ComponentType;
}

const CAPABILITIES: CapabilityRow[] = [
  {
    n: '01',
    label: 'Booking',
    title: 'A calendar that knows who works where.',
    body:
      "Each provider gets their own column. Drag to reschedule. Click to take payment. Unsigned consent is flagged before the client walks in.",
    bullets: [
      'Per-provider, per-location columns',
      'Drag-to-reschedule with conflict detection',
      'Online booking with deposit-on-book',
      'Automated SMS + email reminders',
    ],
    href: '/features/booking',
    url: '/calendar',
    Mock: CalendarMock,
  },
  {
    n: '02',
    label: 'Client charts',
    title: 'The whole client, on one page.',
    body:
      "Treatment history, allergies, signed consents, outstanding paperwork, invoice history, provider notes. Two clicks from the calendar. The same record across every location.",
    bullets: [
      'Searchable across all locations',
      'Treatment history with outcome tracking',
      'Provider-only notes thread',
      'Pending forms surfaced where needed',
    ],
    href: '/features/charts',
    url: '/clients/sarah-chen',
    Mock: ChartMock,
  },
  {
    n: '03',
    label: 'Consent forms',
    title: 'Consent forms that survive an audit.',
    body:
      "Intake signs once. Per-treatment consent signs every visit. One tokenized link. Every signature captures IP and user-agent. The template is snapshotted at signing, so next month's edits never rewrite last month's record.",
    bullets: [
      'Version-snapshotted at signing',
      'Tokenized fill links (no login required)',
      'Auto-assigned per service or per visit',
      'Audit trail with IP, user-agent, timestamp',
    ],
    href: '/features/forms',
    url: '/sign/9j4k…',
    Mock: FormMock,
  },
  {
    n: '04',
    label: 'Payments',
    title: 'Invoicing and integrated payments in one flow.',
    body:
      "Card, cash, and check go in with a payment reference. Card processing runs through our licensed payment partner inside the appointment flow — no separate terminal to reconcile against. Daily close-out splits totals by method. Sixty-day reopen window.",
    bullets: [
      'Owner-only 60-day reopen window',
      'Per-payment-method daily close-out',
      'Tax handled per service line item',
      'Integrated card processing through a licensed partner',
    ],
    href: '/features/payments',
    url: '/appointments/4218/invoice',
    Mock: InvoiceMock,
  },
  {
    n: '05',
    label: 'Reports',
    title: 'The reports your accountant keeps asking for.',
    body:
      'Twenty-two of them: daily close-out, AR aging, revenue by service or provider or location, no-show rate, top spenders, booking lead time. Live data. Every CSV export sits behind a HIPAA confirm and is audit-logged.',
    bullets: [
      '22 pre-built reports',
      'Live data, no nightly refresh delay',
      'CSV export with PHI confirmation',
      'Audit-logged on every run',
    ],
    href: '/features/reports',
    url: '/reports/financial/sales-by-date-range',
    Mock: ReportsMock,
  },
  {
    n: '06',
    label: 'Multi-location',
    title: 'Open a second location without re-onboarding.',
    body:
      "Each site gets its own calendar, staff schedule, and reporting filter. An org-level dashboard shows every location alongside cross-location revenue. The location switcher only appears for staff who span more than one.",
    bullets: [
      'Per-location calendars + staff schedules',
      'Org-level locations dashboard',
      'Per-location revenue + reporting filters',
      'Single sign-on across sites',
    ],
    href: '/features/multi-location',
    url: '/org/dashboard',
    Mock: LocationsMock,
  },
];

function Capabilities() {
  return (
    <section>
      <div className="mx-auto max-w-7xl px-6 lg:px-10 py-24 lg:py-32">
        <ScrollReveal>
          <SectionEyebrow
            eyebrow="The platform"
            headline={
              <>
                Six capabilities,{' '}
                <span className="accent-italic">every one for medspas.</span>
              </>
            }
            description="Not a salon tool with the word 'aesthetics' pasted on top."
          />
        </ScrollReveal>

        <div className="mt-20 space-y-24 lg:space-y-32">
          {CAPABILITIES.map((c, i) => (
            <CapabilityRow key={c.n} cap={c} flip={i % 2 === 1} />
          ))}
        </div>
      </div>
    </section>
  );
}

function CapabilityRow({ cap, flip }: { cap: CapabilityRow; flip: boolean }) {
  const { n, label, title, body, bullets, href, url, Mock } = cap;
  return (
    <div className="grid items-center gap-12 lg:grid-cols-12 lg:gap-16">
      <ScrollReveal
        className={flip ? 'lg:col-span-5 lg:col-start-8 lg:order-2' : 'lg:col-span-5'}
      >
        <div className="flex items-baseline gap-4">
          <span className="font-display text-3xl text-accent/80">{n}</span>
          <span className="eyebrow text-foreground/60">{label}</span>
        </div>
        <h3 className="mt-4 font-serif text-3xl font-medium text-foreground sm:text-4xl">
          {title}
        </h3>
        <p className="mt-5 text-base leading-relaxed text-foreground/75 sm:text-lg">
          {body}
        </p>
        <ul className="mt-6 grid grid-cols-1 gap-2 text-sm text-foreground/75 sm:grid-cols-2">
          {bullets.map((b) => (
            <li key={b} className="flex items-start gap-2">
              <span aria-hidden className="mt-2 inline-block size-1 shrink-0 rounded-full bg-accent" />
              {b}
            </li>
          ))}
        </ul>
        <Link
          href={href}
          className="mt-8 inline-flex items-center text-xs font-medium uppercase tracking-[0.16em] text-foreground/70 hover:text-accent transition-colors"
        >
          <span className="link-underline decoration-accent">Learn more</span>
          <span className="ml-2" aria-hidden>→</span>
        </Link>
      </ScrollReveal>

      <ScrollReveal
        delay={140}
        className={flip ? 'lg:col-span-7 lg:col-start-1 lg:order-1' : 'lg:col-span-7 lg:col-start-6'}
      >
        <ProductFrame url={url}>
          <Mock />
        </ProductFrame>
      </ScrollReveal>
    </div>
  );
}

// ── 4. Why Lumè ────────────────────────────────────────────────────────

const REASONS = [
  {
    label: 'Built for medspas, not adapted.',
    body:
      'Mindbody for salons. Boulevard for high-end salons. Zenoti for spa chains. None of them built around treatment-cycle scheduling, per-procedure consent, multi-provider rooms, or a close-out that matches the drawer.',
  },
  {
    label: "HIPAA isn't a pricing tier.",
    body:
      "Every customer runs on the same compliant architecture. Tenant data isolated at the database. Audit log on every PHI read. AWS under a signed BAA, included in your standard contract.",
  },
  {
    label: 'Pricing without the games.',
    body:
      "Flat per workspace, not per seat. Clinical notes, packages, memberships, and consent forms ship in the $99 Starter — never gated to a higher tier. Add staff or locations one click + $20 at a time. No annual lock-in. No paywall on data export. No setup fee.",
  },
];

function WhyLume() {
  return (
    <section className="border-y border-border bg-foreground/[0.02]">
      <div className="mx-auto max-w-7xl px-6 lg:px-10 py-24 lg:py-32">
        <ScrollReveal>
          <SectionEyebrow
            eyebrow="Why Lumè"
            headline="Three things other platforms get wrong."
            description="Each is a deliberate choice baked into how Lumè is built, not a roadmap promise."
          />
        </ScrollReveal>

        <ol className="mt-16 grid gap-12 lg:grid-cols-3">
          {REASONS.map((r, i) => (
            <ScrollReveal as="li" key={r.label} delay={i * 100}>
              <div className="flex items-baseline gap-3">
                <span className="font-display text-2xl text-accent">
                  {String(i + 1).padStart(2, '0')}
                </span>
                <h3 className="font-serif text-xl font-medium text-foreground">
                  {r.label}
                </h3>
              </div>
              <p className="mt-4 text-base leading-relaxed text-foreground/75">
                {r.body}
              </p>
            </ScrollReveal>
          ))}
        </ol>
      </div>
    </section>
  );
}

// ── 5. Compliance ──────────────────────────────────────────────────────

function Compliance() {
  return (
    <section>
      <div className="mx-auto max-w-7xl px-6 lg:px-10 py-20 lg:py-24">
        <ScrollReveal>
          <div className="grid items-center gap-10 lg:grid-cols-12">
            <div className="lg:col-span-7">
              <p className="eyebrow text-foreground/60">Security & compliance</p>
              <h2 className="mt-4 font-display text-4xl text-foreground sm:text-5xl">
                HIPAA-compliant by{' '}
                <span className="accent-italic">architecture, not by checkbox.</span>
              </h2>
              <p className="mt-5 max-w-2xl text-base leading-relaxed text-foreground/75 sm:text-lg">
                Tenant data isolated at the database layer. Permissions
                resolved per request from a forty-permission catalog.
                Audit log entries on every PHI read and every state
                change. AWS infrastructure under a signed BAA. SOC 2
                Type II in progress.
              </p>
            </div>
            <div className="lg:col-span-4 lg:col-start-9 lg:text-right">
              <Link
                href="/security"
                className="inline-flex h-12 items-center rounded-full border border-foreground px-7 text-sm font-medium uppercase tracking-[0.16em] text-foreground hover:bg-foreground hover:text-background transition-colors"
              >
                Read the security overview
              </Link>
            </div>
          </div>
        </ScrollReveal>
      </div>
    </section>
  );
}

// ── 6. Demo CTA ────────────────────────────────────────────────────────

function DemoCta() {
  return (
    <section className="border-t border-border bg-foreground text-background">
      <div className="mx-auto max-w-7xl px-6 lg:px-10 py-24 lg:py-32">
        <ScrollReveal>
          <div className="grid gap-10 lg:grid-cols-12 lg:items-center">
            <div className="lg:col-span-7">
              <p className="eyebrow text-background/60">Thirty-minute demo</p>
              <h2 className="mt-4 font-display text-4xl sm:text-5xl lg:text-6xl">
                See Lumè running on your spa, not a generic one.
              </h2>
              <p className="mt-6 max-w-2xl text-base leading-relaxed text-background/80 sm:text-lg">
                Send us your service menu. We'll configure the demo on
                your real data. Thirty minutes. The first call is the
                demo.
              </p>
            </div>

            <div className="lg:col-span-4 lg:col-start-9 lg:text-right">
              <Link
                href="/demo"
                className="inline-flex h-12 items-center rounded-full bg-background px-8 text-sm font-medium uppercase tracking-[0.16em] text-foreground hover:bg-background/90 transition-colors"
              >
                Get a demo
              </Link>
              <p className="mt-4 text-xs text-background/55">
                One business day to a calendar invite.
              </p>
            </div>
          </div>
        </ScrollReveal>
      </div>
    </section>
  );
}
