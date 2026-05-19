/**
 * `/sign/[token]` — public form fill page.
 *
 * UNAUTHENTICATED. Lives outside the `(app)` layout group so it
 * doesn't inherit the auth gate, sidebar, or any app chrome. The
 * token in the URL IS the security boundary — see ADR 0011.
 *
 * Three states:
 *   - **pending** — render the schema as a fillable form with a
 *     signature canvas at the bottom. Submit transitions to completed.
 *   - **completed** — render the answers + signature in read-only
 *     mode (the same URL serves the operator-facing "view this signed
 *     form" flow without a separate route).
 *   - **voided** — show a clear "this form has been voided; contact
 *     the spa for a new link" message.
 *
 * Designed mobile-first because the most common contexts are
 * (1) client opens an SMS / email link on their phone, and
 * (2) front-desk hands an iPad across the counter at check-in.
 */

'use client';

import {
  Check,
  CircleAlert,
  CircleCheck,
  Loader2,
  Lock,
  ShieldCheck,
  Unlock,
  X,
  XCircle,
} from 'lucide-react';
import Link from 'next/link';
import { use, useCallback, useEffect, useRef, useState } from 'react';

import {
  SignatureCanvas,
  type SignatureCanvasHandle,
} from '@/components/signature-canvas';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Field, FieldError, FieldLabel } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { ApiError } from '@/lib/api';
import { useVerifyCredentials } from '@/lib/auth';
import {
  type PublicFormSubmission,
  useSubmitPublicForm,
  usePublicSubmission,
} from '@/lib/form-submissions';
import {
  type FormField,
  isChoiceField,
} from '@/lib/form-templates';
import { cn } from '@/lib/utils';

export default function PublicSignPage({
  params,
}: {
  params: Promise<{ token: string }>;
}) {
  const { token } = use(params);
  const { data: submission, isLoading, error } = usePublicSubmission(token);

  if (isLoading) {
    return (
      <FullPageState
        icon={<Loader2 className="size-6 animate-spin text-muted-foreground" />}
        title="Loading…"
        message="Just a moment while we pull up your form."
      />
    );
  }

  if (error || !submission) {
    const is404 = error instanceof ApiError && error.status === 404;
    return (
      <FullPageState
        tone="destructive"
        icon={<XCircle className="size-7 text-destructive" />}
        title={is404 ? 'Form not found' : 'Could not load form'}
        message={
          is404
            ? "This signing link doesn't exist or has been replaced. If you think this is a mistake, contact the spa."
            : 'Please refresh and try again. If the problem persists, contact the spa.'
        }
      />
    );
  }

  if (submission.status === 'voided') {
    return (
      <FullPageState
        tone="muted"
        icon={<CircleAlert className="size-7 text-muted-foreground" />}
        title="This form has been voided"
        message="The spa replaced this form with a new one. Please contact them for the updated link."
      />
    );
  }

  if (submission.status === 'completed') {
    return <SignedView submission={submission} />;
  }

  return <FillView submission={submission} token={token} />;
}

// ── Pending fill view ──────────────────────────────────────────────

function FillView({
  submission,
  token,
}: {
  submission: PublicFormSubmission;
  token: string;
}) {
  const submit = useSubmitPublicForm(token);
  const signatureRef = useRef<SignatureCanvasHandle>(null);
  const [answers, setAnswers] = useState<Record<string, unknown>>({});
  const [submitError, setSubmitError] = useState<string | null>(null);

  const fields = submission.schema_snapshot.fields;
  const nonSignatureFields = fields.filter((f) => f.type !== 'signature');
  const signatureField = fields.find((f) => f.type === 'signature');

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitError(null);

    // Validate required fields client-side. The backend re-validates
    // against the schema snapshot, but inline feedback is friendlier
    // than scrolling back from a server-side error.
    for (const field of nonSignatureFields) {
      if (!field.required) continue;
      const value = answers[field.id];
      const isEmpty =
        value === undefined ||
        value === null ||
        value === '' ||
        (Array.isArray(value) && value.length === 0);
      if (isEmpty) {
        setSubmitError(`Please answer "${field.label}" before signing.`);
        return;
      }
    }

    const signatureData = signatureRef.current?.getSignatureDataUrl() ?? '';
    if (!signatureData) {
      setSubmitError('Please sign the form before submitting.');
      return;
    }

    submit.mutate(
      { answers, signature_data: signatureData },
      {
        onError: (err) => {
          if (err instanceof ApiError && err.status === 409) {
            setSubmitError('This form has already been signed. Refresh the page to see the signed copy.');
          } else if (
            err instanceof ApiError &&
            err.status === 400 &&
            typeof err.body === 'object' &&
            err.body
          ) {
            const body = err.body as Record<string, string[] | string>;
            const firstField = Object.keys(body)[0];
            setSubmitError(
              firstField
                ? Array.isArray(body[firstField])
                  ? (body[firstField] as string[])[0]
                  : String(body[firstField])
                : 'Could not submit. Please review your answers.',
            );
          } else {
            setSubmitError('Could not submit. Please try again.');
          }
        },
      },
    );
  };

  return (
    <KioskShell>
      <div className="min-h-screen bg-stone-50/60 pb-12">
        <BrandedHeader submission={submission} />

        <div className="max-w-2xl mx-auto px-4 sm:px-6 pt-6 sm:pt-10">
          <header className="mb-6 sm:mb-8">
            <p className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground font-semibold">
              Consent &amp; intake form
            </p>
            <h1 className="font-serif text-2xl sm:text-[2rem] leading-[1.1] font-semibold tracking-tight mt-2">
              {submission.template_name}
            </h1>
            {submission.customer_first_name ? (
              <p className="text-sm text-muted-foreground mt-3">
                Hi {submission.customer_first_name} — please review the form
                below and sign at the bottom.
              </p>
            ) : null}
          </header>

          <form onSubmit={handleSubmit} className="space-y-5">
          {nonSignatureFields.map((field) => (
            <FieldRenderer
              key={field.id}
              field={field}
              value={answers[field.id]}
              onChange={(v) => setAnswers((prev) => ({ ...prev, [field.id]: v }))}
            />
          ))}

          {signatureField ? (
            <Field>
              <FieldLabel>
                {signatureField.label}
                {signatureField.required ? (
                  <span className="text-destructive ml-1">*</span>
                ) : null}
              </FieldLabel>
              <SignatureCanvas ref={signatureRef} />
              {'help_text' in signatureField && signatureField.help_text ? (
                <p className="text-[11px] text-muted-foreground mt-1">
                  {signatureField.help_text}
                </p>
              ) : null}
            </Field>
          ) : null}

          {submitError ? (
            <div className="rounded-md border border-destructive/40 bg-destructive/[0.04] px-3 py-2.5 flex items-start gap-2 text-sm">
              <CircleAlert className="size-4 shrink-0 text-destructive mt-0.5" />
              <p className="text-foreground/90">{submitError}</p>
            </div>
          ) : null}

          <Button
            type="submit"
            className="w-full sm:w-auto"
            disabled={submit.isPending}
            size="lg"
          >
            <Check className="size-4" />
            {submit.isPending ? 'Submitting…' : 'Submit & sign'}
          </Button>

          <p className="text-[11px] text-muted-foreground/80 leading-relaxed pt-2">
            By submitting, you confirm the information above is accurate to the
            best of your knowledge. Your signature, IP address, and the time
            of signing are recorded for your record.
          </p>
          </form>
        </div>
      </div>
    </KioskShell>
  );
}

// ── Branded header ─────────────────────────────────────────────────
//
// Spa logo on the left, name on the right (or just the name if no
// logo). Sits above the form so the patient sees who they're signing
// for before anything else.

function BrandedHeader({ submission }: { submission: PublicFormSubmission }) {
  const logo = submission.tenant_logo_url?.trim();
  const name = submission.tenant_name?.trim();
  if (!logo && !name) {
    return null;
  }
  return (
    <header className="bg-white border-b border-stone-200/80">
      <div className="max-w-2xl mx-auto px-4 sm:px-6 h-16 sm:h-20 flex items-center gap-3">
        {logo ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={logo}
            alt={name || 'Spa logo'}
            className="h-10 sm:h-12 w-auto max-w-[220px] object-contain"
          />
        ) : (
          <span className="font-serif text-base sm:text-lg font-semibold tracking-tight text-stone-900">
            {name}
          </span>
        )}
      </div>
    </header>
  );
}

// ── Kiosk lock ─────────────────────────────────────────────────────
//
// Front-desk hands the iPad to a customer to fill + sign. The Lock
// button puts the page into a hardened kiosk mode:
//   - Goes fullscreen (Fullscreen API) — hides browser chrome on
//     Safari + Chrome on tablets.
//   - Re-enters fullscreen automatically if the user exits.
//   - Blocks the back button by re-pushing the same history entry.
//   - Surfaces a banner with an "Unlock" affordance.
//
// To unlock, ANY staff member at the tenant types their email +
// password (verified by `/api/auth/verify-credentials/`, which does
// NOT open a session — the customer's anonymous fill session keeps
// going).
//
// Web kiosk is not bulletproof — a determined user can still open
// iPad app switcher or use Guided Access escapes. For true lockdown
// pair this with iOS's built-in Guided Access (Settings →
// Accessibility → Guided Access) which restricts the iPad to a
// single app entirely.

function KioskShell({ children }: { children: React.ReactNode }) {
  const [locked, setLocked] = useState(false);
  const [unlockOpen, setUnlockOpen] = useState(false);

  const enterFullscreen = useCallback(async () => {
    try {
      if (document.documentElement.requestFullscreen) {
        await document.documentElement.requestFullscreen();
      }
    } catch {
      // Fullscreen API can refuse (already fullscreen, user gesture
      // requirement, iframe context, etc.) — silently degrade.
    }
  }, []);

  const exitFullscreen = useCallback(async () => {
    try {
      if (document.fullscreenElement && document.exitFullscreen) {
        await document.exitFullscreen();
      }
    } catch {
      // ignore
    }
  }, []);

  // Re-enter fullscreen any time the user escapes it while locked.
  useEffect(() => {
    if (!locked) return;
    const onFullscreenChange = () => {
      if (locked && !document.fullscreenElement) {
        void enterFullscreen();
      }
    };
    document.addEventListener('fullscreenchange', onFullscreenChange);
    return () => document.removeEventListener('fullscreenchange', onFullscreenChange);
  }, [locked, enterFullscreen]);

  // Block the browser back button while locked. We push a sentinel
  // entry on lock; any popstate (back/forward gesture) re-pushes it
  // so the patient can't navigate away. Released on unlock.
  useEffect(() => {
    if (!locked) return;
    window.history.pushState({ kioskLocked: true }, '');
    const onPop = () => {
      window.history.pushState({ kioskLocked: true }, '');
    };
    window.addEventListener('popstate', onPop);
    return () => window.removeEventListener('popstate', onPop);
  }, [locked]);

  // Prompt before close/refresh while locked.
  useEffect(() => {
    if (!locked) return;
    const onBeforeUnload = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = '';
    };
    window.addEventListener('beforeunload', onBeforeUnload);
    return () => window.removeEventListener('beforeunload', onBeforeUnload);
  }, [locked]);

  const onLock = () => {
    setLocked(true);
    void enterFullscreen();
  };

  const onUnlockSuccess = () => {
    setLocked(false);
    setUnlockOpen(false);
    void exitFullscreen();
  };

  return (
    <>
      {locked ? <KioskBanner onRequestUnlock={() => setUnlockOpen(true)} /> : null}
      <div className={cn(locked && 'pt-12')}>{children}</div>
      {!locked ? <KioskLockFab onClick={onLock} /> : null}
      <UnlockDialog
        open={unlockOpen}
        onOpenChange={setUnlockOpen}
        onSuccess={onUnlockSuccess}
      />
    </>
  );
}

function KioskBanner({ onRequestUnlock }: { onRequestUnlock: () => void }) {
  return (
    <div className="fixed inset-x-0 top-0 z-40 h-12 bg-stone-900 text-white flex items-center justify-between px-4 sm:px-6 shadow-md">
      <div className="flex items-center gap-2 text-sm">
        <Lock className="size-4" aria-hidden />
        <span className="font-medium">Kiosk mode</span>
        <span className="hidden sm:inline text-white/70">
          · Pass the device to the patient to complete this form
        </span>
      </div>
      <Button
        type="button"
        size="sm"
        variant="outline"
        onClick={onRequestUnlock}
        className="bg-white/10 border-white/30 text-white hover:bg-white/20 hover:text-white"
      >
        <Unlock className="size-3.5" />
        Unlock
      </Button>
    </div>
  );
}

function KioskLockFab({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      title="Lock to kiosk mode — for staff use before handing the device to a patient"
      className="fixed bottom-4 right-4 z-30 inline-flex items-center gap-2 rounded-full bg-stone-900 px-4 py-2.5 text-sm font-medium text-white shadow-lg hover:bg-stone-800 transition-colors"
    >
      <Lock className="size-3.5" />
      Lock to kiosk
    </button>
  );
}

function UnlockDialog({
  open,
  onOpenChange,
  onSuccess,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSuccess: () => void;
}) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const verify = useVerifyCredentials();

  const reset = () => {
    setEmail('');
    setPassword('');
    setError(null);
  };

  useEffect(() => {
    if (!open) {
      // Wipe credentials when the dialog closes so they don't linger
      // in memory for the next time it opens.
      reset();
    }
  }, [open]);

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    verify.mutate(
      { email: email.trim().toLowerCase(), password },
      {
        onSuccess: () => {
          reset();
          onSuccess();
        },
        onError: (err) => {
          if (err instanceof ApiError && err.status === 401) {
            setError('Invalid email or password.');
          } else {
            setError('Could not verify — please try again.');
          }
        },
      },
    );
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <div className="flex items-center gap-3">
            <div className="inline-flex size-9 items-center justify-center rounded-md bg-stone-900 text-white">
              <ShieldCheck className="size-4" />
            </div>
            <div>
              <DialogTitle className="font-serif">Staff unlock</DialogTitle>
              <DialogDescription>
                Sign in with any staff account at this spa to unlock the page.
              </DialogDescription>
            </div>
          </div>
        </DialogHeader>

        <form onSubmit={onSubmit} className="space-y-4 mt-2">
          <Field>
            <FieldLabel htmlFor="unlock_email">Staff email</FieldLabel>
            <Input
              id="unlock_email"
              type="email"
              autoComplete="username"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              autoFocus
              disabled={verify.isPending}
            />
          </Field>
          <Field>
            <FieldLabel htmlFor="unlock_password">Password</FieldLabel>
            <Input
              id="unlock_password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              disabled={verify.isPending}
            />
          </Field>
          {error ? (
            <div className="rounded-md border border-destructive/40 bg-destructive/[0.04] px-3 py-2 flex items-start gap-2 text-sm">
              <CircleAlert className="size-4 shrink-0 text-destructive mt-0.5" />
              <p className="text-foreground/90">{error}</p>
            </div>
          ) : null}
          <DialogFooter className="flex-col-reverse sm:flex-row sm:items-center sm:justify-end gap-2">
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
              disabled={verify.isPending}
              className="w-full sm:w-auto"
            >
              Cancel
            </Button>
            <Button
              type="submit"
              disabled={verify.isPending || !email.trim() || !password}
              className="w-full sm:w-auto"
            >
              {verify.isPending ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <Unlock className="size-4" />
              )}
              Unlock
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

// ── Field renderers (pending fill) ──────────────────────────────────

function FieldRenderer({
  field,
  value,
  onChange,
}: {
  field: FormField;
  value: unknown;
  onChange: (v: unknown) => void;
}) {
  if (field.type === 'paragraph') {
    return (
      <section className="rounded-md border bg-muted/30 px-4 py-3.5">
        <h3 className="font-serif text-sm font-semibold tracking-tight text-foreground">
          {field.label}
        </h3>
        <p className="text-[13px] text-foreground/85 mt-2 leading-relaxed whitespace-pre-line">
          {field.body}
        </p>
      </section>
    );
  }
  return (
    <Field>
      <FieldLabel>
        {field.label}
        {field.required ? <span className="text-destructive ml-1">*</span> : null}
      </FieldLabel>
      {'help_text' in field && field.help_text ? (
        <p className="text-[11px] text-muted-foreground -mt-0.5">
          {field.help_text}
        </p>
      ) : null}
      <FieldControl field={field} value={value} onChange={onChange} />
    </Field>
  );
}

function FieldControl({
  field,
  value,
  onChange,
}: {
  field: FormField;
  value: unknown;
  onChange: (v: unknown) => void;
}) {
  switch (field.type) {
    case 'short_text':
      return (
        <Input
          value={typeof value === 'string' ? value : ''}
          onChange={(e) => onChange(e.target.value)}
          placeholder={'placeholder' in field ? field.placeholder : undefined}
        />
      );
    case 'long_text':
      return (
        <textarea
          value={typeof value === 'string' ? value : ''}
          onChange={(e) => onChange(e.target.value)}
          rows={4}
          placeholder={'placeholder' in field ? field.placeholder : undefined}
          className="w-full rounded-md border bg-background px-3 py-2 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 resize-y"
        />
      );
    case 'date':
      return (
        <Input
          type="date"
          value={typeof value === 'string' ? value : ''}
          onChange={(e) => onChange(e.target.value)}
        />
      );
    case 'choice_single':
      return (
        <div className="space-y-1.5">
          {field.options.map((opt) => (
            <label
              key={opt.value}
              className={cn(
                'flex items-center gap-2 rounded-md border px-3 py-2 cursor-pointer transition-colors',
                value === opt.value
                  ? 'border-accent/50 bg-accent/[0.04]'
                  : 'border-border hover:bg-muted/40',
              )}
            >
              <input
                type="radio"
                checked={value === opt.value}
                onChange={() => onChange(opt.value)}
                className="size-4"
              />
              <span className="text-sm">{opt.label}</span>
            </label>
          ))}
        </div>
      );
    case 'choice_multiple': {
      const arr: string[] = Array.isArray(value) ? (value as string[]) : [];
      return (
        <div className="space-y-1.5">
          {field.options.map((opt) => {
            const checked = arr.includes(opt.value);
            return (
              <label
                key={opt.value}
                className={cn(
                  'flex items-center gap-2 rounded-md border px-3 py-2 cursor-pointer transition-colors',
                  checked
                    ? 'border-accent/50 bg-accent/[0.04]'
                    : 'border-border hover:bg-muted/40',
                )}
              >
                <input
                  type="checkbox"
                  checked={checked}
                  onChange={(e) => {
                    if (e.target.checked) {
                      onChange([...arr, opt.value]);
                    } else {
                      onChange(arr.filter((v) => v !== opt.value));
                    }
                  }}
                  className="size-4"
                />
                <span className="text-sm">{opt.label}</span>
              </label>
            );
          })}
        </div>
      );
    }
    case 'signature':
    case 'paragraph':
      // Signature renders via SignatureCanvas in the parent; paragraph
      // short-circuits in FieldRenderer. Both branches exist only to
      // satisfy the exhaustive switch.
      return null;
  }
}

// ── Signed (read-only) view ────────────────────────────────────────

function SignedView({ submission }: { submission: PublicFormSubmission }) {
  const fields = submission.schema_snapshot.fields;
  const signedDate = submission.signed_at
    ? new Date(submission.signed_at).toLocaleString()
    : 'Unknown';

  return (
    <div className="min-h-screen bg-stone-50/60">
      <BrandedHeader submission={submission} />
      <div className="max-w-2xl mx-auto px-4 sm:px-6 py-6 sm:py-10">
        <header className="mb-6">
          <div className="rounded-md border border-emerald-500/30 bg-emerald-50/50 dark:bg-emerald-950/10 px-4 py-3 flex items-center gap-2.5">
            <CircleCheck className="size-5 shrink-0 text-emerald-600 dark:text-emerald-500" />
            <div>
              <p className="text-sm font-medium">Signed</p>
              <p className="text-[11px] text-muted-foreground">
                {signedDate}
              </p>
            </div>
          </div>
          <h1 className="font-serif text-2xl sm:text-3xl font-semibold tracking-tight mt-6">
            {submission.template_name}
          </h1>
        </header>

        <dl className="space-y-5">
          {fields.map((field) => {
            if (field.type === 'paragraph') {
              return (
                <section key={field.id} className="rounded-md border bg-muted/30 px-4 py-3.5">
                  <h3 className="font-serif text-sm font-semibold tracking-tight text-foreground">
                    {field.label}
                  </h3>
                  <p className="text-[13px] text-foreground/85 mt-2 leading-relaxed whitespace-pre-line">
                    {field.body}
                  </p>
                </section>
              );
            }
            return (
              <div key={field.id}>
                <dt className="text-[11px] uppercase tracking-wide text-muted-foreground font-medium">
                  {field.label}
                </dt>
                <dd className="mt-1 text-sm">
                  {field.type === 'signature' ? (
                    submission.answers && typeof submission.answers === 'object' ? (
                      <span className="text-muted-foreground italic">
                        Signature on file.
                      </span>
                    ) : null
                  ) : (
                    <DisplayedAnswer
                      field={field}
                      value={submission.answers[field.id]}
                    />
                  )}
                </dd>
              </div>
            );
          })}
        </dl>

        <p className="text-[11px] text-muted-foreground/80 mt-8 leading-relaxed">
          This signed copy is part of your spa record. Contact the spa if you
          need a printable version.
        </p>
      </div>
    </div>
  );
}

function DisplayedAnswer({
  field,
  value,
}: {
  field: FormField;
  value: unknown;
}) {
  if (value === undefined || value === null || value === '') {
    return <span className="text-muted-foreground italic">—</span>;
  }
  if (isChoiceField(field)) {
    if (field.type === 'choice_single' && typeof value === 'string') {
      const opt = field.options.find((o) => o.value === value);
      return <>{opt?.label ?? value}</>;
    }
    if (field.type === 'choice_multiple' && Array.isArray(value)) {
      const labels = (value as string[]).map(
        (v) => field.options.find((o) => o.value === v)?.label ?? v,
      );
      return <>{labels.join(', ')}</>;
    }
  }
  return <>{String(value)}</>;
}

// ── Full-page status surfaces ──────────────────────────────────────

function FullPageState({
  icon,
  title,
  message,
  tone,
}: {
  icon: React.ReactNode;
  title: string;
  message: string;
  tone?: 'destructive' | 'muted';
}) {
  return (
    <div className="min-h-screen bg-background flex items-center justify-center px-4 py-12">
      <div className="max-w-md text-center space-y-3">
        <div className="inline-flex">{icon}</div>
        <h1
          className={cn(
            'font-serif text-2xl font-semibold tracking-tight',
            tone === 'destructive' && 'text-destructive',
          )}
        >
          {title}
        </h1>
        <p className="text-sm text-muted-foreground leading-relaxed">{message}</p>
        <p className="pt-2">
          <Link
            href="/"
            className="text-xs text-muted-foreground/80 hover:text-foreground hover:underline transition-colors"
          >
            Return to home
          </Link>
        </p>
      </div>
    </div>
  );
}
