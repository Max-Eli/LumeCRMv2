/**
 * Root-level 404 — replaces Next.js's default barebones page.
 *
 * Lives at `app/not-found.tsx` so it covers any route the router
 * can't match across all route groups. Per-group `not-found.tsx`
 * files (e.g. inside `(portal)`) can be added later if a
 * customer-portal-flavoured 404 is wanted; for v1 the same screen
 * works everywhere.
 *
 * Client component so the "Go back" affordance can call
 * `router.back()` — the most useful action from a 404 in practice
 * (the user just clicked a stale link).
 */

'use client';

import { ArrowLeft, Home } from 'lucide-react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';

import { BrandMark } from '@/components/brand-mark';
import { Button } from '@/components/ui/button';

export default function NotFoundPage() {
  const router = useRouter();

  return (
    <div className="min-h-screen flex flex-col items-center justify-center bg-muted/30 px-6 py-16">
      <div className="max-w-md w-full text-center">
        <div className="mb-8 inline-flex">
          <BrandMark variant="icon" size={48} />
        </div>

        <p className="font-mono text-[11px] uppercase tracking-[0.2em] text-muted-foreground mb-3">
          404 · Page not found
        </p>
        <h1 className="font-serif text-3xl sm:text-4xl font-semibold tracking-tight">
          We couldn&rsquo;t find that page.
        </h1>
        <p className="text-sm text-muted-foreground mt-3 max-w-sm mx-auto leading-relaxed">
          The link may be broken or the page may have moved. Try one of the
          actions below to get back on track.
        </p>

        <div className="mt-8 flex flex-col sm:flex-row items-center justify-center gap-2">
          <Button
            type="button"
            variant="outline"
            onClick={() => router.back()}
          >
            <ArrowLeft className="size-4" />
            Go back
          </Button>
          <Button render={<Link href="/dashboard" />} nativeButton={false}>
            <Home className="size-4" />
            Go to dashboard
          </Button>
        </div>

        <p className="mt-12 text-[11px] text-muted-foreground">
          Need a hand? Reach out to your spa&rsquo;s team or
          <a
            href="mailto:support@lumecrm.com"
            className="ml-1 underline underline-offset-2 hover:text-foreground"
          >
            support@lumecrm.com
          </a>
          .
        </p>
      </div>
    </div>
  );
}
