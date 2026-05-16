/**
 * `/platform/login` — dedicated platform admin login surface.
 *
 * Visually distinct from the customer-facing `/login` page:
 *   - Dark theme (inherits from `data-theme="platform"` set by the
 *     platform layout)
 *   - "PLATFORM CONSOLE" eyebrow + serif "Lumè" wordmark — different
 *     register from the customer login
 *   - Posts to `/api/auth/platform/login/` (NOT the regular endpoint)
 *
 * On success: redirect to `/platform`. On failure: generic "invalid
 * email or password" — the backend never tells us whether the email
 * exists on the customer surface, so we don't leak it either.
 */

'use client';

import { zodResolver } from '@hookform/resolvers/zod';
import { Lock } from 'lucide-react';
import { useRouter } from 'next/navigation';
import { useForm } from 'react-hook-form';
import { toast } from 'sonner';
import { z } from 'zod';

import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { Field, FieldError, FieldGroup, FieldLabel } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { ApiError } from '@/lib/api';
import { usePlatformLogin } from '@/lib/auth';

const schema = z.object({
  email: z.string().email('Enter a valid email'),
  password: z.string().min(1, 'Password is required'),
});

type FormValues = z.infer<typeof schema>;

export default function PlatformLoginPage() {
  const router = useRouter();
  const login = usePlatformLogin();

  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { email: '', password: '' },
  });

  const onSubmit = (values: FormValues) => {
    login.mutate(values, {
      onSuccess: () => {
        toast.success('Signed in to platform console');
        router.push('/platform');
      },
      onError: (err) => {
        if (err instanceof ApiError && (err.status === 401 || err.status === 403)) {
          form.setError('password', { message: 'Invalid email or password.' });
        } else {
          toast.error('Sign in failed. Please try again.');
        }
      },
    });
  };

  return (
    <div
      data-theme="platform"
      className="min-h-screen flex items-center justify-center bg-background text-foreground px-6 py-12"
    >
      <div className="w-full max-w-sm space-y-6">
        <div className="text-center space-y-3">
          <p className="text-[11px] uppercase tracking-[0.18em] text-accent font-semibold">
            Platform Console
          </p>
          <h1 className="font-serif text-3xl font-semibold tracking-tight text-foreground">
            Lumè
          </h1>
          <p className="text-xs text-muted-foreground">
            Internal — superuser access only.
          </p>
        </div>

        <Card className="border bg-card shadow-none">
          <CardHeader className="space-y-1.5">
            <CardTitle className="font-serif text-xl tracking-tight flex items-center gap-2">
              <Lock className="size-4 text-accent" aria-hidden />
              Sign in
            </CardTitle>
            <CardDescription>
              Platform admins only. Customer accounts sign in at /login.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={form.handleSubmit(onSubmit)} noValidate>
              <FieldGroup>
                <Field data-invalid={form.formState.errors.email ? true : undefined}>
                  <FieldLabel htmlFor="email">Email</FieldLabel>
                  <Input
                    id="email"
                    type="email"
                    autoComplete="email"
                    autoFocus
                    placeholder="you@xn--lumcrm-5ua.com"
                    disabled={login.isPending}
                    {...form.register('email')}
                  />
                  {form.formState.errors.email ? (
                    <FieldError>{form.formState.errors.email.message}</FieldError>
                  ) : null}
                </Field>

                <Field data-invalid={form.formState.errors.password ? true : undefined}>
                  <FieldLabel htmlFor="password">Password</FieldLabel>
                  <Input
                    id="password"
                    type="password"
                    autoComplete="current-password"
                    disabled={login.isPending}
                    {...form.register('password')}
                  />
                  {form.formState.errors.password ? (
                    <FieldError>{form.formState.errors.password.message}</FieldError>
                  ) : null}
                </Field>

                <Button type="submit" disabled={login.isPending} className="w-full">
                  {login.isPending ? 'Signing in…' : 'Sign in'}
                </Button>
              </FieldGroup>
            </form>
          </CardContent>
        </Card>

        <p className="text-center text-[11px] text-muted-foreground">
          Lost access? Run{' '}
          <code className="font-mono text-foreground/80">
            python manage.py createplatformadmin
          </code>{' '}
          on the server.
        </p>
      </div>
    </div>
  );
}
