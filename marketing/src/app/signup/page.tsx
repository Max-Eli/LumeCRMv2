/**
 * `/signup` — self-serve 30-day trial signup.
 *
 * Two-step flow:
 *
 *   1. Form step: business name + owner email + password + name +
 *      timezone + monthly/annual toggle + BAA/ToS click-through.
 *      Subdomain preview updates live as the operator types.
 *
 *   2. Card step: Stripe Elements PaymentElement collects the card.
 *      On submit we call ``stripe.createPaymentMethod`` first
 *      (collects + returns ``pm_…``) then POST to the backend
 *      ``/api/public/signup/`` with everything in one shot. Backend
 *      provisions tenant + Stripe Customer + Subscription + sends
 *      verification email, redirects us to the new tenant's login URL.
 *
 * Backend re-validates every field — this UI is for UX, not security.
 *
 * The Stripe publishable key is read from
 * ``NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY`` (test-mode key in dev,
 * live-mode in prod). Single-key UX — we don't need a separate
 * Connect publishable key here because signup uses the platform
 * (Billing) account, not a connected account.
 */

'use client';

import {
  Elements,
  PaymentElement,
  useElements,
  useStripe,
} from '@stripe/react-stripe-js';
import { loadStripe } from '@stripe/stripe-js';
import { AlertCircle, ArrowRight, CheckCircle2, Loader2 } from 'lucide-react';
import Link from 'next/link';
import { useMemo, useState } from 'react';

import { PageHero } from '@/components/page-hero';

// Resolve the API URL once at module load. Falls back to relative
// paths in dev so the Next.js proxy can route /api/* to the backend.
const API_URL =
  process.env.NEXT_PUBLIC_API_URL || 'https://api.xn--lumcrm-5ua.com';
const PUBLISHABLE_KEY =
  process.env.NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY || '';

// Cache the loadStripe promise so re-mounts don't re-fetch Stripe.js.
const stripePromise = PUBLISHABLE_KEY
  ? loadStripe(PUBLISHABLE_KEY)
  : null;

// ── Page shell ─────────────────────────────────────────────────────

export default function SignupPage() {
  return (
    <main>
      <PageHero
        eyebrow="Start your trial"
        headline={
          <>
            30 days free.{' '}
            <span className="accent-italic">No charge until day 31.</span>
          </>
        }
        standfirst="Run a full appointment cycle on Lumè — set up your service catalog, train your team, take real bookings — before your card is charged. Cancel anytime during the trial."
      />
      <SignupShell />
    </main>
  );
}

// ── Multi-step state machine ──────────────────────────────────────

interface FormState {
  businessName: string;
  ownerEmail: string;
  ownerPassword: string;
  ownerFirstName: string;
  ownerLastName: string;
  timezone: string;
  billingCycle: 'monthly' | 'annual';
  baaAccepted: boolean;
  tosAccepted: boolean;
}

const INITIAL_FORM: FormState = {
  businessName: '',
  ownerEmail: '',
  ownerPassword: '',
  ownerFirstName: '',
  ownerLastName: '',
  timezone: 'America/New_York',
  billingCycle: 'annual',
  baaAccepted: false,
  tosAccepted: false,
};

function SignupShell() {
  const [step, setStep] = useState<'form' | 'card' | 'done'>('form');
  const [form, setForm] = useState<FormState>(INITIAL_FORM);
  const [successUrl, setSuccessUrl] = useState<string | null>(null);

  if (!PUBLISHABLE_KEY) {
    return (
      <section className="mx-auto max-w-2xl px-6 lg:px-10 py-16">
        <ConfigBanner />
      </section>
    );
  }

  return (
    <section className="mx-auto max-w-2xl px-6 lg:px-10 py-12 lg:py-16">
      {step === 'form' ? (
        <FormStep
          form={form}
          onChange={setForm}
          onSubmit={() => setStep('card')}
        />
      ) : step === 'card' ? (
        <Elements
          stripe={stripePromise}
          options={{
            mode: 'setup',
            currency: 'usd',
            paymentMethodCreation: 'manual',
            appearance: { theme: 'stripe' },
          }}
        >
          <CardStep
            form={form}
            onBack={() => setStep('form')}
            onSuccess={(loginUrl) => {
              setSuccessUrl(loginUrl);
              setStep('done');
            }}
          />
        </Elements>
      ) : (
        <SuccessStep loginUrl={successUrl ?? ''} ownerEmail={form.ownerEmail} />
      )}
    </section>
  );
}

// ── Step 1: form ──────────────────────────────────────────────────

function FormStep({
  form,
  onChange,
  onSubmit,
}: {
  form: FormState;
  onChange: (form: FormState) => void;
  onSubmit: () => void;
}) {
  const [error, setError] = useState<string | null>(null);
  const subdomain = useMemo(() => slugifyBusinessName(form.businessName), [form.businessName]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    if (form.businessName.trim().length < 2) {
      setError('Enter your business name.');
      return;
    }
    if (!form.ownerEmail || !form.ownerEmail.includes('@')) {
      setError('Enter a valid email address.');
      return;
    }
    if (form.ownerPassword.length < 8) {
      setError('Password must be at least 8 characters.');
      return;
    }
    if (!form.ownerFirstName.trim() || !form.ownerLastName.trim()) {
      setError('Enter your first and last name.');
      return;
    }
    if (!form.baaAccepted) {
      setError('You must accept the Business Associate Agreement (HIPAA requirement).');
      return;
    }
    if (!form.tosAccepted) {
      setError('You must accept the Terms of Service.');
      return;
    }
    onSubmit();
  };

  return (
    <form
      onSubmit={handleSubmit}
      className="rounded-2xl border border-border bg-card p-6 lg:p-8 space-y-6"
    >
      <header>
        <h2 className="font-serif text-2xl font-semibold tracking-tight">
          Tell us about your spa
        </h2>
        <p className="text-sm text-muted-foreground mt-1.5">
          We&apos;ll spin up your workspace + start your 30-day trial in about 60 seconds.
        </p>
      </header>

      <Field label="Business name" required>
        <input
          type="text"
          value={form.businessName}
          onChange={(e) => onChange({ ...form, businessName: e.target.value })}
          required
          autoFocus
          placeholder="e.g. Acme Med Spa"
          className={INPUT_CLASS}
        />
        {subdomain ? (
          <p className="text-[11px] text-muted-foreground mt-1.5 font-mono">
            Your workspace will live at{' '}
            <span className="text-foreground">{subdomain}.lume-crm.com</span>
          </p>
        ) : null}
      </Field>

      <div className="grid sm:grid-cols-2 gap-4">
        <Field label="Your first name" required>
          <input
            type="text"
            value={form.ownerFirstName}
            onChange={(e) => onChange({ ...form, ownerFirstName: e.target.value })}
            required
            autoComplete="given-name"
            className={INPUT_CLASS}
          />
        </Field>
        <Field label="Your last name" required>
          <input
            type="text"
            value={form.ownerLastName}
            onChange={(e) => onChange({ ...form, ownerLastName: e.target.value })}
            required
            autoComplete="family-name"
            className={INPUT_CLASS}
          />
        </Field>
      </div>

      <Field label="Work email" required hint="Use your business email, not a personal Gmail/Yahoo.">
        <input
          type="email"
          value={form.ownerEmail}
          onChange={(e) => onChange({ ...form, ownerEmail: e.target.value })}
          required
          autoComplete="email"
          placeholder="founder@yourspa.com"
          className={INPUT_CLASS}
        />
      </Field>

      <Field label="Set a password" required hint="At least 8 characters. You'll use this to log in.">
        <input
          type="password"
          value={form.ownerPassword}
          onChange={(e) => onChange({ ...form, ownerPassword: e.target.value })}
          required
          autoComplete="new-password"
          minLength={8}
          className={INPUT_CLASS}
        />
      </Field>

      <Field label="Timezone" required>
        <select
          value={form.timezone}
          onChange={(e) => onChange({ ...form, timezone: e.target.value })}
          className={INPUT_CLASS}
        >
          {TIMEZONE_OPTIONS.map((tz) => (
            <option key={tz} value={tz}>{tz.replace('_', ' ')}</option>
          ))}
        </select>
      </Field>

      <Field label="Billing cycle">
        <div className="grid grid-cols-2 gap-2">
          {(['annual', 'monthly'] as const).map((cycle) => {
            const active = form.billingCycle === cycle;
            const price = cycle === 'annual' ? '$79' : '$99';
            const suffix = cycle === 'annual' ? '/mo billed annually (20% off)' : '/mo billed monthly';
            return (
              <button
                key={cycle}
                type="button"
                onClick={() => onChange({ ...form, billingCycle: cycle })}
                className={`text-left rounded-xl border-2 p-3 transition-colors ${
                  active
                    ? 'border-foreground bg-foreground/[0.03]'
                    : 'border-border bg-card hover:border-foreground/40'
                }`}
              >
                <p className="text-sm font-semibold capitalize">{cycle}</p>
                <p className="text-[11px] text-muted-foreground mt-0.5">
                  {price}{suffix}
                </p>
              </button>
            );
          })}
        </div>
      </Field>

      <div className="space-y-3 pt-2 border-t border-border">
        <Checkbox
          checked={form.baaAccepted}
          onChange={(checked) => onChange({ ...form, baaAccepted: checked })}
          label={
            <>
              I&apos;ve read + accept the{' '}
              <Link href="/baa" target="_blank" className="underline text-foreground">
                Business Associate Agreement
              </Link>
              <span className="text-muted-foreground"> (HIPAA requirement)</span>
            </>
          }
        />
        <Checkbox
          checked={form.tosAccepted}
          onChange={(checked) => onChange({ ...form, tosAccepted: checked })}
          label={
            <>
              I&apos;ve read + accept the{' '}
              <Link href="/terms" target="_blank" className="underline text-foreground">
                Terms of Service
              </Link>{' '}
              and{' '}
              <Link href="/privacy" target="_blank" className="underline text-foreground">
                Privacy Policy
              </Link>
            </>
          }
        />
      </div>

      {error ? <FieldError message={error} /> : null}

      <button
        type="submit"
        className="w-full inline-flex items-center justify-center gap-2 h-12 rounded-full bg-foreground text-background text-sm font-medium uppercase tracking-[0.12em] hover:bg-foreground/90 transition-colors"
      >
        Continue to payment
        <ArrowRight className="size-4" />
      </button>
      <p className="text-[11px] text-center text-muted-foreground">
        Card captured on the next step. No charge until day 31. Cancel anytime in the trial.
      </p>
    </form>
  );
}

// ── Step 2: card collection + signup submit ───────────────────────

function CardStep({
  form,
  onBack,
  onSuccess,
}: {
  form: FormState;
  onBack: () => void;
  onSuccess: (loginUrl: string) => void;
}) {
  const stripe = useStripe();
  const elements = useElements();
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!stripe || !elements) return;
    setSubmitting(true);
    setError(null);

    // Step A: Stripe Elements validates client-side + creates a
    // PaymentMethod we can hand to the backend. submit() must come
    // first per Stripe's deferred-confirmation flow.
    const { error: submitError } = await elements.submit();
    if (submitError) {
      setError(submitError.message ?? 'Could not validate the card.');
      setSubmitting(false);
      return;
    }

    const { error: pmError, paymentMethod } = await stripe.createPaymentMethod({
      elements,
      params: {
        billing_details: {
          name: `${form.ownerFirstName} ${form.ownerLastName}`.trim(),
          email: form.ownerEmail,
        },
      },
    });
    if (pmError || !paymentMethod) {
      setError(pmError?.message ?? 'Could not collect the card.');
      setSubmitting(false);
      return;
    }

    // Step B: POST everything to the backend. Backend creates the
    // tenant + Stripe Customer + Subscription + sends verification
    // email. Failures arrive as { detail, code } from the server.
    try {
      const resp = await fetch(`${API_URL}/api/public/signup/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          business_name: form.businessName,
          owner_email: form.ownerEmail,
          owner_password: form.ownerPassword,
          owner_first_name: form.ownerFirstName,
          owner_last_name: form.ownerLastName,
          timezone: form.timezone,
          plan: 'starter',
          billing_cycle: form.billingCycle,
          payment_method_id: paymentMethod.id,
          baa_accepted: form.baaAccepted,
          tos_accepted: form.tosAccepted,
        }),
      });

      if (!resp.ok) {
        const body = await resp.json().catch(() => ({ detail: 'Signup failed.' }));
        setError(body.detail ?? 'Signup failed.');
        setSubmitting(false);
        return;
      }

      const body = await resp.json();
      onSuccess(body.login_url);
    } catch (err) {
      setError((err as Error).message ?? 'Network error.');
      setSubmitting(false);
    }
  };

  return (
    <form
      onSubmit={handleSubmit}
      className="rounded-2xl border border-border bg-card p-6 lg:p-8 space-y-6"
    >
      <header>
        <h2 className="font-serif text-2xl font-semibold tracking-tight">
          Card details
        </h2>
        <p className="text-sm text-muted-foreground mt-1.5">
          Captured now, charged on day 31 ({form.billingCycle === 'annual' ? '$79/mo billed annually' : '$99/mo billed monthly'}). Cancel anytime in the trial — no charge.
        </p>
      </header>

      <PaymentElement options={{ layout: 'tabs' }} />

      {error ? <FieldError message={error} /> : null}

      <div className="space-y-2">
        <button
          type="submit"
          disabled={submitting || !stripe || !elements}
          className="w-full inline-flex items-center justify-center gap-2 h-12 rounded-full bg-foreground text-background text-sm font-medium uppercase tracking-[0.12em] hover:bg-foreground/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {submitting ? <Loader2 className="size-4 animate-spin" /> : null}
          Start my 30-day trial
        </button>
        <button
          type="button"
          onClick={onBack}
          disabled={submitting}
          className="w-full h-10 text-xs uppercase tracking-[0.12em] text-muted-foreground hover:text-foreground transition-colors"
        >
          ← Back
        </button>
      </div>
      <p className="text-[11px] text-center text-muted-foreground leading-relaxed">
        Payments processed securely by Stripe. Lumè CRM is a product of
        Voxtro LLC. Your card data never touches our servers.
      </p>
    </form>
  );
}

// ── Step 3: success / verification prompt ─────────────────────────

function SuccessStep({
  loginUrl,
  ownerEmail,
}: {
  loginUrl: string;
  ownerEmail: string;
}) {
  return (
    <div className="rounded-2xl border border-emerald-500/30 bg-emerald-50/40 dark:bg-emerald-950/20 p-6 lg:p-8 space-y-5">
      <div className="flex items-start gap-3">
        <CheckCircle2 className="size-6 text-emerald-600 dark:text-emerald-400 shrink-0 mt-0.5" />
        <div className="space-y-1">
          <h2 className="font-serif text-2xl font-semibold tracking-tight">
            Welcome to Lumè
          </h2>
          <p className="text-sm text-muted-foreground">
            Your workspace is live and your 30-day trial has started.
          </p>
        </div>
      </div>

      <div className="space-y-3 text-sm">
        <p>
          <strong>Check your inbox.</strong> We sent a verification email to{' '}
          <span className="font-mono">{ownerEmail}</span>. Click the link to
          confirm your address.
        </p>
        <p className="text-muted-foreground">
          You can log in to your workspace immediately — verification is required for some operations (sending marketing campaigns, inviting staff) but not for setup.
        </p>
      </div>

      {loginUrl ? (
        <a
          href={loginUrl}
          className="inline-flex items-center justify-center gap-2 h-12 px-6 rounded-full bg-foreground text-background text-sm font-medium uppercase tracking-[0.12em] hover:bg-foreground/90 transition-colors"
        >
          Open my workspace
          <ArrowRight className="size-4" />
        </a>
      ) : null}
    </div>
  );
}

// ── Helpers ───────────────────────────────────────────────────────

const INPUT_CLASS =
  'w-full h-11 rounded-lg border border-border bg-background px-3 text-sm placeholder:text-muted-foreground/60 focus:outline-none focus:border-foreground/60 focus:ring-2 focus:ring-foreground/10 transition-colors';

function Field({
  label,
  required,
  hint,
  children,
}: {
  label: string;
  required?: boolean;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <label className="block text-xs uppercase tracking-wide text-muted-foreground font-medium">
        {label}
        {required ? <span className="text-foreground"> *</span> : null}
      </label>
      {children}
      {hint ? <p className="text-[11px] text-muted-foreground">{hint}</p> : null}
    </div>
  );
}

function Checkbox({
  checked,
  onChange,
  label,
}: {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label: React.ReactNode;
}) {
  return (
    <label className="flex items-start gap-2.5 cursor-pointer text-sm">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="mt-0.5 size-4 rounded border-border text-foreground focus:ring-foreground/20"
      />
      <span className="leading-snug">{label}</span>
    </label>
  );
}

function FieldError({ message }: { message: string }) {
  return (
    <div className="flex items-start gap-2 rounded-md border border-destructive/30 bg-destructive/5 p-3 text-xs text-destructive">
      <AlertCircle className="size-4 shrink-0 mt-0.5" />
      <p className="leading-snug">{message}</p>
    </div>
  );
}

function ConfigBanner() {
  return (
    <div className="rounded-2xl border border-amber-500/30 bg-amber-50/30 dark:bg-amber-950/20 p-6">
      <div className="flex items-start gap-3">
        <AlertCircle className="size-5 text-amber-600 dark:text-amber-400 shrink-0 mt-0.5" />
        <div className="space-y-2">
          <h2 className="font-serif text-lg font-semibold">
            Signup temporarily unavailable
          </h2>
          <p className="text-sm text-muted-foreground">
            Our self-serve signup is in final-mile configuration. In the
            meantime,{' '}
            <Link href="/demo" className="underline text-foreground">
              book a demo
            </Link>{' '}
            and we&apos;ll start your trial manually within one business day.
          </p>
        </div>
      </div>
    </div>
  );
}

// Mirror of the backend slugify logic. Used for the live preview
// only — the backend re-runs the canonical slugify on submit.
function slugifyBusinessName(name: string): string {
  const slug = name
    .toLowerCase()
    .replace(/[^a-z0-9\s-]/g, '')
    .trim()
    .replace(/\s+/g, '-')
    .replace(/-+/g, '-')
    .substring(0, 63);
  return slug;
}

// Common US/CA timezones — keeps the picker short. International
// signups land via the demo flow for now (Phase 6+).
const TIMEZONE_OPTIONS = [
  'America/New_York',
  'America/Chicago',
  'America/Denver',
  'America/Los_Angeles',
  'America/Phoenix',
  'America/Anchorage',
  'Pacific/Honolulu',
  'America/Toronto',
  'America/Vancouver',
];
