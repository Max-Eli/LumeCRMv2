/**
 * `/marketing/audiences/[id]` — audience detail view.
 *
 * v1: read-only summary (filters + last count) plus a "Refresh
 * count" action that hits the preview endpoint and updates the
 * cached numbers. Edit + delete UIs land in session 2 alongside
 * the campaign-create flow.
 */

'use client';

import { ChevronLeft, Lock, Mail, MessageSquare, RefreshCw, Users } from 'lucide-react';
import Link from 'next/link';
import { use } from 'react';
import { toast } from 'sonner';

import { PageHeader } from '@/components/page-header';
import { Button } from '@/components/ui/button';
import {
  type AudienceFilterSpec,
  useAudience,
  usePreviewAudience,
} from '@/lib/marketing';
import { cn } from '@/lib/utils';

export default function AudienceDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const audienceId = Number(id);
  const { data: audience, isLoading, error } = useAudience(audienceId);
  const preview = usePreviewAudience(audienceId);

  if (isLoading) {
    return (
      <div className="px-10 py-10 max-w-3xl">
        <p className="text-sm text-muted-foreground">Loading…</p>
      </div>
    );
  }
  if (error || !audience) {
    return (
      <div className="px-10 py-10 max-w-3xl">
        <p className="text-sm text-destructive">Could not load audience.</p>
        <Link
          href="/marketing/audiences"
          className="mt-3 inline-block text-sm font-medium text-foreground underline"
        >
          Back to audiences
        </Link>
      </div>
    );
  }

  const handleRefresh = () => {
    preview.mutate(undefined, {
      onSuccess: () => toast.success('Count refreshed'),
      onError: () => toast.error('Could not refresh.'),
    });
  };

  const lastCounted = audience.last_counted_at
    ? new Date(audience.last_counted_at).toLocaleString()
    : 'never';

  return (
    <div className="px-10 py-10 max-w-3xl space-y-6">
      <Link
        href="/marketing/audiences"
        className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ChevronLeft className="size-3.5" />
        Back to audiences
      </Link>

      <PageHeader
        title={audience.name}
        description={audience.description || 'No description'}
        actions={
          audience.is_used_in_campaign ? (
            <span
              className="inline-flex items-center gap-1 rounded-full bg-stone-100 text-stone-700 px-2 py-1 text-[11px] font-medium uppercase tracking-wider"
              title="Referenced by an active campaign — definition is locked"
            >
              <Lock className="size-3" />
              Used in campaign
            </span>
          ) : null
        }
      />

      <section className="rounded-lg border bg-card p-5">
        <div className="flex items-baseline justify-between gap-2 mb-3">
          <h2 className="font-serif text-base font-semibold tracking-tight">
            Counts
          </h2>
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={handleRefresh}
            disabled={preview.isPending}
          >
            <RefreshCw className={cn('size-3.5', preview.isPending && 'animate-spin')} />
            Refresh
          </Button>
        </div>

        {preview.data ? (
          <>
            <div className="grid grid-cols-3 gap-3">
              <Stat icon={Users} label="Total" value={preview.data.total_count} />
              <Stat icon={Mail} label="Email-eligible" value={preview.data.email_eligible_count} tone="email" />
              <Stat icon={MessageSquare} label="SMS-eligible" value={preview.data.sms_eligible_count} tone="sms" />
            </div>
            {preview.data.total_count > 0 &&
            preview.data.email_eligible_count === 0 &&
            preview.data.sms_eligible_count === 0 ? (
              <div className="mt-3 rounded-md border border-amber-200 bg-amber-50 px-3 py-2.5 text-xs text-amber-900 leading-relaxed">
                <p className="font-medium">
                  {preview.data.total_count} client{preview.data.total_count === 1 ? '' : 's'} in the audience, but 0 are reachable.
                </p>
                <p className="mt-1 text-amber-800">
                  Promotional channels are opt-in per ADR 0016 — a client has to be marked
                  &ldquo;Include in promotional email/SMS campaigns&rdquo; for them to receive
                  a campaign send. Toggle the opt-in on the client&apos;s <span className="font-medium">Marketing</span> tab,
                  or pre-check the boxes on the New client form when adding people.
                </p>
              </div>
            ) : null}
          </>
        ) : (
          <div className="grid grid-cols-3 gap-3">
            <Stat icon={Users} label="Cached total" value={audience.last_member_count} />
            <Stat
              icon={Mail}
              label="Email-eligible"
              value="—"
              sub="Click Refresh"
              tone="email"
            />
            <Stat
              icon={MessageSquare}
              label="SMS-eligible"
              value="—"
              sub="Click Refresh"
              tone="sms"
            />
          </div>
        )}

        <p className="text-[11px] text-muted-foreground mt-3">
          Last counted: {lastCounted}
        </p>
      </section>

      <section className="rounded-lg border bg-card p-5">
        <h2 className="font-serif text-base font-semibold tracking-tight mb-3">
          Filters
        </h2>
        <FilterSummary spec={audience.filter_spec} />
      </section>
    </div>
  );
}

// ── Sub-components ───────────────────────────────────────────────────

function Stat({
  icon: Icon,
  label,
  value,
  sub,
  tone,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  value: number | string;
  sub?: string;
  tone?: 'email' | 'sms';
}) {
  return (
    <div className="rounded-md border bg-card px-3 py-2.5">
      <div className="flex items-center gap-1.5 mb-1">
        <Icon className="size-3 text-muted-foreground" />
        <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-medium">
          {label}
        </p>
      </div>
      <p
        className={cn(
          'text-xl font-semibold tabular-nums tracking-tight',
          tone === 'email' && 'text-blue-700',
          tone === 'sms' && 'text-emerald-700',
        )}
      >
        {value}
      </p>
      {sub ? <p className="text-[10px] text-muted-foreground mt-0.5">{sub}</p> : null}
    </div>
  );
}

function FilterSummary({ spec }: { spec: AudienceFilterSpec }) {
  const entries: { label: string; value: string }[] = [];
  if (spec.last_visit_within_days !== undefined) {
    entries.push({
      label: 'Visited recently',
      value: `last ${spec.last_visit_within_days} days`,
    });
  }
  if (spec.last_visit_more_than_days !== undefined) {
    entries.push({
      label: 'Win-back',
      value: `no visit in ${spec.last_visit_more_than_days} days`,
    });
  }
  if (spec.created_within_days !== undefined) {
    entries.push({
      label: 'Recently signed up',
      value: `last ${spec.created_within_days} days`,
    });
  }
  if (spec.email_marketing_opt_in !== undefined) {
    entries.push({
      label: 'Email consent',
      value: spec.email_marketing_opt_in ? 'opted in' : 'opted out',
    });
  }
  if (spec.sms_marketing_opt_in !== undefined) {
    entries.push({
      label: 'SMS consent',
      value: spec.sms_marketing_opt_in ? 'opted in' : 'opted out',
    });
  }
  if (spec.tag_ids && spec.tag_ids.length > 0) {
    entries.push({
      label: 'Tags',
      value: `${spec.tag_ids.length} tag${spec.tag_ids.length === 1 ? '' : 's'}`,
    });
  }

  if (entries.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        No filters — this audience matches every active customer.
      </p>
    );
  }

  return (
    <ul className="divide-y">
      {entries.map((e) => (
        <li key={e.label} className="flex items-center justify-between py-2 text-sm">
          <span className="text-muted-foreground">{e.label}</span>
          <span className="font-medium text-foreground">{e.value}</span>
        </li>
      ))}
    </ul>
  );
}
