'use client';

import { useRouter } from 'next/navigation';
import { useEffect } from 'react';

import { AppSidebar } from '@/components/app-sidebar';
import { useUser } from '@/lib/auth';

/**
 * Authenticated app shell.
 *
 * Two-pane layout: the sidebar is pinned (own component, viewport-tall),
 * `<main>` is the scrolling area. Routes that need to use sticky positioning
 * (sticky save bar on forms, sticky filter row on tables, etc.) work because
 * `<main>` is the nearest scrolling ancestor.
 *
 * Auth gate: anyone without a current user is redirected to /login. Loading
 * state is shown briefly during the initial /api/auth/me/ check so we don't
 * flash the dashboard then redirect.
 */
export default function AppLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const { data: user, isLoading } = useUser();

  useEffect(() => {
    if (!isLoading && !user) {
      router.replace('/login');
    }
  }, [isLoading, user, router]);

  if (isLoading) {
    return (
      <div className="flex h-screen items-center justify-center text-sm text-muted-foreground">
        Loading…
      </div>
    );
  }
  if (!user) return null;

  return (
    <div className="flex h-screen overflow-hidden bg-background">
      <AppSidebar user={user} />
      <main className="flex-1 min-w-0 overflow-y-auto">{children}</main>
    </div>
  );
}
