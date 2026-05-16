/**
 * `<ProtocolTab>` — the provider-facing clinical protocol editor for a
 * service.
 *
 * Distinct from `Service.description` (the customer-facing marketing
 * copy on the booking page). This is the protocol staff follow at
 * the treatment table — pre-treatment checks, the procedure walk-
 * through, post-treatment care, and free-form notes.
 *
 * Mode: in-place editor with debounced "dirty" detection + an
 * explicit Save button. We don't auto-save because (a) the operator
 * may abandon a draft mid-edit and (b) the audit log writes a row
 * per save and we don't want one per keystroke.
 */

'use client';

import { Check, ClipboardCheck, Loader2, Save } from 'lucide-react';
import { useEffect, useState } from 'react';
import { toast } from 'sonner';

import { ApiError } from '@/lib/api';
import {
  type ServiceProtocol,
  useServiceProtocol,
  useUpdateServiceProtocol,
} from '@/lib/services';
import { cn } from '@/lib/utils';

import { Button } from '@/components/ui/button';

interface DraftState {
  pre_treatment: string;
  intra_treatment: string;
  post_treatment: string;
  notes: string;
}

function draftFrom(protocol: ServiceProtocol | undefined): DraftState {
  return {
    pre_treatment: protocol?.pre_treatment ?? '',
    intra_treatment: protocol?.intra_treatment ?? '',
    post_treatment: protocol?.post_treatment ?? '',
    notes: protocol?.notes ?? '',
  };
}

export function ProtocolTab({ serviceId }: { serviceId: number }) {
  const { data: protocol, isLoading } = useServiceProtocol(serviceId);
  const update = useUpdateServiceProtocol(serviceId);
  const [draft, setDraft] = useState<DraftState>(() => draftFrom(undefined));
  const [error, setError] = useState<string | null>(null);

  // Reset the draft whenever the server-side row changes (initial
  // load + after a successful save).
  useEffect(() => {
    if (protocol) setDraft(draftFrom(protocol));
  }, [protocol]);

  const dirty =
    protocol !== undefined &&
    (draft.pre_treatment !== (protocol.pre_treatment ?? '') ||
      draft.intra_treatment !== (protocol.intra_treatment ?? '') ||
      draft.post_treatment !== (protocol.post_treatment ?? '') ||
      draft.notes !== (protocol.notes ?? ''));

  const onSave = async () => {
    setError(null);
    try {
      await update.mutateAsync(draft);
      toast.success('Protocol saved.');
    } catch (err) {
      if (err instanceof ApiError && err.body && typeof err.body === 'object') {
        const body = err.body as Record<string, string | string[]>;
        const firstKey = Object.keys(body)[0];
        const raw = firstKey ? body[firstKey] : undefined;
        const msg = Array.isArray(raw) ? raw[0] : raw;
        setError(typeof msg === 'string' ? msg : 'Could not save.');
      } else {
        setError('Could not save.');
      }
    }
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12 text-muted-foreground">
        <Loader2 className="size-4 animate-spin" />
      </div>
    );
  }

  return (
    <div className="space-y-6 max-w-4xl">
      <header className="flex items-start justify-between gap-4">
        <div className="flex items-start gap-3">
          <div
            className="size-9 inline-flex items-center justify-center rounded-md bg-accent/15 text-accent-foreground shrink-0"
            aria-hidden
          >
            <ClipboardCheck className="size-4" />
          </div>
          <div>
            <h2 className="text-lg font-medium tracking-tight">
              Clinical protocol
            </h2>
            <p className="text-sm text-muted-foreground mt-0.5 max-w-xl">
              How your team performs this service. Visible to providers during
              treatment + during onboarding. Not shown to customers.
            </p>
          </div>
        </div>
        {protocol?.updated_at && !protocol.is_empty ? (
          <p className="text-[11px] text-muted-foreground text-right shrink-0">
            Last edited{' '}
            <span className="font-medium text-foreground">
              {formatDate(protocol.updated_at)}
            </span>
            {protocol.updated_by_email ? (
              <>
                <br />
                by {protocol.updated_by_email}
              </>
            ) : null}
          </p>
        ) : null}
      </header>

      <Section
        id="pre"
        label="Pre-treatment"
        hint="Intake checks, contraindications, consent, photos."
        value={draft.pre_treatment}
        onChange={(v) => setDraft((d) => ({ ...d, pre_treatment: v }))}
      />
      <Section
        id="intra"
        label="During treatment"
        hint="Numbered steps, equipment settings, technique."
        value={draft.intra_treatment}
        onChange={(v) => setDraft((d) => ({ ...d, intra_treatment: v }))}
        rows={8}
      />
      <Section
        id="post"
        label="Post-treatment care"
        hint="Immediate post-care + take-home guidance for the customer."
        value={draft.post_treatment}
        onChange={(v) => setDraft((d) => ({ ...d, post_treatment: v }))}
      />
      <Section
        id="notes"
        label="Internal notes"
        hint="Lot tracking conventions, vendor preferences, exclusions."
        value={draft.notes}
        onChange={(v) => setDraft((d) => ({ ...d, notes: v }))}
      />

      {/* Sticky save bar — appears the moment the operator starts
          editing so they always know how to commit. */}
      <div className="sticky bottom-0 -mx-10 px-10 py-3 bg-background/95 backdrop-blur border-t flex items-center justify-end gap-3">
        {error ? (
          <p className="text-xs text-destructive">{error}</p>
        ) : dirty ? (
          <p className="text-xs text-muted-foreground">Unsaved changes</p>
        ) : null}
        <Button
          type="button"
          onClick={onSave}
          disabled={!dirty || update.isPending}
          size="sm"
        >
          {update.isPending ? (
            <Loader2 className="size-4 animate-spin" />
          ) : (
            <Save className="size-4" />
          )}
          Save protocol
        </Button>
      </div>
    </div>
  );
}

// ── Single section editor ──────────────────────────────────────────


function Section({
  id,
  label,
  hint,
  value,
  onChange,
  rows = 5,
}: {
  id: string;
  label: string;
  hint: string;
  value: string;
  onChange: (v: string) => void;
  rows?: number;
}) {
  const isFilled = value.trim().length > 0;
  return (
    <section className="rounded-xl border bg-card p-5">
      <header className="flex items-baseline justify-between gap-2 mb-2">
        <div>
          <label
            htmlFor={`proto-${id}`}
            className="text-sm font-medium inline-flex items-center gap-1.5"
          >
            {label}
            {isFilled ? (
              <Check className="size-3 text-emerald-600" aria-label="Has content" />
            ) : null}
          </label>
          <p className="text-xs text-muted-foreground mt-0.5">{hint}</p>
        </div>
        <span
          className={cn(
            'text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded shrink-0',
            isFilled
              ? 'bg-emerald-50 text-emerald-700 border border-emerald-200'
              : 'bg-muted text-muted-foreground border',
          )}
        >
          {isFilled ? 'Filled' : 'Empty'}
        </span>
      </header>
      <textarea
        id={`proto-${id}`}
        rows={rows}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="block w-full rounded-md border bg-transparent px-3 py-2 text-sm shadow-xs outline-none resize-y focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
      />
    </section>
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
