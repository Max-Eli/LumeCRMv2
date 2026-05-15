/**
 * Automated SMS settings dialog.
 *
 * Editable templates + review-request automation in one place. Three
 * tabs ("Confirmation", "Reminder", "Review request"). Each tab is a
 * Mindbody-style template editor with token chips above the textarea
 * so the operator can see what {{first_name}} etc. resolve to.
 *
 * The review-request tab adds the Google Review URL field and the
 * enabled toggle — those gate whether the cron worker fires at all.
 */

'use client';

import { Bell, Check, Loader2, MessageCircle, Star } from 'lucide-react';
import { useEffect, useState } from 'react';

import { ApiError } from '@/lib/api';
import {
  type AutomatedTemplates,
  useAutomatedTemplates,
  useUpdateAutomatedTemplates,
} from '@/lib/messaging';
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
import { Input } from '@/components/ui/input';

type Tab = 'confirmation' | 'reminder' | 'review';

interface TabDef {
  id: Tab;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  description: string;
}

const TABS: readonly TabDef[] = [
  {
    id: 'confirmation',
    label: 'Confirmation',
    icon: MessageCircle,
    description: 'Sent the moment an appointment is booked.',
  },
  {
    id: 'reminder',
    label: 'Reminder',
    icon: Bell,
    description: 'Sent 24 hours before the appointment.',
  },
  {
    id: 'review',
    label: 'Review request',
    icon: Star,
    description: 'Sent after the appointment is marked completed.',
  },
];

const TOKENS_BY_TAB: Record<Tab, { token: string; description: string }[]> = {
  confirmation: [
    { token: '{{first_name}}', description: "Customer's first name" },
    { token: '{{spa_name}}', description: 'Your spa name' },
    { token: '{{appointment_time}}', description: 'Local time of the appointment' },
  ],
  reminder: [
    { token: '{{first_name}}', description: "Customer's first name" },
    { token: '{{spa_name}}', description: 'Your spa name' },
    { token: '{{appointment_time}}', description: 'Local time of the appointment' },
  ],
  review: [
    { token: '{{first_name}}', description: "Customer's first name" },
    { token: '{{spa_name}}', description: 'Your spa name' },
    { token: '{{review_url}}', description: 'Your Google review link (set below)' },
  ],
};

export function AutomatedTemplatesDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
}) {
  const { data, isLoading } = useAutomatedTemplates();

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle>Automated messages</DialogTitle>
        </DialogHeader>
        <DialogBody className="p-0">
          {isLoading || !data ? (
            <div className="flex items-center justify-center py-12 text-muted-foreground">
              <Loader2 className="size-4 animate-spin" />
            </div>
          ) : (
            <Editor data={data} onClose={() => onOpenChange(false)} />
          )}
        </DialogBody>
      </DialogContent>
    </Dialog>
  );
}

function Editor({
  data,
  onClose,
}: {
  data: AutomatedTemplates;
  onClose: () => void;
}) {
  const [tab, setTab] = useState<Tab>('confirmation');

  // Local draft state per field. Initialised from server values; resets
  // whenever the dialog reopens with fresh data.
  const [draft, setDraft] = useState({
    confirmation_sms_template: data.confirmation_sms_template,
    reminder_sms_template: data.reminder_sms_template,
    review_request_sms_template: data.review_request_sms_template,
    review_request_enabled: data.review_request_enabled,
    review_request_hours_after: data.review_request_hours_after,
    google_review_url: data.google_review_url,
  });
  const [error, setError] = useState<string | null>(null);
  const [savedFlash, setSavedFlash] = useState(false);
  const update = useUpdateAutomatedTemplates();

  // Reset draft whenever the underlying server data changes (e.g. an
  // outside save in another tab).
  useEffect(() => {
    setDraft({
      confirmation_sms_template: data.confirmation_sms_template,
      reminder_sms_template: data.reminder_sms_template,
      review_request_sms_template: data.review_request_sms_template,
      review_request_enabled: data.review_request_enabled,
      review_request_hours_after: data.review_request_hours_after,
      google_review_url: data.google_review_url,
    });
  }, [data]);

  const save = async () => {
    setError(null);
    try {
      await update.mutateAsync(draft);
      setSavedFlash(true);
      window.setTimeout(() => setSavedFlash(false), 1500);
    } catch (err) {
      if (err instanceof ApiError && err.body && typeof err.body === 'object') {
        const body = err.body as Record<string, string | string[]>;
        const firstKey = Object.keys(body)[0];
        const v = body[firstKey];
        const msg = Array.isArray(v) ? v[0] : v;
        setError(typeof msg === 'string' ? msg : 'Could not save.');
      } else {
        setError('Could not save.');
      }
    }
  };

  return (
    <>
      <div className="grid grid-cols-[180px_1fr] h-[28rem]">
        {/* Tab rail */}
        <nav className="border-r p-2 space-y-0.5">
          {TABS.map((t) => {
            const Icon = t.icon;
            const isActive = tab === t.id;
            return (
              <button
                key={t.id}
                type="button"
                onClick={() => setTab(t.id)}
                className={cn(
                  'w-full flex items-center gap-2.5 px-2.5 py-2 rounded-md text-sm text-left transition-colors',
                  isActive
                    ? 'bg-accent text-accent-foreground font-medium'
                    : 'text-foreground/80 hover:bg-muted',
                )}
              >
                <Icon className="size-4 shrink-0" />
                <span className="truncate">{t.label}</span>
              </button>
            );
          })}
        </nav>

        {/* Editor pane */}
        <div className="overflow-y-auto px-6 py-5">
          {tab === 'confirmation' ? (
            <TemplateEditor
              tab="confirmation"
              description={TABS[0].description}
              value={draft.confirmation_sms_template}
              defaultBody={data.default_confirmation_body}
              onChange={(v) => setDraft((d) => ({ ...d, confirmation_sms_template: v }))}
            />
          ) : tab === 'reminder' ? (
            <TemplateEditor
              tab="reminder"
              description={TABS[1].description}
              value={draft.reminder_sms_template}
              defaultBody={data.default_reminder_body}
              onChange={(v) => setDraft((d) => ({ ...d, reminder_sms_template: v }))}
            />
          ) : (
            <ReviewTemplateEditor
              draft={draft}
              defaultBody={data.default_review_request_body}
              onChange={(partial) => setDraft((d) => ({ ...d, ...partial }))}
            />
          )}
        </div>
      </div>

      {error ? (
        <div className="px-6 py-2 text-xs text-destructive border-t">{error}</div>
      ) : null}
      <DialogFooter>
        <Button type="button" variant="outline" onClick={onClose} disabled={update.isPending}>
          Close
        </Button>
        <Button type="button" onClick={save} disabled={update.isPending}>
          {update.isPending ? (
            <Loader2 className="size-4 animate-spin" />
          ) : savedFlash ? (
            <Check className="size-4" />
          ) : null}
          {savedFlash ? 'Saved' : 'Save'}
        </Button>
      </DialogFooter>
    </>
  );
}

function TemplateEditor({
  tab,
  description,
  value,
  defaultBody,
  onChange,
}: {
  tab: Tab;
  description: string;
  value: string;
  defaultBody: string;
  onChange: (v: string) => void;
}) {
  const tokens = TOKENS_BY_TAB[tab];
  return (
    <div className="space-y-4">
      <p className="text-xs text-muted-foreground">{description}</p>

      <div>
        <div className="flex items-center justify-between mb-1.5">
          <label htmlFor={`tpl-${tab}`} className="text-xs font-medium">
            Message
          </label>
          {value.trim() ? (
            <button
              type="button"
              onClick={() => onChange('')}
              className="text-[11px] text-muted-foreground hover:text-foreground transition-colors"
            >
              Reset to default
            </button>
          ) : null}
        </div>
        <textarea
          id={`tpl-${tab}`}
          rows={5}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={defaultBody}
          maxLength={1600}
          className="flex w-full rounded-md border bg-transparent px-3 py-2 text-sm shadow-xs outline-none resize-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
        />
        <p className="mt-1 text-[10px] text-muted-foreground">
          {value.length}/1600 · {value.trim() ? 'Custom' : 'Using the default body shown as placeholder'}
        </p>
      </div>

      <div>
        <p className="text-[11px] uppercase tracking-wide text-muted-foreground font-medium mb-1.5">
          Available tokens
        </p>
        <ul className="space-y-1">
          {tokens.map((t) => (
            <li
              key={t.token}
              className="flex items-baseline gap-2 text-xs text-muted-foreground"
            >
              <code className="font-mono text-[11px] px-1.5 py-0.5 rounded bg-muted text-foreground">
                {t.token}
              </code>
              <span>{t.description}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

function ReviewTemplateEditor({
  draft,
  defaultBody,
  onChange,
}: {
  draft: {
    review_request_sms_template: string;
    review_request_enabled: boolean;
    review_request_hours_after: number;
    google_review_url: string;
  };
  defaultBody: string;
  onChange: (partial: Partial<{
    review_request_sms_template: string;
    review_request_enabled: boolean;
    review_request_hours_after: number;
    google_review_url: string;
  }>) => void;
}) {
  return (
    <div className="space-y-5">
      <p className="text-xs text-muted-foreground">{TABS[2].description}</p>

      <div className="flex items-start justify-between gap-4 p-3 rounded-lg border bg-muted/30">
        <div>
          <p className="text-sm font-medium">Enable review requests</p>
          <p className="text-xs text-muted-foreground mt-0.5">
            Sends the message below to clients after each completed appointment.
          </p>
        </div>
        <button
          type="button"
          role="switch"
          aria-checked={draft.review_request_enabled}
          onClick={() =>
            onChange({ review_request_enabled: !draft.review_request_enabled })
          }
          className={cn(
            'relative inline-flex h-5 w-9 shrink-0 cursor-pointer items-center rounded-full transition-colors',
            draft.review_request_enabled ? 'bg-accent' : 'bg-muted-foreground/30',
          )}
        >
          <span
            className={cn(
              'inline-block size-3.5 transform rounded-full bg-white shadow transition-transform',
              draft.review_request_enabled ? 'translate-x-5' : 'translate-x-1',
            )}
          />
        </button>
      </div>

      <div>
        <label htmlFor="review-url" className="text-xs font-medium mb-1.5 block">
          Google review URL
        </label>
        <Input
          id="review-url"
          type="url"
          value={draft.google_review_url}
          onChange={(e) => onChange({ google_review_url: e.target.value })}
          placeholder="https://g.page/r/CXXXXX/review"
        />
        <p className="mt-1 text-[10px] text-muted-foreground">
          Find this on your Google Business Profile under “Get more reviews.”
        </p>
      </div>

      <div>
        <label htmlFor="review-hours" className="text-xs font-medium mb-1.5 block">
          Send how many hours after completion?
        </label>
        <Input
          id="review-hours"
          type="number"
          min={1}
          max={168}
          value={draft.review_request_hours_after}
          onChange={(e) =>
            onChange({
              review_request_hours_after: Math.max(1, Math.min(168, Number(e.target.value) || 24)),
            })
          }
          className="w-32"
        />
        <p className="mt-1 text-[10px] text-muted-foreground">
          Industry default is 24 hours — fresh enough to remember, late enough to enjoy the result.
        </p>
      </div>

      <div>
        <div className="flex items-center justify-between mb-1.5">
          <label htmlFor="tpl-review" className="text-xs font-medium">
            Message
          </label>
          {draft.review_request_sms_template.trim() ? (
            <button
              type="button"
              onClick={() => onChange({ review_request_sms_template: '' })}
              className="text-[11px] text-muted-foreground hover:text-foreground transition-colors"
            >
              Reset to default
            </button>
          ) : null}
        </div>
        <textarea
          id="tpl-review"
          rows={5}
          value={draft.review_request_sms_template}
          onChange={(e) => onChange({ review_request_sms_template: e.target.value })}
          placeholder={defaultBody}
          maxLength={1600}
          className="flex w-full rounded-md border bg-transparent px-3 py-2 text-sm shadow-xs outline-none resize-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
        />
        <p className="mt-1 text-[10px] text-muted-foreground">
          {draft.review_request_sms_template.length}/1600 ·{' '}
          {draft.review_request_sms_template.trim() ? 'Custom' : 'Using the default body shown as placeholder'}
        </p>
      </div>

      <div>
        <p className="text-[11px] uppercase tracking-wide text-muted-foreground font-medium mb-1.5">
          Available tokens
        </p>
        <ul className="space-y-1">
          {TOKENS_BY_TAB.review.map((t) => (
            <li
              key={t.token}
              className="flex items-baseline gap-2 text-xs text-muted-foreground"
            >
              <code className="font-mono text-[11px] px-1.5 py-0.5 rounded bg-muted text-foreground">
                {t.token}
              </code>
              <span>{t.description}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
