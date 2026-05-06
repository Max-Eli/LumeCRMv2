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
  return (
    <header className="border-b border-stone-200 bg-white">
      <div className="max-w-3xl mx-auto px-4 sm:px-6 py-4 flex items-center gap-3">
        {bookingHref ? (
          <Link href={bookingHref} className="flex items-center gap-3 group">
            <BrandMark logoUrl={logoUrl} initial={initial} primaryColor={primaryColor} />
            <span className="font-serif text-lg font-semibold tracking-tight text-stone-900 group-hover:opacity-80 transition-opacity">
              {tenantName}
            </span>
          </Link>
        ) : (
          <div className="flex items-center gap-3">
            <BrandMark logoUrl={logoUrl} initial={initial} primaryColor={primaryColor} />
            <span className="font-serif text-lg font-semibold tracking-tight text-stone-900">
              {tenantName}
            </span>
          </div>
        )}
      </div>
    </header>
  );
}

function BrandMark({
  logoUrl,
  initial,
  primaryColor,
}: {
  logoUrl?: string;
  initial: string;
  primaryColor: string;
}) {
  if (logoUrl) {
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <img
        src={logoUrl}
        alt=""
        className="size-8 rounded-md object-contain"
      />
    );
  }
  return (
    <div
      className="size-8 rounded-md flex items-center justify-center text-white font-semibold text-sm"
      style={{ background: primaryColor }}
    >
      {initial}
    </div>
  );
}

export function brandStyle(primaryColor: string): React.CSSProperties {
  return { ['--brand' as string]: primaryColor };
}
