/**
 * `/portal/magic/[token]` — consumes the magic-link token, sets the
 * portal session cookie, and redirects to /portal.
 *
 * The token in the URL path is consumed via POST to the backend (not
 * GET) to keep accidental prefetches / link previews from spending
 * the single-use token. We render a brief "Signing you in…" state
 * while the request is in flight.
 */

'use client';

import { Loader2, ShieldAlert } from 'lucide-react';
import Link from 'next/link';
import { useParams, useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';

import { ApiError } from '@/lib/api';
import { useConsumeMagicLink } from '@/lib/portal';

import { Button } from '@/components/ui/button';

export default function PortalMagicConsumePage() {
  const params = useParams();
  const router = useRouter();
  const token = typeof params?.token === 'string' ? params.token : '';
  const consume = useConsumeMagicLink();
  const [error, setError] = useState<string | null>(null);

  // Fire the consume once on mount. We use a guard ref-like state
  // pattern so React's strict-mode double-invoke doesn't burn two
  // tokens (the second would 410).
  useEffect(() => {
    let cancelled = false;
    if (!token) {
      setError('Missing sign-in token in URL.');
      return () => {
        cancelled = true;
      };
    }
    consume
      .mutateAsync({ token })
      .then(() => {
        if (!cancelled) router.replace('/portal');
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        if (err instanceof ApiError && err.body && typeof err.body === 'object') {
          const detail = (err.body as { detail?: string }).detail;
          setError(
            detail ||
              'This sign-in link is no longer valid. Request a new one from the sign-in page.',
          );
        } else {
          setError('Could not sign you in. Try requesting a new link.');
        }
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  return (
    <div className="flex-1 flex items-center justify-center px-4 py-12 bg-muted/40">
      <div className="w-full max-w-md">
        <div className="bg-card border rounded-xl shadow-sm px-8 py-10 text-center">
          {error ? (
            <>
              <ShieldAlert className="size-8 mx-auto mb-3 text-amber-600" />
              <h1 className="font-serif text-xl font-semibold tracking-tight">
                Sign-in link expired
              </h1>
              <p className="text-sm text-muted-foreground mt-2 leading-relaxed">
                {error}
              </p>
              <Button
                render={<Link href="/portal/login" />}
                nativeButton={false}
                className="mt-5"
                style={{ background: 'var(--portal-brand, #1f2937)', color: '#fff' }}
              >
                Request a new link
              </Button>
            </>
          ) : (
            <>
              <Loader2 className="size-6 mx-auto mb-3 animate-spin text-muted-foreground" />
              <p className="text-sm text-muted-foreground">Signing you in…</p>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
