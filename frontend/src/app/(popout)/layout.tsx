/**
 * Popout route-group shell.
 *
 * Sibling of `(app)`, `(calendar)`, `(auth)`. Used for surfaces meant
 * to live in their own browser window (opened via
 * `window.open(..., 'popup,width=…,height=…')`), such as the
 * /inbox window that the calendar tool rail spawns.
 *
 * No sidebar, no global chrome — just the auth gate and a slim
 * `<main>` container. Each popout page renders its own header so
 * the window feels self-contained.
 */

'use client';

import { useRouter } from 'next/navigation';
import { useEffect } from 'react';

import { useUser } from '@/lib/auth';

export default function PopoutLayout({ children }: { children: React.ReactNode }) {
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
    <div className="flex flex-col h-screen overflow-hidden bg-background">
      {children}
    </div>
  );
}
