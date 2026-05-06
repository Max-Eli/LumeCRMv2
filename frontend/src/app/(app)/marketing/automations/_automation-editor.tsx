/**
 * `<AutomationEditor />` — shared form for creating + editing
 * automations. Used by both `/new` and `/[id]`.
 *
 * Trigger config UI varies by trigger_type:
 *   - birthday: no config
 *   - no_visit_days: number-of-days input
 *   - first_visit_anniversary: no config
 *
 * Active/inactive toggle is the most-used control after creation
 * — operator's primary flow is "set up the automation while paused,
 * preview eligibility, flip on when satisfied."
 */

'use client';

import { CheckCircle2, Loader2 } from 'lucide-react';
import { useState } from 'react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Field, FieldLabel } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { ApiError } from '@/lib/api';
import {
  type Automation,
  type AutomationPreview,
  type CreateAutomationInput,
  type TriggerType,
  TRIGGER_LABELS,
  useAudiences,
  useCreateAutomation,
  usePreviewAutomation,
  useTemplates,
  useUpdateAutomation,
} from '@/lib/marketing';

interface Props {
  initial?: Automation;
  onSaved: (automation: Automation) => void;
}

export function AutomationEditor({ initial, onSaved }: Props) {
  const isEdit = !!initial;
  const create = useCreateAutomation();
  const update = useUpdateAutomation(initial?.id ?? 0);
  const preview = usePreviewAutomation(initial?.id ?? 0);

  const { data: templates } = useTemplates({ activeOnly: true });
  const { data: audiences } = useAudiences();

  const [name, setName] = useState(initial?.name ?? '');
  const [description, setDescription] = useState(initial?.description ?? '');
  const [triggerType, setTriggerType] = useState<TriggerType>(initial?.trigger_type ?? 'birthday');
  const [noVisitDays, setNoVisitDays] = useState<number>(
    typeof initial?.trigger_config?.days === 'number' ? (initial.trigger_config.days as number) : 90,
  );
  const [templateId, setTemplateId] = useState<number | ''>(initial?.template ?? '');
  const [audienceId, setAudienceId] = useState<number | ''>(initial?.audience ?? '');
  const [dedupDays, setDedupDays] = useState<number>(initial?.dedup_window_days ?? 365);
  const [isActive, setIsActive] = useState(initial?.is_active ?? false);
  const [error, setError] = useState<string | null>(null);
  const [previewResult, setPreviewResult] = useState<AutomationPreview | null>(null);

  const buildTriggerConfig = (): Record<string, unknown> => {
    if (triggerType === 'no_visit_days') return { days: noVisitDays };
    return {};
  };

  const handleSave = (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!name.trim()) return setError('Name is required.');
    if (!templateId) return setError('Pick a template.');

    const input: CreateAutomationInput = {
      name: name.trim(),
      description: description.trim(),
      trigger_type: triggerType,
      trigger_config: buildTriggerConfig(),
      template: Number(templateId),
      audience: audienceId === '' ? null : Number(audienceId),
      dedup_window_days: dedupDays,
      is_active: isActive,
    };

    const onErr = (err: Error) => {
      if (err instanceof ApiError && err.body && typeof err.body === 'object') {
        const body = err.body as Record<string, unknown>;
        const firstKey = Object.keys(body)[0];
        const firstVal = body[firstKey];
        const msg = Array.isArray(firstVal) ? String(firstVal[0]) : String(firstVal);
        setError(`${firstKey}: ${msg}`);
        return;
      }
      setError("Couldn't save.");
    };

    if (isEdit && initial) {
      update.mutate(input, {
        onSuccess: (a) => {
          toast.success('Automation saved');
          onSaved(a);
        },
        onError: onErr,
      });
    } else {
      create.mutate(input, {
        onSuccess: (a) => {
          toast.success('Automation created');
          onSaved(a);
        },
        onError: onErr,
      });
    }
  };

  const handlePreview = () => {
    if (!isEdit || !initial) return;
    preview.mutate(undefined, {
      onSuccess: (r) => setPreviewResult(r),
      onError: () => toast.error("Couldn't preview."),
    });
  };

  const isPending = create.isPending || update.isPending;

  return (
    <form onSubmit={handleSave} className="grid grid-cols-1 lg:grid-cols-[1fr_320px] gap-6">
      {/* Left — form */}
      <div className="space-y-6">
        <section className="rounded-lg border bg-card p-5 space-y-4">
          <h2 className="font-serif text-base font-semibold tracking-tight">Identity</h2>
          <Field>
            <FieldLabel>Name</FieldLabel>
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Birthday wishes"
              maxLength={100}
            />
          </Field>
          <Field>
            <FieldLabel>Description (optional)</FieldLabel>
            <Input
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Annual birthday-month message with $20 off"
              maxLength={200}
            />
          </Field>
        </section>

        <section className="rounded-lg border bg-card p-5 space-y-4">
          <h2 className="font-serif text-base font-semibold tracking-tight">Trigger</h2>
          <Field>
            <FieldLabel>When to fire</FieldLabel>
            <select
              value={triggerType}
              onChange={(e) => setTriggerType(e.target.value as TriggerType)}
              className="w-full h-9 rounded-md border bg-card px-3 text-sm"
              disabled={isEdit}
            >
              {(Object.entries(TRIGGER_LABELS) as [TriggerType, string][]).map(([k, label]) => (
                <option key={k} value={k}>
                  {label}
                </option>
              ))}
            </select>
            {isEdit ? (
              <p className="text-[11px] text-muted-foreground mt-1">
                Trigger type is locked after create. Make a new automation to switch.
              </p>
            ) : null}
          </Field>

          {triggerType === 'no_visit_days' ? (
            <Field>
              <FieldLabel>Days since last visit</FieldLabel>
              <div className="flex items-center gap-2">
                <Input
                  type="number"
                  min={7}
                  max={3650}
                  value={noVisitDays}
                  onChange={(e) => setNoVisitDays(Number(e.target.value) || 90)}
                  className="w-24"
                />
                <span className="text-sm text-muted-foreground">days</span>
              </div>
              <p className="text-[11px] text-muted-foreground mt-1">
                Customer is eligible when their most recent completed visit
                is more than this many days ago, OR they&rsquo;ve never visited.
              </p>
            </Field>
          ) : null}
        </section>

        <section className="rounded-lg border bg-card p-5 space-y-4">
          <h2 className="font-serif text-base font-semibold tracking-tight">Send</h2>
          <Field>
            <FieldLabel>Template</FieldLabel>
            <select
              value={templateId}
              onChange={(e) => setTemplateId(e.target.value ? Number(e.target.value) : '')}
              className="w-full h-9 rounded-md border bg-card px-3 text-sm"
            >
              <option value="">Pick a template…</option>
              {(templates ?? []).map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name} ({t.channel})
                </option>
              ))}
            </select>
          </Field>
          <Field>
            <FieldLabel>Audience filter (optional)</FieldLabel>
            <select
              value={audienceId}
              onChange={(e) => setAudienceId(e.target.value ? Number(e.target.value) : '')}
              className="w-full h-9 rounded-md border bg-card px-3 text-sm"
            >
              <option value="">Everyone matching the trigger</option>
              {(audiences ?? []).map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </select>
            <p className="text-[11px] text-muted-foreground mt-1">
              Narrow trigger eligibility further. E.g.: &ldquo;win-back, but only
              for VIP-tagged customers.&rdquo;
            </p>
          </Field>
          <Field>
            <FieldLabel>Dedup window</FieldLabel>
            <div className="flex items-center gap-2">
              <Input
                type="number"
                min={1}
                max={3650}
                value={dedupDays}
                onChange={(e) => setDedupDays(Number(e.target.value) || 365)}
                className="w-24"
              />
              <span className="text-sm text-muted-foreground">days</span>
            </div>
            <p className="text-[11px] text-muted-foreground mt-1">
              Don&rsquo;t fire the same automation for the same customer within
              this many days.
            </p>
          </Field>
        </section>

        <section className="rounded-lg border bg-card p-5">
          <Field>
            <FieldLabel className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={isActive}
                onChange={(e) => setIsActive(e.target.checked)}
                className="size-4"
              />
              Active
            </FieldLabel>
            <p className="text-[11px] text-muted-foreground">
              New automations land paused so you can preview eligibility before
              they fire. Flip on once you&rsquo;ve verified the count.
            </p>
          </Field>
        </section>

        {error ? (
          <div className="rounded-md border border-destructive/40 bg-destructive/[0.04] px-3 py-2 text-sm text-destructive">
            {error}
          </div>
        ) : null}

        <div className="flex items-center gap-2">
          <Button type="submit" disabled={isPending}>
            {isPending ? <Loader2 className="size-4 animate-spin" /> : <CheckCircle2 className="size-4" />}
            {isEdit ? 'Save changes' : 'Create automation'}
          </Button>
        </div>
      </div>

      {/* Right — preview */}
      <aside className="lg:sticky lg:top-6 lg:self-start space-y-3">
        <div className="rounded-lg border bg-card p-5">
          <h3 className="font-serif text-sm font-semibold tracking-tight mb-2">
            Eligibility preview
          </h3>
          {isEdit ? (
            <>
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={handlePreview}
                disabled={preview.isPending}
                className="w-full mb-3"
              >
                {preview.isPending ? <Loader2 className="size-3.5 animate-spin" /> : null}
                Refresh
              </Button>
              {previewResult ? (
                <div className="space-y-2 text-xs">
                  <PreviewRow label="Trigger eligible" value={previewResult.total_count} />
                  <PreviewRow label="With consent" value={previewResult.consent_eligible_count} />
                  <PreviewRow label="After dedup (would send now)" value={previewResult.final_count} highlight />
                </div>
              ) : (
                <p className="text-xs text-muted-foreground italic">
                  Click Refresh to see how many customers are eligible right now.
                </p>
              )}
            </>
          ) : (
            <p className="text-xs text-muted-foreground italic">
              Save to enable the eligibility preview.
            </p>
          )}
        </div>
      </aside>
    </form>
  );
}

function PreviewRow({ label, value, highlight }: { label: string; value: number; highlight?: boolean }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-muted-foreground">{label}</span>
      <span
        className={
          highlight
            ? 'font-semibold tabular-nums text-emerald-700'
            : 'tabular-nums text-foreground'
        }
      >
        {value}
      </span>
    </div>
  );
}
