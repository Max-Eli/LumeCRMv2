/**
 * `/marketing/campaigns` — list one-shot email + SMS campaigns.
 *
 * Stat strip + status filter + searchable data table. Rows show
 * the name, audience → template pairing, channel, status, recipient
 * + sent counts, schedule, and last update. Click → detail/edit.
 */

'use client';

import {
  Mail,
  MessageSquare,
  Plus,
  Search,
  Send,
} from 'lucide-react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useMemo, useState } from 'react';

import { PageHeader } from '@/components/page-header';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { useCurrentMembership } from '@/lib/auth';
import {
  type CampaignListItem,
  type CampaignStatus,
  canSendMarketing,
  useCampaigns,
} from '@/lib/marketing';
import { cn } from '@/lib/utils';

import { CampaignStatusPill } from './_components/campaign-status-pill';

const STATUS_FILTERS: { value: CampaignStatus | 'all'; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: 'draft', label: 'Drafts' },
  { value: 'scheduled', label: 'Scheduled' },
  { value: 'sending', label: 'Sending' },
  { value: 'sent', label: 'Sent' },
  { value: 'cancelled', label: 'Cancelled' },
];

export default function CampaignsListPage() {
  const me = useCurrentMembership();
  const canCreate = canSendMarketing(me?.role);
  const router = useRouter();
  const [statusFilter, setStatusFilter] = useState<CampaignStatus | 'all'>('all');
  const [search, setSearch] = useState('');
  const { data, isLoading, error } = useCampaigns(
    statusFilter === 'all' ? {} : { status: statusFilter },
  );

  const filtered = useMemo(() => {
    const list = data ?? [];
    const q = search.trim().toLowerCase();
    if (!q) return list;
    return list.filter(
      (c) =>
        c.name.toLowerCase().includes(q) ||
        c.audience_name.toLowerCase().includes(q) ||
        c.template_name.toLowerCase().includes(q),
    );
  }, [data, search]);
  const campaigns = data ?? [];

  // Stats from the unfiltered set so the strip stays informative
  // when a status filter is selected.
  const all = useCampaigns();
  const allCampaigns = all.data ?? [];
  const liveCount = allCampaigns.filter(
    (c) => c.status === 'scheduled' || c.status === 'sending',
  ).length;
  const sentCount = allCampaigns.filter((c) => c.status === 'sent').length;
  const totalSent = allCampaigns.reduce((s, c) => s + c.sent_count, 0);

  return (
    <div className="px-8 py-8 space-y-6">
      <PageHeader
        title="Campaigns"
        description="One-shot email + SMS sends. Pick an audience, pick a template, schedule the send."
        actions={
          canCreate ? (
            <Button render={<Link href="/marketing/campaigns/new" />} nativeButton={false}>
              <Plus className="size-4" />
              New campaign
            </Button>
          ) : null
        }
      />

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Stat label="Total" value={allCampaigns.length} />
        <Stat label="Live" value={liveCount} tone="amber" />
        <Stat label="Sent" value={sentCount} tone="emerald" />
        <Stat label="Messages delivered" value={totalSent} tone="blue" />
      </div>

      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div className="flex flex-wrap gap-1">
          {STATUS_FILTERS.map((f) => (
            <button
              key={f.value}
              type="button"
              onClick={() => setStatusFilter(f.value)}
              className={cn(
                'rounded-full px-3 h-8 text-xs font-medium transition-colors',
                statusFilter === f.value
                  ? 'bg-foreground text-background'
                  : 'bg-muted text-foreground/70 hover:bg-muted/80',
              )}
            >
              {f.label}
            </button>
          ))}
        </div>
        <div className="relative max-w-md flex-1 min-w-[240px]">
          <Search className="size-4 absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground pointer-events-none" />
          <Input
            placeholder="Search campaigns…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-9"
          />
        </div>
      </div>

      {error ? (
        <div className="rounded-lg border border-destructive/40 bg-destructive/5 p-6 text-sm text-destructive">
          Could not load campaigns.
        </div>
      ) : isLoading ? (
        <div className="rounded-lg border bg-card p-12 text-center text-sm text-muted-foreground">
          Loading campaigns…
        </div>
      ) : filtered.length === 0 ? (
        campaigns.length === 0 ? (
          <EmptyState canCreate={canCreate} />
        ) : (
          <div className="rounded-lg border bg-card p-12 text-center">
            <Search className="size-8 mx-auto text-muted-foreground/40 mb-3" />
            <p className="text-sm text-muted-foreground">
              No campaigns match the current filters.
            </p>
          </div>
        )
      ) : (
        <CampaignsTable rows={filtered} onClick={(id) => router.push(`/marketing/campaigns/${id}`)} />
      )}
    </div>
  );
}

function CampaignsTable({
  rows,
  onClick,
}: {
  rows: CampaignListItem[];
  onClick: (id: number) => void;
}) {
  return (
    <div className="rounded-lg border bg-card overflow-hidden">
      <Table>
        <TableHeader>
          <TableRow className="bg-muted/30 hover:bg-muted/30">
            <TableHead className="w-[26%]">Name</TableHead>
            <TableHead>Audience &rarr; Template</TableHead>
            <TableHead className="w-[110px]">Status</TableHead>
            <TableHead className="w-[140px] text-right">Recipients</TableHead>
            <TableHead className="w-[140px] text-right">Sent</TableHead>
            <TableHead className="w-[170px]">Scheduled / sent</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((c) => {
            const Icon = c.channel === 'email' ? Mail : MessageSquare;
            const channelTone =
              c.channel === 'email'
                ? 'bg-violet-50 text-violet-700'
                : 'bg-amber-50 text-amber-700';
            const when =
              c.completed_at ?? c.started_at ?? c.scheduled_at;
            return (
              <TableRow
                key={c.id}
                className="cursor-pointer"
                onClick={() => onClick(c.id)}
              >
                <TableCell className="py-3.5">
                  <div className="flex items-center gap-3">
                    <div
                      className={cn(
                        'inline-flex size-8 items-center justify-center rounded-md shrink-0',
                        channelTone,
                      )}
                    >
                      <Icon className="size-4" />
                    </div>
                    <span className="font-medium truncate">{c.name}</span>
                  </div>
                </TableCell>
                <TableCell className="text-muted-foreground max-w-md">
                  <span className="block truncate">
                    <span className="text-foreground">{c.audience_name}</span>
                    <span className="mx-2 text-muted-foreground/60">&rarr;</span>
                    <span>{c.template_name}</span>
                  </span>
                </TableCell>
                <TableCell>
                  <CampaignStatusPill status={c.status} />
                </TableCell>
                <TableCell className="text-right tabular-nums font-medium">
                  {c.recipient_count_snapshot
                    ? c.recipient_count_snapshot.toLocaleString()
                    : '—'}
                </TableCell>
                <TableCell className="text-right tabular-nums text-muted-foreground">
                  {c.status === 'sent' || c.status === 'sending' ? (
                    <span>
                      <span className="text-foreground font-medium">
                        {c.sent_count.toLocaleString()}
                      </span>
                      {c.failed_count > 0 ? (
                        <span className="ml-2 text-red-600">
                          ·{c.failed_count} failed
                        </span>
                      ) : null}
                      {c.suppressed_count > 0 ? (
                        <span className="ml-2 text-amber-700">
                          ·{c.suppressed_count} suppressed
                        </span>
                      ) : null}
                    </span>
                  ) : (
                    '—'
                  )}
                </TableCell>
                <TableCell className="text-xs text-muted-foreground">
                  {when ? new Date(when).toLocaleString() : '—'}
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}

function Stat({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone?: 'amber' | 'emerald' | 'blue';
}) {
  return (
    <div className="rounded-lg border bg-card px-5 py-4">
      <p className="text-[11px] uppercase tracking-wider text-muted-foreground font-medium">
        {label}
      </p>
      <p
        className={cn(
          'text-2xl font-semibold tabular-nums leading-tight mt-1',
          tone === 'amber' && 'text-amber-700',
          tone === 'emerald' && 'text-emerald-700',
          tone === 'blue' && 'text-blue-700',
        )}
      >
        {value.toLocaleString()}
      </p>
    </div>
  );
}

function EmptyState({ canCreate }: { canCreate: boolean }) {
  return (
    <div className="rounded-lg border bg-card p-12 text-center">
      <div className="inline-flex size-12 items-center justify-center rounded-full bg-amber-50 text-amber-700 mb-4">
        <Send className="size-6" />
      </div>
      <h3 className="font-serif text-xl font-semibold tracking-tight">
        No campaigns yet
      </h3>
      <p className="text-sm text-muted-foreground mt-2 max-w-md mx-auto leading-relaxed">
        Pick an audience + template, set a send time, and you&rsquo;re live.
        For recurring messages (birthdays, win-back), use{' '}
        <Link
          href="/marketing/automations"
          className="font-medium text-foreground underline"
        >
          automations
        </Link>{' '}
        instead.
      </p>
      {canCreate ? (
        <Button render={<Link href="/marketing/campaigns/new" />} nativeButton={false} className="mt-6">
          <Plus className="size-4" />
          Create your first campaign
        </Button>
      ) : null}
    </div>
  );
}
