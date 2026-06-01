/**
 * Marketing footer.
 *
 * Editorial layout: the brand monogram + a one-line tagline on the
 * left; three small columns of links on the right (Product, Company,
 * Legal). A fine ruled line, then a thin baseline strip with the
 * copyright notice + a single "made for medspas" italic flourish.
 *
 * No social-media glyph soup, no newsletter signup form (the CTA
 * lives at the top of every page in the nav), no ten-column link
 * grid. The footer's job here is wayfinding + closure, not another
 * marketing surface.
 */

import Link from 'next/link';

import { BrandMark } from './brand-mark';

const FOOTER_GROUPS = [
  {
    label: 'Product',
    links: [
      { href: '/features', label: 'Features' },
      { href: '/features/booking', label: 'Booking calendar' },
      { href: '/features/charts', label: 'Client charts' },
      { href: '/features/forms', label: 'Forms & e-sign' },
      { href: '/features/reports', label: 'Reporting' },
      { href: '/pricing', label: 'Pricing' },
    ],
  },
  {
    label: 'Company',
    links: [
      { href: '/medspas', label: 'For medspas' },
      { href: '/compare', label: 'Compare alternatives' },
      { href: '/security', label: 'Security' },
      { href: '/blog', label: 'Journal' },
      { href: '/about', label: 'About' },
      { href: '/demo', label: 'Request a demo' },
    ],
  },
  {
    label: 'Legal',
    links: [
      { href: '/privacy', label: 'Privacy' },
      { href: '/terms', label: 'Terms' },
      { href: '/baa', label: 'BAA' },
    ],
  },
] as const;

export function Footer() {
  return (
    <footer className="mt-24 border-t border-border bg-background">
      <div className="mx-auto max-w-7xl px-6 lg:px-10 py-16">
        <div className="grid gap-16 lg:grid-cols-[1.4fr_2fr]">
          <div>
            <BrandMark variant="lockup" size={48} />
            <p className="mt-6 max-w-sm text-sm leading-relaxed text-muted-foreground">
              The HIPAA-compliant CRM for medical spas. Booking, charts,
              consent forms, payments, AI SMS agent, email + SMS marketing,
              and a full reporting suite — built for the way medspas operate.
            </p>
          </div>

          <div className="grid grid-cols-2 gap-12 sm:grid-cols-3">
            {FOOTER_GROUPS.map((group) => (
              <div key={group.label}>
                <p className="eyebrow text-foreground/60">{group.label}</p>
                <ul className="mt-4 space-y-3">
                  {group.links.map((link) => (
                    <li key={link.href}>
                      <Link
                        href={link.href}
                        className="text-sm text-foreground/80 hover:text-accent transition-colors"
                      >
                        {link.label}
                      </Link>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </div>

        <hr className="rule mt-16 mb-6" />
        <div className="flex flex-col-reverse gap-3 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-xs text-muted-foreground">
            © {new Date().getFullYear()} Lumè. All rights reserved.
          </p>
          <p className="text-xs text-muted-foreground">
            HIPAA-compliant · BAA included in every contract
          </p>
        </div>
      </div>
    </footer>
  );
}
