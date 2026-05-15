/**
 * `/portal/forms` — customer's form submissions.
 *
 * Pending forms first (the customer's actionable list — these have
 * a `sign_url` to the tokenized fill flow at /sign/<token>),
 * completed forms next (read-only confirmation), voided last.
 *
 * Answers and signature data are PHI and never appear in this
 * list — the customer signs through the existing tokenized page
 * which renders the schema fresh from the snapshot.
 */

'use client';

import {
  ArrowUpRight,
  CheckCircle2,
  ClipboardList,
  FileText,
  XCircle,
} from 'lucide-react';
import Link from 'next/link';

import { Button } from '@/components/ui/button';
import {
  type PortalFormStatus,
  type PortalFormSubmission,
  usePortalForms,
} from '@/lib/portal';
import { cn } from '@/lib/utils';

export default function PortalFormsPage() {
  const { data: forms, isLoading } = usePortalForms();
  const pending = (forms ?? []).filter((f) => f.status === 'pending');
  const completed = (forms ?? []).filter((f) => f.status === 'completed');
  const voided = (forms ?? []).filter((f) => f.status === 'voided');

  return (
    <div className="max-w-4xl mx-auto w-full px-6 py-10">
      <header className="mb-8">
        <h1 className="font-serif text-3xl font-semibold tracking-tight">
          Forms
        </h1>
        <p className="text-sm text-muted-foreground mt-1.5">
          Intake and consent forms — pending forms can be signed any time
          before your visit.
        </p>
      </header>

      {isLoading ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : (forms?.length ?? 0) === 0 ? (
        <EmptyState />
      ) : (
        <div className="space-y-8">
          <Section title="Pending signature" empty="You&apos;re all caught up.">
            {pending.map((f) => (
              <FormRow key={f.id} form={f} />
            ))}
          </Section>
          <Section title="Signed" empty="No completed forms on file yet.">
            {completed.map((f) => (
              <FormRow key={f.id} form={f} />
            ))}
          </Section>
          {voided.length > 0 ? (
            <Section title="Voided" empty="">
              {voided.map((f) => (
                <FormRow key={f.id} form={f} />
              ))}
            </Section>
          ) : null}
        </div>
      )}
    </div>
  );
}

function Section({
  title,
  empty,
  children,
}: {
  title: string;
  empty: string;
  children: React.ReactNode;
}) {
  const items = Array.isArray(children) ? children : [children];
  // Detect empty by absence of React children — works regardless of
  // whether the parent passed [] or null.
  const hasItems = items.some((c) => c != null && c !== false);

  return (
    <section>
      <h2 className="text-xs uppercase tracking-wide text-muted-foreground font-medium mb-3">
        {title}
      </h2>
      {hasItems ? (
        <ul className="space-y-2">{children}</ul>
      ) : empty ? (
        <p className="text-sm text-muted-foreground border border-dashed rounded-lg px-4 py-5 text-center">
          {empty}
        </p>
      ) : null}
    </section>
  );
}

function FormRow({ form }: { form: PortalFormSubmission }) {
  const isPending = form.status === 'pending';

  return (
    <li
      className={cn(
        'rounded-xl border bg-card shadow-sm p-5',
        isPending && 'ring-1 ring-[var(--portal-brand,#1f2937)]/20',
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1 flex items-start gap-3">
          <div
            className={cn(
              'inline-flex size-9 items-center justify-center rounded-md shrink-0',
              isPending
                ? 'bg-[var(--portal-brand,#1f2937)]/10 text-[var(--portal-brand,#1f2937)]'
                : 'bg-muted text-muted-foreground',
            )}
            aria-hidden
          >
            <FileText className="size-4" />
          </div>
          <div className="min-w-0 flex-1">
            <p className="font-medium truncate">{form.template_name}</p>
            <p className="text-xs text-muted-foreground capitalize mt-0.5">
              {form.template_form_type}
              {form.signed_at ? (
                <> · Signed {formatDate(form.signed_at)}</>
              ) : null}
              {form.voided_at ? (
                <> · Voided {formatDate(form.voided_at)}</>
              ) : null}
            </p>
          </div>
        </div>
        <StatusBadge status={form.status} display={form.status_display} />
      </div>

      {isPending && form.sign_url ? (
        <div className="mt-4 flex justify-end">
          <Button
            render={<Link href={form.sign_url} target="_blank" />}
            nativeButton={false}
            size="sm"
            style={{
              background: 'var(--portal-brand, #1f2937)',
              color: '#fff',
            }}
          >
            Sign now
            <ArrowUpRight className="size-3.5" />
          </Button>
        </div>
      ) : null}
    </li>
  );
}

function StatusBadge({
  status,
  display,
}: {
  status: PortalFormStatus;
  display: string;
}) {
  const tone =
    status === 'completed'
      ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
      : status === 'pending'
        ? 'bg-amber-50 text-amber-800 border-amber-200'
        : 'bg-muted text-muted-foreground border-muted-foreground/20';
  const Icon =
    status === 'completed' ? CheckCircle2 : status === 'voided' ? XCircle : null;
  return (
    <span
      className={cn(
        'shrink-0 inline-flex items-center gap-1 text-[10px] uppercase tracking-wide font-medium px-2 py-1 rounded-full border whitespace-nowrap',
        tone,
      )}
    >
      {Icon ? <Icon className="size-3" /> : null}
      {display}
    </span>
  );
}

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center text-center px-10 py-16 gap-3 rounded-xl border border-dashed bg-card">
      <div className="inline-flex size-12 items-center justify-center rounded-full bg-muted">
        <ClipboardList className="size-5 text-muted-foreground" />
      </div>
      <p className="font-medium">No forms yet</p>
      <p className="text-sm text-muted-foreground max-w-md">
        Forms appear here when the spa sends one — intake before your first
        visit, consent before specific treatments.
      </p>
    </div>
  );
}

function formatDate(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });
}
