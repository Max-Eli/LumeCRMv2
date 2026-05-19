'use client';

import { useRouter } from 'next/navigation';
import { useEffect } from 'react';

import { AppSidebar } from '@/components/app-sidebar';
import { MobileNav } from '@/components/mobile-nav';
import { useLogout, useUser } from '@/lib/auth';
import { cn } from '@/lib/utils';

/**
 * Authenticated app shell.
 *
 * **Desktop (≥1024px)**: two-pane layout — the `<AppSidebar>` is
 * pinned (own component, viewport-tall) and `<main>` is the scrolling
 * area. Routes that need sticky positioning (sticky save bars, sticky
 * filter rows) work because `<main>` is the nearest scrolling ancestor.
 *
 * **Mobile (<1024px)**: the desktop sidebar is hidden; `<MobileNav>`
 * supplies a top app bar (hamburger + brand) and a bottom tab bar
 * (Calendar · Clients · Catalog · More). The page body sits between
 * them with enough bottom padding to clear the tab bar.
 *
 * Auth gates:
 *   1. Anyone without a current user is redirected to /login.
 *   2. Defense-in-depth tenant-isolation check: if the user IS
 *      authenticated but their `memberships` list doesn't include the
 *      tenant matching the current subdomain, force a logout +
 *      redirect. The backend `TenantMiddleware` already kills the
 *      session on cross-tenant navigation; this is the UI mirror so
 *      a stale React Query cache can't briefly render a foreign
 *      tenant's chrome.
 */
export default function AppLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const { data: user, isLoading } = useUser();
  const logout = useLogout();

  // Detect a user on the wrong tenant's subdomain. Returns true when:
  //   - We're in the browser (not SSR).
  //   - The hostname looks like `<slug>.<domain>` (not localhost / IP).
  //   - The user has NO active membership whose tenant slug matches
  //     that first label.
  const isOnForeignTenant = (() => {
    if (typeof window === 'undefined' || !user) return false;
    if (user.is_platform_admin || user.is_superuser) return false;
    const host = window.location.hostname;
    if (host === 'localhost' || /^\d+\.\d+\.\d+\.\d+$/.test(host)) return false;
    const parts = host.split('.');
    if (parts.length < 2) return false;
    const subdomain = parts[0].toLowerCase();
    // Reserved subdomains aren't tenants — leave them alone.
    if (['www', 'api', 'admin'].includes(subdomain)) return false;
    return !user.memberships.some(
      (m) => m.tenant.slug.toLowerCase() === subdomain,
    );
  })();

  useEffect(() => {
    if (isLoading) return;
    if (!user) {
      router.replace('/login');
      return;
    }
    if (isOnForeignTenant) {
      // Fire logout to flush both server session + client cookies,
      // then route to the login page on this tenant's subdomain.
      logout.mutate(undefined, {
        onSettled: () => router.replace('/login'),
      });
    }
  }, [isLoading, user, isOnForeignTenant, router, logout]);

  if (isLoading) {
    return (
      <div className="flex h-screen items-center justify-center text-sm text-muted-foreground">
        Loading…
      </div>
    );
  }
  if (!user) return null;
  // Don't render the chrome (with the wrong tenant's data) while the
  // logout-and-redirect effect is in flight.
  if (isOnForeignTenant) {
    return (
      <div className="flex h-screen items-center justify-center text-sm text-muted-foreground">
        Signing you out…
      </div>
    );
  }

  return (
    <div className="lg:flex lg:h-screen lg:overflow-hidden bg-background">
      {/* Desktop sidebar — hidden on mobile, the MobileNav fills in. */}
      <div className="hidden lg:flex">
        <AppSidebar user={user} />
      </div>

      {/* Mobile top + bottom nav bars. Self-hides at lg+. */}
      <MobileNav user={user} />

      <main
        className={cn(
          // Desktop: own scrollable column inside the flex shell.
          'lg:flex-1 lg:min-w-0 lg:overflow-y-auto',
          // Mobile: page body scrolls naturally; pad the bottom so
          // content clears the 56px tab bar (+ iOS safe-area).
          'pb-[calc(56px+env(safe-area-inset-bottom))] lg:pb-0',
        )}
      >
        {children}
      </main>
    </div>
  );
}
