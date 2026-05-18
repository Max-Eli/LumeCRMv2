/**
 * Edge proxy (formerly "middleware" in Next < 16) that powers the
 * `platform.lumècrm.com` subdomain for the platform-admin portal.
 *
 * The platform admin pages live under `app/(platform)/platform/*` and
 * are served at the URL `/platform/*` on any host. This proxy makes
 * them ALSO reachable at the root of `platform.<root-domain>` so the
 * URL bar reads `platform.lumècrm.com/tenants` instead of
 * `acmespa.lumècrm.com/platform/tenants`.
 *
 * Two routing rules:
 *
 *   1. On the platform subdomain:
 *      - `platform.lumè.../foo` → rewritten internally to `/platform/foo`
 *        (server-side rewrite — browser URL stays clean).
 *      - `platform.lumè.../platform/foo` → 308 redirect to
 *        `platform.lumè.../foo` so canonical URLs converge.
 *
 *   2. On ANY non-platform host (root domain + every tenant subdomain):
 *      - `acmespa.lumè.../platform/foo` → 308 redirect to
 *        `platform.lumè.../foo`. Keeps old bookmarks alive AND makes
 *        sure platform pages never leak into a tenant context.
 *
 * Local dev (`localhost:3000`) bails out of all rewrites — the
 * developer hits `/platform/*` paths directly and there's no
 * subdomain to play with.
 *
 * Notes on Next 16 specifically:
 *   - The convention is now `proxy.ts` (not `middleware.ts`).
 *   - The export name is `proxy`.
 *   - `NextResponse.rewrite/redirect` and the `config.matcher` are
 *     unchanged from the older middleware API.
 */

import { NextResponse, type NextRequest } from 'next/server';

const ROOT_DOMAIN = process.env.NEXT_PUBLIC_ROOT_DOMAIN || 'xn--lumcrm-5ua.com';
const PLATFORM_HOST = `platform.${ROOT_DOMAIN}`;

export function proxy(request: NextRequest) {
  // Strip the port so `platform.foo.com:443` matches `platform.foo.com`.
  const host = (request.headers.get('host') || '').toLowerCase().split(':')[0];
  const url = request.nextUrl.clone();
  const pathname = url.pathname;

  // Bail in local dev / preview deploys that don't use the production
  // root domain. Existing `/platform/*` paths continue to work.
  if (!host.endsWith(ROOT_DOMAIN)) {
    return NextResponse.next();
  }

  const onPlatformHost = host === PLATFORM_HOST;

  if (onPlatformHost) {
    // Canonicalise: if someone lands on the platform host with a
    // redundant `/platform` prefix (old bookmark, an in-app link
    // pasted around), strip it via 308 so the URL bar reads cleanly.
    if (pathname === '/platform' || pathname.startsWith('/platform/')) {
      url.pathname =
        pathname === '/platform' ? '/' : pathname.slice('/platform'.length);
      return NextResponse.redirect(url, 308);
    }

    // Internal rewrite so the existing app/(platform)/platform/<page>
    // route tree serves the request without us moving any files. The
    // browser URL is unchanged — still reads `platform.foo.com/tenants`.
    url.pathname = `/platform${pathname === '/' ? '' : pathname}`;
    return NextResponse.rewrite(url);
  }

  // On the root domain or a tenant subdomain — if someone hits
  // `/platform/foo`, redirect them to the canonical platform host.
  // Catches old bookmarks AND prevents accidental cross-context
  // navigation (e.g. owner of acmespa accidentally landing on the
  // platform admin while logged in as a tenant user).
  if (pathname === '/platform' || pathname.startsWith('/platform/')) {
    const target = new URL(request.url);
    target.host = PLATFORM_HOST;
    target.pathname =
      pathname === '/platform' ? '/' : pathname.slice('/platform'.length);
    return NextResponse.redirect(target, 308);
  }

  return NextResponse.next();
}

export const config = {
  // Skip Next internals, the API proxy (we don't have one), static
  // assets that look like `*.png` / `*.svg` / etc., and the favicon.
  matcher: ['/((?!_next/static|_next/image|favicon.ico|api/).*)'],
};
