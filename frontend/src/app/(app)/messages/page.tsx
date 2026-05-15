/**
 * Customer messaging inbox.
 *
 * Three-pane layout the same way Mindbody / Boulevard / Fresha
 * present their inbox:
 *
 *   ┌───────────────┬──────────────────────────────────────────┐
 *   │ Thread list   │ Conversation header                      │
 *   │ (left rail)   │──────────────────────────────────────────│
 *   │               │                                          │
 *   │ Pat Patient   │  ┌─ inbound bubble                       │
 *   │ Jane Doe   ●  │                            outbound bubble┐│
 *   │ ...           │  ┌─ inbound bubble                       │
 *   │               │                                          │
 *   │               │──────────────────────────────────────────│
 *   │               │ Compose box                              │
 *   └───────────────┴──────────────────────────────────────────┘
 *
 * Selected customer survives in the URL (`?c=<id>`) so the calendar
 * right-rail can deep-link a specific thread without state hand-off.
 *
 * Polling — `useThreads` and `useConversation` both refetch every
 * 15s. No SSE / websocket yet (Phase polish). PHI: every conversation
 * fetch is audit-logged at the backend.
 */

'use client';

import { AlertCircle, Loader2, MessageSquare, Phone, Send } from 'lucide-react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { useEffect, useMemo, useRef, useState } from 'react';

import { ApiError } from '@/lib/api';
import {
  type ConversationResponse,
  type Message,
  type ThreadSummary,
  useConversation,
  useMarkThreadRead,
  useSendMessage,
  useThreads,
} from '@/lib/messaging';
import { cn } from '@/lib/utils';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { PageHeader } from '@/components/page-header';

export default function MessagesPage() {
  const router = useRouter();
  const params = useSearchParams();
  const selectedFromQs = params.get('c');
  const selectedCustomerId = selectedFromQs ? Number(selectedFromQs) : undefined;

  const { data: threads, isLoading: threadsLoading, error: threadsError } = useThreads();
  const [search, setSearch] = useState('');

  const filteredThreads = useMemo(() => {
    if (!threads) return [];
    if (!search.trim()) return threads;
    const q = search.toLowerCase();
    return threads.filter((t) => {
      const name = `${t.customer_first_name} ${t.customer_last_name}`.toLowerCase();
      return (
        name.includes(q) ||
        t.customer_phone.toLowerCase().includes(q) ||
        t.last_message_body.toLowerCase().includes(q)
      );
    });
  }, [threads, search]);

  // First-visit affordance: auto-pick the top thread if nothing is
  // selected yet. Replace (not push) so the back button doesn't
  // bounce to the empty state.
  useEffect(() => {
    if (selectedCustomerId === undefined && (threads?.length ?? 0) > 0) {
      router.replace(`/messages?c=${threads![0].customer_id}`);
    }
  }, [selectedCustomerId, threads, router]);

  return (
    <div className="flex flex-col h-[calc(100vh-0px)] px-10 py-8 gap-4">
      <PageHeader
        title="Messages"
        description="Two-way SMS and MMS with your clients. Social DMs (Instagram, Facebook, WhatsApp) live under the Social tab when those integrations land."
      />
      <div className="flex-1 min-h-0 grid grid-cols-[320px_1fr] gap-4 rounded-lg border bg-card overflow-hidden">
        <ThreadList
          threads={filteredThreads}
          loading={threadsLoading}
          error={threadsError as Error | null}
          search={search}
          onSearchChange={setSearch}
          selectedCustomerId={selectedCustomerId}
        />
        {selectedCustomerId ? (
          <ConversationPane key={selectedCustomerId} customerId={selectedCustomerId} />
        ) : (
          <EmptyState empty={(threads?.length ?? 0) === 0 && !threadsLoading} />
        )}
      </div>
    </div>
  );
}

// ── Thread list ─────────────────────────────────────────────────────


function ThreadList({
  threads,
  loading,
  error,
  search,
  onSearchChange,
  selectedCustomerId,
}: {
  threads: ThreadSummary[];
  loading: boolean;
  error: Error | null;
  search: string;
  onSearchChange: (v: string) => void;
  selectedCustomerId: number | undefined;
}) {
  return (
    <div className="border-r flex flex-col min-h-0">
      <div className="p-3 border-b">
        <Input
          placeholder="Search threads…"
          value={search}
          onChange={(e) => onSearchChange(e.target.value)}
        />
      </div>
      <div className="flex-1 min-h-0 overflow-y-auto">
        {loading ? (
          <p className="px-4 py-6 text-sm text-muted-foreground">Loading…</p>
        ) : error ? (
          <p className="px-4 py-6 text-sm text-destructive">Failed to load threads.</p>
        ) : threads.length === 0 ? (
          <p className="px-4 py-6 text-sm text-muted-foreground">
            No conversations yet. Inbound texts to your toll-free number show up here.
          </p>
        ) : (
          <ul className="divide-y">
            {threads.map((t) => (
              <li key={t.customer_id}>
                <Link
                  href={`/messages?c=${t.customer_id}`}
                  className={cn(
                    'block px-4 py-3 transition-colors',
                    selectedCustomerId === t.customer_id
                      ? 'bg-accent text-accent-foreground'
                      : 'hover:bg-muted',
                  )}
                >
                  <div className="flex items-baseline justify-between gap-2">
                    <span className="text-sm font-medium truncate">
                      {t.customer_first_name} {t.customer_last_name}
                    </span>
                    <time className="text-[10px] text-muted-foreground shrink-0">
                      {formatRelative(t.last_message_at)}
                    </time>
                  </div>
                  <div className="flex items-baseline justify-between gap-2 mt-0.5">
                    <p className="text-xs text-muted-foreground truncate">
                      {t.last_message_direction === 'outbound' ? 'You: ' : ''}
                      {t.last_message_body || '—'}
                    </p>
                    {t.unread_inbound_count > 0 ? (
                      <span className="text-[10px] uppercase tracking-wide px-1.5 py-px rounded bg-foreground text-background shrink-0">
                        {t.unread_inbound_count}
                      </span>
                    ) : null}
                  </div>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

// ── Conversation pane (header + scrollback + compose) ───────────────


function ConversationPane({ customerId }: { customerId: number }) {
  const { data, isLoading, error } = useConversation(customerId);
  const markRead = useMarkThreadRead(customerId);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  // Mark-read fires once on mount per thread switch. We don't gate on
  // unread-count from the threads endpoint because that's a polled
  // snapshot and we'd race against new inbound messages.
  useEffect(() => {
    markRead.mutate();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [customerId]);

  // Auto-scroll to the latest message on load + any time the message
  // count grows.
  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [data?.messages.length]);

  if (isLoading && !data) {
    return (
      <div className="flex items-center justify-center text-muted-foreground">
        <Loader2 className="size-4 animate-spin" />
      </div>
    );
  }
  if (error || !data) {
    return (
      <div className="flex items-center justify-center text-destructive text-sm">
        Failed to load conversation.
      </div>
    );
  }

  return (
    <div className="flex flex-col min-h-0">
      <ConversationHeader conversation={data} />
      <div ref={scrollRef} className="flex-1 min-h-0 overflow-y-auto px-6 py-5 space-y-3 bg-muted/30">
        {data.messages.length === 0 ? (
          <p className="text-center text-sm text-muted-foreground py-10">
            No messages yet. Start the conversation below.
          </p>
        ) : (
          data.messages.map((m) => <MessageBubble key={m.id} message={m} />)
        )}
      </div>
      <Composer customerId={customerId} smsOptIn={data.customer.sms_opt_in} hasPhone={!!data.customer.phone} />
    </div>
  );
}

function ConversationHeader({ conversation }: { conversation: ConversationResponse }) {
  const c = conversation.customer;
  return (
    <header className="border-b px-6 py-3 flex items-center justify-between">
      <div className="min-w-0">
        <Link
          href={`/clients/${c.id}`}
          className="text-sm font-semibold hover:underline truncate block"
        >
          {c.first_name} {c.last_name}
        </Link>
        {c.phone ? (
          <p className="text-xs text-muted-foreground flex items-center gap-1.5">
            <Phone className="size-3" /> {c.phone}
          </p>
        ) : (
          <p className="text-xs text-muted-foreground">No phone on file</p>
        )}
      </div>
      {!c.sms_opt_in ? (
        <span className="inline-flex items-center gap-1.5 text-[11px] uppercase tracking-wide px-2 py-1 rounded bg-amber-100 text-amber-900 border border-amber-200">
          <AlertCircle className="size-3" /> SMS opt-in off
        </span>
      ) : null}
    </header>
  );
}

function MessageBubble({ message }: { message: Message }) {
  const isOutbound = message.direction === 'outbound';
  const failed = message.status === 'failed';

  return (
    <div className={cn('flex', isOutbound ? 'justify-end' : 'justify-start')}>
      <div className="max-w-[70%]">
        <div
          className={cn(
            'rounded-2xl px-3.5 py-2 text-sm whitespace-pre-wrap break-words',
            isOutbound
              ? failed
                ? 'bg-destructive/10 text-destructive border border-destructive/30'
                : 'bg-accent text-accent-foreground'
              : 'bg-card border',
          )}
        >
          {message.body}
          {message.media_urls.length > 0 ? (
            <div className="mt-2 grid grid-cols-2 gap-1">
              {message.media_urls.map((u) => (
                <a key={u} href={u} target="_blank" rel="noopener noreferrer">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={u} alt="MMS attachment" className="rounded-md w-full h-auto" />
                </a>
              ))}
            </div>
          ) : null}
        </div>
        <p
          className={cn(
            'mt-1 text-[10px] text-muted-foreground',
            isOutbound ? 'text-right' : 'text-left',
          )}
        >
          {formatTimestamp(message.created_at)}
          {isOutbound ? (
            <>
              {' · '}
              <span className={cn(failed ? 'text-destructive' : '')}>
                {labelForStatus(message.status)}
              </span>
              {message.sent_by_name ? <> · {message.sent_by_name}</> : null}
            </>
          ) : null}
        </p>
      </div>
    </div>
  );
}

function Composer({
  customerId,
  smsOptIn,
  hasPhone,
}: {
  customerId: number;
  smsOptIn: boolean;
  hasPhone: boolean;
}) {
  const [body, setBody] = useState('');
  const [error, setError] = useState<string | null>(null);
  const send = useSendMessage(customerId);
  const disabled = !smsOptIn || !hasPhone;

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    const trimmed = body.trim();
    if (!trimmed) return;
    try {
      await send.mutateAsync({ body: trimmed });
      setBody('');
    } catch (err) {
      if (err instanceof ApiError && err.body && typeof err.body === 'object') {
        const detail = (err.body as { detail?: string }).detail;
        setError(detail || 'Could not send the message.');
      } else {
        setError('Could not send the message.');
      }
    }
  };

  return (
    <form onSubmit={onSubmit} className="border-t bg-card px-4 py-3 space-y-2">
      {error ? (
        <p className="text-xs text-destructive">{error}</p>
      ) : null}
      {disabled ? (
        <p className="text-xs text-amber-800 bg-amber-50 border border-amber-200 rounded px-3 py-2">
          {!hasPhone
            ? 'This customer has no phone number on file — add one on their profile to send SMS.'
            : 'This customer has not opted into SMS. Toggle their SMS opt-in to send messages.'}
        </p>
      ) : null}
      <div className="flex items-end gap-2">
        <textarea
          rows={2}
          value={body}
          onChange={(e) => setBody(e.target.value)}
          disabled={disabled || send.isPending}
          placeholder={disabled ? '' : 'Type a message…'}
          maxLength={1600}
          onKeyDown={(e) => {
            // Cmd/Ctrl+Enter sends — common chat convention; plain Enter inserts a newline so a misplaced touch doesn't fire.
            if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
              onSubmit(e as unknown as React.FormEvent);
            }
          }}
          className="flex-1 rounded-md border bg-transparent px-3 py-2 text-sm shadow-xs outline-none resize-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:opacity-50"
        />
        <Button type="submit" disabled={disabled || send.isPending || !body.trim()}>
          {send.isPending ? <Loader2 className="size-4 animate-spin" /> : <Send className="size-4" />}
          Send
        </Button>
      </div>
      <p className="text-[10px] text-muted-foreground">
        {body.length}/1600 chars · ⌘ + Enter to send
      </p>
    </form>
  );
}

function EmptyState({ empty }: { empty: boolean }) {
  return (
    <div className="flex flex-col items-center justify-center text-center px-10 py-16 gap-3">
      <MessageSquare className="size-8 text-muted-foreground" />
      {empty ? (
        <>
          <p className="font-medium">No conversations yet</p>
          <p className="text-sm text-muted-foreground max-w-md">
            When a customer texts your toll-free number, the thread will land here. To start a thread, open a client&apos;s profile and use the message action.
          </p>
        </>
      ) : (
        <p className="text-sm text-muted-foreground">Pick a thread from the list to view the conversation.</p>
      )}
    </div>
  );
}

// ── Helpers ─────────────────────────────────────────────────────────


function labelForStatus(status: Message['status']): string {
  switch (status) {
    case 'queued':
      return 'Queued';
    case 'sent':
      return 'Sent';
    case 'delivered':
      return 'Delivered';
    case 'failed':
      return 'Failed';
    case 'received':
      return 'Received';
    default:
      return status;
  }
}

function formatTimestamp(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  });
}

function formatRelative(iso: string): string {
  const d = new Date(iso);
  const diffMs = Date.now() - d.getTime();
  const diffMin = Math.floor(diffMs / 60_000);
  if (diffMin < 1) return 'now';
  if (diffMin < 60) return `${diffMin}m`;
  const diffH = Math.floor(diffMin / 60);
  if (diffH < 24) return `${diffH}h`;
  const diffD = Math.floor(diffH / 24);
  if (diffD < 7) return `${diffD}d`;
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}
