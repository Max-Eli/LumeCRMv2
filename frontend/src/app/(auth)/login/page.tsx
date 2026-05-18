'use client';

import { zodResolver } from '@hookform/resolvers/zod';
import Image from 'next/image';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useForm } from 'react-hook-form';
import { toast } from 'sonner';
import { z } from 'zod';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Field, FieldError, FieldGroup, FieldLabel } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { ApiError } from '@/lib/api';
import { useLogin } from '@/lib/auth';
import { usePublicBranding } from '@/lib/branding';

const schema = z.object({
  email: z.string().email('Enter a valid email'),
  password: z.string().min(1, 'Password is required'),
});

type FormValues = z.infer<typeof schema>;

export default function LoginPage() {
  const router = useRouter();
  const login = useLogin();
  const branding = usePublicBranding();
  const tenant = branding.data ?? null;

  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { email: '', password: '' },
  });

  const onSubmit = (values: FormValues) => {
    login.mutate(values, {
      onSuccess: () => {
        toast.success('Signed in');
        router.push('/dashboard');
      },
      onError: (err) => {
        if (err instanceof ApiError && err.status === 401) {
          // Platform admins get a structured error code so we can
          // redirect them to their dedicated login surface rather
          // than show a misleading "wrong password" message.
          const body = err.body as { code?: string } | null;
          if (body?.code === 'platform_admin_account') {
            toast.message('Platform admin accounts sign in elsewhere.', {
              description: 'Redirecting to /platform/login…',
            });
            setTimeout(() => router.push('/platform/login'), 500);
            return;
          }
          form.setError('password', { message: 'Invalid email or password.' });
        } else {
          toast.error('Sign in failed. Please try again.');
        }
      },
    });
  };

  return (
    <div className="space-y-8">
      <div className="text-center space-y-3">
        <Link href="/" className="inline-block" aria-label={tenant?.name ?? 'Lumè'}>
          {tenant?.logo_url ? (
            // Tenant-supplied logos can be any aspect ratio (PNG / SVG)
            // hosted on S3 or any public URL; an unconstrained <img>
            // with object-contain gives them predictable sizing without
            // forcing Next/Image's domain allowlist.
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={tenant.logo_url}
              alt={tenant.name}
              className="mx-auto h-20 w-auto max-w-[220px] object-contain"
            />
          ) : (
            <Image
              src="/logosquare.png"
              alt="Lumè"
              width={120}
              height={120}
              priority
            />
          )}
        </Link>
        {tenant ? (
          <p className="font-serif text-sm tracking-tight text-muted-foreground">
            {tenant.name}
          </p>
        ) : null}
      </div>

      <Card className="border-0 shadow-sm">
        <CardHeader className="space-y-1.5">
          <CardTitle className="font-serif text-2xl tracking-tight">Sign in</CardTitle>
          <CardDescription>
            {tenant
              ? `Sign in to ${tenant.name}.`
              : 'Enter your email and password to continue.'}
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
                  placeholder="you@yourspa.com"
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
                  {...form.register('password')}
                />
                {form.formState.errors.password ? (
                  <FieldError>{form.formState.errors.password.message}</FieldError>
                ) : null}
              </Field>

              <Button type="submit" className="w-full" disabled={login.isPending}>
                {login.isPending ? 'Signing in…' : 'Sign in'}
              </Button>
            </FieldGroup>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
