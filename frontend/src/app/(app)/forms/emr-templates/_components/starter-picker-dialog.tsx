/**
 * `<StarterPickerDialog>` — browse + clone the pre-built EMR
 * starter library.
 *
 * Two-pane layout: the left rail lists starters grouped by
 * category; the right pane previews the selected starter's full
 * field list. The "Use this template" action POSTs a regular
 * create-template call (the starter is just data — the cloned row
 * is fully editable + independent of the library afterwards).
 *
 * Keep this component focused: no inline editing, no field
 * customization. Operators land in the editor right after import,
 * which is the right place to tweak field labels / add fields /
 * assign to services.
 */

'use client';

import {
  ArrowRight,
  CheckCircle2,
  ClipboardList,
  FileText,
  Hash,
  Loader2,
  PenLine,
  Sparkles,
  Type,
} from 'lucide-react';
import { useRouter } from 'next/navigation';
import { useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';

import { ApiError } from '@/lib/api';
import {
  type StarterTemplateSummary,
  type TemplateField,
  type TemplateFieldType,
  useCloneStarterTemplate,
  useStarterTemplate,
  useStarterTemplates,
} from '@/lib/treatments';
import { cn } from '@/lib/utils';

import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';

export function StarterPickerDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
}) {
  const router = useRouter();
  const { data, isLoading } = useStarterTemplates();
  const [selectedSlug, setSelectedSlug] = useState<string | null>(null);
  const clone = useCloneStarterTemplate();

  // Pre-select the first starter once the catalog loads so the
  // preview pane has something to render on first open.
  useEffect(() => {
    if (!selectedSlug && data?.starters?.length) {
      setSelectedSlug(data.starters[0].slug);
    }
  }, [data, selectedSlug]);

  // Reset the selection when the dialog closes — opening it next
  // time should land back on the first starter, not the previous
  // one (which might no longer be relevant).
  useEffect(() => {
    if (!open) {
      setSelectedSlug(null);
    }
  }, [open]);

  // Group + sort starters by category for the rail.
  const grouped = useMemo(() => {
    if (!data) return [] as Array<{ category: string; items: StarterTemplateSummary[] }>;
    const map = new Map<string, StarterTemplateSummary[]>();
    for (const s of data.starters) {
      if (!map.has(s.category)) map.set(s.category, []);
      map.get(s.category)!.push(s);
    }
    // Order by `data.categories` so the picker reads in the
    // intended order even if the API returns out of order.
    return data.categories
      .map((cat) => ({ category: cat, items: map.get(cat) ?? [] }))
      .filter((g) => g.items.length > 0);
  }, [data]);

  const detail = useStarterTemplate(selectedSlug ?? undefined);

  const onUse = async () => {
    if (!detail.data) return;
    try {
      const created = await clone.mutateAsync(detail.data);
      toast.success(`${created.name} added to your templates`);
      onOpenChange(false);
      router.push(`/forms/emr-templates/${created.id}`);
    } catch (err) {
      const msg =
        err instanceof ApiError && typeof err.body === 'object' && err.body
          ? (err.body as { detail?: string; name?: string[] }).detail ??
            (err.body as { name?: string[] }).name?.[0] ??
            'Could not add the template.'
          : 'Could not add the template.';
      toast.error(msg);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-4xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Sparkles className="size-4 text-accent-foreground" />
            Template library
          </DialogTitle>
        </DialogHeader>

        <DialogBody className="p-0">
          {isLoading ? (
            <div className="flex items-center justify-center h-[28rem] text-muted-foreground">
              <Loader2 className="size-4 animate-spin" />
            </div>
          ) : (data?.starters?.length ?? 0) === 0 ? (
            <p className="px-6 py-12 text-sm text-muted-foreground text-center">
              No starter templates available.
            </p>
          ) : (
            <div className="grid grid-cols-[260px_1fr] h-[32rem]">
              {/* Rail */}
              <nav className="border-r overflow-y-auto p-2 space-y-3">
                {grouped.map((group) => (
                  <section key={group.category}>
                    <p className="text-[10px] uppercase tracking-wide text-muted-foreground font-medium px-2 mb-1">
                      {group.category}
                    </p>
                    <ul className="space-y-px">
                      {group.items.map((s) => {
                        const isActive = s.slug === selectedSlug;
                        return (
                          <li key={s.slug}>
                            <button
                              type="button"
                              onClick={() => setSelectedSlug(s.slug)}
                              className={cn(
                                'w-full text-left px-2.5 py-2 rounded-md text-sm transition-colors',
                                isActive
                                  ? 'bg-accent text-accent-foreground font-medium'
                                  : 'text-foreground/80 hover:bg-muted',
                              )}
                            >
                              <div className="truncate">{s.name}</div>
                              <p
                                className={cn(
                                  'text-[11px] truncate mt-0.5',
                                  isActive
                                    ? 'text-accent-foreground/80'
                                    : 'text-muted-foreground',
                                )}
                              >
                                {s.field_count} field
                                {s.field_count === 1 ? '' : 's'}
                              </p>
                            </button>
                          </li>
                        );
                      })}
                    </ul>
                  </section>
                ))}
              </nav>

              {/* Preview */}
              <PreviewPane
                slug={selectedSlug}
                detailLoading={detail.isLoading}
                detail={detail.data ?? null}
              />
            </div>
          )}
        </DialogBody>

        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={clone.isPending}
          >
            Cancel
          </Button>
          <Button
            type="button"
            onClick={onUse}
            disabled={!detail.data || clone.isPending}
          >
            {clone.isPending ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <CheckCircle2 className="size-4" />
            )}
            Use this template
            <ArrowRight className="size-3.5" />
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ── Preview pane ───────────────────────────────────────────────────


function PreviewPane({
  slug,
  detailLoading,
  detail,
}: {
  slug: string | null;
  detailLoading: boolean;
  detail: { name: string; description: string; fields: TemplateField[] } | null;
}) {
  if (!slug) {
    return (
      <div className="flex items-center justify-center text-muted-foreground text-sm">
        Pick a template on the left to preview.
      </div>
    );
  }
  if (detailLoading || !detail) {
    return (
      <div className="flex items-center justify-center text-muted-foreground">
        <Loader2 className="size-4 animate-spin" />
      </div>
    );
  }

  return (
    <div className="overflow-y-auto px-6 py-5">
      <header className="mb-4">
        <h3 className="text-base font-medium tracking-tight">{detail.name}</h3>
        {detail.description ? (
          <p className="text-xs text-muted-foreground mt-1.5 leading-relaxed">
            {detail.description}
          </p>
        ) : null}
      </header>

      <p className="text-[10px] uppercase tracking-wide text-muted-foreground font-medium mb-2">
        Fields ({detail.fields.length})
      </p>
      <ul className="rounded-lg border bg-background divide-y">
        {detail.fields.map((f) => (
          <li
            key={f.id}
            className="flex items-start gap-2.5 px-3 py-2 text-sm"
          >
            <FieldTypeIcon type={f.type} />
            <div className="min-w-0 flex-1">
              <p className="font-medium truncate">
                {f.label}
                {f.required ? (
                  <span className="ml-1 text-destructive font-normal">*</span>
                ) : null}
              </p>
              <p className="text-[10px] text-muted-foreground">
                {FIELD_TYPE_LABELS[f.type]}
                {f.options?.length
                  ? ` · ${f.options.length} options`
                  : ''}
              </p>
            </div>
          </li>
        ))}
      </ul>
      <p className="mt-4 text-[11px] text-muted-foreground leading-relaxed">
        After import you&apos;ll land in the editor — rename fields, add or
        remove rows, and assign the template to specific services.
      </p>
    </div>
  );
}

const FIELD_TYPE_LABELS: Record<TemplateFieldType, string> = {
  short_text: 'Short text',
  long_text: 'Long text',
  choice_single: 'Single choice',
  choice_multiple: 'Multiple choice',
  number: 'Number',
  date: 'Date',
  signature: 'Signature',
};

function FieldTypeIcon({ type }: { type: TemplateFieldType }) {
  const className = 'size-3.5 text-muted-foreground shrink-0 mt-1';
  switch (type) {
    case 'short_text':
      return <Type className={className} />;
    case 'long_text':
      return <FileText className={className} />;
    case 'choice_single':
    case 'choice_multiple':
      return <ClipboardList className={className} />;
    case 'number':
      return <Hash className={className} />;
    case 'date':
      return <Sparkles className={className} />;
    case 'signature':
      return <PenLine className={className} />;
  }
}
