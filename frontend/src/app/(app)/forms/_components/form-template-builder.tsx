/**
 * Shared builder for create + edit of `FormTemplate`.
 *
 * Two columns of state under the surface:
 *   - The template metadata (name, type, recurrence, active flag,
 *     service mapping when consent).
 *   - The schema's `fields` array — added / removed / reordered /
 *     edited inline.
 *
 * v1 reordering is up/down buttons (drag-and-drop is polish).
 * Per-field config stays inline (no expand/collapse) so the operator
 * sees everything at once. Validation mirrors the backend so invalid
 * states can't be saved — submit button stays disabled with an
 * inline summary of what's wrong.
 *
 * Service mapping is shown only for `consent` form_type. Switching
 * type to intake clears any selected services (with a warning) since
 * the backend rejects intake-with-services.
 */

'use client';

import {
  AlertCircle,
  ArrowDown,
  ArrowUp,
  ClipboardCheck,
  ClipboardList,
  GripVertical,
  Plus,
  Trash2,
} from 'lucide-react';
import { useEffect, useState } from 'react';

import { Button } from '@/components/ui/button';
import { Field, FieldError, FieldLabel } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';
import {
  defaultField,
  FIELD_TYPE_LABELS,
  FIELD_TYPES,
  type FieldType,
  type FormField,
  type FormSchema,
  type FormTemplate,
  type FormType,
  isChoiceField,
  type Recurrence,
} from '@/lib/form-templates';
import { useServices } from '@/lib/services';
import { cn } from '@/lib/utils';

export interface FormTemplateBuilderValues {
  name: string;
  description: string;
  form_type: FormType;
  recurrence: Recurrence;
  is_active: boolean;
  schema: FormSchema;
  service_ids: number[];
}

export interface FormTemplateBuilderProps {
  /** When provided, the builder is in edit mode (pre-fills fields,
   *  shows the current version, surfaces "Will bump to vN+1 on
   *  schema change" hint). When undefined, create mode. */
  existing?: FormTemplate;
  /** Optional initial form_type (used by `/forms/new?type=...`
   *  links from the empty-state CTAs to land in the right mode). */
  initialFormType?: FormType;
  /** Pre-fill the form with these values (used by the starter-template
   *  picker on `/forms/new?starter=...`). Operator can edit any field
   *  before saving — these aren't read-only, just default values.
   *  Ignored when `existing` is provided (edit mode wins). */
  initialValues?: Partial<FormTemplateBuilderValues>;
  onSubmit: (values: FormTemplateBuilderValues) => void;
  onCancel: () => void;
  isSubmitting: boolean;
}

export function FormTemplateBuilder({
  existing,
  initialFormType,
  initialValues,
  onSubmit,
  onCancel,
  isSubmitting,
}: FormTemplateBuilderProps) {
  const isEdit = existing !== undefined;
  const [values, setValues] = useState<FormTemplateBuilderValues>(() => {
    // Edit mode wins over starter pre-fill; starter wins over plain
    // defaults. Recurrence falls back to the type-appropriate default
    // when not explicitly supplied (intake → once; consent → per_visit).
    const formType: FormType =
      existing?.form_type
      ?? initialValues?.form_type
      ?? initialFormType
      ?? 'consent';
    return {
      name: existing?.name ?? initialValues?.name ?? '',
      description: existing?.description ?? initialValues?.description ?? '',
      form_type: formType,
      recurrence:
        existing?.recurrence
        ?? initialValues?.recurrence
        ?? (formType === 'intake' ? 'once' : 'per_visit'),
      is_active: existing?.is_active ?? initialValues?.is_active ?? true,
      schema: existing?.schema ?? initialValues?.schema ?? { fields: [] },
      service_ids: existing?.service_ids ?? initialValues?.service_ids ?? [],
    };
  });

  // Re-seed when the source template refetches after a save.
  useEffect(() => {
    if (existing) {
      setValues({
        name: existing.name,
        description: existing.description,
        form_type: existing.form_type,
        recurrence: existing.recurrence,
        is_active: existing.is_active,
        schema: existing.schema,
        service_ids: existing.service_ids,
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [existing?.updated_at, existing?.id]);

  // ── Validation ────────────────────────────────────────────────────
  const errors = validate(values);
  const canSave = errors.length === 0 && values.name.trim().length > 0;

  const setField = <K extends keyof FormTemplateBuilderValues>(
    key: K,
    value: FormTemplateBuilderValues[K],
  ) => {
    setValues((prev) => ({ ...prev, [key]: value }));
  };

  const handleTypeChange = (next: FormType) => {
    setValues((prev) => ({
      ...prev,
      form_type: next,
      // Intake forms reject service mapping (backend enforces) — clear
      // here so the user doesn't lose them silently if they switch back.
      service_ids: next === 'intake' ? [] : prev.service_ids,
      // Switching to intake → default recurrence to "once" (one-time
      // intake is the typical case); to consent → "per_visit" (CYA).
      // Only apply the default if the recurrence matches the OTHER
      // type's default — otherwise the user customized it and we
      // shouldn't overwrite.
      recurrence:
        next === 'intake' && prev.recurrence === 'per_visit'
          ? 'once'
          : next === 'consent' && prev.recurrence === 'once'
            ? 'per_visit'
            : prev.recurrence,
    }));
  };

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (!canSave || isSubmitting) return;
        onSubmit(values);
      }}
    >
      <div className="divide-y border-t border-b">
        {/* Identity */}
        <Section title="Form details" icon={<ClipboardList className="size-4 text-muted-foreground" />}>
          <Field>
            <FieldLabel htmlFor="name">Name</FieldLabel>
            <Input
              id="name"
              value={values.name}
              onChange={(e) => setField('name', e.target.value)}
              placeholder="e.g. New client intake, Botox consent"
              autoFocus={!isEdit}
            />
            {!values.name.trim() ? (
              <FieldError>Name is required.</FieldError>
            ) : null}
          </Field>

          <Field>
            <FieldLabel htmlFor="description">Internal notes (optional)</FieldLabel>
            <textarea
              id="description"
              value={values.description}
              onChange={(e) => setField('description', e.target.value)}
              rows={2}
              placeholder="When to use this form, what state regs require it, etc. Not shown to clients."
              className="w-full rounded-md border bg-background px-3 py-2 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 resize-y"
            />
          </Field>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <RadioGroup
              label="Form type"
              value={values.form_type}
              onChange={(next) => handleTypeChange(next as FormType)}
              options={[
                {
                  value: 'intake',
                  label: 'Intake',
                  description: "Auto-assigned to a client's first appointment ever (any service).",
                  icon: <ClipboardList className="size-3.5" />,
                },
                {
                  value: 'consent',
                  label: 'Consent',
                  description: 'Mapped to specific services and assigned when those services are booked.',
                  icon: <ClipboardCheck className="size-3.5" />,
                },
              ]}
            />
            <RadioGroup
              label="Re-sign rule"
              value={values.recurrence}
              onChange={(next) => setField('recurrence', next as Recurrence)}
              options={[
                {
                  value: 'once',
                  label: 'Once per customer',
                  description: 'Sign once forever. Typical for intake.',
                },
                {
                  value: 'per_visit',
                  label: 'Every visit',
                  description: 'Sign each appointment that triggers the form. Safest for clinical consent.',
                },
              ]}
            />
          </div>

          <ToggleRow
            label="Active"
            description="Inactive forms stop auto-assigning to new appointments. Existing pending or signed forms are unaffected."
            value={values.is_active}
            onChange={(next) => setField('is_active', next)}
          />
        </Section>

        {/* Service mapping (consent only) */}
        {values.form_type === 'consent' ? (
          <Section
            title="Services"
            description="Which services trigger this consent form when booked. Pick at least one — otherwise the form sits unused."
            icon={<ClipboardCheck className="size-4 text-muted-foreground" />}
          >
            <ServicePicker
              value={values.service_ids}
              onChange={(ids) => setField('service_ids', ids)}
            />
            {values.service_ids.length === 0 ? (
              <p className="text-[11px] text-amber-600 dark:text-amber-500 mt-1">
                Not mapped to any service yet. The form won&apos;t auto-assign
                to bookings until you pick at least one.
              </p>
            ) : null}
          </Section>
        ) : null}

        {/* Schema editor */}
        <Section
          title="Fields"
          description="The questions and signature blocks the client sees on the form. Drag-and-drop reordering is on the polish list — for now, use the up/down buttons."
        >
          <FieldEditor
            schema={values.schema}
            onChange={(schema) => setField('schema', schema)}
          />
        </Section>
      </div>

      {/* Validation summary + actions */}
      {errors.length > 0 ? (
        <div className="rounded-md border border-destructive/30 bg-destructive/[0.04] px-3 py-2.5 mt-4 flex items-start gap-2 text-xs">
          <AlertCircle className="size-3.5 shrink-0 text-destructive mt-0.5" />
          <div className="text-foreground/90 leading-relaxed">
            <p className="font-medium text-destructive mb-0.5">
              Fix these before saving:
            </p>
            <ul className="list-disc list-inside space-y-0.5 text-muted-foreground">
              {errors.map((err, i) => (
                <li key={i}>{err}</li>
              ))}
            </ul>
          </div>
        </div>
      ) : null}

      <div className="flex items-center justify-between gap-2 pt-4">
        {isEdit ? (
          <p className="text-[11px] text-muted-foreground">
            Currently v{existing!.version}.{' '}
            {schemaChanged(existing!.schema, values.schema)
              ? `Saving will bump to v${existing!.version + 1}.`
              : 'No schema changes pending.'}
          </p>
        ) : (
          <span />
        )}
        <div className="flex items-center gap-2">
          <Button
            type="button"
            variant="outline"
            disabled={isSubmitting}
            onClick={onCancel}
          >
            Cancel
          </Button>
          <Button type="submit" disabled={!canSave || isSubmitting}>
            {isSubmitting ? 'Saving…' : isEdit ? 'Save changes' : 'Create form'}
          </Button>
        </div>
      </div>
    </form>
  );
}

// ── Field editor ─────────────────────────────────────────────────────

function FieldEditor({
  schema,
  onChange,
}: {
  schema: FormSchema;
  onChange: (next: FormSchema) => void;
}) {
  const fields = schema.fields;

  const replaceField = (index: number, next: FormField) => {
    const out = [...fields];
    out[index] = next;
    onChange({ fields: out });
  };

  const removeField = (index: number) => {
    onChange({ fields: fields.filter((_, i) => i !== index) });
  };

  const moveField = (index: number, dir: -1 | 1) => {
    const target = index + dir;
    if (target < 0 || target >= fields.length) return;
    const out = [...fields];
    [out[index], out[target]] = [out[target], out[index]];
    onChange({ fields: out });
  };

  const addField = (type: FieldType) => {
    onChange({ fields: [...fields, defaultField(type, fields)] });
  };

  return (
    <div className="space-y-3">
      {fields.length === 0 ? (
        <div className="border border-dashed rounded-md bg-muted/20 px-4 py-6 text-center">
          <p className="text-sm text-muted-foreground">No fields yet.</p>
          <p className="text-[11px] text-muted-foreground/80 mt-1">
            Add at least one signature field for consent forms — that&apos;s
            the actual signing block.
          </p>
        </div>
      ) : (
        <ul className="space-y-2">
          {fields.map((field, i) => (
            <FieldRow
              key={field.id}
              field={field}
              index={i}
              total={fields.length}
              onChange={(next) => replaceField(i, next)}
              onMove={(dir) => moveField(i, dir)}
              onRemove={() => removeField(i)}
            />
          ))}
        </ul>
      )}

      <AddFieldPicker onPick={addField} />
    </div>
  );
}

function FieldRow({
  field,
  index,
  total,
  onChange,
  onMove,
  onRemove,
}: {
  field: FormField;
  index: number;
  total: number;
  onChange: (next: FormField) => void;
  onMove: (dir: -1 | 1) => void;
  onRemove: () => void;
}) {
  return (
    <li className="rounded-md border bg-card p-3 space-y-3">
      <div className="flex items-start gap-2">
        <div className="flex flex-col items-center pt-1">
          <button
            type="button"
            onClick={() => onMove(-1)}
            disabled={index === 0}
            aria-label="Move field up"
            className="inline-flex size-6 items-center justify-center rounded text-muted-foreground hover:text-foreground hover:bg-muted disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
          >
            <ArrowUp className="size-3.5" />
          </button>
          <GripVertical className="size-3 text-muted-foreground/30" aria-hidden />
          <button
            type="button"
            onClick={() => onMove(1)}
            disabled={index === total - 1}
            aria-label="Move field down"
            className="inline-flex size-6 items-center justify-center rounded text-muted-foreground hover:text-foreground hover:bg-muted disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
          >
            <ArrowDown className="size-3.5" />
          </button>
        </div>

        <div className="min-w-0 flex-1 space-y-2">
          <div className="flex items-center gap-2">
            <span className="text-[10px] uppercase tracking-wide text-muted-foreground/80 font-medium">
              {FIELD_TYPE_LABELS[field.type]}
            </span>
            <span className="text-[10px] text-muted-foreground/60 font-mono">
              {field.id}
            </span>
          </div>
          <Input
            value={field.label}
            onChange={(e) => onChange({ ...field, label: e.target.value })}
            placeholder="Field label shown to the client"
          />
          {/* Help text */}
          <Input
            value={field.help_text ?? ''}
            onChange={(e) => onChange({ ...field, help_text: e.target.value || undefined })}
            placeholder="Help text (optional)"
            className="text-xs"
          />
          {isChoiceField(field) ? (
            <ChoiceOptionsEditor
              options={field.options}
              onChange={(opts) => onChange({ ...field, options: opts })}
            />
          ) : null}
          <label className="inline-flex items-center gap-1.5 text-xs cursor-pointer">
            <input
              type="checkbox"
              checked={field.required}
              onChange={(e) => onChange({ ...field, required: e.target.checked })}
              className="size-3.5 rounded border-border text-foreground focus-visible:ring-2 focus-visible:ring-ring/50"
            />
            <span className="text-foreground">Required</span>
          </label>
        </div>

        <button
          type="button"
          onClick={onRemove}
          aria-label="Remove field"
          className="inline-flex size-7 items-center justify-center rounded text-muted-foreground hover:bg-destructive/10 hover:text-destructive transition-colors shrink-0"
        >
          <Trash2 className="size-3.5" />
        </button>
      </div>
    </li>
  );
}

function ChoiceOptionsEditor({
  options,
  onChange,
}: {
  options: { value: string; label: string }[];
  onChange: (next: { value: string; label: string }[]) => void;
}) {
  const setOption = (index: number, patch: Partial<{ value: string; label: string }>) => {
    onChange(options.map((o, i) => (i === index ? { ...o, ...patch } : o)));
  };

  const addOption = () => {
    const nextIndex = options.length + 1;
    onChange([
      ...options,
      { value: `option_${nextIndex}`, label: `Option ${nextIndex}` },
    ]);
  };

  const removeOption = (index: number) => {
    onChange(options.filter((_, i) => i !== index));
  };

  return (
    <div className="space-y-1.5 pl-2 border-l-2 border-muted">
      {options.map((opt, i) => (
        <div key={i} className="flex items-center gap-1.5">
          <Input
            value={opt.label}
            onChange={(e) => setOption(i, { label: e.target.value })}
            placeholder="Label shown to client"
            className="text-xs flex-1"
          />
          <Input
            value={opt.value}
            onChange={(e) => setOption(i, { value: e.target.value })}
            placeholder="value"
            className="text-xs font-mono w-32"
          />
          <button
            type="button"
            onClick={() => removeOption(i)}
            disabled={options.length <= 2}
            aria-label="Remove option"
            title={options.length <= 2 ? 'Choice fields require at least 2 options' : 'Remove'}
            className="inline-flex size-7 items-center justify-center rounded text-muted-foreground hover:bg-destructive/10 hover:text-destructive disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
          >
            <Trash2 className="size-3" />
          </button>
        </div>
      ))}
      <button
        type="button"
        onClick={addOption}
        className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
      >
        <Plus className="size-3" />
        Add option
      </button>
    </div>
  );
}

function AddFieldPicker({ onPick }: { onPick: (type: FieldType) => void }) {
  const [open, setOpen] = useState(false);
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger
        render={
          <button
            type="button"
            className="inline-flex items-center gap-1.5 h-8 px-3 rounded-md border bg-card text-xs font-medium hover:bg-muted transition-colors w-full justify-center"
          >
            <Plus className="size-3.5" />
            Add field
          </button>
        }
      />
      <PopoverContent align="center" sideOffset={6} className="w-56 p-1">
        <ul className="space-y-0.5">
          {FIELD_TYPES.map((type) => (
            <li key={type}>
              <button
                type="button"
                onClick={() => {
                  onPick(type);
                  setOpen(false);
                }}
                className="w-full text-left text-sm px-2 py-1.5 rounded-md hover:bg-muted transition-colors"
              >
                {FIELD_TYPE_LABELS[type]}
              </button>
            </li>
          ))}
        </ul>
      </PopoverContent>
    </Popover>
  );
}

// ── Service picker ──────────────────────────────────────────────────

function ServicePicker({
  value,
  onChange,
}: {
  value: number[];
  onChange: (ids: number[]) => void;
}) {
  const { data: services, isLoading } = useServices();
  const selected = new Set(value);

  if (isLoading) {
    return <p className="text-sm text-muted-foreground">Loading services…</p>;
  }
  if (!services || services.length === 0) {
    return (
      <p className="text-sm text-muted-foreground italic">
        No services configured yet. Create services first, then come back to map them.
      </p>
    );
  }

  const toggle = (id: number) => {
    const next = new Set(selected);
    if (next.has(id)) {
      next.delete(id);
    } else {
      next.add(id);
    }
    onChange([...next]);
  };

  return (
    <ul className="space-y-1 max-h-72 overflow-y-auto border rounded-md bg-background p-1">
      {services.map((svc) => {
        const isSelected = selected.has(svc.id);
        return (
          <li key={svc.id}>
            <label
              className={cn(
                'flex items-center gap-2 px-2 py-1.5 rounded-md cursor-pointer transition-colors',
                isSelected ? 'bg-accent/10' : 'hover:bg-muted/40',
              )}
            >
              <input
                type="checkbox"
                checked={isSelected}
                onChange={() => toggle(svc.id)}
                className="size-3.5 rounded border-border text-foreground focus-visible:ring-2 focus-visible:ring-ring/50"
              />
              <span className="text-sm flex-1 truncate">{svc.name}</span>
              <span className="text-[10px] text-muted-foreground font-mono">
                {svc.code}
              </span>
            </label>
          </li>
        );
      })}
    </ul>
  );
}

// ── Layout primitives ───────────────────────────────────────────────

function Section({
  title,
  description,
  icon,
  children,
}: {
  title: string;
  description?: string;
  icon?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className="grid grid-cols-1 lg:grid-cols-[280px_1fr] gap-6 lg:gap-12 py-6 first:pt-8 last:pb-8">
      <header>
        <div className="flex items-center gap-2">
          {icon}
          <h2 className="font-serif text-base font-semibold tracking-tight">
            {title}
          </h2>
        </div>
        {description ? (
          <p className="text-xs text-muted-foreground mt-1.5 leading-relaxed">
            {description}
          </p>
        ) : null}
      </header>
      <div className="space-y-3 max-w-2xl">{children}</div>
    </section>
  );
}

function RadioGroup({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: Array<{
    value: string;
    label: string;
    description: string;
    icon?: React.ReactNode;
  }>;
}) {
  return (
    <div>
      <p className="text-[11px] uppercase tracking-wide text-muted-foreground font-medium mb-2">
        {label}
      </p>
      <div className="space-y-1.5">
        {options.map((opt) => {
          const checked = value === opt.value;
          return (
            <label
              key={opt.value}
              className={cn(
                'block rounded-md border px-3 py-2 cursor-pointer transition-colors',
                checked
                  ? 'border-accent/50 bg-accent/[0.04]'
                  : 'border-border hover:bg-muted/40',
              )}
            >
              <div className="flex items-center gap-2">
                <input
                  type="radio"
                  checked={checked}
                  onChange={() => onChange(opt.value)}
                  className="size-3.5"
                />
                {opt.icon}
                <span className="text-sm font-medium">{opt.label}</span>
              </div>
              <p className="text-[11px] text-muted-foreground mt-0.5 ml-6 leading-relaxed">
                {opt.description}
              </p>
            </label>
          );
        })}
      </div>
    </div>
  );
}

function ToggleRow({
  label,
  description,
  value,
  onChange,
  disabled,
}: {
  label: string;
  description: string;
  value: boolean;
  onChange: (next: boolean) => void;
  disabled?: boolean;
}) {
  return (
    <label className="flex items-start gap-3 py-2 cursor-pointer">
      <input
        type="checkbox"
        checked={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
        className="mt-0.5 size-4 rounded border-border text-foreground focus-visible:ring-2 focus-visible:ring-ring/50 disabled:opacity-50"
      />
      <div className="min-w-0 flex-1">
        <span className="text-sm font-medium">{label}</span>
        <p className="text-[11px] text-muted-foreground leading-relaxed">
          {description}
        </p>
      </div>
    </label>
  );
}

// ── Validation ──────────────────────────────────────────────────────

function validate(values: FormTemplateBuilderValues): string[] {
  const errors: string[] = [];
  if (!values.name.trim()) {
    errors.push('Form name is required.');
  }
  // Per-field validation mirrors the backend rules.
  const seenIds = new Set<string>();
  values.schema.fields.forEach((field, i) => {
    if (!field.label.trim()) {
      errors.push(`Field ${i + 1}: label is required.`);
    }
    if (seenIds.has(field.id)) {
      errors.push(`Field ${i + 1}: duplicate id "${field.id}".`);
    }
    seenIds.add(field.id);
    if (isChoiceField(field)) {
      if (field.options.length < 2) {
        errors.push(`Field ${i + 1}: choice fields need at least 2 options.`);
      }
      const optValues = new Set<string>();
      field.options.forEach((opt, oi) => {
        if (!opt.value.trim()) {
          errors.push(`Field ${i + 1}, option ${oi + 1}: value required.`);
        }
        if (!opt.label.trim()) {
          errors.push(`Field ${i + 1}, option ${oi + 1}: label required.`);
        }
        if (optValues.has(opt.value)) {
          errors.push(`Field ${i + 1}: duplicate option value "${opt.value}".`);
        }
        optValues.add(opt.value);
      });
    }
  });
  return errors;
}

function schemaChanged(a: FormSchema, b: FormSchema): boolean {
  return JSON.stringify(a) !== JSON.stringify(b);
}
