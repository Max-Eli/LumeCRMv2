/**
 * `<TreatmentRecordsTab>` — read-only history of structured EMR
 * records signed against this customer.
 *
 * Distinct from the `<NotesTab>` which lists free-form chart notes.
 * Treatment records are the structured per-template instances —
 * units used, lots, observations — produced from the appointment
 * "Sign treatment record" flow.
 *
 * Renders the schema_snapshot + answers exactly as they were at
 * signing time so the record stays legible even after the template
 * has been edited.
 */

'use client';

import {
  CalendarClock,
  Check,
  ChevronDown,
  ChevronUp,
  ClipboardCheck,
  FileX,
  Loader2,
  Lock,
  Plus,
  UserCircle2,
} from 'lucide-react';
import { useRouter, useSearchParams } from 'next/navigation';
import { useEffect, useState } from 'react';
import { toast } from 'sonner';

import { ApiError } from '@/lib/api';
import {
  authorDisplayName,
  type TemplateField,
  type TreatmentRecord,
  type TreatmentRecordTemplate,
  useCustomerTreatmentRecords,
  useSubmitTreatmentRecord,
  useTreatmentTemplate,
  useTreatmentTemplates,
} from '@/lib/treatments';
import { cn } from '@/lib/utils';

import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';

export function TreatmentRecordsTab({ customerId }: { customerId: number }) {
  const { data: records, isLoading } = useCustomerTreatmentRecords(customerId);
  const [signOpen, setSignOpen] = useState(false);
  const router = useRouter();
  const searchParams = useSearchParams();

  // Deep-link from the calendar appointment popover:
  //   /clients/<id>?tab=treatment-records&sign=<appointmentId>
  // Auto-opens the new-record dialog with that appointment pre-pinned.
  // We strip the `sign` param after opening so a back/forward doesn't
  // pop the dialog open every time.
  const signParam = searchParams.get('sign');
  const pinnedAppointmentId = signParam ? Number(signParam) : null;
  useEffect(() => {
    if (pinnedAppointmentId && pinnedAppointmentId > 0) {
      setSignOpen(true);
      const next = new URLSearchParams(searchParams);
      next.delete('sign');
      const qs = next.toString();
      router.replace(qs ? `?${qs}` : '?', { scroll: false });
    }
    // Intentionally empty deps — fire once on mount when the param exists.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 text-sm text-muted-foreground py-12">
        <Loader2 className="size-4 animate-spin" />
        Loading treatment records…
      </div>
    );
  }
  if (!records?.length) {
    return (
      <>
        <div className="rounded-xl border border-dashed bg-card px-10 py-16 text-center max-w-2xl">
          <div className="inline-flex size-12 items-center justify-center rounded-full bg-muted mb-3">
            <ClipboardCheck className="size-5 text-muted-foreground" />
          </div>
          <p className="font-medium">No treatment records on file</p>
          <p className="text-sm text-muted-foreground mt-1 max-w-md mx-auto">
            Records are signed structured forms documenting what was performed
            in a session. Templates are managed in
            <span className="font-mono mx-1 text-xs px-1.5 py-0.5 rounded bg-muted">
              Forms → EMR templates
            </span>.
          </p>
          <Button onClick={() => setSignOpen(true)} className="mt-4">
            <Plus className="size-4" />
            Sign new record
          </Button>
        </div>
        <SignRecordDialog
          customerId={customerId}
          appointmentId={pinnedAppointmentId}
          open={signOpen}
          onOpenChange={setSignOpen}
        />
      </>
    );
  }

  // Group by parent: top-level records first, addenda nested.
  const byId = new Map<number, TreatmentRecord>();
  for (const r of records) byId.set(r.id, r);
  const topLevel = records.filter((r) => r.parent_record_id === null);
  const addendaByParent = new Map<number, TreatmentRecord[]>();
  for (const r of records) {
    if (r.parent_record_id !== null) {
      const arr = addendaByParent.get(r.parent_record_id) ?? [];
      arr.push(r);
      addendaByParent.set(r.parent_record_id, arr);
    }
  }

  return (
    <div className="space-y-4 max-w-3xl">
      <div className="flex items-center justify-between">
        <p className="text-xs text-muted-foreground">
          {topLevel.length} record{topLevel.length === 1 ? '' : 's'} on file
        </p>
        <Button onClick={() => setSignOpen(true)} size="sm">
          <Plus className="size-3.5" />
          Sign new record
        </Button>
      </div>
      {topLevel.map((rec) => (
        <RecordCard
          key={rec.id}
          record={rec}
          addenda={addendaByParent.get(rec.id) ?? []}
        />
      ))}
      <SignRecordDialog
        customerId={customerId}
        open={signOpen}
        onOpenChange={setSignOpen}
      />
    </div>
  );
}

// ── Sign-new-record dialog ─────────────────────────────────────────


function SignRecordDialog({
  customerId,
  appointmentId,
  open,
  onOpenChange,
}: {
  customerId: number;
  /** When set, the record is pinned to this appointment — used by
   *  the calendar popover's "Sign treatment record" flow so the
   *  resulting EMR row links back to the visit it documents. */
  appointmentId?: number | null;
  open: boolean;
  onOpenChange: (v: boolean) => void;
}) {
  const [templateId, setTemplateId] = useState<number | null>(null);
  const [answers, setAnswers] = useState<Record<string, unknown>>({});
  const [error, setError] = useState<string | null>(null);
  const submit = useSubmitTreatmentRecord();
  const { data: templates } = useTreatmentTemplates({ active: true });
  const { data: template } = useTreatmentTemplate(templateId ?? undefined);

  // Reset state when the dialog closes so a re-open starts clean.
  useEffect(() => {
    if (!open) {
      setTemplateId(null);
      setAnswers({});
      setError(null);
    }
  }, [open]);

  const onSubmit = async () => {
    setError(null);
    if (!templateId) {
      setError('Pick a template.');
      return;
    }
    // Required-field check on the client. The backend will enforce
    // schema-vs-answers shape too, but we surface inline here for
    // the operator before round-tripping.
    if (template) {
      for (const f of template.schema?.fields ?? []) {
        if (f.required) {
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
      }
    }
    try {
      await submit.mutateAsync({
        customer_id: customerId,
        template_id: templateId,
        answers,
        ...(appointmentId ? { appointment_id: appointmentId } : {}),
      });
      toast.success('Treatment record signed.');
      onOpenChange(false);
    } catch (err) {
      if (err instanceof ApiError && err.body && typeof err.body === 'object') {
        const body = err.body as Record<string, string | string[]>;
        const firstKey = Object.keys(body)[0];
        const v = firstKey ? body[firstKey] : undefined;
        const msg = Array.isArray(v) ? v[0] : v;
        setError(typeof msg === 'string' ? msg : 'Could not sign.');
      } else {
        setError('Could not sign.');
      }
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>Sign treatment record</DialogTitle>
        </DialogHeader>
        <DialogBody className="space-y-4">
          {appointmentId ? (
            <div className="rounded-md border border-accent/30 bg-accent/[0.05] px-3 py-2 flex items-start gap-2 text-xs">
              <CalendarClock className="size-3.5 shrink-0 text-accent-foreground/80 mt-0.5" />
              <p className="text-foreground/85 leading-relaxed">
                This record will be pinned to the appointment you came from,
                so it shows up under that visit's chart.
              </p>
            </div>
          ) : null}
          <div>
            <label className="text-xs font-medium block mb-1.5">Template</label>
            <Select
              value={templateId ? String(templateId) : undefined}
              onValueChange={(v) => {
                setTemplateId(v ? Number(v) : null);
                setAnswers({});
              }}
            >
              <SelectTrigger>
                <SelectValue placeholder="Pick a template…">
                  {(v) => {
                    if (!v) return 'Pick a template…';
                    const picked = (templates ?? []).find(
                      (t) => String(t.id) === v,
                    );
                    return picked?.name ?? v;
                  }}
                </SelectValue>
              </SelectTrigger>
              <SelectContent>
                {(templates ?? []).map((t) => (
                  <SelectItem key={t.id} value={String(t.id)}>
                    {t.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {template ? (
            <SchemaForm
              template={template}
              answers={answers}
              onChange={setAnswers}
            />
          ) : (
            <p className="text-xs text-muted-foreground italic">
              Pick a template to continue.
            </p>
          )}

          {error ? <p className="text-xs text-destructive">{error}</p> : null}
        </DialogBody>
        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={submit.isPending}
          >
            Cancel
          </Button>
          <Button
            type="button"
            onClick={onSubmit}
            disabled={submit.isPending || !templateId}
          >
            {submit.isPending ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <Check className="size-4" />
            )}
            Sign record
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

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
    <div className="space-y-4 max-h-[60vh] overflow-y-auto pr-1">
      {fields.map((field) => (
        <div key={field.id}>
          <label className="text-xs font-medium block mb-1.5">
            {field.label}
            {field.required ? (
              <span className="text-destructive ml-0.5">*</span>
            ) : null}
          </label>
          <FieldInput
            field={field}
            value={answers[field.id]}
            onChange={(v) => setField(field.id, v)}
          />
          {field.hint ? (
            <p className="text-[11px] text-muted-foreground mt-1">{field.hint}</p>
          ) : null}
        </div>
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
  if (field.type === 'short_text') {
    return (
      <Input
        value={typeof value === 'string' ? value : ''}
        onChange={(e) => onChange(e.target.value)}
      />
    );
  }
  if (field.type === 'long_text') {
    return (
      <textarea
        rows={3}
        value={typeof value === 'string' ? value : ''}
        onChange={(e) => onChange(e.target.value)}
        className="block w-full rounded-md border bg-transparent px-3 py-2 text-sm shadow-xs outline-none resize-y focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
      />
    );
  }
  if (field.type === 'number') {
    return (
      <Input
        type="number"
        inputMode="decimal"
        value={value == null ? '' : String(value)}
        onChange={(e) => {
          const v = e.target.value;
          onChange(v === '' ? null : Number(v));
        }}
      />
    );
  }
  if (field.type === 'date') {
    return (
      <Input
        type="date"
        value={typeof value === 'string' ? value : ''}
        onChange={(e) => onChange(e.target.value)}
      />
    );
  }
  if (field.type === 'choice_single') {
    return (
      <Select
        value={typeof value === 'string' ? value : undefined}
        onValueChange={(v) => onChange(v ?? '')}
      >
        <SelectTrigger>
          <SelectValue placeholder="Select…">
            {(v) => {
              if (!v) return 'Select…';
              const opt = (field.options ?? []).find((o) => o.value === v);
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
  }
  if (field.type === 'choice_multiple') {
    const arr = Array.isArray(value) ? (value as string[]) : [];
    return (
      <div className="space-y-1.5">
        {(field.options ?? []).map((opt) => {
          const checked = arr.includes(opt.value);
          return (
            <label
              key={opt.value}
              className="flex items-center gap-2 text-sm cursor-pointer"
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
  if (field.type === 'signature') {
    return (
      <p className="text-xs text-muted-foreground italic">
        (Signature capture coming with the iPad Pencil flow.)
      </p>
    );
  }
  return null;
}

function RecordCard({
  record,
  addenda,
}: {
  record: TreatmentRecord;
  addenda: TreatmentRecord[];
}) {
  const [expanded, setExpanded] = useState(false);
  const isVoided = record.is_voided;

  return (
    <article
      className={cn(
        'rounded-xl border bg-card shadow-sm overflow-hidden',
        isVoided && 'opacity-60',
      )}
    >
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        className="w-full text-left px-5 py-4 flex items-start gap-3 hover:bg-muted/40 transition-colors"
      >
        <div
          className={cn(
            'size-9 inline-flex items-center justify-center rounded-md shrink-0',
            isVoided
              ? 'bg-muted text-muted-foreground'
              : 'bg-accent/15 text-accent-foreground',
          )}
          aria-hidden
        >
          <ClipboardCheck className="size-4" />
        </div>
        <div className="min-w-0 flex-1">
          <p
            className={cn(
              'font-medium truncate',
              isVoided && 'line-through',
            )}
          >
            {record.template_name}{' '}
            <span className="text-xs text-muted-foreground font-normal">
              v{record.template_version_at_signing}
            </span>
          </p>
          <p className="text-xs text-muted-foreground mt-0.5 inline-flex items-center gap-2">
            <CalendarClock className="size-3" />
            Signed {formatDate(record.signed_at)}
            <span aria-hidden>·</span>
            <UserCircle2 className="size-3" />
            {authorDisplayName(record)}
            {record.author_was_clinical ? (
              <span className="text-emerald-700">· Clinical</span>
            ) : null}
          </p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {isVoided ? (
            <span className="text-[10px] uppercase tracking-wide font-medium px-1.5 py-0.5 rounded bg-muted text-muted-foreground border">
              Voided
            </span>
          ) : record.is_locked ? (
            <span
              className="text-[10px] uppercase tracking-wide font-medium px-1.5 py-0.5 rounded bg-muted text-muted-foreground border inline-flex items-center gap-1"
              title="Past edit window — additions go through addenda."
            >
              <Lock className="size-2.5" /> Locked
            </span>
          ) : null}
          {expanded ? (
            <ChevronUp className="size-4 text-muted-foreground" />
          ) : (
            <ChevronDown className="size-4 text-muted-foreground" />
          )}
        </div>
      </button>

      {expanded ? (
        <div className="px-5 pb-5 pt-0 border-t bg-muted/20">
          {isVoided ? (
            <div className="my-3 rounded-md bg-destructive/5 border border-destructive/20 px-3 py-2 text-xs text-destructive">
              <p className="inline-flex items-center gap-1.5 font-medium">
                <FileX className="size-3.5" /> Voided record
              </p>
              {record.voided_reason ? (
                <p className="mt-1 leading-relaxed">{record.voided_reason}</p>
              ) : null}
            </div>
          ) : null}
          <RecordAnswers record={record} />
          {addenda.length > 0 ? (
            <div className="mt-4 pt-4 border-t border-muted-foreground/10">
              <p className="text-[11px] uppercase tracking-wide text-muted-foreground font-medium mb-2">
                Addenda ({addenda.length})
              </p>
              <ul className="space-y-3">
                {addenda.map((a) => (
                  <li key={a.id} className="rounded-md border bg-card p-3">
                    <p className="text-[11px] text-muted-foreground inline-flex items-center gap-1.5 mb-2">
                      <CalendarClock className="size-3" />
                      {formatDate(a.signed_at)}
                      <span aria-hidden>·</span>
                      <UserCircle2 className="size-3" />
                      {authorDisplayName(a)}
                    </p>
                    <RecordAnswers record={a} />
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      ) : null}
    </article>
  );
}

function RecordAnswers({ record }: { record: TreatmentRecord }) {
  const fields: TemplateField[] = record.schema_snapshot?.fields ?? [];
  if (fields.length === 0) {
    return (
      <p className="text-sm text-muted-foreground italic">
        No structured fields on this record.
      </p>
    );
  }
  return (
    <dl className="grid grid-cols-1 sm:grid-cols-[140px_1fr] gap-x-3 gap-y-2 text-sm">
      {fields.map((field) => {
        const value = record.answers?.[field.id];
        return (
          <div key={field.id} className="contents">
            <dt className="text-xs text-muted-foreground sm:pt-0.5">
              {field.label}
            </dt>
            <dd className={cn(value == null || value === '' ? 'text-muted-foreground italic' : '')}>
              {renderAnswer(field, value)}
            </dd>
          </div>
        );
      })}
    </dl>
  );
}

function renderAnswer(field: TemplateField, value: unknown): React.ReactNode {
  if (value == null || value === '') return '—';
  if (field.type === 'choice_multiple' && Array.isArray(value)) {
    const labels = value.map((v) => {
      const opt = field.options?.find((o) => o.value === v);
      return opt?.label ?? String(v);
    });
    return labels.join(', ');
  }
  if (field.type === 'choice_single') {
    const opt = field.options?.find((o) => o.value === value);
    return opt?.label ?? String(value);
  }
  if (field.type === 'long_text') {
    return <span className="whitespace-pre-wrap">{String(value)}</span>;
  }
  if (field.type === 'signature') {
    return <span className="text-xs text-muted-foreground italic">(Signature on file)</span>;
  }
  return String(value);
}

function formatDate(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString(undefined, {
    weekday: 'short',
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  });
}
