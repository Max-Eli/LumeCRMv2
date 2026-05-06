/**
 * `/marketing/templates` — list email + SMS templates.
 *
 * Stat strip + channel tabs + searchable data table. Rows show
 * the template name, channel, subject (email) / preview (SMS),
 * discovered tokens, active state, and last-updated time. Click
 * → detail page (edit + preview).
 */

'use client';

import {
  FileText,
  Mail,
  MessageSquare,
  Plus,
  Search,
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
  type Channel,
  type MarketingTemplate,
  canSendMarketing,
  useTemplates,
} from '@/lib/marketing';
import { cn } from '@/lib/utils';

export default function TemplatesListPage() {
  const me = useCurrentMembership();
  const canCreate = canSendMarketing(me?.role);
  const [channel, setChannel] = useState<Channel | 'all'>('all');
  const [search, setSearch] = useState('');
  const { data, isLoading, error } = useTemplates(
    channel === 'all' ? {} : { channel },
  );

  const filtered = useMemo(() => {
    const list = data ?? [];
    const q = search.trim().toLowerCase();
    if (!q) return list;
    return list.filter(
      (t) =>
        t.name.toLowerCase().includes(q) ||
        (t.subject ?? '').toLowerCase().includes(q),
    );
  }, [data, search]);
  const templates = data ?? [];

  // Aggregate counts ignore the channel filter so the strip reflects
  // the full library — operators want a complete picture even while
  // filtering.
  const all = useTemplates();
  const allTemplates = all.data ?? [];
  const emailCount = allTemplates.filter((t) => t.channel === 'email').length;
  const smsCount = allTemplates.filter((t) => t.channel === 'sms').length;
  const inactiveCount = allTemplates.filter((t) => !t.is_active).length;

  return (
    <div className="px-8 py-8 space-y-6">
      <PageHeader
        title="Templates"
        description="Reusable email + SMS bodies with personalization tokens. Pair with audiences to ship campaigns."
        actions={
          canCreate ? (
            <Button render={<Link href="/marketing/templates/new" />} nativeButton={false}>
              <Plus className="size-4" />
              New template
            </Button>
          ) : null
        }
      />

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Stat label="Total templates" value={allTemplates.length} />
        <Stat label="Email" value={emailCount} icon={Mail} />
        <Stat label="SMS" value={smsCount} icon={MessageSquare} />
        <Stat label="Inactive" value={inactiveCount} muted />
      </div>

      <div className="flex items-center justify-between gap-4 flex-wrap">
        <ChannelTabs value={channel} onChange={setChannel} />
        <div className="relative max-w-md flex-1 min-w-[240px]">
          <Search className="size-4 absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground pointer-events-none" />
          <Input
            placeholder="Search by name or subject…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-9"
          />
        </div>
      </div>

      {error ? (
        <div className="rounded-lg border border-destructive/40 bg-destructive/5 p-6 text-sm text-destructive">
          Could not load templates.
        </div>
      ) : isLoading ? (
        <div className="rounded-lg border bg-card p-12 text-center text-sm text-muted-foreground">
          Loading templates…
        </div>
      ) : filtered.length === 0 ? (
        templates.length === 0 ? (
          <EmptyState canCreate={canCreate} />
        ) : (
          <div className="rounded-lg border bg-card p-12 text-center">
            <Search className="size-8 mx-auto text-muted-foreground/40 mb-3" />
            <p className="text-sm text-muted-foreground">
              No templates match the current filters.
            </p>
          </div>
        )
      ) : (
        <TemplatesTable rows={filtered} />
      )}
    </div>
  );
}

function TemplatesTable({ rows }: { rows: MarketingTemplate[] }) {
  const router = useRouter();
  return (
    <div className="rounded-lg border bg-card overflow-hidden">
      <Table>
        <TableHeader>
          <TableRow className="bg-muted/30 hover:bg-muted/30">
            <TableHead className="w-[28%]">Name</TableHead>
            <TableHead className="w-[100px]">Channel</TableHead>
            <TableHead>Subject / preview</TableHead>
            <TableHead>Tokens</TableHead>
            <TableHead className="w-[110px]">State</TableHead>
            <TableHead className="w-[120px]">Updated</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((t) => {
            const Icon = t.channel === 'email' ? Mail : MessageSquare;
            const tone =
              t.channel === 'email'
                ? 'bg-violet-50 text-violet-700'
                : 'bg-amber-50 text-amber-700';
            return (
              <TableRow
                key={t.id}
                className="cursor-pointer"
                onClick={() => router.push(`/marketing/templates/${t.id}`)}
              >
                <TableCell className="py-3.5">
                  <div className="flex items-center gap-3">
                    <div
                      className={cn(
                        'inline-flex size-8 items-center justify-center rounded-md shrink-0',
                        tone,
                      )}
                    >
                      <Icon className="size-4" />
                    </div>
                    <span className="font-medium truncate">{t.name}</span>
                  </div>
                </TableCell>
                <TableCell>
                  <span className="inline-flex items-center rounded-md bg-muted px-2 py-0.5 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
                    {t.channel}
                  </span>
                </TableCell>
                <TableCell className="text-muted-foreground max-w-md">
                  {t.channel === 'email' ? (
                    t.subject ? (
                      <span className="block truncate italic">{t.subject}</span>
                    ) : (
                      <span className="text-muted-foreground/60">
                        No subject
                      </span>
                    )
                  ) : (
                    <span className="block truncate">
                      {t.body.slice(0, 80)}
                      {t.body.length > 80 ? '…' : ''}
                    </span>
                  )}
                </TableCell>
                <TableCell>
                  {t.discovered_tokens.length === 0 ? (
                    <span className="text-xs text-muted-foreground/70">—</span>
                  ) : (
                    <div className="flex flex-wrap gap-1">
                      {t.discovered_tokens.slice(0, 3).map((tok) => (
                        <span
                          key={tok}
                          className="inline-flex items-center rounded bg-muted px-1.5 py-0.5 text-[10px] font-mono text-muted-foreground"
                        >
                          {`{{${tok}}}`}
                        </span>
                      ))}
                      {t.discovered_tokens.length > 3 ? (
                        <span className="text-[10px] text-muted-foreground/70 self-center">
                          +{t.discovered_tokens.length - 3}
                        </span>
                      ) : null}
                    </div>
                  )}
                </TableCell>
                <TableCell>
                  {t.is_active ? (
                    <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 text-emerald-700 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider">
                      <span className="size-1.5 rounded-full bg-emerald-500" />
                      Active
                    </span>
                  ) : (
                    <span className="inline-flex items-center rounded-full bg-stone-100 text-stone-600 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider">
                      Inactive
                    </span>
                  )}
                </TableCell>
                <TableCell className="text-muted-foreground text-xs">
                  {new Date(t.updated_at).toLocaleDateString()}
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}

function ChannelTabs({
  value,
  onChange,
}: {
  value: Channel | 'all';
  onChange: (v: Channel | 'all') => void;
}) {
  const tabs: { id: Channel | 'all'; label: string }[] = [
    { id: 'all', label: 'All' },
    { id: 'email', label: 'Email' },
    { id: 'sms', label: 'SMS' },
  ];
  return (
    <div className="inline-flex items-center gap-0.5 rounded-md border bg-muted/40 p-0.5">
      {tabs.map((t) => (
        <button
          key={t.id}
          type="button"
          onClick={() => onChange(t.id)}
          className={cn(
            'px-3 h-8 rounded-md text-sm transition-colors',
            value === t.id
              ? 'bg-card text-foreground shadow-sm font-medium'
              : 'text-muted-foreground hover:text-foreground',
          )}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}

function Stat({
  label,
  value,
  icon: Icon,
  muted,
}: {
  label: string;
  value: number;
  icon?: React.ComponentType<{ className?: string }>;
  muted?: boolean;
}) {
  return (
    <div className="rounded-lg border bg-card px-5 py-4 flex items-center gap-3">
      {Icon ? (
        <div className="inline-flex size-9 items-center justify-center rounded-md bg-muted text-muted-foreground shrink-0">
          <Icon className="size-4" />
        </div>
      ) : null}
      <div className="min-w-0">
        <p className="text-[11px] uppercase tracking-wider text-muted-foreground font-medium">
          {label}
        </p>
        <p
          className={cn(
            'text-2xl font-semibold tabular-nums leading-tight mt-0.5',
            muted && 'text-muted-foreground',
          )}
        >
          {value.toLocaleString()}
        </p>
      </div>
    </div>
  );
}

function EmptyState({ canCreate }: { canCreate: boolean }) {
  return (
    <div className="rounded-lg border bg-card p-12 text-center">
      <div className="inline-flex size-12 items-center justify-center rounded-full bg-violet-50 text-violet-700 mb-4">
        <FileText className="size-6" />
      </div>
      <h3 className="font-serif text-xl font-semibold tracking-tight">
        No templates yet
      </h3>
      <p className="text-sm text-muted-foreground mt-2 max-w-md mx-auto leading-relaxed">
        Templates are reusable email or SMS bodies with personalization
        tokens like <span className="font-mono">{'{{first_name}}'}</span>.
        Build them once, use them across campaigns and automations.
      </p>
      {canCreate ? (
        <Button render={<Link href="/marketing/templates/new" />} nativeButton={false} className="mt-6">
          <Plus className="size-4" />
          Create your first template
        </Button>
      ) : null}
    </div>
  );
}
