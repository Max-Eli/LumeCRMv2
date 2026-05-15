/**
 * Customer-portal route-group shell.
 *
 * Sibling of `(app)`, `(calendar)`, `(auth)`, `(book)`, `(popout)`.
 * Customers — not staff — sign into the portal via the magic-link
 * cookie; this layout intentionally does NOT use the staff auth gate
 * or the staff sidebar.
 *
 * Two responsibilities:
 *
 *   1. **Tenant-branded chrome.** Once a customer is signed in, every
 *      portal page renders with the spa's primary color + logo. The
 *      layout fetches `/api/portal/me/` once and applies the brand
 *      via CSS custom properties so individual pages don't have to
 *      thread the tenant down through props.
 *   2. **Auth-aware routing.** Unauthenticated customers on a
 *      non-public portal route (anything other than `/portal/login`
 *      and `/portal/magic/...`) are redirected to login. Conversely,
 *      already-authenticated customers landing on `/portal/login`
 *      get bounced into the dashboard.
 */

'use client';

import { usePathname, useRouter } from 'next/navigation';
import { useEffect } from 'react';

import { ApiError } from '@/lib/api';
import { usePortalMe } from '@/lib/portal';

/** Routes that don't require an authenticated portal session. Used to
 *  gate the redirect behaviour below. */
const PUBLIC_PORTAL_ROUTES = ['/portal/login', '/portal/magic'];

export default function PortalLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const isPublicRoute = PUBLIC_PORTAL_ROUTES.some((r) => pathname?.startsWith(r));

  const { data: customer, isLoading, error } = usePortalMe();

  // Auth-aware routing. Two states matter:
  //   - On a protected route + not authed (401/403) → /portal/login
  //   - On a public route + already authed → /portal (skip login)
  const authError =
    error instanceof ApiError && (error.status === 401 || error.status === 403);

  useEffect(() => {
    if (isLoading) return;
    if (!isPublicRoute && (authError || !customer)) {
      router.replace('/portal/login');
    } else if (isPublicRoute && customer && !authError && pathname === '/portal/login') {
      router.replace('/portal');
    }
  }, [isLoading, isPublicRoute, customer, authError, router, pathname]);

  // Apply the tenant brand color as a CSS custom property on the root
  // wrapper. Pages use `var(--portal-brand)` for accent surfaces; the
  // logo URL is consumed directly in the header below.
  const brand = customer?.tenant.primary_color || '#1f2937';
  const logoUrl = customer?.tenant.logo_url || '';
  const spaName = customer?.tenant.name || '';

  if (isLoading && !customer) {
    return (
      <div className="flex h-screen items-center justify-center text-sm text-muted-foreground">
        Loading…
      </div>
    );
  }

  return (
    <div
      className="min-h-screen flex flex-col bg-background"
      style={{ ['--portal-brand' as string]: brand }}
    >
      {!isPublicRoute && customer ? (
        <PortalTopBar spaName={spaName} logoUrl={logoUrl} />
      ) : null}
      <main className="flex-1 flex flex-col">{children}</main>
    </div>
  );
}

// ── Top bar ─────────────────────────────────────────────────────────


function PortalTopBar({
  spaName,
  logoUrl,
}: {
  spaName: string;
  logoUrl: string;
}) {
  const pathname = usePathname();
  const router = useRouter();

  const links = [
    { href: '/portal', label: 'Home' },
    { href: '/portal/book', label: 'Book' },
    { href: '/portal/appointments', label: 'Appointments' },
    { href: '/portal/memberships', label: 'Memberships' },
    { href: '/portal/packages', label: 'Packages' },
    { href: '/portal/forms', label: 'Forms' },
    { href: '/portal/profile', label: 'Profile' },
  ];

  return (
    <header className="border-b bg-card sticky top-0 z-30">
      <div className="max-w-5xl mx-auto px-6 h-14 flex items-center justify-between gap-6">
        <button
          type="button"
          onClick={() => router.push('/portal')}
          className="flex items-center gap-2.5 min-w-0"
          aria-label={`${spaName} portal home`}
        >
          {logoUrl ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={logoUrl}
              alt={spaName}
              className="h-7 w-auto max-w-[140px] object-contain"
            />
          ) : (
            <span
              className="size-7 rounded-md inline-flex items-center justify-center text-white text-xs font-semibold"
              style={{ background: 'var(--portal-brand)' }}
            >
              {spaName.charAt(0).toUpperCase()}
            </span>
          )}
          <span className="font-serif text-sm font-semibold tracking-tight truncate">
            {spaName}
          </span>
        </button>
        {/* Horizontal scroll on narrow viewports so the nav doesn't
            wrap or get cut off — common pattern for portal/account
            top-bars in apps like Stripe, Linear, etc. */}
        <nav className="flex items-center gap-1 overflow-x-auto -mx-2 px-2 scrollbar-thin">
          {links.map((l) => {
            const isActive =
              pathname === l.href ||
              (l.href !== '/portal' && pathname?.startsWith(l.href));
            return (
              <button
                key={l.href}
                type="button"
                onClick={() => router.push(l.href)}
                className={`text-sm px-3 py-1.5 rounded-md transition-colors whitespace-nowrap shrink-0 ${
                  isActive
                    ? 'bg-muted text-foreground font-medium'
                    : 'text-muted-foreground hover:text-foreground hover:bg-muted/60'
                }`}
              >
                {l.label}
              </button>
            );
          })}
        </nav>
      </div>
    </header>
  );
}
