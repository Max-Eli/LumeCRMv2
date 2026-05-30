/**
 * Inbox UI for the popout window at `/inbox`.
 *
 * The popout is the only entry point for messaging — it's spawned
 * by the calendar right-rail Messages tile. The previous dashboard
 * `/messages` route has been removed; front-desk staff always work
 * the inbox alongside the calendar, not on a separate sidebar page.
 *
 * Internals: 15s polling on threads + open conversation, mark-read
 * fires on thread switch, auto-scroll to the latest message,
 * Cmd/Ctrl+Enter to send.
 */

'use client';

import {
  AlertCircle,
  ArrowUpRight,
  Loader2,
  MessageSquare,
  Phone,
  Plus,
  Search,
  Send,
  Settings2,
} from 'lucide-react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { useEffect, useMemo, useRef, useState } from 'react';

import {
  usePauseAI,
  useResumeAI,
  useAIConversationStatus,
} from '@/lib/ai-inbox';
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
import { InitialsAvatar } from '@/components/initials-avatar';
import { Input } from '@/components/ui/input';

import { AutomatedTemplatesDialog } from './automated-templates';
import {
  ManageSavedRepliesDialog,
  SavedRepliesPopover,
} from './saved-replies';

/** Mounted at `/inbox` inside the popout window the calendar tile
 *  spawns. The path is hard-coded into thread links + the new-
 *  conversation picker target since the popout is the only place
 *  this component is rendered. */
const BASE_PATH = '/inbox';

export function InboxView() {
  const router = useRouter();
  const params = useSearchParams();
  const selectedFromQs = params.get('c');
  const selectedCustomerId = selectedFromQs ? Number(selectedFromQs) : undefined;

  const { data: threads, isLoading: threadsLoading, error: threadsError } = useThreads();
  const [search, setSearch] = useState('');
  const [pickerOpen, setPickerOpen] = useState(false);
  const [manageRepliesOpen, setManageRepliesOpen] = useState(false);
  const [templatesOpen, setTemplatesOpen] = useState(false);

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
      router.replace(`${BASE_PATH}?c=${threads![0].customer_id}`);
    }
  }, [selectedCustomerId, threads, router]);

  return (
    <>
      <div className="flex-1 min-h-0 grid grid-cols-[320px_1fr] gap-0 rounded-xl border bg-card overflow-hidden shadow-sm">
        <ThreadList
          threads={filteredThreads}
          loading={threadsLoading}
          error={threadsError as Error | null}
          search={search}
          onSearchChange={setSearch}
          selectedCustomerId={selectedCustomerId}
          onNewConversation={() => setPickerOpen(true)}
          onManageReplies={() => setManageRepliesOpen(true)}
          onOpenTemplates={() => setTemplatesOpen(true)}
        />
        {selectedCustomerId ? (
          <ConversationPane
            key={selectedCustomerId}
            customerId={selectedCustomerId}
            onManageReplies={() => setManageRepliesOpen(true)}
          />
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
          router.push(`${BASE_PATH}?c=${c.id}`);
        }}
      />
      <ManageSavedRepliesDialog
        open={manageRepliesOpen}
        onOpenChange={setManageRepliesOpen}
      />
      <AutomatedTemplatesDialog
        open={templatesOpen}
        onOpenChange={setTemplatesOpen}
      />
    </>
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
  onNewConversation,
  onManageReplies,
  onOpenTemplates,
}: {
  threads: ThreadSummary[];
  loading: boolean;
  error: Error | null;
  search: string;
  onSearchChange: (v: string) => void;
  selectedCustomerId: number | undefined;
  onNewConversation: () => void;
  onManageReplies: () => void;
  onOpenTemplates: () => void;
}) {
  return (
    <div className="border-r flex flex-col min-h-0 bg-card">
      <div className="px-3 pt-3 pb-2 flex items-center gap-2">
        <div className="relative flex-1">
          <Search className="size-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground pointer-events-none" />
          <Input
            placeholder="Search threads…"
            value={search}
            onChange={(e) => onSearchChange(e.target.value)}
            className="h-9 pl-8 text-sm"
          />
        </div>
        <Button
          size="icon"
          onClick={onNewConversation}
          aria-label="New conversation"
          title="New conversation"
          className="h-9 w-9 shrink-0"
        >
          <Plus className="size-4" />
        </Button>
      </div>
      <div className="flex-1 min-h-0 overflow-y-auto px-1.5 pb-2">
        {loading ? (
          <p className="px-4 py-6 text-sm text-muted-foreground">Loading…</p>
        ) : error ? (
          <p className="px-4 py-6 text-sm text-destructive">Failed to load threads.</p>
        ) : threads.length === 0 ? (
          <p className="px-4 py-6 text-sm text-muted-foreground">
            No conversations yet. Inbound texts to your toll-free number show up here.
          </p>
        ) : (
          <ul className="space-y-px">
            {threads.map((t) => {
              const name = `${t.customer_first_name} ${t.customer_last_name}`.trim();
              const isSelected = selectedCustomerId === t.customer_id;
              const isUnread = t.unread_inbound_count > 0;
              return (
                <li key={t.customer_id}>
                  <Link
                    href={`${BASE_PATH}?c=${t.customer_id}`}
                    className={cn(
                      'block px-2.5 py-2.5 rounded-lg transition-colors',
                      isSelected
                        ? 'bg-accent text-accent-foreground'
                        : 'hover:bg-muted',
                    )}
                  >
                    <div className="flex items-start gap-2.5">
                      <InitialsAvatar name={name} size="sm" />
                      <div className="min-w-0 flex-1">
                        <div className="flex items-baseline justify-between gap-2">
                          <span
                            className={cn(
                              'text-sm truncate',
                              isUnread ? 'font-semibold' : 'font-medium',
                            )}
                          >
                            {name}
                          </span>
                          <time
                            className={cn(
                              'text-[10px] shrink-0',
                              isSelected
                                ? 'text-accent-foreground/70'
                                : isUnread
                                  ? 'text-foreground font-medium'
                                  : 'text-muted-foreground',
                            )}
                          >
                            {formatRelative(t.last_message_at)}
                          </time>
                        </div>
                        <div className="flex items-baseline justify-between gap-2 mt-0.5">
                          <p
                            className={cn(
                              'text-xs truncate',
                              isSelected
                                ? 'text-accent-foreground/80'
                                : isUnread
                                  ? 'text-foreground'
                                  : 'text-muted-foreground',
                            )}
                          >
                            {t.last_message_direction === 'outbound' ? (
                              <span className={cn(isSelected ? 'opacity-70' : 'text-muted-foreground/70')}>
                                You:{' '}
                              </span>
                            ) : null}
                            {t.last_message_body || '—'}
                          </p>
                          {isUnread ? (
                            <span
                              className={cn(
                                'text-[10px] font-semibold leading-none px-1.5 py-1 rounded-full shrink-0 min-w-5 text-center',
                                isSelected
                                  ? 'bg-accent-foreground/20 text-accent-foreground'
                                  : 'bg-foreground text-background',
                              )}
                            >
                              {t.unread_inbound_count}
                            </span>
                          ) : null}
                        </div>
                      </div>
                    </div>
                  </Link>
                </li>
              );
            })}
          </ul>
        )}
      </div>
      {/* Foot rail — quick access to settings shared across threads. */}
      <div className="border-t px-2 py-1.5 space-y-px">
        <button
          type="button"
          onClick={onManageReplies}
          className="w-full flex items-center gap-2 px-2 py-1.5 rounded-md text-xs text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
        >
          <Settings2 className="size-3.5" />
          Saved replies
        </button>
        <button
          type="button"
          onClick={onOpenTemplates}
          className="w-full flex items-center gap-2 px-2 py-1.5 rounded-md text-xs text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
        >
          <Settings2 className="size-3.5" />
          Automated messages
        </button>
      </div>
    </div>
  );
}

// ── Conversation pane (header + scrollback + compose) ───────────────


function ConversationPane({
  customerId,
  onManageReplies,
}: {
  customerId: number;
  onManageReplies: () => void;
}) {
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
      <div ref={scrollRef} className="flex-1 min-h-0 overflow-y-auto px-6 py-5 space-y-2.5 bg-muted/40">
        {data.messages.length === 0 ? (
          <p className="text-center text-sm text-muted-foreground py-10">
            No messages yet. Start the conversation below.
          </p>
        ) : (
          data.messages.map((m) => <MessageBubble key={m.id} message={m} />)
        )}
      </div>
      <AIStatusBanner customerId={customerId} />
      <Composer
        customerId={customerId}
        smsOptIn={data.customer.sms_opt_in}
        hasPhone={!!data.customer.phone}
        onManageReplies={onManageReplies}
      />
    </div>
  );
}

/**
 * Renders nothing until the AI feature responds (tenant might be on
 * a tier without F_AI_INBOX, in which case the endpoint 402s and the
 * banner stays hidden). When the tenant DOES have the feature, shows
 * one of three states:
 *
 *   - active     — green strip, "AI is replying" + Pause button
 *   - paused     — amber strip, "AI paused — you're driving" + Resume
 *   - escalated  — red strip, reason text + "Mark resolved" (which
 *                  also flips status back to active)
 *
 * Status is polled every 10s by useAIConversationStatus so the
 * operator sees the agent reply or escalate within a turn.
 */
function AIStatusBanner({ customerId }: { customerId: number }) {
  const { data, isError } = useAIConversationStatus(customerId);
  const pause = usePauseAI(customerId);
  const resume = useResumeAI(customerId);

  // 402 (PlanFeatureRequired) or any other error → hide the banner
  // completely. Don't broadcast "AI is off" — that's not the user's
  // job to think about on a thread.
  if (isError || !data) return null;

  if (data.status === 'closed') return null;

  const isPaused = data.status === 'paused';
  const isEscalated = data.status === 'escalated';

  const tone = isEscalated
    ? 'bg-rose-50 border-rose-200 text-rose-900'
    : isPaused
      ? 'bg-amber-50 border-amber-200 text-amber-900'
      : 'bg-violet-50 border-violet-200 text-violet-900';

  const label = isEscalated
    ? `AI escalated — ${data.escalation_reason || 'needs attention'}.`
    : isPaused
      ? `AI paused${data.paused_by_email ? ' by ' + data.paused_by_email : ''}. You’re driving this thread.`
      : 'AI is replying to this thread. Click Pause to take over.';

  const buttonLabel = isEscalated
    ? 'Resume AI'
    : isPaused
      ? 'Resume AI'
      : 'Pause AI';
  const onClick = () => (isPaused || isEscalated ? resume.mutate() : pause.mutate());
  const busy = pause.isPending || resume.isPending;

  return (
    <div
      className={cn(
        'flex items-center justify-between gap-3 border-t px-5 py-2 text-xs',
        tone,
      )}
    >
      <span className="truncate">{label}</span>
      <button
        type="button"
        onClick={onClick}
        disabled={busy}
        className={cn(
          'rounded-md border px-2.5 py-1 text-[11px] font-medium transition-colors',
          'bg-card hover:bg-muted disabled:opacity-50 disabled:cursor-not-allowed',
          isEscalated || isPaused ? 'border-current' : 'border-violet-300',
        )}
      >
        {busy ? '...' : buttonLabel}
      </button>
    </div>
  );
}

function ConversationHeader({ conversation }: { conversation: ConversationResponse }) {
  const c = conversation.customer;
  const name = `${c.first_name} ${c.last_name}`.trim();
  return (
    <header className="border-b px-5 py-3 flex items-center justify-between bg-card">
      <div className="flex items-center gap-3 min-w-0">
        <InitialsAvatar name={name} />
        <div className="min-w-0">
          <Link
            href={`/clients/${c.id}`}
            target="_blank"
            rel="noopener noreferrer"
            className="text-sm font-semibold tracking-tight hover:underline truncate flex items-center gap-1.5"
          >
            {name}
            <ArrowUpRight className="size-3 text-muted-foreground/60" />
          </Link>
          {c.phone ? (
            <p className="text-xs text-muted-foreground flex items-center gap-1.5 mt-0.5">
              <Phone className="size-3" /> {c.phone}
            </p>
          ) : (
            <p className="text-xs text-muted-foreground mt-0.5">No phone on file</p>
          )}
        </div>
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
  const isAI = message.generated_by_ai === true;
  const isAutomated =
    !isAI && (
      message.kind === 'confirmation' ||
      message.kind === 'reminder' ||
      message.kind === 'review_request'
    );

  return (
    <div className={cn('flex', isOutbound ? 'justify-end' : 'justify-start')}>
      <div className="max-w-[70%]">
        {(isAutomated || isAI) ? (
          <div className={cn('mb-1 flex', isOutbound ? 'justify-end' : 'justify-start')}>
            <KindBadge kind={isAI ? 'ai' : message.kind} />
          </div>
        ) : null}
        <div
          className={cn(
            'rounded-2xl px-3.5 py-2 text-sm whitespace-pre-wrap break-words shadow-sm',
            isOutbound
              ? failed
                ? 'bg-destructive/10 text-destructive border border-destructive/30'
                : isAI
                  ? 'bg-violet-50 text-violet-900 border border-violet-200 rounded-br-md'
                  : isAutomated
                    ? 'bg-card border rounded-br-md'
                    : 'bg-accent text-accent-foreground rounded-br-md'
              : 'bg-card border rounded-bl-md',
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
            'mt-1 text-[10px] text-muted-foreground px-1',
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
              {isAI ? <> · AI agent</> : message.sent_by_name ? <> · {message.sent_by_name}</> : null}
            </>
          ) : null}
        </p>
      </div>
    </div>
  );
}

function KindBadge({ kind }: { kind: Message['kind'] }) {
  // Visual hierarchy: automated messages get a subtle, system-toned
  // chip so the operator instantly recognises them as platform-sent
  // rather than typed by staff. AI gets a distinct violet tone so
  // the operator can tell at a glance whether the agent or a
  // template wrote a given outbound.
  const meta =
    kind === 'confirmation'
      ? { label: 'Confirmation', prefix: 'Auto', tone: 'bg-emerald-50 text-emerald-700 border-emerald-200' }
      : kind === 'reminder'
        ? { label: 'Reminder', prefix: 'Auto', tone: 'bg-sky-50 text-sky-700 border-sky-200' }
        : kind === 'review_request'
          ? { label: 'Review request', prefix: 'Auto', tone: 'bg-amber-50 text-amber-800 border-amber-200' }
          : kind === 'ai'
            ? { label: 'agent reply', prefix: 'AI', tone: 'bg-violet-50 text-violet-700 border-violet-200' }
            : null;
  if (!meta) return null;
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 text-[10px] uppercase tracking-wide font-medium px-1.5 py-px rounded-full border',
        meta.tone,
      )}
    >
      {meta.prefix} · {meta.label}
    </span>
  );
}

function Composer({
  customerId,
  smsOptIn,
  hasPhone,
  onManageReplies,
}: {
  customerId: number;
  smsOptIn: boolean;
  hasPhone: boolean;
  onManageReplies: () => void;
}) {
  const [body, setBody] = useState('');
  const [error, setError] = useState<string | null>(null);
  const send = useSendMessage(customerId);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
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

  // Inserts a saved reply at the cursor position. If there's a
  // selection, the reply replaces it; otherwise it's inserted inline
  // with a leading space when adjacent to existing text. Mirrors the
  // expected behaviour of an "insert" affordance — never destructive.
  const insertSavedReply = (replyBody: string) => {
    const ta = textareaRef.current;
    if (!ta) {
      setBody((prev) => (prev ? `${prev}\n${replyBody}` : replyBody));
      return;
    }
    const start = ta.selectionStart ?? body.length;
    const end = ta.selectionEnd ?? body.length;
    const before = body.slice(0, start);
    const after = body.slice(end);
    const separatorBefore = before && !before.endsWith(' ') && !before.endsWith('\n') ? ' ' : '';
    const separatorAfter = after && !after.startsWith(' ') && !after.startsWith('\n') ? ' ' : '';
    const next = `${before}${separatorBefore}${replyBody}${separatorAfter}${after}`;
    setBody(next);
    // Restore caret to end of inserted text on the next tick.
    requestAnimationFrame(() => {
      if (!textareaRef.current) return;
      const caret = before.length + separatorBefore.length + replyBody.length;
      textareaRef.current.focus();
      textareaRef.current.setSelectionRange(caret, caret);
    });
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
      <div className="rounded-xl border bg-background focus-within:border-ring focus-within:ring-3 focus-within:ring-ring/30 transition-colors">
        <textarea
          ref={textareaRef}
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
          className="block w-full bg-transparent px-3.5 py-2.5 text-sm outline-none resize-none disabled:opacity-50 placeholder:text-muted-foreground/70"
        />
        <div className="flex items-center justify-between gap-2 px-2 pb-1.5">
          <SavedRepliesPopover
            disabled={disabled || send.isPending}
            onInsert={insertSavedReply}
            onManage={onManageReplies}
          />
          <div className="flex items-center gap-3">
            <p className="text-[10px] text-muted-foreground hidden sm:block">
              {body.length}/1600 · ⌘ + Enter to send
            </p>
            <Button
              type="submit"
              size="sm"
              disabled={disabled || send.isPending || !body.trim()}
            >
              {send.isPending ? <Loader2 className="size-4 animate-spin" /> : <Send className="size-4" />}
              Send
            </Button>
          </div>
        </div>
      </div>
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
    <div className="flex flex-col items-center justify-center text-center px-10 py-16 gap-3 bg-muted/30">
      <div className="inline-flex size-12 items-center justify-center rounded-full bg-card border shadow-sm">
        <MessageSquare className="size-5 text-muted-foreground" />
      </div>
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
