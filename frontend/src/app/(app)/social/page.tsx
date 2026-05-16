/**
 * `/social` — Social inbox (Camera Business DMs in Session 1).
 *
 * Two-column layout: thread list on the left, selected thread detail
 * on the right. Selected thread tracked via `?thread=<id>` so deep
 * links and back/forward navigation work.
 *
 * Sidebar-resident (not popout) because IG DMs are less time-critical
 * than SMS — operators triage them in batches, not alongside the
 * live calendar. Owner + manager only (mirrors the backend's
 * MANAGE_INTEGRATIONS gate).
 *
 * Session 1 is read-only. The reply box renders a placeholder
 * explaining that Session 2 will add outbound sending; this is
 * deliberate so operators can SEE what's arriving even before they
 * can respond from Lumè (they reply via the IG app for now).
 */

'use client';

import { useEffect, useMemo, useState } from 'react';
import { Camera, Inbox, RefreshCw } from 'lucide-react';
import { useRouter, useSearchParams } from 'next/navigation';

import {
  PROVIDER_LABEL,
  PROVIDER_TONE,
  displayHandle,
  relativeAgo,
  useMarkThreadRead,
  useSocialThread,
  useSocialThreads,
  type SocialThreadSummary,
} from '@/lib/social';

export default function SocialInboxPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const selectedId = useMemo(() => {
    const raw = searchParams.get('thread');
    if (!raw) return null;
    const parsed = Number.parseInt(raw, 10);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
  }, [searchParams]);

  const [unreadOnly, setUnreadOnly] = useState(false);
  const threadsQuery = useSocialThreads({ unreadOnly });
  const threadQuery = useSocialThread(selectedId);
  const markRead = useMarkThreadRead();

  // Auto-mark-read when a thread is opened. Single fire per thread
  // open — useEffect deps include selectedId so reopening the same
  // thread doesn't re-stamp.
  useEffect(() => {
    if (!selectedId) return;
    const t = threadsQuery.data?.threads.find((x) => x.id === selectedId);
    if (t && t.is_unread) {
      markRead.mutate({ threadId: selectedId });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId]);

  const handleSelect = (id: number) => {
    const params = new URLSearchParams(searchParams.toString());
    params.set('thread', String(id));
    router.push(`/social?${params.toString()}`);
  };

  return (
    <div className="flex flex-col h-[calc(100vh-4rem)]">
      <header className="shrink-0 flex items-center justify-between border-b border-border bg-card px-6 py-4">
        <div className="flex items-center gap-3">
          <div className="inline-flex size-9 items-center justify-center rounded-lg bg-pink-100 text-pink-900 dark:bg-pink-950/40 dark:text-pink-100">
            <Inbox className="size-5" />
          </div>
          <div>
            <h1 className="text-lg font-serif font-semibold tracking-tight">
              Social inbox
            </h1>
            <p className="text-xs text-muted-foreground">
              Direct messages from connected social accounts
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setUnreadOnly((v) => !v)}
            className={
              'inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium ring-1 ring-inset transition ' +
              (unreadOnly
                ? 'bg-accent/15 text-accent-foreground ring-accent/30'
                : 'bg-muted text-muted-foreground ring-border hover:bg-muted/80')
            }
          >
            {unreadOnly ? 'Showing unread' : 'All threads'}
          </button>
          <button
            type="button"
            onClick={() => threadsQuery.refetch()}
            className="inline-flex size-8 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground transition"
            aria-label="Refresh"
          >
            <RefreshCw
              className={
                'size-4 ' + (threadsQuery.isFetching ? 'animate-spin' : '')
              }
            />
          </button>
        </div>
      </header>

      <div className="flex-1 flex min-h-0">
        {/* Thread list */}
        <aside className="w-[360px] shrink-0 border-r border-border bg-card overflow-y-auto">
          <ThreadList
            threads={threadsQuery.data?.threads ?? []}
            isLoading={threadsQuery.isLoading}
            selectedId={selectedId}
            onSelect={handleSelect}
            unreadOnly={unreadOnly}
          />
        </aside>

        {/* Detail pane */}
        <main className="flex-1 min-w-0 bg-muted/30 overflow-y-auto">
          {selectedId === null ? (
            <EmptyState />
          ) : threadQuery.isLoading ? (
            <DetailSkeleton />
          ) : threadQuery.data ? (
            <ThreadDetail detail={threadQuery.data} />
          ) : (
            <div className="p-8 text-sm text-muted-foreground">
              Thread not found.
            </div>
          )}
        </main>
      </div>
    </div>
  );
}

function ThreadList({
  threads,
  isLoading,
  selectedId,
  onSelect,
  unreadOnly,
}: {
  threads: SocialThreadSummary[];
  isLoading: boolean;
  selectedId: number | null;
  onSelect: (id: number) => void;
  unreadOnly: boolean;
}) {
  if (isLoading) {
    return (
      <ul className="p-2 space-y-1">
        {[...Array(6)].map((_, i) => (
          <li
            key={i}
            className="h-16 rounded-md bg-muted/50 animate-pulse"
          />
        ))}
      </ul>
    );
  }
  if (threads.length === 0) {
    return (
      <div className="p-6 text-center">
        <Camera className="mx-auto size-8 text-muted-foreground/60 mb-3" />
        <p className="text-sm text-muted-foreground">
          {unreadOnly
            ? 'No unread threads.'
            : 'No conversations yet. When a customer DMs your connected Camera account, the thread shows up here.'}
        </p>
      </div>
    );
  }
  return (
    <ul className="divide-y divide-border">
      {threads.map((t) => (
        <li key={t.id}>
          <button
            type="button"
            onClick={() => onSelect(t.id)}
            className={
              'w-full text-left px-4 py-3 hover:bg-muted/40 transition flex items-start gap-3 ' +
              (selectedId === t.id ? 'bg-accent/10' : '')
            }
          >
            <ProviderBadge provider={t.provider} />
            <div className="flex-1 min-w-0">
              <div className="flex items-center justify-between gap-2">
                <span
                  className={
                    'text-sm truncate ' +
                    (t.is_unread ? 'font-semibold' : 'font-medium')
                  }
                >
                  {displayHandle(t)}
                </span>
                <span className="text-[10px] text-muted-foreground shrink-0">
                  {relativeAgo(t.last_message_at)}
                </span>
              </div>
              <div className="flex items-center gap-1.5 mt-0.5">
                <span className="text-xs text-muted-foreground truncate">
                  {t.customer.is_social_guest
                    ? 'Social guest'
                    : t.customer.full_name}
                </span>
                {t.is_unread && (
                  <span
                    aria-label="Unread"
                    className="size-1.5 rounded-full bg-accent shrink-0"
                  />
                )}
              </div>
            </div>
          </button>
        </li>
      ))}
    </ul>
  );
}

function ProviderBadge({ provider }: { provider: SocialThreadSummary['provider'] }) {
  const Icon = provider === 'instagram' ? Camera : Inbox;
  return (
    <div
      className={
        'inline-flex size-8 shrink-0 items-center justify-center rounded-md ring-1 ring-inset ' +
        PROVIDER_TONE[provider]
      }
      title={PROVIDER_LABEL[provider]}
    >
      <Icon className="size-4" />
    </div>
  );
}

function EmptyState() {
  return (
    <div className="h-full flex items-center justify-center p-8">
      <div className="max-w-sm text-center">
        <Inbox className="mx-auto size-10 text-muted-foreground/50 mb-4" />
        <p className="text-sm text-muted-foreground">
          Select a conversation from the list to view messages.
        </p>
      </div>
    </div>
  );
}

function DetailSkeleton() {
  return (
    <div className="p-8 space-y-3">
      <div className="h-12 rounded-md bg-muted/50 animate-pulse" />
      <div className="h-20 rounded-md bg-muted/50 animate-pulse" />
      <div className="h-20 rounded-md bg-muted/50 animate-pulse" />
    </div>
  );
}

function ThreadDetail({
  detail,
}: {
  detail: { thread: SocialThreadSummary; messages: ReturnType<typeof useSocialThread>['data'] extends infer T ? T extends { messages: infer M } ? M : never : never };
}) {
  const { thread, messages } = detail;

  return (
    <div className="flex flex-col h-full">
      <header className="shrink-0 border-b border-border bg-card px-6 py-4 flex items-center gap-3">
        <ProviderBadge provider={thread.provider} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <h2 className="text-base font-medium truncate">
              {displayHandle(thread)}
            </h2>
            {thread.customer.is_social_guest && (
              <span className="inline-flex items-center rounded-md bg-amber-100 px-1.5 py-0.5 text-[10px] font-medium text-amber-900 ring-1 ring-inset ring-amber-200 dark:bg-amber-950/40 dark:text-amber-100 dark:ring-amber-900">
                Social guest
              </span>
            )}
          </div>
          <p className="text-xs text-muted-foreground">
            {thread.customer.is_social_guest
              ? 'Not yet linked to a client record'
              : (
                <a
                  href={`/clients/${thread.customer.id}`}
                  className="hover:underline"
                >
                  {thread.customer.full_name}
                </a>
              )}
          </p>
        </div>
      </header>

      <div className="flex-1 min-h-0 overflow-y-auto px-6 py-4 space-y-3">
        {messages.length === 0 ? (
          <p className="text-sm text-muted-foreground text-center">
            No messages in this thread yet.
          </p>
        ) : (
          messages.map((m) => <MessageBubble key={m.id} message={m} />)
        )}
      </div>

      {/* Reply box — placeholder in Session 1 */}
      <div className="shrink-0 border-t border-border bg-card px-6 py-4">
        <div className="rounded-md bg-muted/50 border border-dashed border-border p-4 text-sm text-muted-foreground">
          <p className="font-medium text-foreground mb-1">Reply from Lumè</p>
          <p>
            Outbound sending is coming in the next release. For now, reply
            directly from the Camera app. Inbound messages will continue
            to flow into this inbox.
          </p>
          <p className="mt-2 text-xs">
            Reminder: Meta&apos;s platform terms prohibit sending PHI through
            DMs — keep all replies non-clinical.
          </p>
        </div>
      </div>
    </div>
  );
}

function MessageBubble({
  message,
}: {
  message: { id: number; direction: string; body: string; media_urls: string[]; created_at: string };
}) {
  const isOutbound = message.direction === 'outbound';
  return (
    <div className={'flex ' + (isOutbound ? 'justify-end' : 'justify-start')}>
      <div
        className={
          'max-w-[70%] rounded-2xl px-4 py-2.5 ring-1 ring-inset ' +
          (isOutbound
            ? 'bg-accent text-accent-foreground ring-accent/40'
            : 'bg-card text-foreground ring-border')
        }
      >
        {message.body && (
          <p className="text-sm whitespace-pre-wrap break-words">
            {message.body}
          </p>
        )}
        {message.media_urls.length > 0 && (
          <div className="mt-2 space-y-1">
            {message.media_urls.map((url, i) => (
              <a
                key={i}
                href={url}
                target="_blank"
                rel="noreferrer"
                className="block text-xs underline opacity-80 hover:opacity-100"
              >
                Attachment {i + 1}
              </a>
            ))}
          </div>
        )}
        <p
          className={
            'mt-1 text-[10px] ' +
            (isOutbound ? 'text-accent-foreground/70' : 'text-muted-foreground')
          }
        >
          {relativeAgo(message.created_at)}
        </p>
      </div>
    </div>
  );
}
