/**
 * Marketing top navigation.
 *
 * Desktop: thin bordered bar — brand mark left, nav links center-right,
 * "Get a demo" CTA far right. No shadow, no glass. Nav links are
 * small-caps + tracked; they read as section markers, not buttons.
 *
 * Mobile: hamburger button opens a full-screen overlay panel with a
 * solid background, large touch-target links, and a close button.
 * Closes automatically when any link is tapped (via the onClick
 * handler + useState) so the user lands on the right page. Using
 * React state instead of <details> so we can: (a) lock body scroll
 * while the panel is open, (b) render a proper close × button, and
 * (c) close on link tap without a separate JS workaround.
 */

'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';

import { BrandMark } from './brand-mark';

const NAV_LINKS = [
  { href: '/features', label: 'Features' },
  { href: '/medspas', label: 'For medspas' },
  { href: '/compare', label: 'Compare' },
  { href: '/pricing', label: 'Pricing' },
  { href: '/blog', label: 'Journal' },
  { href: '/about', label: 'About' },
] as const;

export function TopNav() {
  const [open, setOpen] = useState(false);

  // Lock body scroll while the mobile menu is open — prevents the
  // page from scrolling behind the overlay.
  useEffect(() => {
    if (open) {
      document.body.style.overflow = 'hidden';
    } else {
      document.body.style.overflow = '';
    }
    return () => {
      document.body.style.overflow = '';
    };
  }, [open]);

  return (
    <>
      <header className="sticky top-0 z-40 border-b border-border bg-background">
        <div className="mx-auto max-w-7xl px-6 lg:px-10">
          <div className="flex h-20 items-center justify-between gap-8 lg:h-28">
            <Link
              href="/"
              className="inline-flex shrink-0"
              aria-label="Lumè home"
              onClick={() => setOpen(false)}
            >
              <BrandMark variant="lockup" size={56} />
            </Link>

            {/* Desktop nav */}
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

            {/* Mobile hamburger */}
            <button
              type="button"
              onClick={() => setOpen((v) => !v)}
              aria-label={open ? 'Close menu' : 'Open menu'}
              aria-expanded={open}
              className="lg:hidden inline-flex size-10 items-center justify-center rounded-md text-foreground/80 hover:bg-muted/50 transition-colors"
            >
              {open ? (
                /* × close icon */
                <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden>
                  <path d="M4 4l12 12M16 4L4 16" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                </svg>
              ) : (
                /* hamburger */
                <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden>
                  <path d="M3 5h14M3 10h14M3 15h14" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                </svg>
              )}
            </button>
          </div>
        </div>
      </header>

      {/* Mobile nav overlay — full-screen, solid background, above everything */}
      {open && (
        <div
          className="fixed inset-0 z-50 flex flex-col bg-background lg:hidden"
          aria-label="Mobile navigation"
        >
          {/* Overlay header — mirrors the main header height + brand */}
          <div className="flex h-20 items-center justify-between border-b border-border px-6">
            <Link
              href="/"
              aria-label="Lumè home"
              onClick={() => setOpen(false)}
            >
              <BrandMark variant="lockup" size={56} />
            </Link>
            <button
              type="button"
              onClick={() => setOpen(false)}
              aria-label="Close menu"
              className="inline-flex size-10 items-center justify-center rounded-md text-foreground/80 hover:bg-muted/50 transition-colors"
            >
              <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden>
                <path d="M4 4l12 12M16 4L4 16" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
              </svg>
            </button>
          </div>

          {/* Nav links — large touch targets */}
          <nav className="flex flex-1 flex-col px-6 pt-8 pb-10 overflow-y-auto">
            <ul className="space-y-1">
              {NAV_LINKS.map((link) => (
                <li key={link.href}>
                  <Link
                    href={link.href}
                    onClick={() => setOpen(false)}
                    className="flex items-center rounded-lg px-3 py-4 text-lg font-medium text-foreground hover:bg-muted/50 transition-colors"
                  >
                    {link.label}
                  </Link>
                </li>
              ))}
            </ul>

            {/* CTA at the bottom of the panel */}
            <div className="mt-auto pt-8 border-t border-border">
              <Link
                href="/demo"
                onClick={() => setOpen(false)}
                className="flex w-full items-center justify-center rounded-full bg-foreground px-6 py-4 text-sm font-medium uppercase tracking-[0.16em] text-background hover:bg-foreground/90 transition-colors"
              >
                Get a demo
              </Link>
              <p className="mt-3 text-center text-xs text-foreground/50">
                30-day free trial · BAA included · No setup fee
              </p>
            </div>
          </nav>
        </div>
      )}
    </>
  );
}
