'use client';

import { useRouter } from 'next/navigation';
import { useEffect } from 'react';

import { AppSidebar } from '@/components/app-sidebar';
import { useLogout, useUser } from '@/lib/auth';

/**
 * Authenticated app shell.
 *
 * Two-pane layout: the sidebar is pinned (own component, viewport-tall),
 * `<main>` is the scrolling area. Routes that need to use sticky positioning
 * (sticky save bar on forms, sticky filter row on tables, etc.) work because
 * `<main>` is the nearest scrolling ancestor.
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
    <div className="flex h-screen overflow-hidden bg-background">
      <AppSidebar user={user} />
      <main className="flex-1 min-w-0 overflow-y-auto">{children}</main>
    </div>
  );
}
