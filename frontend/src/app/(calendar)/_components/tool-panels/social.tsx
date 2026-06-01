/**
 * Calendar right-rail Social DM panel — in-rail mini inbox.
 *
 * Two states inside the 340-px panel:
 *
 *   1. Thread list (default) — top 10 threads sorted newest-first.
 *      Click a row to drill into the conversation.
 *
 *   2. Thread detail — last N messages + a compact reply box. Honors
 *      the same 24-hour reply window the full `/social` page does
 *      (ADR 0027 §7). A 'Back to inbox' button returns to the list.
 *
 * When no Meta channel is connected we surface a connect prompt
 * routing to /org/integrations.
 *
 * HIPAA posture matches the full inbox: messages persist
 * encrypted-at-rest; the reply composer carries the non-dismissible
 * "Meta forbids PHI in DMs" reminder; audit log records body length
 * only.
 */

'use client';

import { ArrowLeft, ArrowUpRight, AtSign, Inbox, Loader2 } from 'lucide-react';
import Link from 'next/link';
import { useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { InitialsAvatar } from '@/components/initials-avatar';
import { ApiError } from '@/lib/api';
import {
  useAIConversationStatus,
  usePauseAI,
  useResumeAI,
} from '@/lib/ai-inbox';
import { useIntegrations } from '@/lib/integrations';
import {
  PROVIDER_LABEL,
  PROVIDER_TONE,
  displayHandle,
  displayName,
  relativeAgo,
  useMarkThreadRead,
  useReplyToThread,
  useSocialThread,
  useSocialThreads,
  type SocialMessage,
  type SocialThreadSummary,
} from '@/lib/social';
import { cn } from '@/lib/utils';

const MAX_REPLY_CHARS = 1000;

export function SocialPanel() {
  const [openThreadId, setOpenThreadId] = useState<number | null>(null);

  return openThreadId === null ? (
    <ThreadListView onOpenThread={setOpenThreadId} />
  ) : (
    <ThreadDetailView
      threadId={openThreadId}
      onBack={() => setOpenThreadId(null)}
    />
  );
}

// ── Thread list ────────────────────────────────────────────────────

function ThreadListView({
  onOpenThread,
}: {
  onOpenThread: (id: number) => void;
}) {
  const threadsQuery = useSocialThreads({});
  const integrationsQuery = useIntegrations();
  const connectedCount =
    (integrationsQuery.data ?? []).filter((p) => p.status === 'connected').length;

  const threads = threadsQuery.data?.threads ?? [];
  const unread = threads.filter((t) => t.is_unread).length;

  // Strict newest-at-top chronological order. We tried unread-first
  // bucketing earlier and it confused operators — a brand-new reply
  // would sink below an older unread thread that hadn't been triaged
  // yet. Unread state stays visible via the row's unread dot.
  // No cap — the panel body scrolls, and the backend already caps at
  // 200 rows (more than any realistic spa's inbox length).
  const sorted = useMemo(() => {
    return [...threads].sort((a, b) => {
      return new Date(b.last_message_at).getTime() - new Date(a.last_message_at).getTime();
    });
  }, [threads]);

  return (
    <div className="flex flex-col h-full">
      <div className="px-4 pt-3 pb-2 border-b">
        <p className="text-xs text-muted-foreground">
          {threadsQuery.isLoading ? (
            'Loading…'
          ) : connectedCount === 0 ? (
            'No social channels connected yet.'
          ) : threads.length === 0 ? (
            'No conversations yet.'
          ) : (
            <>
              <span className="font-medium text-foreground">{unread}</span>
              {' unread '}
              {unread === 1 ? 'thread' : 'threads'}
              {' · '}
              {threads.length} total
            </>
          )}
        </p>
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto">
        {connectedCount === 0 && !integrationsQuery.isLoading ? (
          <ConnectPrompt />
        ) : threadsQuery.isLoading ? (
          <Loading />
        ) : sorted.length === 0 ? (
          <EmptyState />
        ) : (
          <ul className="divide-y">
            {sorted.map((t) => (
              <ThreadRow
                key={t.id}
                thread={t}
                onOpen={() => onOpenThread(t.id)}
              />
            ))}
          </ul>
        )}
      </div>

      <div className="border-t px-3 py-2.5">
        <Button
          render={<Link href="/social" />}
          nativeButton={false}
          variant="outline"
          size="sm"
          className="w-full"
        >
          Open full inbox
          <ArrowUpRight className="size-3.5" />
        </Button>
      </div>
    </div>
  );
}

function ThreadRow({
  thread,
  onOpen,
}: {
  thread: SocialThreadSummary;
  onOpen: () => void;
}) {
  return (
    <li>
      <button
        type="button"
        onClick={onOpen}
        className="w-full text-left px-4 py-2.5 hover:bg-muted/40 transition flex items-start gap-2.5"
      >
        <div className="relative shrink-0">
          <InitialsAvatar
            name={displayName(thread)}
            src={thread.external_profile_pic_url || undefined}
            size="sm"
          />
          <span
            className={cn(
              'absolute -bottom-0.5 -right-0.5 inline-flex size-3.5 items-center justify-center rounded-full ring-2 ring-card',
              PROVIDER_TONE[thread.provider],
            )}
            title={PROVIDER_LABEL[thread.provider]}
            aria-label={PROVIDER_LABEL[thread.provider]}
          >
            <AtSign className="size-2" />
          </span>
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between gap-2">
            <span
              className={cn(
                'text-sm truncate',
                thread.is_unread ? 'font-semibold' : 'font-medium',
              )}
            >
              {displayName(thread)}
            </span>
            <span className="text-[10px] text-muted-foreground shrink-0">
              {relativeAgo(thread.last_message_at)}
            </span>
          </div>
          <div className="flex items-center gap-1.5 mt-0.5">
            <span className="text-[11px] text-muted-foreground truncate">
              {displayHandle(thread)} · {PROVIDER_LABEL[thread.provider]}
            </span>
            {thread.is_unread && (
              <span
                aria-label="Unread"
                className="size-1.5 rounded-full bg-accent shrink-0"
              />
            )}
          </div>
        </div>
      </button>
    </li>
  );
}

function ConnectPrompt() {
  return (
    <div className="px-4 py-6 text-center">
      <AtSign className="size-6 mx-auto mb-2 text-muted-foreground" />
      <p className="text-xs text-muted-foreground mb-3">
        Connect your spa&apos;s Instagram so DMs land here alongside SMS.
      </p>
      <Button
        render={<Link href="/org/integrations" />}
        nativeButton={false}
        variant="outline"
        size="sm"
      >
        Connect a channel
        <ArrowUpRight className="size-3.5" />
      </Button>
    </div>
  );
}

function EmptyState() {
  return (
    <div className="px-4 py-6 text-center">
      <Inbox className="size-6 mx-auto mb-2 text-muted-foreground" />
      <p className="text-xs text-muted-foreground">
        No conversations yet. When a customer DMs your connected accounts,
        the thread appears here.
      </p>
    </div>
  );
}

function Loading() {
  return (
    <div className="flex items-center justify-center py-6 text-muted-foreground">
      <Loader2 className="size-4 animate-spin" />
    </div>
  );
}

// ── Thread detail (in-panel) ───────────────────────────────────────

function ThreadDetailView({
  threadId,
  onBack,
}: {
  threadId: number;
  onBack: () => void;
}) {
  const detailQuery = useSocialThread(threadId);
  const markRead = useMarkThreadRead();

  // Auto-mark-read on open (matches the full /social page behaviour).
  useEffect(() => {
    const t = detailQuery.data?.thread;
    if (t && t.read_at === null) {
      markRead.mutate({ threadId });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [threadId, detailQuery.data?.thread?.id]);

  if (detailQuery.isLoading) {
    return (
      <div className="flex flex-col h-full">
        <DetailHeader onBack={onBack} title="Loading…" />
        <Loading />
      </div>
    );
  }
  if (!detailQuery.data) {
    return (
      <div className="flex flex-col h-full">
        <DetailHeader onBack={onBack} title="Thread" />
        <p className="px-4 py-6 text-sm text-muted-foreground">
          Thread not found.
        </p>
      </div>
    );
  }

  const { thread, messages } = detailQuery.data;
  return (
    <div className="flex flex-col h-full">
      <DetailHeader
        onBack={onBack}
        title={displayName(thread)}
        subtitle={`${displayHandle(thread)} · ${PROVIDER_LABEL[thread.provider]}`}
        threadId={threadId}
      />

      <div className="flex-1 min-h-0 overflow-y-auto px-3 py-3 space-y-2">
        {messages.length === 0 ? (
          <p className="text-xs text-muted-foreground text-center py-4">
            No messages in this thread yet.
          </p>
        ) : (
          // Show the last 30 messages in chronological order. The
          // full /social page is the place for very long threads.
          messages.slice(-30).map((m) => <MiniBubble key={m.id} message={m} />)
        )}
      </div>

      <MiniAIStatusBanner customerId={thread.customer.id} />
      <MiniComposer thread={thread} />
    </div>
  );
}

function DetailHeader({
  onBack,
  title,
  subtitle,
  threadId,
}: {
  onBack: () => void;
  title: string;
  subtitle?: string;
  threadId?: number;
}) {
  return (
    <header className="shrink-0 flex items-center gap-2 border-b px-3 py-2.5">
      <button
        type="button"
        onClick={onBack}
        className="inline-flex size-7 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
        aria-label="Back to inbox"
      >
        <ArrowLeft className="size-4" />
      </button>
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium truncate">{title}</p>
        {subtitle && (
          <p className="text-[11px] text-muted-foreground truncate">
            {subtitle}
          </p>
        )}
      </div>
      {threadId && (
        <Link
          href={`/social?thread=${threadId}`}
          target="_blank"
          className="text-[11px] text-muted-foreground hover:text-foreground inline-flex items-center gap-0.5"
          title="Open full conversation"
        >
          Open <ArrowUpRight className="size-3" />
        </Link>
      )}
    </header>
  );
}

function MiniBubble({ message }: { message: SocialMessage }) {
  const isOutbound = message.direction === 'outbound';
  const isFailed = message.status === 'failed';
  const isAI = message.generated_by_ai === true;
  return (
    <div className={cn('flex', isOutbound ? 'justify-end' : 'justify-start')}>
      <div
        className={cn(
          'max-w-[80%] rounded-xl px-3 py-2 ring-1 ring-inset text-xs',
          isFailed
            ? 'bg-rose-50 text-rose-900 ring-rose-200 dark:bg-rose-950/40 dark:text-rose-100 dark:ring-rose-900'
            : isAI
              ? 'bg-violet-100 text-violet-900 ring-violet-200 dark:bg-violet-950/40 dark:text-violet-100 dark:ring-violet-900'
              : isOutbound
                ? 'bg-accent text-accent-foreground ring-accent/40'
                : 'bg-card text-foreground ring-border',
        )}
      >
        {isAI && (
          <p className="mb-0.5 text-[9px] font-semibold uppercase tracking-wide text-violet-700 dark:text-violet-300">
            AI · agent reply
          </p>
        )}
        {message.body && (
          <p className="whitespace-pre-wrap break-words leading-snug">
            {message.body}
          </p>
        )}
        <p className={cn(
          'mt-0.5 text-[9px]',
          isFailed
            ? 'text-rose-700 dark:text-rose-200'
            : isAI
              ? 'text-violet-700/70 dark:text-violet-300/70'
              : isOutbound
                ? 'text-accent-foreground/70'
                : 'text-muted-foreground',
        )}>
          {relativeAgo(message.created_at)}
          {isOutbound && message.status !== 'sent' && (
            <span> · {message.status}</span>
          )}
        </p>
      </div>
    </div>
  );
}

/**
 * Compact AI status strip for the calendar rail — mirrors the
 * `/social` page banner but sized for the 340-px panel. Renders
 * nothing when the conversation has no Instagram AI state (or the
 * feature is off → the status query 402s and `isError` short-circuits).
 */
function MiniAIStatusBanner({ customerId }: { customerId: number }) {
  const { data, isError } = useAIConversationStatus(customerId, 'instagram');
  const pause = usePauseAI(customerId, 'instagram');
  const resume = useResumeAI(customerId, 'instagram');

  if (isError || !data || data.status === 'closed') return null;

  const isPaused = data.status === 'paused';
  const isEscalated = data.status === 'escalated';

  const tone = isEscalated
    ? 'bg-rose-50 border-rose-200 text-rose-900 dark:bg-rose-950/30 dark:text-rose-100 dark:border-rose-900'
    : isPaused
      ? 'bg-amber-50 border-amber-200 text-amber-900 dark:bg-amber-950/30 dark:text-amber-100 dark:border-amber-900'
      : 'bg-violet-50 border-violet-200 text-violet-900 dark:bg-violet-950/30 dark:text-violet-100 dark:border-violet-900';

  const label = isEscalated
    ? `AI escalated — ${data.escalation_reason || 'needs attention'}.`
    : isPaused
      ? 'AI paused. You’re handling this thread.'
      : 'AI is replying to this thread.';

  const busy = pause.isPending || resume.isPending;
  const onClick = () => (isPaused || isEscalated ? resume.mutate() : pause.mutate());

  return (
    <div className={cn('flex items-center justify-between gap-2 border-t px-3 py-1.5 text-[11px]', tone)}>
      <span className="truncate">{label}</span>
      <button
        type="button"
        onClick={onClick}
        disabled={busy}
        className="shrink-0 rounded-md border border-current/30 bg-card px-2 py-0.5 text-[10px] font-medium hover:bg-muted disabled:opacity-50 disabled:cursor-not-allowed"
      >
        {busy ? '…' : isPaused || isEscalated ? 'Resume' : 'Pause'}
      </button>
    </div>
  );
}

function MiniComposer({ thread }: { thread: SocialThreadSummary }) {
  const [body, setBody] = useState('');
  const reply = useReplyToThread();
  const trimmed = body.trim();
  const canSend =
    trimmed.length > 0 && trimmed.length <= MAX_REPLY_CHARS && !reply.isPending;

  const handleSend = () => {
    if (!canSend) return;
    reply.mutate(
      { threadId: thread.id, body: trimmed },
      {
        onSuccess: () => setBody(''),
        onError: (err) => {
          if (err instanceof ApiError) {
            const errBody = err.body as { detail?: string } | null;
            toast.error(errBody?.detail ?? 'Could not send.');
          } else {
            toast.error('Could not send.');
          }
        },
      },
    );
  };

  return (
    <div className="shrink-0 border-t px-3 py-2 space-y-1.5">
      {/* HIPAA reminder — non-dismissible (ADR 0027 §7) */}
      <p className="text-[9px] text-muted-foreground uppercase tracking-wide">
        Meta prohibits PHI in DMs — keep replies non-clinical
      </p>
      <textarea
        value={body}
        onChange={(e) => setBody(e.target.value)}
        onKeyDown={(e) => {
          if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
            e.preventDefault();
            handleSend();
          }
        }}
        placeholder="Reply…"
        rows={2}
        disabled={reply.isPending}
        className="w-full resize-none rounded-md border border-input bg-background px-2 py-1.5 text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60"
      />
      <div className="flex items-center justify-between gap-2">
        <span className="text-[9px] text-muted-foreground">
          Cmd/Ctrl+Enter
        </span>
        <Button
          size="sm"
          onClick={handleSend}
          disabled={!canSend}
          className="h-7 text-xs px-3"
        >
          {reply.isPending ? 'Sending…' : 'Send'}
        </Button>
      </div>
    </div>
  );
}
