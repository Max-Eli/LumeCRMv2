/**
 * Edge proxy (Next 16's renamed-but-otherwise-same middleware) that
 * powers the `platform.lumècrm.com` subdomain for the platform-admin
 * portal.
 *
 * The platform admin pages live at `/platform/*` in the app router.
 * This proxy makes them reachable via the dedicated `platform.<root>`
 * subdomain instead of mixing into a tenant's URL space.
 *
 * Design — REDIRECT-ONLY (no internal rewrite). An earlier version
 * tried rewriting `platform.<root>/foo` → internal `/platform/foo` to
 * achieve cleaner URLs, but Next.js's `usePathname()` returned the
 * browser URL on the client and the rewritten URL on the server,
 * which broke hydration and confused page-level pathname checks
 * (e.g. `isLoginPage = pathname === '/platform/login'`).
 *
 * The fix: keep `/platform/*` in the URL bar AND in the page code.
 * The proxy now does only:
 *
 *   1. `platform.<root>/`             → 308 → `platform.<root>/platform`
 *   2. `platform.<root>/<anything>`   if path doesn't start with
 *      `/platform`, 308 → `platform.<root>/platform/<anything>` so a
 *      stray path on this host always ends up under the admin tree.
 *   3. `<not-platform>/platform/<x>`  → 308 → `platform.<root>/platform/<x>`
 *      so an old bookmark / cross-tenant nav hits the canonical host.
 *
 * Local dev untouched: when the host doesn't end with the root
 * domain (localhost etc.), the proxy bails and existing `/platform/*`
 * paths work directly.
 */

import { NextResponse, type NextRequest } from 'next/server';

const ROOT_DOMAIN = process.env.NEXT_PUBLIC_ROOT_DOMAIN || 'xn--lumcrm-5ua.com';
const PLATFORM_HOST = `platform.${ROOT_DOMAIN}`;

export function proxy(request: NextRequest) {
  // Strip the port so `platform.foo.com:443` matches `platform.foo.com`.
  const host = (request.headers.get('host') || '').toLowerCase().split(':')[0];
  const url = request.nextUrl.clone();
  const pathname = url.pathname;

  // Local dev / preview deploys without the production root domain
  // pass through untouched.
  if (!host.endsWith(ROOT_DOMAIN)) {
    return NextResponse.next();
  }

  const onPlatformHost = host === PLATFORM_HOST;
  const isUnderPlatform =
    pathname === '/platform' || pathname.startsWith('/platform/');

  if (onPlatformHost && !isUnderPlatform) {
    // On platform.<root>, anything not already under /platform gets
    // redirected so the app-router page tree resolves cleanly.
    // Examples:
    //   /            → /platform
    //   /tenants     → /platform/tenants
    //   /logs        → /platform/logs
    url.pathname = `/platform${pathname === '/' ? '' : pathname}`;
    return NextResponse.redirect(url, 308);
  }

  if (!onPlatformHost && isUnderPlatform) {
    // Old bookmark / accidental link — bounce to the canonical host
    // so platform admin pages never load inside a tenant context.
    const target = new URL(request.url);
    target.host = PLATFORM_HOST;
    return NextResponse.redirect(target, 308);
  }

  return NextResponse.next();
}

export const config = {
  // Exclude Next internals, any path with a file extension (favicon
  // .png / .ico, robots.txt, manifest.json, etc.), and the internal
  // API proxy. Matching anything with a dot covers static assets
  // we don't own paths for — without this guard, `/favicon.png` on
  // the platform host would redirect to `/platform/favicon.png`
  // which 404s.
  matcher: ['/((?!_next/|api/|.*\\..*).*)'],
};
