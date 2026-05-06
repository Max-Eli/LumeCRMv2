/**
 * `/marketing/campaigns/new` — compose a new one-shot campaign.
 *
 * Three-step form on one page:
 *   1. Pick audience
 *   2. Pick template (filters automatically by channel — campaign
 *      channel = template channel)
 *   3. Schedule (now or later)
 *
 * On save, the campaign lands in DRAFT. The operator hits Schedule
 * from the detail page to commit the recipient list snapshot and
 * queue for send.
 */

'use client';

import {
  ChevronLeft,
  Loader2,
} from 'lucide-react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { toast } from 'sonner';

import { PageHeader } from '@/components/page-header';
import { Button } from '@/components/ui/button';
import { Field, FieldLabel } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { ApiError } from '@/lib/api';
import {
  useAudiences,
  useCreateCampaign,
  useTemplates,
} from '@/lib/marketing';

export default function NewCampaignPage() {
  const router = useRouter();
  const create = useCreateCampaign();
  const { data: audiences } = useAudiences();
  const { data: templates } = useTemplates({ activeOnly: true });

  const [name, setName] = useState('');
  const [audienceId, setAudienceId] = useState<number | ''>('');
  const [templateId, setTemplateId] = useState<number | ''>('');
  const [scheduledAt, setScheduledAt] = useState<string>('');
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!name.trim()) return setError('Name is required.');
    if (!audienceId) return setError('Pick an audience.');
    if (!templateId) return setError('Pick a template.');

    create.mutate(
      {
        name: name.trim(),
        audience: Number(audienceId),
        template: Number(templateId),
        scheduled_at: scheduledAt ? new Date(scheduledAt).toISOString() : null,
      },
      {
        onSuccess: (c) => {
          toast.success('Campaign created');
          router.push(`/marketing/campaigns/${c.id}`);
        },
        onError: (err) => {
          if (err instanceof ApiError && err.body && typeof err.body === 'object') {
            const body = err.body as Record<string, unknown>;
            const firstKey = Object.keys(body)[0];
            const firstVal = body[firstKey];
            const msg = Array.isArray(firstVal) ? String(firstVal[0]) : String(firstVal);
            setError(`${firstKey}: ${msg}`);
            return;
          }
          setError("Couldn't create campaign.");
        },
      },
    );
  };

  return (
    <div className="px-10 py-10 max-w-3xl space-y-6">
      <Link
        href="/marketing/campaigns"
        className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ChevronLeft className="size-3.5" />
        Back to campaigns
      </Link>

      <PageHeader
        title="New campaign"
        description="Pick an audience and a template, then schedule the send. The campaign starts as a draft — you'll commit the recipient list snapshot when you hit Schedule on the detail page."
      />

      <form onSubmit={handleSubmit} className="space-y-6">
        <section className="rounded-lg border bg-card p-5 space-y-4">
          <h2 className="font-serif text-base font-semibold tracking-tight">
            Setup
          </h2>

          <Field>
            <FieldLabel>Name</FieldLabel>
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="May 2026 promo"
              maxLength={100}
            />
          </Field>

          <Field>
            <FieldLabel>Audience</FieldLabel>
            <select
              value={audienceId}
              onChange={(e) => setAudienceId(e.target.value ? Number(e.target.value) : '')}
              className="w-full h-9 rounded-md border bg-card px-3 text-sm"
            >
              <option value="">Pick an audience…</option>
              {(audiences ?? []).map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name} ({a.last_member_count} members)
                </option>
              ))}
            </select>
            {(audiences ?? []).length === 0 ? (
              <p className="text-xs text-muted-foreground">
                No audiences yet.{' '}
                <Link href="/marketing/audiences/new" className="underline font-medium text-foreground">
                  Create one
                </Link>
                .
              </p>
            ) : null}
          </Field>

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
            {(templates ?? []).length === 0 ? (
              <p className="text-xs text-muted-foreground">
                No active templates.{' '}
                <Link href="/marketing/templates/new" className="underline font-medium text-foreground">
                  Create one
                </Link>
                .
              </p>
            ) : null}
          </Field>

          <Field>
            <FieldLabel>Schedule (optional)</FieldLabel>
            <Input
              type="datetime-local"
              value={scheduledAt}
              onChange={(e) => setScheduledAt(e.target.value)}
            />
            <p className="text-[11px] text-muted-foreground mt-1">
              Leave blank to send-now after scheduling. SMS sends respect TCPA
              quiet hours regardless (8am–9pm in the recipient&rsquo;s tz).
            </p>
          </Field>
        </section>

        {error ? (
          <div className="rounded-md border border-destructive/40 bg-destructive/[0.04] px-3 py-2 text-sm text-destructive">
            {error}
          </div>
        ) : null}

        <div className="flex items-center gap-2">
          <Button type="submit" disabled={create.isPending}>
            {create.isPending ? <Loader2 className="size-4 animate-spin" /> : null}
            Create draft
          </Button>
          <Link href="/marketing/campaigns" className="text-sm text-muted-foreground hover:text-foreground">
            Cancel
          </Link>
        </div>
      </form>
    </div>
  );
}
