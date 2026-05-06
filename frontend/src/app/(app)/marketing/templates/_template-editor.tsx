/**
 * `<TemplateEditor />` — shared form for creating + editing
 * marketing templates. Used by both `/new` and `/[id]` so the
 * editor + preview behavior is identical across modes.
 *
 * Two-pane layout: editor on the left, live preview on the right.
 * Preview hits the backend on save (since rendering depends on
 * server-side token resolution); the right pane shows raw token
 * chips while editing, then expands them on Save → Preview.
 */

'use client';

import {
  AlertCircle,
  CheckCircle2,
  Eye,
  Loader2,
  Mail,
  MessageSquare,
  X,
} from 'lucide-react';
import { useEffect, useState } from 'react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Field, FieldError, FieldLabel } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { ApiError } from '@/lib/api';
import {
  ALLOWED_TOKENS,
  type Channel,
  type CreateTemplateInput,
  type MarketingTemplate,
  type TemplatePreviewResult,
  useCreateTemplate,
  usePreviewTemplate,
  useUpdateTemplate,
} from '@/lib/marketing';
import { cn } from '@/lib/utils';

interface TemplateEditorProps {
  initial?: MarketingTemplate;
  onSaved: (template: MarketingTemplate) => void;
}

export function TemplateEditor({ initial, onSaved }: TemplateEditorProps) {
  const isEdit = !!initial;
  const create = useCreateTemplate();
  const update = useUpdateTemplate(initial?.id ?? 0);
  const preview = usePreviewTemplate(initial?.id ?? 0);

  const [channel, setChannel] = useState<Channel>(initial?.channel ?? 'email');
  const [name, setName] = useState(initial?.name ?? '');
  const [subject, setSubject] = useState(initial?.subject ?? '');
  const [body, setBody] = useState(initial?.body ?? '');
  const [isActive, setIsActive] = useState(initial?.is_active ?? true);
  const [error, setError] = useState<string | null>(null);
  const [previewResult, setPreviewResult] = useState<TemplatePreviewResult | null>(null);

  // Reset preview state when the body changes — what's previewed
  // shouldn't drift from what's currently in the editor.
  useEffect(() => {
    setPreviewResult(null);
  }, [body, subject, channel]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!name.trim()) return setError('Name is required.');
    if (!body.trim()) return setError('Body is required.');

    const input: CreateTemplateInput = {
      name: name.trim(),
      channel,
      subject: subject.trim(),
      body,
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
      setError("Couldn't save template.");
    };

    if (isEdit && initial) {
      update.mutate(input, {
        onSuccess: (t) => {
          toast.success('Template saved');
          onSaved(t);
        },
        onError: onErr,
      });
    } else {
      create.mutate(input, {
        onSuccess: (t) => {
          toast.success('Template created');
          onSaved(t);
        },
        onError: onErr,
      });
    }
  };

  const isPending = create.isPending || update.isPending;
  const canPreview = isEdit && !!initial?.id;

  const handlePreview = () => {
    if (!canPreview || !initial) return;
    preview.mutate(
      {},
      {
        onSuccess: (r) => setPreviewResult(r),
        onError: () => toast.error("Couldn't render preview."),
      },
    );
  };

  return (
    <form onSubmit={handleSubmit} className="grid grid-cols-1 lg:grid-cols-2 gap-6">
      {/* Left — editor */}
      <div className="space-y-6">
        <section className="rounded-lg border bg-card p-5 space-y-4">
          <h2 className="font-serif text-base font-semibold tracking-tight">Setup</h2>

          <Field>
            <FieldLabel>Channel</FieldLabel>
            <ChannelToggle value={channel} onChange={setChannel} disabled={isEdit} />
            {isEdit ? (
              <p className="text-[11px] text-muted-foreground mt-1">
                Channel can&rsquo;t change after create. Make a new template if
                you need to switch.
              </p>
            ) : null}
          </Field>

          <Field>
            <FieldLabel>Name</FieldLabel>
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="May promo"
              maxLength={100}
            />
          </Field>

          {channel === 'email' ? (
            <Field>
              <FieldLabel>Subject</FieldLabel>
              <Input
                value={subject}
                onChange={(e) => setSubject(e.target.value)}
                placeholder="Welcome to {{tenant_name}}, {{first_name}}!"
                maxLength={200}
              />
              <p className="text-[11px] text-muted-foreground mt-1">
                Tokens like <span className="font-mono">{'{{first_name}}'}</span> work in the subject too.
              </p>
            </Field>
          ) : null}

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
              Inactive templates are hidden from the campaign + automation pickers
              but stay in the list for archival reference.
            </p>
          </Field>
        </section>

        <section className="rounded-lg border bg-card p-5 space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="font-serif text-base font-semibold tracking-tight">Body</h2>
            <CharCounter channel={channel} body={body} />
          </div>
          <textarea
            value={body}
            onChange={(e) => setBody(e.target.value)}
            rows={channel === 'sms' ? 6 : 12}
            placeholder={
              channel === 'email'
                ? "Hi {{first_name}},\n\nWe miss you at {{tenant_name}}…\n\nUnsubscribe: {{unsubscribe_url}}"
                : "Hi {{first_name}}! {{tenant_name}}: limited-time offer. Reply STOP to opt out."
            }
            className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm font-mono leading-relaxed focus:outline-hidden focus:ring-2 focus:ring-ring/40"
            maxLength={channel === 'sms' ? 1600 : 50000}
          />
          <TokenLegend channel={channel} />
          {channel === 'email' ? (
            <UnsubscribeRequirementHint hasUnsubToken={body.includes('{{unsubscribe_url}}')} />
          ) : null}
        </section>

        {error ? (
          <div className="rounded-md border border-destructive/40 bg-destructive/[0.04] px-3 py-2 text-sm text-destructive">
            {error}
          </div>
        ) : null}

        <div className="flex items-center gap-2">
          <Button type="submit" disabled={isPending}>
            {isPending ? <Loader2 className="size-4 animate-spin" /> : <CheckCircle2 className="size-4" />}
            {isEdit ? 'Save changes' : 'Create template'}
          </Button>
        </div>
      </div>

      {/* Right — preview */}
      <aside className="lg:sticky lg:top-6 lg:self-start space-y-4">
        <div className="rounded-lg border bg-card overflow-hidden">
          <div className="px-5 py-3 border-b flex items-center justify-between gap-2">
            <h3 className="font-serif text-sm font-semibold tracking-tight inline-flex items-center gap-1.5">
              <Eye className="size-4" />
              Preview
            </h3>
            {canPreview ? (
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={handlePreview}
                disabled={preview.isPending}
              >
                {preview.isPending ? (
                  <Loader2 className="size-3.5 animate-spin" />
                ) : (
                  <Eye className="size-3.5" />
                )}
                Render against sample
              </Button>
            ) : null}
          </div>
          <div className="px-5 py-4">
            {previewResult ? (
              <div className="space-y-3">
                {channel === 'email' && previewResult.subject ? (
                  <div className="border-b pb-2">
                    <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-medium">
                      Subject
                    </p>
                    <p className="text-sm font-medium text-foreground">
                      {previewResult.subject}
                    </p>
                  </div>
                ) : null}
                <div className="text-sm whitespace-pre-wrap font-mono leading-relaxed text-foreground">
                  {previewResult.body}
                </div>
              </div>
            ) : isEdit ? (
              <p className="text-xs text-muted-foreground italic">
                Click &ldquo;Render against sample&rdquo; to expand tokens against
                a synthetic customer.
              </p>
            ) : (
              <p className="text-xs text-muted-foreground italic">
                Save the template to enable the live preview.
              </p>
            )}
          </div>
        </div>
      </aside>
    </form>
  );
}

// ── Sub-components ───────────────────────────────────────────────────

function ChannelToggle({
  value,
  onChange,
  disabled,
}: {
  value: Channel;
  onChange: (v: Channel) => void;
  disabled?: boolean;
}) {
  const tabs: { id: Channel; label: string; icon: React.ComponentType<{ className?: string }> }[] = [
    { id: 'email', label: 'Email', icon: Mail },
    { id: 'sms', label: 'SMS', icon: MessageSquare },
  ];
  return (
    <div className="flex rounded-md border border-input overflow-hidden">
      {tabs.map((t) => {
        const Icon = t.icon;
        const active = value === t.id;
        return (
          <button
            key={t.id}
            type="button"
            disabled={disabled}
            onClick={() => onChange(t.id)}
            className={cn(
              'flex-1 px-3 py-2 text-sm font-medium transition-colors inline-flex items-center justify-center gap-1.5 disabled:opacity-50',
              active
                ? 'bg-foreground text-background'
                : 'bg-card text-muted-foreground hover:bg-muted/60',
            )}
          >
            <Icon className="size-4" />
            {t.label}
          </button>
        );
      })}
    </div>
  );
}

function CharCounter({ channel, body }: { channel: Channel; body: string }) {
  if (channel === 'email') {
    return <span className="text-[11px] text-muted-foreground">{body.length} chars</span>;
  }
  // SMS: 160 = 1 segment; 153/segment after the first. Approximate.
  const len = body.length;
  const segments = len === 0 ? 0 : len <= 160 ? 1 : Math.ceil(len / 153);
  const tone = segments <= 1 ? 'muted' : segments <= 3 ? 'attention' : 'destructive';
  return (
    <span
      className={cn(
        'text-[11px]',
        tone === 'muted' && 'text-muted-foreground',
        tone === 'attention' && 'text-amber-700',
        tone === 'destructive' && 'text-red-700',
      )}
    >
      {len} chars · {segments} {segments === 1 ? 'segment' : 'segments'}
    </span>
  );
}

function TokenLegend({ channel }: { channel: Channel }) {
  return (
    <div className="rounded-md border bg-muted/20 px-3 py-2.5">
      <p className="text-[11px] uppercase tracking-wider text-muted-foreground font-medium mb-1.5">
        Allowed tokens
      </p>
      <div className="flex flex-wrap gap-1">
        {ALLOWED_TOKENS.map((token) => (
          <span
            key={token}
            className="inline-flex items-center rounded-full bg-card border px-1.5 py-0.5 text-[10px] font-mono text-foreground"
          >
            {`{{${token}}}`}
          </span>
        ))}
      </div>
      {channel === 'email' ? null : (
        <p className="text-[11px] text-muted-foreground mt-2 italic">
          SMS doesn&rsquo;t need <span className="font-mono">{'{{unsubscribe_url}}'}</span> —
          customers reply STOP to opt out.
        </p>
      )}
    </div>
  );
}

function UnsubscribeRequirementHint({ hasUnsubToken }: { hasUnsubToken: boolean }) {
  if (hasUnsubToken) {
    return (
      <div className="rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs flex items-start gap-2">
        <CheckCircle2 className="size-3.5 text-emerald-600 shrink-0 mt-0.5" />
        <p className="text-emerald-800">
          Unsubscribe link present — CAN-SPAM compliant.
        </p>
      </div>
    );
  }
  return (
    <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs flex items-start gap-2">
      <AlertCircle className="size-3.5 text-amber-600 shrink-0 mt-0.5" />
      <p className="text-amber-800">
        Required: include <span className="font-mono">{'{{unsubscribe_url}}'}</span> somewhere in
        the body. Saving without it will be rejected (CAN-SPAM).
      </p>
    </div>
  );
}
