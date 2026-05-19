/**
 * `/emr/[id]` — fill / view treatment record for a single appointment.
 *
 * The `[id]` segment IS the appointment id. Lives in the `(emr)`
 * route group — its own window, no CRM sidebar. Operators open this
 * via `openTreatmentRecordWindow(appointmentId)` from the calendar
 * appointment popover.
 *
 * The flow:
 *
 *   1. Look up the appointment.
 *   2. Check for an existing treatment record on this appointment.
 *      If found → render the read-only signed view (same as the
 *      customer-profile EMR tab).
 *   3. Otherwise, fetch the templates assigned to this appointment's
 *      service. Three outcomes:
 *        - 0 templates assigned → empty state pointing the operator
 *          at `/forms/emr-templates` to set up the mapping.
 *        - 1 template assigned → auto-select it.
 *        - many → render a template picker at the top of the form.
 *   4. Operator fills the schema-driven form + hits "Sign record."
 *      The submitted record is pinned to the appointment.
 *
 * Per ADR (treatment records): the schema_snapshot is taken at
 * signing time so the record stays legible even after the template
 * has been edited. The backend handles that — we just POST the
 * template id + answers.
 */

'use client';

import {
  Activity,
  CalendarClock,
  Check,
  ChevronLeft,
  CircleAlert,
  CircleCheck,
  ExternalLink,
  Loader2,
  Sparkles,
  XCircle,
} from 'lucide-react';
import Link from 'next/link';
import { use, useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Field, FieldError, FieldLabel } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { StatusBadge } from '@/components/status-badge';
import { ApiError } from '@/lib/api';
import { useAppointment } from '@/lib/appointments';
import {
  type TemplateField,
  type TreatmentRecord,
  type TreatmentRecordTemplate,
  useAppointmentTreatmentRecords,
  useSubmitTreatmentRecord,
  useTreatmentTemplates,
} from '@/lib/treatments';
import { cn } from '@/lib/utils';

export default function EmrAppointmentPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id: idStr } = use(params);
  const appointmentId = Number(idStr);

  const { data: appointment, isLoading: loadingAppt, error: apptError } = useAppointment(appointmentId);
  const { data: records, isLoading: loadingRecords } = useAppointmentTreatmentRecords(appointmentId);

  if (loadingAppt || loadingRecords) {
    return <FullPageState icon={<Loader2 className="size-5 animate-spin text-muted-foreground" />} title="Loading…" />;
  }
  if (apptError || !appointment) {
    const is404 = apptError instanceof ApiError && apptError.status === 404;
    return (
      <FullPageState
        tone="destructive"
        icon={<XCircle className="size-6 text-destructive" />}
        title={is404 ? 'Appointment not found' : 'Could not load this appointment'}
        message={
          is404
            ? "This appointment link is no longer valid."
            : 'Please refresh and try again.'
        }
      />
    );
  }

  const signed = (records ?? []).find((r) => r.parent_record_id === null);

  return (
    <div className="px-3 sm:px-8 py-4 sm:py-10 max-w-3xl mx-auto">
      <EmrHeader appointment={appointment} signedRecord={signed ?? null} />
      {signed ? (
        <SignedRecordView record={signed} />
      ) : (
        <FillRecord appointment={appointment} />
      )}
    </div>
  );
}

// ── Header ────────────────────────────────────────────────────────

function EmrHeader({
  appointment,
  signedRecord,
}: {
  appointment: NonNullable<ReturnType<typeof useAppointment>['data']>;
  signedRecord: TreatmentRecord | null;
}) {
  const start = new Date(appointment.start_time);
  const dateLabel = start.toLocaleString(undefined, {
    weekday: 'short',
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  });
  const providerName =
    `${appointment.provider.user_first_name ?? ''} ${appointment.provider.user_last_name ?? ''}`.trim() ||
    appointment.provider.user_email;

  return (
    <div className="mb-5 sm:mb-8">
      <Link
        href="/calendar"
        className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground transition-colors mb-3"
      >
        <ChevronLeft className="size-3.5" />
        Back to calendar
      </Link>
      <div className="flex items-start gap-3 flex-wrap">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <h1 className="font-serif text-xl sm:text-3xl font-semibold tracking-tight text-foreground">
              Treatment record
            </h1>
            {signedRecord ? (
              <StatusBadge tone="success">Signed</StatusBadge>
            ) : (
              <StatusBadge tone="neutral">Draft</StatusBadge>
            )}
          </div>
          <p className="text-xs sm:text-sm text-muted-foreground mt-2 leading-relaxed">
            <span className="font-medium text-foreground/90">{appointment.customer.full_name}</span>
            <span className="mx-1.5 text-muted-foreground/50">·</span>
            {appointment.service.name}
            <span className="mx-1.5 text-muted-foreground/50">·</span>
            <span className="tabular-nums">{dateLabel}</span>
            <span className="mx-1.5 text-muted-foreground/50">·</span>
            with {providerName}
          </p>
        </div>
      </div>
    </div>
  );
}

// ── Fill flow ─────────────────────────────────────────────────────

function FillRecord({
  appointment,
}: {
  appointment: NonNullable<ReturnType<typeof useAppointment>['data']>;
}) {
  const serviceId = appointment.service.id;
  const customerId = appointment.customer.id;
  const { data: templates, isLoading: loadingTemplates } = useTreatmentTemplates({
    serviceId,
    active: true,
  });
  const submit = useSubmitTreatmentRecord();

  const active = useMemo(
    () => (templates ?? []).filter((t) => t.is_active),
    [templates],
  );

  const [templateId, setTemplateId] = useState<number | null>(null);
  const [answers, setAnswers] = useState<Record<string, unknown>>({});
  const [error, setError] = useState<string | null>(null);

  // Auto-select when exactly one template is assigned to this
  // service. Operators with a single chart per service shouldn't
  // have to pick from a list of one.
  useEffect(() => {
    if (!loadingTemplates && templateId === null && active.length === 1) {
      setTemplateId(active[0].id);
    }
  }, [loadingTemplates, active, templateId]);

  const template = useMemo(
    () => active.find((t) => t.id === templateId) ?? null,
    [active, templateId],
  );

  if (loadingTemplates) {
    return (
      <Card>
        <div className="p-10 text-center text-sm text-muted-foreground inline-flex items-center gap-2 justify-center w-full">
          <Loader2 className="size-4 animate-spin" />
          Loading templates…
        </div>
      </Card>
    );
  }

  if (active.length === 0) {
    return (
      <Card>
        <div className="px-6 py-12 sm:py-16 text-center max-w-md mx-auto">
          <div className="inline-flex size-12 items-center justify-center rounded-full bg-amber-50 text-amber-700 mb-4">
            <CircleAlert className="size-5" />
          </div>
          <h2 className="font-serif text-lg font-semibold tracking-tight">
            No treatment record templates assigned
          </h2>
          <p className="text-sm text-muted-foreground mt-2 leading-relaxed">
            No EMR templates are mapped to{' '}
            <span className="font-medium text-foreground">{appointment.service.name}</span>{' '}
            yet. Assign one (or more) on the template's edit page so it
            shows up here for every visit of this service.
          </p>
          <Button
            type="button"
            render={
              <Link href="/forms/emr-templates" target="_blank" rel="noopener noreferrer" />
            }
            nativeButton={false}
            className="mt-5"
          >
            <Sparkles className="size-4" />
            Manage EMR templates
          </Button>
        </div>
      </Card>
    );
  }

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    if (!template || !templateId) {
      setError('Pick a template to continue.');
      return;
    }
    for (const f of template.schema?.fields ?? []) {
      if (!f.required) continue;
      const v = answers[f.id];
      const empty =
        v == null ||
        v === '' ||
        (Array.isArray(v) && v.length === 0);
      if (empty) {
        setError(`"${f.label}" is required.`);
        return;
      }
    }

    submit.mutate(
      {
        customer_id: customerId,
        template_id: templateId,
        answers,
        appointment_id: appointment.id,
      },
      {
        onSuccess: () => {
          toast.success('Treatment record signed.');
          // Refresh — the page flips to the signed view automatically
          // because `useAppointmentTreatmentRecords` invalidates.
        },
        onError: (err) => {
          if (err instanceof ApiError && err.body && typeof err.body === 'object') {
            const body = err.body as Record<string, string | string[]>;
            const first = Object.keys(body)[0];
            const v = first ? body[first] : undefined;
            const msg = Array.isArray(v) ? v[0] : v;
            setError(typeof msg === 'string' ? msg : 'Could not sign record.');
          } else {
            setError('Could not sign record.');
          }
        },
      },
    );
  };

  return (
    <form onSubmit={onSubmit} className="space-y-5">
      <Card>
        <div className="p-4 sm:p-6 space-y-5">
          {active.length > 1 ? (
            <Field>
              <FieldLabel htmlFor="template">Template</FieldLabel>
              <Select
                value={templateId ? String(templateId) : undefined}
                onValueChange={(v) => {
                  setTemplateId(v ? Number(v) : null);
                  setAnswers({});
                }}
              >
                <SelectTrigger id="template" className="w-full">
                  <SelectValue placeholder="Pick a template…">
                    {(v) => {
                      if (!v) return 'Pick a template…';
                      return active.find((t) => String(t.id) === v)?.name ?? v;
                    }}
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  {active.map((t) => (
                    <SelectItem key={t.id} value={String(t.id)}>
                      {t.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Field>
          ) : template ? (
            <div className="rounded-md border border-accent/30 bg-accent/[0.05] px-3 py-2 flex items-start gap-2 text-xs">
              <Activity className="size-3.5 shrink-0 text-accent-foreground/80 mt-0.5" />
              <p className="text-foreground/85 leading-relaxed">
                Charting <span className="font-medium">{template.name}</span>. This
                record pins to the appointment above.
              </p>
            </div>
          ) : null}

          {template ? (
            <SchemaForm
              template={template}
              answers={answers}
              onChange={setAnswers}
            />
          ) : null}
        </div>
      </Card>

      {error ? (
        <div className="rounded-md border border-destructive/40 bg-destructive/[0.04] px-3 py-2.5 flex items-start gap-2 text-sm">
          <CircleAlert className="size-4 shrink-0 text-destructive mt-0.5" />
          <p className="text-foreground/90">{error}</p>
        </div>
      ) : null}

      <div className="flex flex-col-reverse sm:flex-row sm:items-center sm:justify-end gap-2">
        <Button
          type="button"
          variant="outline"
          render={<Link href="/calendar" />}
          nativeButton={false}
          className="w-full sm:w-auto"
        >
          Cancel
        </Button>
        <Button
          type="submit"
          disabled={submit.isPending || !template}
          size="lg"
          className="w-full sm:w-auto"
        >
          {submit.isPending ? (
            <Loader2 className="size-4 animate-spin" />
          ) : (
            <Check className="size-4" />
          )}
          {submit.isPending ? 'Signing…' : 'Sign record'}
        </Button>
      </div>

      <p className="text-[11px] text-muted-foreground/80 leading-relaxed pt-1">
        Signing locks the record after a 15-minute edit window. Corrections after
        the window close are made by adding an addendum from the customer's
        chart.
      </p>
    </form>
  );
}

// ── Signed view ───────────────────────────────────────────────────

function SignedRecordView({ record }: { record: TreatmentRecord }) {
  const signed = new Date(record.signed_at);
  const author =
    `${record.author_first_name ?? ''} ${record.author_last_name ?? ''}`.trim() ||
    record.author_email;
  const fields: TemplateField[] = record.schema_snapshot?.fields ?? [];

  return (
    <Card>
      <div className="px-4 sm:px-6 py-5 border-b flex items-start gap-3">
        <CircleCheck className="size-5 text-emerald-600 dark:text-emerald-500 mt-0.5 shrink-0" />
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium">
            {record.template_name}
          </p>
          <p className="text-xs text-muted-foreground mt-0.5">
            Signed by {author} on{' '}
            <span className="tabular-nums">
              {signed.toLocaleString(undefined, {
                year: 'numeric',
                month: 'short',
                day: 'numeric',
                hour: 'numeric',
                minute: '2-digit',
              })}
            </span>
          </p>
        </div>
        <Link
          href={`/clients/${record.customer}?tab=treatment-records`}
          className="text-xs text-muted-foreground hover:text-foreground transition-colors inline-flex items-center gap-1 shrink-0"
        >
          Full chart
          <ExternalLink className="size-3" aria-hidden />
        </Link>
      </div>
      <dl className="px-4 sm:px-6 py-5 space-y-4">
        {fields.map((field) => (
          <div key={field.id}>
            <dt className="text-[11px] uppercase tracking-wide text-muted-foreground font-medium">
              {field.label}
            </dt>
            <dd className="mt-1 text-sm">
              <RenderAnswer field={field} value={record.answers[field.id]} />
            </dd>
          </div>
        ))}
      </dl>
    </Card>
  );
}

function RenderAnswer({ field, value }: { field: TemplateField; value: unknown }) {
  if (value == null || value === '' || (Array.isArray(value) && value.length === 0)) {
    return <span className="text-muted-foreground italic">—</span>;
  }
  if (field.type === 'choice_single' && typeof value === 'string') {
    const opt = field.options?.find((o) => o.value === value);
    return <span>{opt?.label ?? value}</span>;
  }
  if (field.type === 'choice_multiple' && Array.isArray(value)) {
    const labels = (value as string[]).map(
      (v) => field.options?.find((o) => o.value === v)?.label ?? v,
    );
    return <span>{labels.join(', ')}</span>;
  }
  if (field.type === 'signature') {
    return <span className="text-muted-foreground italic">Signature on file.</span>;
  }
  return <span>{String(value)}</span>;
}

// ── Schema form ───────────────────────────────────────────────────

function SchemaForm({
  template,
  answers,
  onChange,
}: {
  template: TreatmentRecordTemplate;
  answers: Record<string, unknown>;
  onChange: (next: Record<string, unknown>) => void;
}) {
  const fields = template.schema?.fields ?? [];
  if (fields.length === 0) {
    return (
      <p className="text-sm text-muted-foreground italic">
        This template has no fields.
      </p>
    );
  }
  const setField = (id: string, value: unknown) => {
    onChange({ ...answers, [id]: value });
  };
  return (
    <div className="space-y-4">
      {fields.map((field) => (
        <Field key={field.id}>
          <FieldLabel htmlFor={`f-${field.id}`}>
            {field.label}
            {field.required ? <span className="text-destructive ml-0.5">*</span> : null}
          </FieldLabel>
          <FieldInput
            field={field}
            value={answers[field.id]}
            onChange={(v) => setField(field.id, v)}
          />
        </Field>
      ))}
    </div>
  );
}

function FieldInput({
  field,
  value,
  onChange,
}: {
  field: TemplateField;
  value: unknown;
  onChange: (v: unknown) => void;
}) {
  switch (field.type) {
    case 'short_text':
      return (
        <Input
          id={`f-${field.id}`}
          value={typeof value === 'string' ? value : ''}
          onChange={(e) => onChange(e.target.value)}
        />
      );
    case 'long_text':
      return (
        <textarea
          id={`f-${field.id}`}
          rows={3}
          value={typeof value === 'string' ? value : ''}
          onChange={(e) => onChange(e.target.value)}
          className="block w-full rounded-md border bg-transparent px-3 py-2 text-sm shadow-xs outline-none resize-y focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
        />
      );
    case 'number':
      return (
        <Input
          id={`f-${field.id}`}
          type="number"
          inputMode="decimal"
          value={value == null ? '' : String(value)}
          onChange={(e) => {
            const v = e.target.value;
            onChange(v === '' ? null : Number(v));
          }}
        />
      );
    case 'date':
      return (
        <Input
          id={`f-${field.id}`}
          type="date"
          value={typeof value === 'string' ? value : ''}
          onChange={(e) => onChange(e.target.value)}
        />
      );
    case 'choice_single':
      return (
        <Select
          value={typeof value === 'string' ? value : undefined}
          onValueChange={(v) => onChange(v ?? '')}
        >
          <SelectTrigger id={`f-${field.id}`} className="w-full">
            <SelectValue placeholder="Select…">
              {(v) => {
                if (!v) return 'Select…';
                const opt = field.options?.find((o) => o.value === v);
                return opt?.label ?? v;
              }}
            </SelectValue>
          </SelectTrigger>
          <SelectContent>
            {(field.options ?? []).map((opt) => (
              <SelectItem key={opt.value} value={opt.value}>
                {opt.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      );
    case 'choice_multiple': {
      const arr = Array.isArray(value) ? (value as string[]) : [];
      return (
        <div className="space-y-1.5">
          {(field.options ?? []).map((opt) => {
            const checked = arr.includes(opt.value);
            return (
              <label
                key={opt.value}
                className={cn(
                  'flex items-center gap-2 rounded-md border px-3 py-2 cursor-pointer transition-colors text-sm',
                  checked
                    ? 'border-accent/50 bg-accent/[0.04]'
                    : 'border-border hover:bg-muted/40',
                )}
              >
                <Checkbox
                  checked={checked}
                  onCheckedChange={(v) => {
                    if (v === true) {
                      onChange([...arr, opt.value]);
                    } else {
                      onChange(arr.filter((x) => x !== opt.value));
                    }
                  }}
                />
                {opt.label}
              </label>
            );
          })}
        </div>
      );
    }
    case 'signature':
      return (
        <p className="text-xs text-muted-foreground italic">
          The provider signature is captured automatically on submit from the
          signed-in user.
        </p>
      );
  }
}

// ── Card wrapper ─────────────────────────────────────────────────

function Card({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-2xl border bg-card overflow-hidden">
      {children}
    </div>
  );
}

// ── Full-page state (loading, 404) ───────────────────────────────

function FullPageState({
  icon,
  title,
  message,
  tone,
}: {
  icon: React.ReactNode;
  title: string;
  message?: string;
  tone?: 'destructive' | 'muted';
}) {
  return (
    <div className="min-h-screen flex items-center justify-center px-4 py-12">
      <div className="max-w-md text-center">
        <div className="flex justify-center mb-4">{icon}</div>
        <h2
          className={cn(
            'font-serif text-2xl font-semibold tracking-tight mb-2',
            tone === 'destructive' && 'text-destructive',
            tone === 'muted' && 'text-muted-foreground',
          )}
        >
          {title}
        </h2>
        {message ? (
          <p className="text-sm text-muted-foreground leading-relaxed">{message}</p>
        ) : null}
      </div>
    </div>
  );
}
