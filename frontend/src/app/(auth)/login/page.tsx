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

const schema = z.object({
  email: z.string().email('Enter a valid email'),
  password: z.string().min(1, 'Password is required'),
});

type FormValues = z.infer<typeof schema>;

export default function LoginPage() {
  const router = useRouter();
  const login = useLogin();

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
      <div className="text-center">
        <Link href="/" className="inline-block" aria-label="Lumè">
          <Image
            src="/logosquare.png"
            alt="Lumè"
            width={120}
            height={120}
            priority
          />
        </Link>
      </div>

      <Card className="border-0 shadow-sm">
        <CardHeader className="space-y-1.5">
          <CardTitle className="font-serif text-2xl tracking-tight">Sign in</CardTitle>
          <CardDescription>Enter your email and password to continue.</CardDescription>
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
