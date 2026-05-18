/**
 * `/portal/login` — customer sign-in entry point.
 *
 * Email-only form: customer enters their email, we POST to the
 * magic-link request endpoint, and show a "check your email"
 * confirmation. The backend's response is identical whether or not
 * the email matches a customer (email-enumeration defense), so the
 * confirmation copy is intentionally non-committal.
 *
 * The layout above handles already-authenticated customers landing
 * here — they get bounced to /portal.
 */

'use client';

import { ArrowRight, CheckCircle2, Loader2 } from 'lucide-react';
import { useState } from 'react';

import { ApiError } from '@/lib/api';
import { usePublicBranding } from '@/lib/branding';
import { useRequestMagicLink } from '@/lib/portal';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

export default function PortalLoginPage() {
  const [email, setEmail] = useState('');
  const [submitted, setSubmitted] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const request = useRequestMagicLink();
  const branding = usePublicBranding();
  const tenant = branding.data ?? null;

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      await request.mutateAsync({ email: email.trim() });
      setSubmitted(true);
    } catch (err) {
      if (err instanceof ApiError && err.body && typeof err.body === 'object') {
        const detail =
          (err.body as { detail?: string }).detail ??
          (err.body as { email?: string[] }).email?.[0];
        setError(detail || 'Could not send the sign-in link. Try again in a moment.');
      } else {
        setError('Could not send the sign-in link. Try again in a moment.');
      }
    }
  };

  return (
    <div className="flex-1 flex items-center justify-center px-4 py-12 bg-muted/40">
      <div className="w-full max-w-md">
        <div className="bg-card border rounded-xl shadow-sm overflow-hidden">
          <div className="px-8 pt-8 pb-4 text-center">
            {tenant?.logo_url ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={tenant.logo_url}
                alt={tenant.name}
                className="mx-auto h-16 w-auto max-w-[200px] object-contain mb-3"
              />
            ) : (
              // Falls back to the neutral branded accent when a tenant
              // hasn't uploaded a logo (or no tenant resolves).
              <div
                className="mx-auto size-12 rounded-full inline-flex items-center justify-center mb-3"
                style={{ background: tenant?.primary_color || 'var(--portal-brand, #1f2937)' }}
              >
                <div className="size-4 rounded-full bg-white/80" />
              </div>
            )}
            <h1 className="font-serif text-2xl font-semibold tracking-tight">
              {tenant && !tenant.logo_url ? tenant.name : 'Sign in'}
            </h1>
            <p className="text-sm text-muted-foreground mt-1.5">
              We&apos;ll email you a one-time sign-in link.
            </p>
          </div>

          <div className="px-8 pb-8">
            {submitted ? (
              <div className="text-center space-y-3 py-2">
                <CheckCircle2
                  className="size-8 mx-auto"
                  style={{ color: 'var(--portal-brand, #1f2937)' }}
                />
                <p className="text-sm font-medium">Check your inbox</p>
                <p className="text-xs text-muted-foreground leading-relaxed">
                  If that email is on file, we just sent a sign-in link.
                  It expires in 30 minutes and can only be used once.
                </p>
                <button
                  type="button"
                  onClick={() => {
                    setSubmitted(false);
                    setEmail('');
                  }}
                  className="text-xs text-muted-foreground hover:text-foreground transition-colors underline underline-offset-2 mt-2"
                >
                  Use a different email
                </button>
              </div>
            ) : (
              <form onSubmit={onSubmit} className="space-y-3">
                <div>
                  <label htmlFor="email" className="text-xs font-medium block mb-1.5">
                    Email
                  </label>
                  <Input
                    id="email"
                    type="email"
                    autoComplete="email"
                    autoFocus
                    required
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="you@example.com"
                  />
                </div>
                {error ? (
                  <p className="text-xs text-destructive">{error}</p>
                ) : null}
                <Button
                  type="submit"
                  className="w-full"
                  disabled={request.isPending || !email.trim()}
                  style={{
                    background: 'var(--portal-brand, #1f2937)',
                    color: '#fff',
                  }}
                >
                  {request.isPending ? (
                    <Loader2 className="size-4 animate-spin" />
                  ) : null}
                  Send sign-in link
                  <ArrowRight className="size-4" />
                </Button>
              </form>
            )}
          </div>
        </div>

        <p className="text-center text-[11px] text-muted-foreground mt-6">
          Powered by Lumè
        </p>
      </div>
    </div>
  );
}
