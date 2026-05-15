'use client';

import { ArrowUpRight, MessageSquare } from 'lucide-react';
import Link from 'next/link';

import { Button } from '@/components/ui/button';
import { useThreads } from '@/lib/messaging';

/**
 * Calendar right-rail Messages preview.
 *
 * Lightweight snapshot of the SMS/MMS inbox — top few threads with
 * unread counts so the front-desk can triage from the calendar
 * without leaving the page. The "Open inbox" button deep-links to
 * `/messages` for the full conversation view (compose + history).
 */
export function MessagesPanel() {
  const { data: threads, isLoading } = useThreads();
  const totalUnread = (threads ?? []).reduce(
    (sum, t) => sum + (t.unread_inbound_count ?? 0),
    0,
  );
  const top = (threads ?? []).slice(0, 5);

  return (
    <div className="flex flex-col h-full">
      <div className="px-4 pt-3 pb-2 border-b">
        <p className="text-xs text-muted-foreground">
          SMS & MMS with your clients.{' '}
          {totalUnread > 0 ? (
            <span className="text-foreground font-medium">{totalUnread} unread</span>
          ) : null}
        </p>
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto">
        {isLoading ? (
          <p className="px-4 py-6 text-xs text-muted-foreground">Loading…</p>
        ) : top.length === 0 ? (
          <div className="px-4 py-8 text-center">
            <MessageSquare className="size-6 mx-auto mb-2 text-muted-foreground" />
            <p className="text-xs text-muted-foreground">
              No conversations yet. Inbound texts to your toll-free number show up here.
            </p>
          </div>
        ) : (
          <ul className="divide-y">
            {top.map((t) => (
              <li key={t.customer_id}>
                <Link
                  href={`/messages?c=${t.customer_id}`}
                  className="block px-4 py-2.5 hover:bg-muted transition-colors"
                >
                  <div className="flex items-baseline justify-between gap-2">
                    <span className="text-sm font-medium truncate">
                      {t.customer_first_name} {t.customer_last_name}
                    </span>
                    {t.unread_inbound_count > 0 ? (
                      <span className="text-[10px] uppercase tracking-wide px-1.5 py-px rounded bg-accent text-accent-foreground">
                        {t.unread_inbound_count}
                      </span>
                    ) : null}
                  </div>
                  <p className="text-xs text-muted-foreground truncate">
                    {t.last_message_direction === 'outbound' ? 'You: ' : ''}
                    {t.last_message_body || '—'}
                  </p>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="border-t px-3 py-2.5">
        <Button
          render={<Link href="/messages" />}
          nativeButton={false}
          variant="outline"
          size="sm"
          className="w-full"
        >
          Open inbox
          <ArrowUpRight className="size-3.5" />
        </Button>
      </div>
    </div>
  );
}
