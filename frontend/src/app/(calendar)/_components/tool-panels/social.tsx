'use client';

import { AtSign } from 'lucide-react';

import { PlaceholderPanel } from './_placeholder';

export function SocialPanel({ phase }: { phase?: string }) {
  return (
    <PlaceholderPanel
      icon={AtSign}
      title="Social DM inbox"
      summary="Customer DMs from Instagram, Facebook, and WhatsApp will land here alongside your SMS threads — one place to reply, no app-switching."
      bullets={[
        'Instagram Business DMs via Meta Graph API',
        'Facebook Page Messenger',
        'WhatsApp Business inbound + templated replies',
        'Per-tenant OAuth — each spa connects their own accounts',
      ]}
      phase={phase ?? 'Phase 3F · Social channels'}
    />
  );
}
