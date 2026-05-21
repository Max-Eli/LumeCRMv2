/**
 * Invoice route-group shell.
 *
 * The invoice / payment surface is intentionally hoisted out of the
 * main `(app)` chrome — no sidebar, no top bar. Take-payment flows
 * are usually opened in a separate window from the calendar popover
 * or the customer wallet tab, and operators expect them to feel like
 * a focused payment terminal rather than a tab inside the CRM.
 *
 * Mirrors the `(popout)` and `(calendar)` patterns: own auth gate,
 * full-height container, each page renders its own header.
 *
 * URL contract: `/invoice/[id]` — `[id]` is an appointment id by
 * default, or an invoice id when `?by=invoice` is set (standalone
 * invoices with no appointment, e.g. custom packages). Open the page
 * with `target="_blank"` so it lives in its own browser tab/window.
 */

'use client';

import { useRouter } from 'next/navigation';
import { useEffect } from 'react';

import { useUser } from '@/lib/auth';

export default function InvoiceShellLayout({ children }: { children: React.ReactNode }) {
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
