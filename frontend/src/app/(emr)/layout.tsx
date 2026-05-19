/**
 * EMR / treatment-record route-group shell.
 *
 * Mirrors the `(invoice)` pattern — the treatment record surface is
 * lifted out of the CRM dashboard chrome so providers can document
 * a visit in a focused window without the sidebar competing for
 * attention. Opened via `window.open(..., 'popup,width=...')` from
 * the calendar appointment popover.
 *
 * URL contract: `/emr/[appointmentId]`.
 */

'use client';

import { useRouter } from 'next/navigation';
import { useEffect } from 'react';

import { useUser } from '@/lib/auth';

export default function EmrShellLayout({ children }: { children: React.ReactNode }) {
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
    <div className="min-h-screen bg-muted/30 text-foreground antialiased">
      {children}
    </div>
  );
}
