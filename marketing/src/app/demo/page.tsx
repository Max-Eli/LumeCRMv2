'use client';

import { useState, type FormEvent } from 'react';

import { PageHero } from '@/components/page-hero';

const SOFTWARE_OPTIONS = [
  'Zenoti',
  'Mindbody',
  'Boulevard',
  'Vagaro',
  'Aesthetic Record',
  'Spreadsheet / paper',
  'Other / nothing yet',
];

export default function DemoRequestPage() {
  const [submitted, setSubmitted] = useState(false);

  const handleSubmit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    // v1: client-side confirmation. Backend wiring (POST to /api/demo-requests/)
    // lands in Session 2.
    setSubmitted(true);
  };

  return (
    <>
      <PageHero
        eyebrow="Get a demo"
        headline={
          <>
            See Lumè in 30 minutes,
            <br />
            <span className="accent-italic">configured for your spa.</span>
          </>
        }
        standfirst="Tell us about your medspa. We'll set up a private 30-minute walkthrough with the product configured for your service menu, your providers, and your locations. We respond within one business day."
      />

      <section>
        <div className="mx-auto max-w-7xl px-6 lg:px-10 py-20 lg:py-28">
          {submitted ? (
            <ThankYou />
          ) : (
            <div className="grid gap-16 lg:grid-cols-12">
              <aside className="lg:col-span-4">
                <p className="eyebrow text-foreground/60">What happens next</p>
                <ol className="mt-6 space-y-6">
                  <Step
                    n="01"
                    title="We review your request"
                    body="Within one business day. A real person, not an autoresponder."
                  />
                  <Step
                    n="02"
                    title="You pick a time"
                    body="We send a calendar link with a 30-minute slot. Usually within the same week."
                  />
                  <Step
                    n="03"
                    title="Walkthrough on your workflow"
                    body="If you can share a sample export from your current platform, we configure the demo on your real services and providers."
                  />
                  <Step
                    n="04"
                    title="Pricing + migration scope"
                    body="A clean quote, plus a one-time migration estimate if you're moving from another platform."
                  />
                </ol>
              </aside>

              <form
                onSubmit={handleSubmit}
                className="lg:col-span-8 space-y-8"
                noValidate
              >
                <div className="grid gap-8 sm:grid-cols-2">
                  <Field
                    name="first_name"
                    label="First name"
                    required
                    autoComplete="given-name"
                  />
                  <Field
                    name="last_name"
                    label="Last name"
                    required
                    autoComplete="family-name"
                  />
                </div>

                <div className="grid gap-8 sm:grid-cols-2">
                  <Field
                    name="email"
                    label="Work email"
                    type="email"
                    required
                    autoComplete="email"
                  />
                  <Field
                    name="phone"
                    label="Phone"
                    type="tel"
                    autoComplete="tel"
                  />
                </div>

                <Field
                  name="spa_name"
                  label="Spa name"
                  required
                  autoComplete="organization"
                />

                <div className="grid gap-8 sm:grid-cols-2">
                  <Field
                    name="locations"
                    label="Number of locations"
                    type="number"
                    inputMode="numeric"
                    min={1}
                    defaultValue={1}
                  />
                  <Field
                    name="providers"
                    label="Number of providers"
                    type="number"
                    inputMode="numeric"
                    min={1}
                  />
                </div>

                <SelectField
                  name="current_software"
                  label="Currently using"
                  options={SOFTWARE_OPTIONS}
                />

                <TextareaField
                  name="message"
                  label="Anything specific you'd like us to focus on?"
                  rows={5}
                  placeholder="e.g. multi-location reporting, Botox consent workflow, migrating from Zenoti…"
                />

                <div className="flex flex-col items-start gap-4 pt-4 sm:flex-row sm:items-center sm:justify-between">
                  <p className="max-w-md text-xs text-muted-foreground">
                    We respond within one business day. We never share or
                    sell your contact information.
                  </p>
                  <button
                    type="submit"
                    className="inline-flex h-12 items-center rounded-full bg-foreground px-7 text-sm font-medium uppercase tracking-[0.16em] text-background hover:bg-foreground/90 transition-colors"
                  >
                    Send request
                  </button>
                </div>
              </form>
            </div>
          )}
        </div>
      </section>
    </>
  );
}

// ── Form primitives ──────────────────────────────────────────────────

interface FieldProps extends React.InputHTMLAttributes<HTMLInputElement> {
  label: string;
}

function Field({ label, name, ...rest }: FieldProps) {
  const id = `f-${name}`;
  return (
    <div>
      <label htmlFor={id} className="eyebrow text-foreground/60">
        {label}
        {rest.required ? <span className="text-accent"> ·</span> : null}
      </label>
      <input
        id={id}
        name={name}
        {...rest}
        className="mt-2 block w-full border-0 border-b border-foreground/30 bg-transparent px-0 py-2 text-base text-foreground outline-none transition-colors focus:border-accent placeholder:text-muted-foreground/60"
      />
    </div>
  );
}

function SelectField({
  name,
  label,
  options,
}: {
  name: string;
  label: string;
  options: readonly string[];
}) {
  const id = `f-${name}`;
  return (
    <div>
      <label htmlFor={id} className="eyebrow text-foreground/60">
        {label}
      </label>
      <select
        id={id}
        name={name}
        defaultValue=""
        className="mt-2 block w-full border-0 border-b border-foreground/30 bg-transparent px-0 py-2 text-base text-foreground outline-none transition-colors focus:border-accent"
      >
        <option value="" disabled>
          Choose one
        </option>
        {options.map((o) => (
          <option key={o} value={o}>
            {o}
          </option>
        ))}
      </select>
    </div>
  );
}

function TextareaField({
  name,
  label,
  rows = 5,
  placeholder,
}: {
  name: string;
  label: string;
  rows?: number;
  placeholder?: string;
}) {
  const id = `f-${name}`;
  return (
    <div>
      <label htmlFor={id} className="eyebrow text-foreground/60">
        {label}
      </label>
      <textarea
        id={id}
        name={name}
        rows={rows}
        placeholder={placeholder}
        className="mt-2 block w-full resize-none border-0 border-b border-foreground/30 bg-transparent px-0 py-2 text-base text-foreground outline-none transition-colors focus:border-accent placeholder:text-muted-foreground/60"
      />
    </div>
  );
}

function Step({ n, title, body }: { n: string; title: string; body: string }) {
  return (
    <li className="border-l-2 border-accent/40 pl-5">
      <div className="flex items-baseline gap-3">
        <span className="font-display text-xl text-accent">{n}</span>
        <h3 className="font-serif text-base font-medium text-foreground">{title}</h3>
      </div>
      <p className="mt-1 text-sm leading-relaxed text-foreground/75">{body}</p>
    </li>
  );
}

function ThankYou() {
  return (
    <div className="mx-auto max-w-2xl border border-foreground/15 px-8 py-16 text-center">
      <p className="eyebrow text-foreground/60">Request received</p>
      <h2 className="mt-6 font-display text-4xl text-foreground sm:text-5xl">
        Thanks — we'll be in touch.
      </h2>
      <p className="mt-6 text-base leading-relaxed text-foreground/80">
        A real person reads every request. You'll hear back within one
        business day with a calendar link and a few notes about how
        we'd configure the walkthrough for your spa.
      </p>
      <p className="mt-8 text-sm text-muted-foreground">
        — The Lumè team
      </p>
    </div>
  );
}
