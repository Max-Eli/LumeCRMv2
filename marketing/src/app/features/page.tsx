/**
 * Features index page.
 *
 * Six capability rows, each paired with a real product mock from
 * `@/components/product-mocks`. Layout alternates left/right so the
 * page reads like a magazine spread instead of a wall of text —
 * matches the home page's Capabilities pattern but with deeper
 * standfirst copy and the "Learn more" deep-link.
 */

import Link from 'next/link';
import type { ComponentType } from 'react';

import { PageHero } from '@/components/page-hero';
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

import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Features',
  description:
    'Booking, client charts, consent forms, payments, reporting, and multi-location. Every capability built for the way a medspa actually runs.',
};

interface FeatureRow {
  n: string;
  kicker: string;
  title: string;
  standfirst: string;
  href: string;
  mockUrl: string;
  Mock: ComponentType;
}

const FEATURES: FeatureRow[] = [
  {
    n: '01',
    kicker: 'Booking',
    title: 'Multi-provider calendar with online booking.',
    standfirst:
      "Per-provider columns. Working hours and breaks honored at the booking layer. Self-serve online booking with a deposit. Consent flagged before check-in.",
    href: '/features/booking',
    mockUrl: '/calendar',
    Mock: CalendarMock,
  },
  {
    n: '02',
    kicker: 'Client charts',
    title: 'Complete client records, searchable across every location.',
    standfirst:
      "Treatment history, allergies, signed consents, outstanding paperwork, provider notes, invoice history. Two clicks from the calendar. Searches across every location.",
    href: '/features/charts',
    mockUrl: '/clients/sarah-chen',
    Mock: ChartMock,
  },
  {
    n: '03',
    kicker: 'Consent forms',
    title: 'E-signed consent that holds up under audit.',
    standfirst:
      "Schema-versioned templates for intake and per-treatment consent. Tokenized fill links. IP, user-agent, and timestamp captured on every signature.",
    href: '/features/forms',
    mockUrl: '/sign/9j4k…',
    Mock: FormMock,
  },
  {
    n: '04',
    kicker: 'Payments',
    title: 'Invoicing built for end-of-day reconciliation.',
    standfirst:
      "Card, cash, and check recorded with payment reference. Integrated card processing inside the appointment flow. Daily close-out matches the drawer. Sixty-day reopen window.",
    href: '/features/payments',
    mockUrl: '/appointments/4218/invoice',
    Mock: InvoiceMock,
  },
  {
    n: '05',
    kicker: 'Reports',
    title: 'Twenty-two reports across financial, staff, guests, and operations.',
    standfirst:
      "Daily close-out, AR aging, revenue by service / provider / location, schedule utilization, no-show rate, booking lead time. Live data, CSV export, audit-logged.",
    href: '/features/reports',
    mockUrl: '/reports/financial/sales-by-date-range',
    Mock: ReportsMock,
  },
  {
    n: '06',
    kicker: 'Multi-location',
    title: 'One brand, multiple locations, one bill.',
    standfirst:
      "Per-location calendars, pricing, staff schedules, and reports. An org-level dashboard shows every site alongside cross-location revenue. Bills per location, not per seat.",
    href: '/features/multi-location',
    mockUrl: '/org/dashboard',
    Mock: LocationsMock,
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
        standfirst="Built around the way a medspa actually runs. Click into any one for the full breakdown."
      />

      <section>
        <div className="mx-auto max-w-7xl px-6 lg:px-10 py-20 lg:py-28">
          <ol className="space-y-24 lg:space-y-32">
            {FEATURES.map((f, i) => (
              <FeatureIndexRow key={f.n} feature={f} flip={i % 2 === 1} />
            ))}
          </ol>
        </div>
      </section>
    </>
  );
}

function FeatureIndexRow({
  feature,
  flip,
}: {
  feature: FeatureRow;
  flip: boolean;
}) {
  const { n, kicker, title, standfirst, href, mockUrl, Mock } = feature;
  return (
    <li>
      <Link
        href={href}
        className="group grid items-center gap-10 lg:grid-cols-12 lg:gap-16"
      >
        <ScrollReveal
          className={
            flip
              ? 'lg:col-span-5 lg:col-start-8 lg:order-2'
              : 'lg:col-span-5'
          }
        >
          <div className="flex items-baseline gap-4">
            <span className="font-display text-3xl text-accent/80 transition-colors group-hover:text-accent">
              {n}
            </span>
            <span className="eyebrow text-foreground/60">{kicker}</span>
          </div>
          <h2 className="mt-4 font-serif text-3xl font-medium text-foreground sm:text-4xl">
            {title}
          </h2>
          <p className="mt-5 max-w-xl text-base leading-relaxed text-foreground/75 sm:text-lg">
            {standfirst}
          </p>
          <span className="mt-8 inline-flex items-center text-xs font-medium uppercase tracking-[0.16em] text-foreground/70 transition-colors group-hover:text-accent">
            <span className="link-underline decoration-accent">Learn more</span>
            <span className="ml-2" aria-hidden>
              →
            </span>
          </span>
        </ScrollReveal>

        <ScrollReveal
          delay={140}
          className={
            flip
              ? 'lg:col-span-7 lg:col-start-1 lg:order-1'
              : 'lg:col-span-7 lg:col-start-6'
          }
        >
          <div className="transition-transform duration-500 ease-out group-hover:-translate-y-1">
            <ProductFrame url={mockUrl}>
              <Mock />
            </ProductFrame>
          </div>
        </ScrollReveal>
      </Link>
    </li>
  );
}
