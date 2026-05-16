/**
 * `<TemplateEditor>` — author + edit a TreatmentRecordTemplate.
 *
 * Tactical schema builder: rows of fields where each row picks the
 * field type, label, required flag, and (for choice fields) a
 * comma-separated options list. Not as polished as the existing
 * `<FormTemplateBuilder>` (which uses drag-handles + per-type
 * dedicated UIs); the trade-off is shipping the EMR templates this
 * session vs. forking a 700-line form builder.
 *
 * Field IDs auto-generate from the label (snake_case) so operators
 * never see them. Saving the same field with a different label
 * keeps the original id (avoids breaking submitted records that
 * already reference it via `schema_snapshot`).
 */

'use client';

import {
  Check,
  ChevronDown,
  ChevronUp,
  Loader2,
  Plus,
  Trash2,
} from 'lucide-react';
import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import { toast } from 'sonner';

import { ApiError } from '@/lib/api';
import { useServices } from '@/lib/services';
import {
  FIELD_TYPE_LABELS,
  type TemplateField,
  type TemplateFieldType,
  type TreatmentRecordTemplate,
  useCreateTreatmentTemplate,
  useDeleteTreatmentTemplate,
  useUpdateTreatmentTemplate,
} from '@/lib/treatments';
import { cn } from '@/lib/utils';

import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';

interface DraftField {
  rowId: number;
  /** Existing id for established fields; empty for new ones (gets
   *  derived from the label at save time). */
  id: string;
  type: TemplateFieldType;
  label: string;
  required: boolean;
  /** Comma-separated for the editor; serialised to {value, label}
   *  pairs at save time. */
  optionsText: string;
}

let _nextRowId = 1;
const FIELD_TYPES: TemplateFieldType[] = [
  'short_text',
  'long_text',
  'number',
  'choice_single',
  'choice_multiple',
  'date',
  'signature',
];

function makeRow(seed?: TemplateField): DraftField {
  return {
    rowId: _nextRowId++,
    id: seed?.id ?? '',
    type: seed?.type ?? 'short_text',
    label: seed?.label ?? '',
    required: seed?.required ?? false,
    optionsText: seed?.options?.map((o) => o.label).join(', ') ?? '',
  };
}

function slugify(label: string, existing: Set<string>): string {
  let base = label
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
    .slice(0, 64);
  if (!base) base = 'field';
  let candidate = base;
  let n = 2;
  while (existing.has(candidate)) {
    candidate = `${base}_${n}`;
    n += 1;
  }
  return candidate;
}

export function TemplateEditor({
  template,
}: {
  template?: TreatmentRecordTemplate;
}) {
  const router = useRouter();
  const isEdit = !!template;

  const [name, setName] = useState(template?.name ?? '');
  const [description, setDescription] = useState(template?.description ?? '');
  const [isActive, setIsActive] = useState(template?.is_active ?? true);
  const [serviceIds, setServiceIds] = useState<number[]>(
    template?.service_ids ?? [],
  );
  const [fields, setFields] = useState<DraftField[]>(() =>
    template?.schema?.fields?.length
      ? template.schema.fields.map((f) => makeRow(f))
      : [makeRow()],
  );
  const [error, setError] = useState<string | null>(null);

  const services = useServices({ activeOnly: true });
  const create = useCreateTreatmentTemplate();
  const update = useUpdateTreatmentTemplate(template?.id ?? 0);
  const del = useDeleteTreatmentTemplate();
  const pending = create.isPending || update.isPending;

  const moveRow = (idx: number, dir: -1 | 1) => {
    setFields((prev) => {
      const next = [...prev];
      const swap = idx + dir;
      if (swap < 0 || swap >= next.length) return prev;
      [next[idx], next[swap]] = [next[swap], next[idx]];
      return next;
    });
  };

  const onSave = async () => {
    setError(null);
    if (!name.trim()) {
      setError('Template name is required.');
      return;
    }
    if (fields.length === 0) {
      setError('Add at least one field.');
      return;
    }

    // Build the schema. Stable ids: keep existing ones; slugify
    // new fields off their label.
    const usedIds = new Set<string>();
    const builtFields: TemplateField[] = [];
    for (const row of fields) {
      const label = row.label.trim();
      if (!label) {
        setError('Every field needs a label.');
        return;
      }
      const id = row.id || slugify(label, usedIds);
      if (usedIds.has(id)) {
        setError(`Duplicate field id "${id}".`);
        return;
      }
      usedIds.add(id);
      const field: TemplateField = {
        id,
        type: row.type,
        label,
        required: row.required,
      };
      if (row.type === 'choice_single' || row.type === 'choice_multiple') {
        const opts = row.optionsText
          .split(',')
          .map((o) => o.trim())
          .filter(Boolean);
        if (opts.length < 2) {
          setError(`"${label}" needs at least two options (comma-separated).`);
          return;
        }
        field.options = opts.map((label) => ({
          value: slugify(label, new Set()),
          label,
        }));
      }
      builtFields.push(field);
    }

    const payload = {
      name: name.trim(),
      description,
      is_active: isActive,
      schema: { fields: builtFields },
      set_service_ids: serviceIds,
    };

    try {
      if (isEdit) {
        await update.mutateAsync(payload);
        toast.success('Template saved.');
        router.refresh();
      } else {
        const created = await create.mutateAsync(payload);
        toast.success('Template created.');
        router.replace(`/catalog/treatment-record-templates/${created.id}`);
      }
    } catch (err) {
      if (err instanceof ApiError && err.body && typeof err.body === 'object') {
        const body = err.body as Record<string, string | string[]>;
        const firstKey = Object.keys(body)[0];
        const v = firstKey ? body[firstKey] : undefined;
        const msg = Array.isArray(v) ? v[0] : v;
        setError(typeof msg === 'string' ? msg : 'Could not save.');
      } else {
        setError('Could not save.');
      }
    }
  };

  const onDelete = async () => {
    if (!template) return;
    if (!window.confirm(`Delete "${template.name}"? This is permanent.`)) return;
    try {
      await del.mutateAsync(template.id);
      toast.success('Template deleted.');
      router.replace('/catalog/treatment-record-templates');
    } catch (err) {
      if (err instanceof ApiError && err.body && typeof err.body === 'object') {
        const body = err.body as { detail?: string };
        toast.error(body.detail || 'Could not delete.');
      } else {
        toast.error('Could not delete.');
      }
    }
  };

  return (
    <div className="space-y-6 max-w-4xl">
      <section className="rounded-xl border bg-card p-6 space-y-4">
        <header>
          <h2 className="text-base font-medium tracking-tight">Basics</h2>
          <p className="text-xs text-muted-foreground mt-0.5">
            How the template appears in the picker.
          </p>
        </header>

        <div>
          <label htmlFor="tpl-name" className="text-xs font-medium block mb-1.5">
            Name
          </label>
          <Input
            id="tpl-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Botox treatment record"
          />
        </div>

        <div>
          <label htmlFor="tpl-desc" className="text-xs font-medium block mb-1.5">
            Description (optional)
          </label>
          <textarea
            id="tpl-desc"
            rows={2}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="When to use this template — internal notes."
            className="block w-full rounded-md border bg-transparent px-3 py-2 text-sm shadow-xs outline-none resize-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
          />
        </div>

        <div className="flex items-center gap-3">
          <Checkbox
            id="tpl-active"
            checked={isActive}
            onCheckedChange={(v) => setIsActive(v === true)}
          />
          <label htmlFor="tpl-active" className="text-sm">
            Active &mdash; show in the &ldquo;new record&rdquo; picker
          </label>
        </div>
      </section>

      <ServiceAssignments
        serviceIds={serviceIds}
        onChange={setServiceIds}
        services={services.data ?? []}
        loading={services.isLoading}
      />

      <section className="rounded-xl border bg-card p-6">
        <header className="flex items-center justify-between mb-3">
          <div>
            <h2 className="text-base font-medium tracking-tight">Fields</h2>
            <p className="text-xs text-muted-foreground mt-0.5">
              The structured questions providers fill out.
            </p>
          </div>
          <button
            type="button"
            onClick={() => setFields((prev) => [...prev, makeRow()])}
            className="text-xs text-muted-foreground hover:text-foreground transition-colors inline-flex items-center gap-1"
          >
            <Plus className="size-3.5" />
            Add field
          </button>
        </header>

        <ul className="space-y-2.5">
          {fields.map((row, idx) => (
            <FieldRow
              key={row.rowId}
              row={row}
              index={idx}
              total={fields.length}
              onChange={(next) =>
                setFields((prev) => prev.map((r, i) => (i === idx ? next : r)))
              }
              onRemove={() =>
                setFields((prev) => prev.filter((_, i) => i !== idx))
              }
              onMove={(dir) => moveRow(idx, dir)}
            />
          ))}
        </ul>
      </section>

      {error ? (
        <p className="text-sm text-destructive">{error}</p>
      ) : null}

      <div className="sticky bottom-0 -mx-10 px-10 py-3 bg-background/95 backdrop-blur border-t flex items-center justify-between gap-2">
        {isEdit ? (
          <Button
            type="button"
            variant="outline"
            onClick={onDelete}
            disabled={del.isPending}
            className="text-destructive border-destructive/30 hover:bg-destructive/10"
          >
            {del.isPending ? <Loader2 className="size-4 animate-spin" /> : <Trash2 className="size-4" />}
            Delete template
          </Button>
        ) : (
          <div />
        )}
        <Button type="button" onClick={onSave} disabled={pending}>
          {pending ? <Loader2 className="size-4 animate-spin" /> : <Check className="size-4" />}
          {isEdit ? 'Save changes' : 'Create template'}
        </Button>
      </div>
    </div>
  );
}

function FieldRow({
  row,
  index,
  total,
  onChange,
  onRemove,
  onMove,
}: {
  row: DraftField;
  index: number;
  total: number;
  onChange: (next: DraftField) => void;
  onRemove: () => void;
  onMove: (dir: -1 | 1) => void;
}) {
  const isChoice = row.type === 'choice_single' || row.type === 'choice_multiple';
  return (
    <li className="rounded-lg border bg-background p-3 space-y-2.5">
      <div className="flex items-start gap-2">
        <div className="flex flex-col">
          <button
            type="button"
            onClick={() => onMove(-1)}
            disabled={index === 0}
            aria-label="Move up"
            className="size-5 inline-flex items-center justify-center rounded text-muted-foreground hover:text-foreground hover:bg-muted disabled:opacity-30"
          >
            <ChevronUp className="size-3" />
          </button>
          <button
            type="button"
            onClick={() => onMove(1)}
            disabled={index === total - 1}
            aria-label="Move down"
            className="size-5 inline-flex items-center justify-center rounded text-muted-foreground hover:text-foreground hover:bg-muted disabled:opacity-30"
          >
            <ChevronDown className="size-3" />
          </button>
        </div>
        <div className="flex-1 min-w-0 grid grid-cols-1 sm:grid-cols-[1fr_180px] gap-2">
          <Input
            value={row.label}
            onChange={(e) => onChange({ ...row, label: e.target.value })}
            placeholder="Field label (e.g. Units used)"
            className="text-sm"
          />
          <Select
            value={row.type}
            onValueChange={(v) =>
              onChange({ ...row, type: (v ?? 'short_text') as TemplateFieldType })
            }
          >
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {FIELD_TYPES.map((t) => (
                <SelectItem key={t} value={t}>
                  {FIELD_TYPE_LABELS[t]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <button
          type="button"
          onClick={onRemove}
          aria-label="Remove field"
          title="Remove field"
          className="size-9 inline-flex items-center justify-center rounded-md text-muted-foreground hover:text-destructive hover:bg-destructive/10 transition-colors shrink-0"
        >
          <Trash2 className="size-3.5" />
        </button>
      </div>

      {isChoice ? (
        <div className="ml-7">
          <label className="text-[11px] font-medium block mb-1">
            Options (comma-separated)
          </label>
          <Input
            value={row.optionsText}
            onChange={(e) => onChange({ ...row, optionsText: e.target.value })}
            placeholder="e.g. Mild, Moderate, Severe"
            className="text-sm"
          />
        </div>
      ) : null}

      <div className="ml-7 flex items-center gap-2 text-xs text-muted-foreground">
        <Checkbox
          id={`req-${row.rowId}`}
          checked={row.required}
          onCheckedChange={(v) => onChange({ ...row, required: v === true })}
        />
        <label htmlFor={`req-${row.rowId}`}>Required</label>
      </div>
    </li>
  );
}

function ServiceAssignments({
  serviceIds,
  onChange,
  services,
  loading,
}: {
  serviceIds: number[];
  onChange: (ids: number[]) => void;
  services: { id: number; name: string }[];
  loading: boolean;
}) {
  const toggle = (id: number) => {
    if (serviceIds.includes(id)) {
      onChange(serviceIds.filter((x) => x !== id));
    } else {
      onChange([...serviceIds, id]);
    }
  };

  return (
    <section className="rounded-xl border bg-card p-6">
      <header className="mb-3">
        <h2 className="text-base font-medium tracking-tight">Assigned services</h2>
        <p className="text-xs text-muted-foreground mt-0.5">
          Templates surface in the &ldquo;new record&rdquo; picker for these
          services. A template can be assigned to many services.
        </p>
      </header>
      {loading ? (
        <p className="text-xs text-muted-foreground">Loading services…</p>
      ) : services.length === 0 ? (
        <p className="text-xs text-muted-foreground">No services available.</p>
      ) : (
        <ul className="grid grid-cols-1 sm:grid-cols-2 gap-1.5 max-h-60 overflow-y-auto">
          {services.map((s) => {
            const checked = serviceIds.includes(s.id);
            return (
              <li key={s.id}>
                <label
                  className={cn(
                    'flex items-center gap-2 px-3 py-2 rounded-md text-sm cursor-pointer border',
                    checked
                      ? 'bg-accent/10 border-accent/50'
                      : 'border-transparent hover:bg-muted',
                  )}
                >
                  <Checkbox
                    checked={checked}
                    onCheckedChange={() => toggle(s.id)}
                  />
                  <span className="truncate">{s.name}</span>
                </label>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
