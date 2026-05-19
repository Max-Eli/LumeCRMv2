/**
 * `/account` — personal account settings for the signed-in user.
 *
 * Available to every authenticated role (owner / manager / front_desk
 * / provider / bookkeeper / marketing). The only setting today is
 * password change; future tabs (profile photo, notification prefs,
 * MFA enrollment) slot in without restructuring the URL.
 *
 * Distinct from `/org/*` which is for business-level settings (an
 * owner-only surface). This is "me" settings, not "the business"
 * settings.
 */

'use client';

import { Lock, Mail, ShieldCheck } from 'lucide-react';
import { useState } from 'react';
import { toast } from 'sonner';

import { PageHeader } from '@/components/page-header';
import { Button } from '@/components/ui/button';
import { Field, FieldError, FieldLabel } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { ApiError } from '@/lib/api';
import { useChangePassword, useUser } from '@/lib/auth';

export default function AccountPage() {
  const { data: user } = useUser();

  return (
    <div className="px-4 sm:px-10 py-4 sm:py-10 max-w-2xl">
      <PageHeader
        title="Account"
        description="Your personal account settings — separate from your business settings."
      />

      {user ? (
        <section className="rounded-lg border bg-card px-4 sm:px-6 py-5 mb-6">
          <div className="flex items-center gap-3">
            <div className="inline-flex size-10 items-center justify-center rounded-md bg-muted">
              <Mail className="size-4 text-muted-foreground" />
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-xs uppercase tracking-wide text-muted-foreground">
                Signed in as
              </p>
              <p className="text-sm font-medium truncate">
                {user.first_name} {user.last_name}
              </p>
              <p className="text-xs text-muted-foreground truncate">{user.email}</p>
            </div>
          </div>
        </section>
      ) : null}

      <ChangePasswordCard />
    </div>
  );
}

function ChangePasswordCard() {
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [confirm, setConfirm] = useState('');
  const [errors, setErrors] = useState<{
    current?: string;
    next?: string[];
    confirm?: string;
  }>({});
  const change = useChangePassword();

  const reset = () => {
    setCurrent('');
    setNext('');
    setConfirm('');
    setErrors({});
  };

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setErrors({});

    if (next !== confirm) {
      setErrors({ confirm: "Doesn't match the new password." });
      return;
    }
    if (next.length < 8) {
      setErrors({ next: ['Password must be at least 8 characters.'] });
      return;
    }

    change.mutate(
      { current_password: current, new_password: next, confirm_password: confirm },
      {
        onSuccess: () => {
          toast.success('Password updated', {
            description: 'Other browser sessions have been signed out.',
          });
          reset();
        },
        onError: (err) => {
          if (err instanceof ApiError && err.status === 400 && err.body && typeof err.body === 'object') {
            const body = err.body as Record<string, unknown>;
            const next: typeof errors = {};
            if (typeof body.current_password === 'string') {
              next.current = body.current_password;
            }
            if (Array.isArray(body.new_password)) {
              next.next = body.new_password as string[];
            } else if (typeof body.new_password === 'string') {
              next.next = [body.new_password];
            }
            if (typeof body.confirm_password === 'string') {
              next.confirm = body.confirm_password;
            }
            setErrors(next);
            if (Object.keys(next).length === 0) {
              toast.error('Could not update password. Please try again.');
            }
            return;
          }
          toast.error('Could not update password. Please try again.');
        },
      },
    );
  };

  return (
    <section className="rounded-lg border bg-card">
      <header className="border-b px-4 sm:px-6 py-4 flex items-center gap-3">
        <div className="inline-flex size-9 items-center justify-center rounded-md bg-accent/10 text-accent-foreground">
          <ShieldCheck className="size-4" />
        </div>
        <div className="min-w-0">
          <h2 className="font-serif text-base font-semibold tracking-tight">
            Password
          </h2>
          <p className="text-xs text-muted-foreground mt-0.5">
            Used to sign in to the CRM. Changing it signs out every other
            browser session you have open.
          </p>
        </div>
      </header>

      <form onSubmit={onSubmit} className="px-4 sm:px-6 py-5 space-y-4">
        <Field data-invalid={errors.current ? true : undefined}>
          <FieldLabel htmlFor="current_password">Current password</FieldLabel>
          <Input
            id="current_password"
            type="password"
            autoComplete="current-password"
            value={current}
            onChange={(e) => setCurrent(e.target.value)}
            disabled={change.isPending}
            required
          />
          {errors.current ? <FieldError>{errors.current}</FieldError> : null}
        </Field>

        <Field data-invalid={errors.next ? true : undefined}>
          <FieldLabel htmlFor="new_password">New password</FieldLabel>
          <Input
            id="new_password"
            type="password"
            autoComplete="new-password"
            value={next}
            onChange={(e) => setNext(e.target.value)}
            disabled={change.isPending}
            required
            minLength={8}
          />
          {errors.next ? (
            <FieldError>
              {errors.next.length === 1 ? errors.next[0] : (
                <ul className="list-disc list-inside space-y-0.5">
                  {errors.next.map((m, i) => <li key={i}>{m}</li>)}
                </ul>
              )}
            </FieldError>
          ) : (
            <p className="text-xs text-muted-foreground mt-1">
              At least 8 characters. Mix in a number or symbol for a stronger password.
            </p>
          )}
        </Field>

        <Field data-invalid={errors.confirm ? true : undefined}>
          <FieldLabel htmlFor="confirm_password">Confirm new password</FieldLabel>
          <Input
            id="confirm_password"
            type="password"
            autoComplete="new-password"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            disabled={change.isPending}
            required
          />
          {errors.confirm ? <FieldError>{errors.confirm}</FieldError> : null}
        </Field>

        <div className="flex flex-col-reverse sm:flex-row sm:items-center sm:justify-end gap-2 pt-1">
          <Button
            type="button"
            variant="outline"
            onClick={reset}
            disabled={change.isPending}
            className="w-full sm:w-auto"
          >
            Discard
          </Button>
          <Button
            type="submit"
            disabled={change.isPending || !current || !next || !confirm}
            className="w-full sm:w-auto"
          >
            <Lock className="size-4" />
            {change.isPending ? 'Updating…' : 'Update password'}
          </Button>
        </div>
      </form>
    </section>
  );
}
