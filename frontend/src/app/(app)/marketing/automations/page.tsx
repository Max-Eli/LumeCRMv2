/**
 * `/marketing/automations` — list always-on triggered campaigns.
 *
 * Stat strip + active toggle + searchable data table. Rows show
 * the name, trigger type, channel, template, last-fired summary,
 * dedup window, and active/paused state. Click → detail/edit.
 */

'use client';

import {
  Cake,
  Clock,
  Heart,
  Mail,
  MessageSquare,
  Plus,
  Search,
  Zap,
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
  type Automation,
  type TriggerType,
  TRIGGER_LABELS,
  canSendMarketing,
  useAutomations,
} from '@/lib/marketing';
import { cn } from '@/lib/utils';

const TRIGGER_ICONS: Record<TriggerType, React.ComponentType<{ className?: string }>> = {
  birthday: Cake,
  no_visit_days: Clock,
  first_visit_anniversary: Heart,
};

export default function AutomationsListPage() {
  const me = useCurrentMembership();
  const canCreate = canSendMarketing(me?.role);
  const router = useRouter();
  const [filter, setFilter] = useState<'all' | 'active' | 'paused'>('all');
  const [search, setSearch] = useState('');
  const { data, isLoading, error } = useAutomations();

  const filtered = useMemo(() => {
    let rows = data ?? [];
    if (filter === 'active') rows = rows.filter((a) => a.is_active);
    else if (filter === 'paused') rows = rows.filter((a) => !a.is_active);
    const q = search.trim().toLowerCase();
    if (q) {
      rows = rows.filter(
        (a) =>
          a.name.toLowerCase().includes(q) ||
          a.template_name.toLowerCase().includes(q),
      );
    }
    return rows;
  }, [data, filter, search]);
  const automations = data ?? [];

  const activeCount = automations.filter((a) => a.is_active).length;
  const pausedCount = automations.length - activeCount;
  const lastFired = automations
    .map((a) => a.last_run_at)
    .filter((d): d is string => !!d)
    .sort()
    .at(-1);
  const totalLastRunSent = automations.reduce(
    (s, a) => s + a.last_run_sent_count,
    0,
  );

  return (
    <div className="px-8 py-8 space-y-6">
      <PageHeader
        title="Automations"
        description="Always-on triggered campaigns. Set them up once, they fire automatically when customers become eligible."
        actions={
          canCreate ? (
            <Button render={<Link href="/marketing/automations/new" />} nativeButton={false}>
              <Plus className="size-4" />
              New automation
            </Button>
          ) : null
        }
      />

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Stat label="Total" value={automations.length} />
        <Stat label="Active" value={activeCount} tone="emerald" />
        <Stat label="Paused" value={pausedCount} muted />
        <Stat
          label="Sent in last run"
          value={totalLastRunSent}
          sublabel={
            lastFired
              ? `Last fire ${new Date(lastFired).toLocaleDateString()}`
              : 'Not fired yet'
          }
        />
      </div>

      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div className="inline-flex items-center gap-0.5 rounded-md border bg-muted/40 p-0.5">
          {(['all', 'active', 'paused'] as const).map((f) => (
            <button
              key={f}
              type="button"
              onClick={() => setFilter(f)}
              className={cn(
                'px-3 h-8 rounded-md text-sm capitalize transition-colors',
                filter === f
                  ? 'bg-card text-foreground shadow-sm font-medium'
                  : 'text-muted-foreground hover:text-foreground',
              )}
            >
              {f}
            </button>
          ))}
        </div>
        <div className="relative max-w-md flex-1 min-w-[240px]">
          <Search className="size-4 absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground pointer-events-none" />
          <Input
            placeholder="Search automations…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-9"
          />
        </div>
      </div>

      {error ? (
        <div className="rounded-lg border border-destructive/40 bg-destructive/5 p-6 text-sm text-destructive">
          Could not load automations.
        </div>
      ) : isLoading ? (
        <div className="rounded-lg border bg-card p-12 text-center text-sm text-muted-foreground">
          Loading automations…
        </div>
      ) : filtered.length === 0 ? (
        automations.length === 0 ? (
          <EmptyState canCreate={canCreate} />
        ) : (
          <div className="rounded-lg border bg-card p-12 text-center">
            <Search className="size-8 mx-auto text-muted-foreground/40 mb-3" />
            <p className="text-sm text-muted-foreground">
              No automations match the current filters.
            </p>
          </div>
        )
      ) : (
        <AutomationsTable
          rows={filtered}
          onClick={(id) => router.push(`/marketing/automations/${id}`)}
        />
      )}
    </div>
  );
}

function AutomationsTable({
  rows,
  onClick,
}: {
  rows: Automation[];
  onClick: (id: number) => void;
}) {
  return (
    <div className="rounded-lg border bg-card overflow-hidden">
      <Table>
        <TableHeader>
          <TableRow className="bg-muted/30 hover:bg-muted/30">
            <TableHead className="w-[26%]">Name</TableHead>
            <TableHead>Trigger</TableHead>
            <TableHead>Channel &middot; Template</TableHead>
            <TableHead className="text-right">Last run</TableHead>
            <TableHead className="w-[110px]">Dedup</TableHead>
            <TableHead className="w-[110px]">State</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((a) => {
            const TriggerIcon = TRIGGER_ICONS[a.trigger_type];
            const ChannelIcon = a.channel === 'email' ? Mail : MessageSquare;
            return (
              <TableRow
                key={a.id}
                className="cursor-pointer"
                onClick={() => onClick(a.id)}
              >
                <TableCell className="py-3.5">
                  <div className="flex items-center gap-3">
                    <div className="inline-flex size-8 items-center justify-center rounded-md bg-emerald-50 text-emerald-700 shrink-0">
                      <TriggerIcon className="size-4" />
                    </div>
                    <div className="min-w-0">
                      <p className="font-medium truncate">{a.name}</p>
                      {a.description ? (
                        <p className="text-xs text-muted-foreground truncate">
                          {a.description}
                        </p>
                      ) : null}
                    </div>
                  </div>
                </TableCell>
                <TableCell className="text-sm">
                  {TRIGGER_LABELS[a.trigger_type]}
                </TableCell>
                <TableCell>
                  <div className="flex items-center gap-2 text-sm text-muted-foreground">
                    <ChannelIcon className="size-3.5" />
                    <span className="truncate">{a.template_name}</span>
                  </div>
                </TableCell>
                <TableCell className="text-right text-xs text-muted-foreground">
                  {a.last_run_at ? (
                    <div className="space-y-0.5">
                      <div className="text-foreground font-medium tabular-nums">
                        {a.last_run_sent_count.toLocaleString()} sent
                      </div>
                      <div>
                        {new Date(a.last_run_at).toLocaleDateString()}
                      </div>
                    </div>
                  ) : (
                    <span className="italic text-muted-foreground/70">
                      Never fired
                    </span>
                  )}
                </TableCell>
                <TableCell className="text-xs text-muted-foreground tabular-nums">
                  {a.dedup_window_days}d
                </TableCell>
                <TableCell>
                  {a.is_active ? (
                    <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 text-emerald-700 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider">
                      <span className="size-1.5 rounded-full bg-emerald-500" />
                      Active
                    </span>
                  ) : (
                    <span className="inline-flex items-center rounded-full bg-stone-100 text-stone-600 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider">
                      Paused
                    </span>
                  )}
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
  sublabel,
  tone,
  muted,
}: {
  label: string;
  value: number;
  sublabel?: string;
  tone?: 'emerald';
  muted?: boolean;
}) {
  return (
    <div className="rounded-lg border bg-card px-5 py-4">
      <p className="text-[11px] uppercase tracking-wider text-muted-foreground font-medium">
        {label}
      </p>
      <p
        className={cn(
          'text-2xl font-semibold tabular-nums leading-tight mt-1',
          tone === 'emerald' && 'text-emerald-700',
          muted && 'text-muted-foreground',
        )}
      >
        {value.toLocaleString()}
      </p>
      {sublabel ? (
        <p className="text-[11px] text-muted-foreground mt-0.5 truncate">
          {sublabel}
        </p>
      ) : null}
    </div>
  );
}

function EmptyState({ canCreate }: { canCreate: boolean }) {
  return (
    <div className="rounded-lg border bg-card p-12 text-center">
      <div className="inline-flex size-12 items-center justify-center rounded-full bg-emerald-50 text-emerald-700 mb-4">
        <Zap className="size-6" />
      </div>
      <h3 className="font-serif text-xl font-semibold tracking-tight">
        No automations yet
      </h3>
      <p className="text-sm text-muted-foreground mt-2 max-w-md mx-auto leading-relaxed">
        Automations fire on a trigger &mdash; birthday month,
        no-visit-in-N-days, first-visit anniversary. Set them up once and
        they keep running. Each customer can only receive a given
        automation once per dedup window.
      </p>
      {canCreate ? (
        <Button render={<Link href="/marketing/automations/new" />} nativeButton={false} className="mt-6">
          <Plus className="size-4" />
          Create your first automation
        </Button>
      ) : null}
    </div>
  );
}
