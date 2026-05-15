/**
 * Customer messaging inbox — full-page view inside the dashboard shell.
 *
 * Thin wrapper around `<InboxView />` (which contains the actual
 * thread-list + conversation + compose + new-conversation picker). The
 * same component backs the standalone popout window at `/inbox` —
 * see `(popout)/inbox/page.tsx`. Keeping the UI in one place means we
 * don't fork features between the two surfaces.
 */

'use client';

import { PageHeader } from '@/components/page-header';

import { InboxView } from './_inbox-view';

export default function MessagesPage() {
  return (
    <div className="flex flex-col h-[calc(100vh-0px)] px-10 py-8 gap-4">
      <PageHeader
        title="Messages"
        description="Two-way SMS and MMS with your clients. Social DMs (Instagram, Facebook, WhatsApp) live under the Social tile in the calendar tool rail when those integrations land."
      />
      <InboxView basePath="/messages" />
    </div>
  );
}
