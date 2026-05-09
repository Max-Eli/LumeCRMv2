/**
 * `/marketing/campaigns/[id]` — campaign detail.
 *
 * Three sections:
 *   1. Status + actions (Schedule / Cancel / Delete based on state)
 *   2. Recipient + send aggregates
 *   3. Send-log table (per-customer rows; populated by the worker
 *      when the campaign fires — empty in DRAFT/SCHEDULED states)
 */

'use client';

import {
  AlertCircle,
  Ban,
  ChevronLeft,
  Loader2,
  Mail,
  MessageSquare,
  Send,
  Trash2,
} from 'lucide-react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { use, useState } from 'react';
import { toast } from 'sonner';

import { PageHeader } from '@/components/page-header';
import { Button } from '@/components/ui/button';
import { ApiError } from '@/lib/api';
import {
  type SendLogRow,
  useCampaign,
  useCampaignSendLog,
  useCancelCampaign,
  useDeleteCampaign,
  useDispatchCampaign,
  useScheduleCampaign,
} from '@/lib/marketing';
import { cn } from '@/lib/utils';

import { CampaignStatusPill } from '../_components/campaign-status-pill';

export default function CampaignDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const cid = Number(id);
  const router = useRouter();
  const { data: campaign, isLoading, error } = useCampaign(cid);
  const { data: sendLog } = useCampaignSendLog(cid);
  const schedule = useScheduleCampaign(cid);
  const cancel = useCancelCampaign(cid);
  const dispatch = useDispatchCampaign(cid);
  const del = useDeleteCampaign();
  const [confirming, setConfirming] = useState<'schedule' | 'cancel' | 'delete' | null>(null);

  if (isLoading) {
    return <div className="px-10 py-10 max-w-3xl"><p className="text-sm text-muted-foreground">Loading…</p></div>;
  }
  if (error || !campaign) {
    return (
      <div className="px-10 py-10 max-w-3xl">
        <p className="text-sm text-destructive">Could not load campaign.</p>
        <Link href="/marketing/campaigns" className="mt-3 inline-block text-sm font-medium underline">
          Back to campaigns
        </Link>
      </div>
    );
  }

  const handleSchedule = (sendNow: boolean) => {
    schedule.mutate(
      { send_now: sendNow },
      {
        onSuccess: () => {
          toast.success(sendNow ? 'Campaign queued for send' : 'Campaign scheduled');
          setConfirming(null);
        },
        onError: (err) => {
          if (err instanceof ApiError && err.body && typeof err.body === 'object') {
            const detail = (err.body as { detail?: unknown }).detail;
            toast.error(typeof detail === 'string' ? detail : "Couldn't schedule.");
          } else {
            toast.error("Couldn't schedule.");
          }
        },
      },
    );
  };

  const handleCancel = () => {
    cancel.mutate(undefined, {
      onSuccess: () => {
        toast.success('Campaign cancelled');
        setConfirming(null);
      },
      onError: () => toast.error("Couldn't cancel."),
    });
  };

  const handleDelete = () => {
    del.mutate(campaign.id, {
      onSuccess: () => {
        toast.success('Campaign deleted');
        router.push('/marketing/campaigns');
      },
      onError: (err) => {
        if (err instanceof ApiError && err.body && typeof err.body === 'object') {
          const detail = (err.body as { detail?: unknown }).detail;
          toast.error(typeof detail === 'string' ? detail : "Couldn't delete.");
        } else {
          toast.error("Couldn't delete.");
        }
      },
    });
  };

  const Icon = campaign.channel === 'email' ? Mail : MessageSquare;
  const isDraft = campaign.status === 'draft';
  const isScheduled = campaign.status === 'scheduled';
  const isTerminal = campaign.status === 'sent' || campaign.status === 'cancelled';

  return (
    <div className="px-10 py-10 max-w-4xl space-y-6">
      <Link
        href="/marketing/campaigns"
        className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ChevronLeft className="size-3.5" />
        Back to campaigns
      </Link>

      <PageHeader
        title={campaign.name}
        description={`${campaign.channel === 'email' ? 'Email' : 'SMS'} campaign · ${campaign.audience_detail.name} → ${campaign.template_detail.name}`}
        actions={<CampaignStatusPill status={campaign.status} />}
      />

      <SendNotReadyBanner />

      {/* Action row */}
      <section className="rounded-lg border bg-card p-5 space-y-3">
        <h2 className="font-serif text-base font-semibold tracking-tight">Actions</h2>
        <div className="flex flex-wrap gap-2">
          {isDraft ? (
            <>
              <Button onClick={() => handleSchedule(false)} disabled={schedule.isPending || !campaign.scheduled_at}>
                {schedule.isPending ? <Loader2 className="size-4 animate-spin" /> : <Send className="size-4" />}
                Schedule
              </Button>
              <Button variant="outline" onClick={() => handleSchedule(true)} disabled={schedule.isPending}>
                Send now
              </Button>
              <Button variant="outline" onClick={() => setConfirming('cancel')} disabled={cancel.isPending}>
                Cancel draft
              </Button>
              <Button variant="outline" onClick={() => setConfirming('delete')} disabled={del.isPending}>
                <Trash2 className="size-4" />
                Delete
              </Button>
            </>
          ) : isScheduled ? (
            <>
              <Button
                onClick={() => {
                  dispatch.mutate(undefined, {
                    onSuccess: () => toast.success('Campaign dispatched'),
                    onError: (err) => {
                      const detail =
                        err instanceof ApiError &&
                        err.body &&
                        typeof err.body === 'object'
                          ? (err.body as { detail?: unknown }).detail
                          : null;
                      toast.error(typeof detail === 'string' ? detail : "Couldn't dispatch.");
                    },
                  });
                }}
                disabled={dispatch.isPending}
              >
                {dispatch.isPending ? <Loader2 className="size-4 animate-spin" /> : <Send className="size-4" />}
                {dispatch.isPending ? 'Dispatching…' : 'Dispatch now'}
              </Button>
              <Button variant="outline" onClick={() => setConfirming('cancel')} disabled={cancel.isPending}>
                <Ban className="size-4" />
                Cancel before send
              </Button>
            </>
          ) : isTerminal && campaign.status === 'cancelled' ? (
            <Button variant="outline" onClick={() => setConfirming('delete')} disabled={del.isPending}>
              <Trash2 className="size-4" />
              Delete
            </Button>
          ) : (
            <p className="text-sm text-muted-foreground">No actions available in this state.</p>
          )}
        </div>

        {confirming === 'cancel' ? (
          <ConfirmRow
            tone="warn"
            label="Cancel this campaign?"
            confirmLabel="Yes, cancel"
            onConfirm={handleCancel}
            onDismiss={() => setConfirming(null)}
            pending={cancel.isPending}
          />
        ) : null}
        {confirming === 'delete' ? (
          <ConfirmRow
            tone="destructive"
            label="Delete this campaign?"
            confirmLabel="Yes, delete"
            onConfirm={handleDelete}
            onDismiss={() => setConfirming(null)}
            pending={del.isPending}
          />
        ) : null}
      </section>

      {/* Send aggregates */}
      <section className="rounded-lg border bg-card p-5 space-y-3">
        <h2 className="font-serif text-base font-semibold tracking-tight">Recipients</h2>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <Stat label="Snapshot" value={campaign.recipient_count_snapshot} />
          <Stat label="Sent" value={campaign.sent_count} tone="success" />
          <Stat label="Failed" value={campaign.failed_count} tone="destructive" />
          <Stat label="Suppressed" value={campaign.suppressed_count} tone="muted" />
        </div>
        {campaign.scheduled_at ? (
          <p className="text-xs text-muted-foreground tabular-nums">
            Scheduled: {new Date(campaign.scheduled_at).toLocaleString()}
          </p>
        ) : null}
      </section>

      {/* Send log */}
      <section className="rounded-lg border bg-card p-5">
        <div className="flex items-baseline justify-between mb-3">
          <h2 className="font-serif text-base font-semibold tracking-tight">Send log</h2>
          <span className="text-xs text-muted-foreground tabular-nums">
            {(sendLog ?? []).length} {(sendLog ?? []).length === 1 ? 'row' : 'rows'}
          </span>
        </div>
        {(sendLog ?? []).length === 0 ? (
          <p className="text-xs text-muted-foreground italic">
            No sends yet. The worker writes per-customer rows here when the
            campaign fires.
          </p>
        ) : (
          <ul className="divide-y">
            {(sendLog ?? []).map((r) => (
              <SendLogRowView key={r.id} row={r} channel={campaign.channel} />
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

// ── Sub-components ───────────────────────────────────────────────────

function SendNotReadyBanner() {
  return (
    <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2.5 flex items-start gap-2 text-xs">
      <AlertCircle className="size-4 shrink-0 text-amber-600 mt-0.5" />
      <div>
        <p className="font-medium text-amber-900">
          Send infrastructure not yet connected.
        </p>
        <p className="text-amber-800 mt-0.5">
          Campaigns flow through the data model end-to-end, but actual email
          (AWS SES) + SMS (Twilio HIPAA-eligible) delivery wires up once the
          processor accounts + BAAs are set up. Until then, scheduled
          campaigns stay in <span className="font-mono">scheduled</span>{' '}
          status without dispatching.
        </p>
      </div>
    </div>
  );
}

function Stat({
  label,
  value,
  tone = 'neutral',
}: {
  label: string;
  value: number;
  tone?: 'neutral' | 'success' | 'destructive' | 'muted';
}) {
  return (
    <div className="rounded-md border bg-card px-3 py-2.5">
      <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-medium">
        {label}
      </p>
      <p
        className={cn(
          'text-xl font-semibold tabular-nums tracking-tight',
          tone === 'success' && 'text-emerald-700',
          tone === 'destructive' && 'text-red-700',
          tone === 'muted' && 'text-stone-500',
        )}
      >
        {value}
      </p>
    </div>
  );
}

function ConfirmRow({
  tone,
  label,
  confirmLabel,
  onConfirm,
  onDismiss,
  pending,
}: {
  tone: 'warn' | 'destructive';
  label: string;
  confirmLabel: string;
  onConfirm: () => void;
  onDismiss: () => void;
  pending: boolean;
}) {
  return (
    <div
      className={cn(
        'rounded-md border px-3 py-2',
        tone === 'warn' && 'border-amber-200 bg-amber-50',
        tone === 'destructive' && 'border-red-200 bg-red-50',
      )}
    >
      <p
        className={cn(
          'text-sm font-medium mb-2',
          tone === 'warn' && 'text-amber-900',
          tone === 'destructive' && 'text-red-900',
        )}
      >
        {label}
      </p>
      <div className="flex items-center gap-2">
        <Button
          type="button"
          size="sm"
          variant={tone === 'destructive' ? 'destructive' : 'default'}
          onClick={onConfirm}
          disabled={pending}
        >
          {pending ? <Loader2 className="size-3.5 animate-spin" /> : null}
          {confirmLabel}
        </Button>
        <Button type="button" size="sm" variant="outline" onClick={onDismiss} disabled={pending}>
          Keep
        </Button>
      </div>
    </div>
  );
}

function SendLogRowView({ row, channel }: { row: SendLogRow; channel: 'email' | 'sms' }) {
  const recipient =
    channel === 'email'
      ? `${row.customer_first_name} (***@${row.recipient_email_domain})`
      : `${row.customer_first_name} (***-***-${row.recipient_phone_last4})`;
  return (
    <li className="flex items-center justify-between py-2 text-sm">
      <span className="text-foreground truncate">{recipient}</span>
      <span
        className={cn(
          'inline-flex items-center rounded-full px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wider shrink-0',
          row.status === 'sent' && 'bg-blue-50 text-blue-800',
          row.status === 'delivered' && 'bg-emerald-50 text-emerald-700',
          row.status === 'failed' && 'bg-red-50 text-red-700',
          row.status === 'suppressed' && 'bg-stone-100 text-stone-600',
          row.status === 'pending' && 'bg-amber-50 text-amber-800',
        )}
      >
        {row.status}
      </span>
    </li>
  );
}
