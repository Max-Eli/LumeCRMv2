/**
 * Platform admin layout.
 *
 * Three jobs:
 *   1. Gate the `/platform/*` subtree to `is_platform_admin=True`
 *      users. Non-platform-admins (anonymous OR signed-in tenant
 *      users) get bounced to `/platform/login` — NOT the customer
 *      `/login` page, since the platform admin surface is its own
 *      world.
 *   2. Apply the dark-theme scope via `data-theme="platform"` on the
 *      wrapper. Tailwind utilities resolve to dark-theme tokens
 *      inside this subtree only — the rest of the CRM stays warm
 *      cream.
 *   3. Render a dedicated platform sidebar.
 *
 * The login page (`/platform/login`) is an exception — it renders
 * its own dark-themed shell directly and bypasses this layout's
 * sidebar + auth gate (since unauthenticated users need to be able
 * to see it).
 */

'use client';

import { usePathname, useRouter } from 'next/navigation';
import { useEffect } from 'react';

import { useUser } from '@/lib/auth';

import { PlatformSidebar } from './_components/platform-sidebar';

export default function PlatformLayout({ children }: { children: React.ReactNode }) {
  const { data: user, isLoading } = useUser();
  const router = useRouter();
  const pathname = usePathname();
  const isLoginPage = pathname === '/platform/login';

  useEffect(() => {
    // The login page handles its own auth (or rather lack thereof) —
    // skip the gate here so unauthenticated users can actually see
    // the form they need to sign in with.
    if (isLoginPage) return;
    if (isLoading) return;
    if (!user || !user.is_platform_admin) {
      router.replace('/platform/login');
    }
  }, [user, isLoading, router, isLoginPage]);

  // Login page renders bare — no sidebar, no auth gate, page
  // controls its own chrome.
  if (isLoginPage) {
    return <>{children}</>;
  }

  if (isLoading || !user || !user.is_platform_admin) {
    return (
      <div
        data-theme="platform"
        className="flex min-h-screen items-center justify-center bg-background text-foreground"
      >
        <p className="text-sm text-muted-foreground">Verifying platform access…</p>
      </div>
    );
  }

  return (
    <div
      data-theme="platform"
      className="flex min-h-screen bg-background text-foreground"
    >
      <PlatformSidebar user={user} />
      <main className="flex-1 overflow-x-hidden">{children}</main>
    </div>
  );
}
