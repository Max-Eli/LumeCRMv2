/**
 * Status pill for a marketing campaign — used by both the list view
 * and the detail page. Lives in `_components/` (an underscored
 * directory is excluded from Next's route discovery) so two pages
 * can share it without one importing the other's `page.tsx`.
 *
 * Tone semantics:
 *   - `pending`  — drafts, not yet scheduled
 *   - `progress` — scheduled but not started
 *   - `active`   — currently sending (animated dot for "live" feel)
 *   - `success`  — fully sent (static dot, calm green)
 *   - `terminal` — cancelled / final state
 */

'use client';

import type { CampaignStatus } from '@/lib/marketing';
import { cn } from '@/lib/utils';

const STATUS_LABELS: Record<CampaignStatus, string> = {
  draft: 'Draft',
  scheduled: 'Scheduled',
  sending: 'Sending',
  sent: 'Sent',
  cancelled: 'Cancelled',
};

const STATUS_TONE: Record<
  CampaignStatus,
  'pending' | 'progress' | 'active' | 'success' | 'terminal'
> = {
  draft: 'pending',
  scheduled: 'progress',
  sending: 'active',
  sent: 'success',
  cancelled: 'terminal',
};

export function CampaignStatusPill({ status }: { status: CampaignStatus }) {
  const tone = STATUS_TONE[status];
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider',
        tone === 'pending' && 'bg-stone-100 text-stone-700',
        tone === 'progress' && 'bg-blue-50 text-blue-800',
        tone === 'active' && 'bg-amber-50 text-amber-800',
        tone === 'success' && 'bg-emerald-50 text-emerald-700',
        tone === 'terminal' && 'bg-stone-100 text-stone-600',
      )}
    >
      {tone === 'active' ? (
        <span className="size-1.5 rounded-full bg-amber-500 animate-pulse" />
      ) : tone === 'success' ? (
        <span className="size-1.5 rounded-full bg-emerald-500" />
      ) : null}
      {STATUS_LABELS[status]}
    </span>
  );
}
