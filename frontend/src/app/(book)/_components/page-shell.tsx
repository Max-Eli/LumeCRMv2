/**
 * Shared page-shell pieces for the public booking pages.
 *
 * `BookingPageState` renders a centered icon + title + message —
 * used for loading, 404, and error states. Mirrors the pattern in
 * `/sign/[token]/page.tsx` so the two public surfaces feel
 * consistent.
 */

'use client';

import { Loader2, XCircle } from 'lucide-react';

import { cn } from '@/lib/utils';

export function BookingPageState({
  icon,
  title,
  message,
  tone = 'default',
}: {
  icon?: React.ReactNode;
  title: string;
  message?: string;
  tone?: 'default' | 'destructive' | 'muted';
}) {
  return (
    <div className="min-h-[calc(100vh-65px)] flex items-center justify-center px-4 py-16">
      <div className="max-w-md text-center">
        {icon ? <div className="flex justify-center mb-4">{icon}</div> : null}
        <h2
          className={cn(
            'font-serif text-2xl font-semibold tracking-tight mb-2',
            tone === 'destructive' && 'text-stone-900',
            tone === 'muted' && 'text-stone-700',
          )}
        >
          {title}
        </h2>
        {message ? (
          <p className="text-sm text-stone-600 leading-relaxed">{message}</p>
        ) : null}
      </div>
    </div>
  );
}

export function BookingLoadingState({ message = 'Loading…' }: { message?: string }) {
  return (
    <BookingPageState
      icon={<Loader2 className="size-6 animate-spin text-stone-500" />}
      title={message}
    />
  );
}

export function BookingNotFoundState({
  title = 'Not found',
  message,
}: {
  title?: string;
  message?: string;
}) {
  return (
    <BookingPageState
      tone="destructive"
      icon={<XCircle className="size-7 text-stone-700" />}
      title={title}
      message={message ?? 'This page doesn’t exist or is no longer available.'}
    />
  );
}

export function BookingContainer({ children }: { children: React.ReactNode }) {
  return (
    <main className="max-w-3xl mx-auto px-4 sm:px-6 py-8 sm:py-12">{children}</main>
  );
}
