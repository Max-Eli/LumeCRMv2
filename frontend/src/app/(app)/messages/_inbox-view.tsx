/**
 * Shared inbox UI — used by both the in-dashboard `/messages` page
 * and the standalone popout window at `/inbox`.
 *
 * The single difference between the two surfaces is the URL the
 * thread links + the new-conversation picker route to. `basePath`
 * lets the caller decide ('/messages' for the dashboard, '/inbox'
 * for the popout). Everything else — polling, mark-read, auto-scroll,
 * send-message error handling — is identical.
 */

'use client';

import {
  AlertCircle,
  Loader2,
  MessageSquare,
  Phone,
  Plus,
  Search,
  Send,
} from 'lucide-react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { useEffect, useMemo, useRef, useState } from 'react';

import { ApiError } from '@/lib/api';
import { useCustomers, type CustomerListItem } from '@/lib/customers';
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
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';

export interface InboxViewProps {
  /** Where thread links + the picker navigate to. Lets the same
   *  component back both `/messages` (in the dashboard) and `/inbox`
   *  (in the popout window) without forking the UI. */
  basePath: '/messages' | '/inbox';
}

export function InboxView({ basePath }: InboxViewProps) {
  const router = useRouter();
  const params = useSearchParams();
  const selectedFromQs = params.get('c');
  const selectedCustomerId = selectedFromQs ? Number(selectedFromQs) : undefined;

  const { data: threads, isLoading: threadsLoading, error: threadsError } = useThreads();
  const [search, setSearch] = useState('');
  const [pickerOpen, setPickerOpen] = useState(false);

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
      router.replace(`${basePath}?c=${threads![0].customer_id}`);
    }
  }, [selectedCustomerId, threads, router, basePath]);

  return (
    <>
      <div className="flex-1 min-h-0 grid grid-cols-[300px_1fr] gap-0 rounded-lg border bg-card overflow-hidden">
        <ThreadList
          basePath={basePath}
          threads={filteredThreads}
          loading={threadsLoading}
          error={threadsError as Error | null}
          search={search}
          onSearchChange={setSearch}
          selectedCustomerId={selectedCustomerId}
          onNewConversation={() => setPickerOpen(true)}
        />
        {selectedCustomerId ? (
          <ConversationPane key={selectedCustomerId} customerId={selectedCustomerId} />
        ) : (
          <EmptyState
            empty={(threads?.length ?? 0) === 0 && !threadsLoading}
            onNewConversation={() => setPickerOpen(true)}
          />
        )}
      </div>
      <NewConversationDialog
        open={pickerOpen}
        onOpenChange={setPickerOpen}
        onPick={(c) => {
          setPickerOpen(false);
          router.push(`${basePath}?c=${c.id}`);
        }}
      />
    </>
  );
}

// ── Thread list ─────────────────────────────────────────────────────


function ThreadList({
  basePath,
  threads,
  loading,
  error,
  search,
  onSearchChange,
  selectedCustomerId,
  onNewConversation,
}: {
  basePath: string;
  threads: ThreadSummary[];
  loading: boolean;
  error: Error | null;
  search: string;
  onSearchChange: (v: string) => void;
  selectedCustomerId: number | undefined;
  onNewConversation: () => void;
}) {
  return (
    <div className="border-r flex flex-col min-h-0">
      <div className="p-3 border-b flex items-center gap-2">
        <Input
          placeholder="Search threads…"
          value={search}
          onChange={(e) => onSearchChange(e.target.value)}
          className="flex-1"
        />
        <Button
          size="icon"
          variant="outline"
          onClick={onNewConversation}
          aria-label="New conversation"
          title="New conversation"
        >
          <Plus className="size-4" />
        </Button>
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
                  href={`${basePath}?c=${t.customer_id}`}
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
          target="_blank"
          rel="noopener noreferrer"
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

function EmptyState({
  empty,
  onNewConversation,
}: {
  empty: boolean;
  onNewConversation: () => void;
}) {
  return (
    <div className="flex flex-col items-center justify-center text-center px-10 py-16 gap-3">
      <MessageSquare className="size-8 text-muted-foreground" />
      {empty ? (
        <>
          <p className="font-medium">No conversations yet</p>
          <p className="text-sm text-muted-foreground max-w-md">
            Start a new SMS thread with a client, or wait for them to text your toll-free number.
          </p>
          <Button onClick={onNewConversation} className="mt-2">
            <Plus className="size-4" />
            New conversation
          </Button>
        </>
      ) : (
        <p className="text-sm text-muted-foreground">Pick a thread from the list to view the conversation.</p>
      )}
    </div>
  );
}

// ── New-conversation picker ─────────────────────────────────────────


function NewConversationDialog({
  open,
  onOpenChange,
  onPick,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  onPick: (customer: CustomerListItem) => void;
}) {
  const [q, setQ] = useState('');
  // Empty-string search returns all customers; backend list is small
  // enough for v1 that this is fine — we'll add server-side
  // pagination/limit if a tenant ever crosses ~10k customers.
  const { data: customers, isLoading } = useCustomers({ q });

  // Reset the query when the dialog closes so reopening starts clean.
  useEffect(() => {
    if (!open) setQ('');
  }, [open]);

  const eligible = customers ?? [];

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>New conversation</DialogTitle>
        </DialogHeader>
        <DialogBody className="space-y-3">
          <div className="relative">
            <Search className="size-4 absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground pointer-events-none" />
            <Input
              autoFocus
              placeholder="Search by name, email, or phone…"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              className="pl-9"
            />
          </div>
          <div className="max-h-80 overflow-y-auto -mx-2">
            {isLoading ? (
              <p className="px-2 py-6 text-sm text-muted-foreground text-center">Loading…</p>
            ) : eligible.length === 0 ? (
              <p className="px-2 py-6 text-sm text-muted-foreground text-center">
                {q.trim() ? `No clients matching “${q}”.` : 'Start typing to search clients.'}
              </p>
            ) : (
              <ul className="divide-y">
                {eligible.map((c) => {
                  const hasPhone = !!(c.phone || '').trim();
                  return (
                    <li key={c.id}>
                      <button
                        type="button"
                        onClick={() => hasPhone && onPick(c)}
                        disabled={!hasPhone}
                        className={cn(
                          'w-full text-left px-3 py-2.5 rounded-md transition-colors',
                          hasPhone ? 'hover:bg-muted cursor-pointer' : 'opacity-50 cursor-not-allowed',
                        )}
                      >
                        <div className="flex items-baseline justify-between gap-2">
                          <span className="text-sm font-medium truncate">
                            {c.first_name} {c.last_name}
                          </span>
                          <span className="text-xs text-muted-foreground shrink-0">
                            {c.phone || 'no phone'}
                          </span>
                        </div>
                        {!hasPhone ? (
                          <p className="text-[11px] text-muted-foreground mt-0.5">
                            Add a phone number on this client&apos;s profile to send SMS.
                          </p>
                        ) : null}
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        </DialogBody>
      </DialogContent>
    </Dialog>
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
