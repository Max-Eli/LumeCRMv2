/**
 * Per-tenant brand header for the public booking flow.
 *
 * Renders the tenant's logo + name and applies their primary color
 * as a CSS variable so child components (buttons, accents) can pick
 * it up via `var(--brand)`. Used by every booking page that has a
 * resolved tenant — the catalog/service/details flow + the manage
 * flow.
 *
 * Branding stays scoped to this route group: the variable is set on
 * a wrapping `div`, not on `:root`, so it doesn't leak into the
 * staff CRM.
 */

'use client';

import Link from 'next/link';

export function BrandHeader({
  tenantName,
  logoUrl,
  primaryColor,
  bookingHref,
}: {
  tenantName: string;
  logoUrl?: string;
  primaryColor: string;
  bookingHref?: string;
}) {
  const initial = tenantName.trim().charAt(0).toUpperCase() || 'L';
  const hasLogo = !!logoUrl;
  const inner = (
    <>
      <BrandMark
        logoUrl={logoUrl}
        initial={initial}
        primaryColor={primaryColor}
        tenantName={tenantName}
      />
      {!hasLogo ? (
        <span className="font-serif text-lg font-semibold tracking-tight text-stone-900">
          {tenantName}
        </span>
      ) : null}
    </>
  );
  return (
    <header className="sticky top-0 z-10 border-b border-stone-200/80 bg-white/95 backdrop-blur supports-[backdrop-filter]:bg-white/70">
      <div className="max-w-3xl mx-auto px-4 sm:px-6 py-3 flex items-center gap-3">
        {bookingHref ? (
          <Link href={bookingHref} className="flex items-center gap-3 group hover:opacity-70 transition-opacity">
            {inner}
          </Link>
        ) : (
          <div className="flex items-center gap-3">{inner}</div>
        )}
      </div>
    </header>
  );
}

function BrandMark({
  logoUrl,
  initial,
  primaryColor,
  tenantName,
}: {
  logoUrl?: string;
  initial: string;
  primaryColor: string;
  tenantName: string;
}) {
  if (logoUrl) {
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <img
        src={logoUrl}
        alt={tenantName}
        className="h-14 sm:h-16 w-auto max-w-[260px] object-contain"
      />
    );
  }
  return (
    <div
      className="size-10 rounded-md flex items-center justify-center text-white font-serif font-semibold text-base shadow-sm"
      style={{ background: primaryColor }}
    >
      {initial}
    </div>
  );
}

export function brandStyle(primaryColor: string): React.CSSProperties {
  return { ['--brand' as string]: primaryColor };
}
