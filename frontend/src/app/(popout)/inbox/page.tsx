/**
 * `/inbox` — standalone popout window for the messaging inbox.
 *
 * Spawned by the calendar right-rail Messages tile via
 * `window.open('/inbox', 'lume-inbox', 'popup,width=…')`. The named
 * window means clicking the tile again from another calendar view
 * focuses the existing window rather than opening a second copy.
 *
 * Reuses `<InboxView basePath="/inbox" />` so this surface stays in
 * lock-step with the dashboard `/messages` page.
 */

'use client';

import { MessageSquare } from 'lucide-react';

import { InboxView } from '../../(app)/messages/_inbox-view';

export default function InboxPopoutPage() {
  return (
    <div className="flex flex-col h-screen bg-muted/40">
      <header className="shrink-0 border-b bg-card px-5 py-3 flex items-center gap-2.5">
        <div className="inline-flex size-7 items-center justify-center rounded-md bg-accent/15 text-accent-foreground">
          <MessageSquare className="size-4" />
        </div>
        <div className="leading-tight">
          <h1 className="text-sm font-serif font-semibold tracking-tight">Messages</h1>
          <p className="text-[10px] uppercase tracking-wide text-muted-foreground">
            Customer inbox · SMS &amp; MMS
          </p>
        </div>
      </header>
      <div className="flex-1 min-h-0 p-3 flex flex-col">
        <InboxView basePath="/inbox" />
      </div>
    </div>
  );
}
