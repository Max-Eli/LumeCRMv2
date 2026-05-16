/**
 * Marketing top navigation.
 *
 * Editorial / luxury approach: thin top rule (no shadow, no glass),
 * the brand mark on the left at restrained size, a small set of nav
 * links in the center-right, and the "Get a demo" CTA on the far
 * right. No mega-menu, no submenus. Nav links are small caps +
 * tracked; the eye reads them as section markers, not buttons.
 *
 * The mobile breakpoint hides the inline nav and surfaces a simple
 * "Menu" disclosure — done with the native `<details>` so we don't
 * pull a JS dependency in for a 5-link menu.
 *
 * No Sign-in link: Lumè is sales-led right now. Every customer goes
 * through a demo and signed contract before a tenant subdomain is
 * provisioned, so a public Sign-in button would mislead visitors and
 * generate support load. When self-serve sign-up lands, restore the
 * link pointing at `APP_URL` from `lib/utils`.
 */

import Link from 'next/link';

import { BrandMark } from './brand-mark';

const NAV_LINKS = [
  { href: '/features', label: 'Features' },
  { href: '/medspas', label: 'For medspas' },
  { href: '/security', label: 'Security' },
  { href: '/pricing', label: 'Pricing' },
  { href: '/blog', label: 'Journal' },
  { href: '/about', label: 'About' },
] as const;

export function TopNav() {
  return (
    <header className="border-b border-border bg-background">
      <div className="mx-auto max-w-7xl px-6 lg:px-10">
        <div className="flex h-28 items-center justify-between gap-8">
          <Link href="/" className="inline-flex shrink-0" aria-label="Lumè home">
            <BrandMark variant="lockup" size={64} />
          </Link>

          <nav className="hidden items-center gap-8 lg:flex" aria-label="Primary">
            {NAV_LINKS.map((link) => (
              <Link
                key={link.href}
                href={link.href}
                className="eyebrow text-foreground/70 hover:text-foreground transition-colors"
              >
                {link.label}
              </Link>
            ))}
          </nav>

          <div className="hidden items-center gap-3 lg:flex">
            <Link
              href="/demo"
              className="inline-flex h-9 items-center rounded-full border border-foreground bg-foreground px-4 text-xs font-medium uppercase tracking-[0.16em] text-background hover:bg-foreground/90 transition-colors"
            >
              Get a demo
            </Link>
          </div>

          <details className="lg:hidden relative">
            <summary className="eyebrow cursor-pointer list-none text-foreground/80">
              Menu
            </summary>
            <div className="absolute right-0 top-full mt-2 w-56 rounded-md border border-border bg-background py-2 shadow-sm">
              {NAV_LINKS.map((link) => (
                <Link
                  key={link.href}
                  href={link.href}
                  className="block px-4 py-2 text-sm text-foreground hover:bg-muted/40"
                >
                  {link.label}
                </Link>
              ))}
              <div className="my-1 h-px bg-border" />
              <Link href="/demo" className="block px-4 py-2 text-sm font-medium text-accent hover:bg-muted/40">
                Get a demo
              </Link>
            </div>
          </details>
        </div>
      </div>
    </header>
  );
}
