/**
 * `/accept-invitation/[token]` — public landing page for an invited
 * staff member.
 *
 * The page does three things:
 *
 *   1. Look up the invitation by token (GET /api/auth/invitation/<token>/).
 *      The lookup returns the tenant name + role + who invited them, so
 *      the recipient knows they're in the right place before filling
 *      anything in. The lookup does NOT echo the recipient's email back
 *      — the token is the identifier; the email is for delivery only.
 *   2. Render an accept form (first name, last name, password) for a
 *      pending invitation.
 *   3. POST to /api/auth/invitation/accept/ to create the user +
 *      membership + log in. On success, redirect to /dashboard.
 *
 * Error states (expired, already accepted, unknown token, existing
 * account) render in-page with a clear next step (contact owner, or
 * sign in instead).
 *
 * See [ADR 0019 — Staff invitation flow](../../../../../docs/decisions/0019-staff-invitations.md).
 */

'use client';

import { zodResolver } from '@hookform/resolvers/zod';
import { Mail, ShieldCheck } from 'lucide-react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { use, useEffect, useState } from 'react';
import { useForm } from 'react-hook-form';
import { toast } from 'sonner';
import { z } from 'zod';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Field, FieldError, FieldGroup, FieldLabel } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { ApiError, api } from '@/lib/api';

interface InvitationLookup {
  tenant_name: string;
  tenant_slug: string;
  role: string;
  role_label: string;
  job_title_name: string | null;
  invited_by_name: string;
  expires_at: string;
  accepted_at: string | null;
  is_pending: boolean;
  is_expired: boolean;
}

const schema = z
  .object({
    first_name: z.string().min(1, 'Required').max(150),
    last_name: z.string().min(1, 'Required').max(150),
    password: z.string().min(12, 'At least 12 characters'),
    confirm_password: z.string(),
  })
  .refine((d) => d.password === d.confirm_password, {
    path: ['confirm_password'],
    message: "Passwords don't match",
  });

type FormValues = z.infer<typeof schema>;

export default function AcceptInvitationPage({
  params,
}: {
  params: Promise<{ token: string }>;
}) {
  const router = useRouter();
  const { token } = use(params);

  const [lookup, setLookup] = useState<InvitationLookup | null>(null);
  const [lookupError, setLookupError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // Look up the invitation once on mount. We do this directly with
  // `api.get` rather than a React Query hook because (a) it runs
  // once, (b) the token is in the URL so cache-key handling is moot,
  // and (c) the route is unauthenticated — the standard `api`
  // helpers still work (they just forward credentials/session
  // cookies, which are empty for this page).
  useEffect(() => {
    let cancelled = false;
    api
      .get<InvitationLookup>(`/api/auth/invitation/${token}/`)
      .then((data) => {
        if (!cancelled) setLookup(data);
      })
      .catch((err) => {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 404) {
          setLookupError("This invitation link isn't valid. Ask your spa owner to send a new one.");
        } else {
          setLookupError('Could not load the invitation. Try refreshing the page.');
        }
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { first_name: '', last_name: '', password: '', confirm_password: '' },
  });

  const onSubmit = (values: FormValues) => {
    setSubmitting(true);
    api
      .post<{ tenant_slug: string; redirect: string }>('/api/auth/invitation/accept/', {
        token,
        first_name: values.first_name.trim(),
        last_name: values.last_name.trim(),
        password: values.password,
      })
      .then((data) => {
        toast.success(`Welcome to ${lookup?.tenant_name ?? 'the team'}!`);
        router.push(data.redirect);
      })
      .catch((err) => {
        if (err instanceof ApiError && err.status === 400 && err.body && typeof err.body === 'object') {
          const body = err.body as { detail?: unknown; password?: unknown };
          if (typeof body.password === 'string') {
            form.setError('password', { message: body.password });
          } else if (typeof body.detail === 'string') {
            toast.error(body.detail);
          } else {
            toast.error('Could not accept the invitation.');
          }
        } else {
          toast.error('Could not accept the invitation. Please try again.');
        }
      })
      .finally(() => setSubmitting(false));
  };

  if (lookupError) {
    return <ErrorState message={lookupError} />;
  }

  if (!lookup) {
    return <LoadingState />;
  }

  if (lookup.accepted_at) {
    return (
      <ErrorState
        message="This invitation has already been accepted."
        nextStep={
          <p className="text-sm text-muted-foreground mt-3">
            <Link href="/login" className="font-medium text-foreground underline underline-offset-2">
              Sign in
            </Link>{' '}
            with the password you set when you accepted.
          </p>
        }
      />
    );
  }

  if (lookup.is_expired) {
    return (
      <ErrorState
        message="This invitation has expired."
        nextStep={
          <p className="text-sm text-muted-foreground mt-3">
            Ask {lookup.invited_by_name || 'your spa owner'} to send a new invitation.
          </p>
        }
      />
    );
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2 text-muted-foreground">
          <ShieldCheck className="size-4" />
          <p className="text-[11px] uppercase tracking-wider">Invitation</p>
        </div>
        <CardTitle className="font-serif text-2xl">
          Join {lookup.tenant_name}
        </CardTitle>
        <CardDescription>
          {lookup.invited_by_name ? (
            <>
              <span className="font-medium text-foreground">{lookup.invited_by_name}</span>{' '}
              invited you
            </>
          ) : (
            'You&apos;ve been invited'
          )}{' '}
          to join as <span className="font-medium text-foreground">{lookup.role_label}</span>
          {lookup.job_title_name ? ` (${lookup.job_title_name})` : ''}.
          Set your name and password to accept.
        </CardDescription>
      </CardHeader>

      <CardContent>
        <form onSubmit={form.handleSubmit(onSubmit)} noValidate>
          <FieldGroup>
            <div className="grid grid-cols-2 gap-3">
              <Field>
                <FieldLabel htmlFor="first_name">First name</FieldLabel>
                <Input id="first_name" autoFocus autoComplete="given-name" {...form.register('first_name')} />
                <FieldError>{form.formState.errors.first_name?.message}</FieldError>
              </Field>
              <Field>
                <FieldLabel htmlFor="last_name">Last name</FieldLabel>
                <Input id="last_name" autoComplete="family-name" {...form.register('last_name')} />
                <FieldError>{form.formState.errors.last_name?.message}</FieldError>
              </Field>
            </div>

            <Field>
              <FieldLabel htmlFor="password">Password</FieldLabel>
              <Input
                id="password"
                type="password"
                autoComplete="new-password"
                {...form.register('password')}
              />
              <p className="text-[11px] text-muted-foreground mt-1">
                At least 12 characters. Choose something you don&apos;t use
                elsewhere — your spa stores PHI and the password is your
                front door.
              </p>
              <FieldError>{form.formState.errors.password?.message}</FieldError>
            </Field>

            <Field>
              <FieldLabel htmlFor="confirm_password">Confirm password</FieldLabel>
              <Input
                id="confirm_password"
                type="password"
                autoComplete="new-password"
                {...form.register('confirm_password')}
              />
              <FieldError>{form.formState.errors.confirm_password?.message}</FieldError>
            </Field>

            <Button type="submit" disabled={submitting} className="w-full">
              <Mail className="size-4" />
              {submitting ? 'Accepting…' : 'Accept invitation'}
            </Button>
          </FieldGroup>
        </form>
      </CardContent>
    </Card>
  );
}

function LoadingState() {
  return (
    <Card>
      <CardContent className="py-12 text-center text-sm text-muted-foreground">
        Loading invitation…
      </CardContent>
    </Card>
  );
}

function ErrorState({
  message,
  nextStep,
}: {
  message: string;
  nextStep?: React.ReactNode;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="font-serif text-xl">Can&apos;t accept this invitation</CardTitle>
      </CardHeader>
      <CardContent>
        <p className="text-sm text-foreground">{message}</p>
        {nextStep}
        <div className="mt-6 text-sm text-muted-foreground">
          Already have a Lumè account?{' '}
          <Link href="/login" className="font-medium text-foreground underline underline-offset-2">
            Sign in
          </Link>
          .
        </div>
      </CardContent>
    </Card>
  );
}
