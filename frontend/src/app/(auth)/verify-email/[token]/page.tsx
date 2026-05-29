/**
 * `/verify-email/<token>` — landing page for the post-signup email
 * verification link.
 *
 * Behavior:
 *   - On mount, POST the token to ``/api/auth/verify-email/<token>/``.
 *   - Backend marks the User as verified + invalidates the token.
 *   - On success: confirmation card with a "Continue" CTA to /login.
 *   - On 410: "this link is expired or already used" — operator can
 *     request a new link from their account settings (Phase 4).
 *
 * No auth required to land here — the new owner clicks the link
 * before they've ever logged in. The token itself is the credential.
 */

'use client';

import { AlertCircle, ArrowRight, CheckCircle2, Loader2 } from 'lucide-react';
import Link from 'next/link';
import { use, useEffect, useState } from 'react';

import { api, ApiError } from '@/lib/api';

type Status = 'loading' | 'success' | 'invalid' | 'error';

interface PageProps {
  params: Promise<{ token: string }>;
}

export default function VerifyEmailPage({ params }: PageProps) {
  const { token } = use(params);
  const [status, setStatus] = useState<Status>('loading');
  const [email, setEmail] = useState<string>('');

  useEffect(() => {
    let cancelled = false;

    const verify = async () => {
      try {
        const resp = await api.post<{ verified: boolean; email: string }>(
          `/api/auth/verify-email/${encodeURIComponent(token)}/`,
          {},
        );
        if (cancelled) return;
        setEmail(resp.email);
        setStatus('success');
      } catch (err) {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 410) {
          setStatus('invalid');
        } else {
          setStatus('error');
        }
      }
    };

    verify();
    return () => {
      cancelled = true;
    };
  }, [token]);

  return (
    <div className="min-h-screen flex items-center justify-center px-4 py-16">
      <div className="w-full max-w-md rounded-2xl border bg-card p-6 sm:p-8 shadow-sm">
        {status === 'loading' ? (
          <LoadingState />
        ) : status === 'success' ? (
          <SuccessState email={email} />
        ) : status === 'invalid' ? (
          <InvalidState />
        ) : (
          <ErrorState />
        )}
      </div>
    </div>
  );
}

// ── States ────────────────────────────────────────────────────────

function LoadingState() {
  return (
    <div className="text-center py-6 space-y-3">
      <Loader2 className="size-6 mx-auto animate-spin text-muted-foreground" />
      <p className="text-sm text-muted-foreground">Verifying your email…</p>
    </div>
  );
}

function SuccessState({ email }: { email: string }) {
  return (
    <div className="space-y-5">
      <div className="flex items-start gap-3">
        <CheckCircle2 className="size-6 text-emerald-600 dark:text-emerald-400 shrink-0 mt-0.5" />
        <div className="space-y-1">
          <h1 className="font-serif text-2xl font-semibold tracking-tight">
            Email verified
          </h1>
          <p className="text-sm text-muted-foreground">
            <span className="font-mono">{email}</span> is now confirmed on your
            Lumè account.
          </p>
        </div>
      </div>
      <Link
        href="/login"
        className="inline-flex w-full items-center justify-center gap-2 h-11 rounded-md bg-foreground text-background text-sm font-medium hover:bg-foreground/90 transition-colors"
      >
        Continue to login
        <ArrowRight className="size-4" />
      </Link>
    </div>
  );
}

function InvalidState() {
  return (
    <div className="space-y-5">
      <div className="flex items-start gap-3">
        <AlertCircle className="size-6 text-amber-600 dark:text-amber-400 shrink-0 mt-0.5" />
        <div className="space-y-1">
          <h1 className="font-serif text-2xl font-semibold tracking-tight">
            Link expired or used
          </h1>
          <p className="text-sm text-muted-foreground">
            This verification link is no longer valid. Verification links
            expire after 7 days and can only be used once.
          </p>
        </div>
      </div>
      <div className="rounded-md border border-border bg-muted/30 p-3 text-xs text-muted-foreground leading-relaxed">
        Sign in to your account and request a new verification email from
        your account settings. Until then, you can still use Lumè — only
        a few operations (sending marketing campaigns, inviting staff)
        require a verified address.
      </div>
      <Link
        href="/login"
        className="inline-flex w-full items-center justify-center gap-2 h-11 rounded-md bg-foreground text-background text-sm font-medium hover:bg-foreground/90 transition-colors"
      >
        Continue to login
      </Link>
    </div>
  );
}

function ErrorState() {
  return (
    <div className="space-y-5">
      <div className="flex items-start gap-3">
        <AlertCircle className="size-6 text-rose-600 dark:text-rose-400 shrink-0 mt-0.5" />
        <div className="space-y-1">
          <h1 className="font-serif text-2xl font-semibold tracking-tight">
            Something went wrong
          </h1>
          <p className="text-sm text-muted-foreground">
            We couldn&apos;t verify your email right now. Please try the link
            again in a minute. If the problem persists, email{' '}
            <a
              href="mailto:support@lume-crm.com"
              className="underline text-foreground"
            >
              support@lume-crm.com
            </a>.
          </p>
        </div>
      </div>
      <Link
        href="/login"
        className="inline-flex w-full items-center justify-center gap-2 h-11 rounded-md border border-border bg-card text-sm font-medium hover:bg-muted transition-colors"
      >
        Back to login
      </Link>
    </div>
  );
}
