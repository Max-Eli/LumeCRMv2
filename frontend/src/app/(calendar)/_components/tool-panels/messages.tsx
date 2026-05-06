'use client';

import { MessageSquare } from 'lucide-react';

import { PlaceholderPanel } from './_placeholder';

export function MessagesPanel({ phase }: { phase?: string }) {
  return (
    <PlaceholderPanel
      icon={MessageSquare}
      title="Unified inbox"
      summary="One thread per client, merging every channel they message you on. Reply from here without leaving the calendar."
      bullets={[
        'Two-way SMS via Twilio (Phase 3A)',
        'Instagram + Facebook DMs via Meta Graph API (Phase 3B)',
        'WhatsApp Business inbound via Twilio (Phase 3B)',
        'Templated quick replies and unread badges',
      ]}
      phase={phase ?? 'Phase 3A · Two-way SMS'}
    />
  );
}
