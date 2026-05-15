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
    <div className="flex flex-col h-screen bg-background">
      <header className="shrink-0 border-b bg-card px-4 py-2.5 flex items-center gap-2">
        <MessageSquare className="size-4 text-muted-foreground" />
        <h1 className="text-sm font-semibold tracking-tight">Messages</h1>
      </header>
      <div className="flex-1 min-h-0 p-3">
        <InboxView basePath="/inbox" />
      </div>
    </div>
  );
}
