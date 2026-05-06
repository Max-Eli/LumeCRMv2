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
import { APP_URL } from '@/lib/utils';

export default function HomePage() {
  return (
    <>
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
              Booking, client charts, e-signed consent forms, payments, and
              twenty-two real-time reports — HIPAA-compliant, multi-location
              ready, designed specifically for the way medspas operate.
            </p>
            <div
              className="hero-rise mt-10 flex flex-wrap items-center gap-6"
              style={{ animationDelay: '380ms' }}
            >
              <Link
                href="/demo"
                className="inline-flex h-12 items-center rounded-full bg-foreground px-7 text-sm font-medium uppercase tracking-[0.16em] text-background hover:bg-foreground/90 transition-colors"
              >
                Get a demo
              </Link>
              <a
                href={APP_URL}
                className="text-sm font-medium text-foreground/70 hover:text-foreground transition-colors"
              >
                <span className="link-underline decoration-accent">Sign in →</span>
              </a>
            </div>

            {/* Concrete trust bullets — three short claims that mean
                something specific. Replaces the literary "01 idea"
                pull-out that previously sat in the right column. */}
            <ul
              className="hero-rise mt-12 grid grid-cols-1 gap-4 text-sm text-foreground/75 sm:grid-cols-3"
              style={{ animationDelay: '500ms' }}
            >
              <li className="border-l-2 border-accent/50 pl-4">
                <span className="block font-serif text-base font-medium text-foreground">HIPAA-compliant</span>
                Architectural, not a checkbox.
              </li>
              <li className="border-l-2 border-accent/50 pl-4">
                <span className="block font-serif text-base font-medium text-foreground">Built for medspas</span>
                Not adapted from a salon tool.
              </li>
              <li className="border-l-2 border-accent/50 pl-4">
                <span className="block font-serif text-base font-medium text-foreground">No payment markup</span>
                Pricing is one clean line.
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
    title: 'A calendar built for multi-provider operations.',
    body:
      "Per-provider columns, per-location scoping, and working-hours awareness. Drag to reschedule, click to take payment, see at a glance which appointments still need consent before check-in.",
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
    title: 'Every client record in one place.',
    body:
      'Contact, treatment history, allergies, signed consent forms, outstanding paperwork, and provider-only notes — accessible in two taps from the calendar or the search bar.',
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
    title: 'E-signed consent that holds up to a compliance review.',
    body:
      'Schema-versioned templates for intake and per-treatment consent. Sent as tokenized links, signed on a tablet, snapshotted at the moment of signing — so an evolving template never rewrites a signed past.',
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
    title: 'Invoicing built around end-of-day reconciliation.',
    body:
      'Cash, check, card-on-terminal, and other — recorded with payment reference, owner-reopenable within sixty days, void with a required reason. The numbers match the cash drawer at close.',
    bullets: [
      'Owner-only 60-day reopen window',
      'Per-payment-method daily close-out',
      'Tax handled per service line item',
      'No platform fee on card volume',
    ],
    href: '/features/payments',
    url: '/appointments/4218/invoice',
    Mock: InvoiceMock,
  },
  {
    n: '05',
    label: 'Reports',
    title: 'Twenty-two reports across financial, staff, guests, and operations.',
    body:
      'Daily close-out, AR aging, revenue by service / provider / location, schedule utilization, top spenders, no-show rates, booking lead time — all running against live data, all exportable to CSV with a HIPAA confirmation gate.',
    bullets: [
      '22 pre-built reports',
      'Live data — no nightly refresh delay',
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
    title: 'One brand, multiple locations, one bill.',
    body:
      'Per-location calendars, pricing, staff schedules, and reporting. The org-level dashboard rolls up revenue, appointments, and utilization across every site. The location switcher only appears when the team has more than one to switch between.',
    bullets: [
      'Per-location pricing + staff',
      'Org-level rollup dashboard',
      'Per-location reporting filters',
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
            eyebrow="What's in the platform"
            headline={
              <>
                Six core capabilities,{' '}
                <span className="accent-italic">built specifically for medspas.</span>
              </>
            }
            description="Each one designed for the actual workflows medical spas run every day — not retrofit from a salon, gym, or general-purpose CRM."
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
    label: 'Built for medspas, not retrofit.',
    body:
      "Most CRMs medspas use today were designed for salons, yoga studios, or general doctors' offices, then patched to handle injectables and lasers. Lumè was built for medspa workflows from the first migration: treatment-cycle scheduling, per-service consent recurrence, multi-provider rooms, and the close-out reconciliation a front desk actually does.",
  },
  {
    label: 'HIPAA compliance is structural.',
    body:
      'Tenant isolation enforced at the database. Role-based permissions resolved per request from a forty-permission catalog. Append-only audit logging on every PHI access. AWS infrastructure under a signed BAA. The compliance posture is the architecture — not a separate "secure" tier.',
  },
  {
    label: 'Pricing without the games.',
    body:
      'One per-seat number, scaled by location count. No platform fee on card volume. No annual contract lockout. No tier upgrade required to export your own data. The Business Associate Agreement is included.',
  },
];

function WhyLume() {
  return (
    <section className="border-y border-border bg-foreground/[0.02]">
      <div className="mx-auto max-w-7xl px-6 lg:px-10 py-24 lg:py-32">
        <ScrollReveal>
          <SectionEyebrow
            eyebrow="Why Lumè"
            headline="Built for the way medspas actually run."
            description="Three specific differences from the platforms most medspas are using today."
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
                Tenant isolation at the database layer. Role-based permissions
                resolved per request. Append-only audit logging on every PHI
                read and write. AWS infrastructure under a signed Business
                Associate Agreement. SOC 2 Type II in progress.
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
              <p className="eyebrow text-background/60">See it in 30 minutes</p>
              <h2 className="mt-4 font-display text-4xl sm:text-5xl lg:text-6xl">
                See Lumè running on workflows like yours.
              </h2>
              <p className="mt-6 max-w-2xl text-base leading-relaxed text-background/80 sm:text-lg">
                Tell us about your spa. We'll set up a private 30-minute
                walkthrough with the product configured for your service
                menu, your providers, and your locations.
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
                No long sales cycle. We respond within one business day.
              </p>
            </div>
          </div>
        </ScrollReveal>
      </div>
    </section>
  );
}
