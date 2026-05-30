/**
 * LifecycleBanner — single thin strip at the top of the CRM shell
 * that surfaces the tenant's subscription lifecycle state.
 *
 * Four states (most → least common):
 *
 *   - active                   → renders nothing (no chrome added)
 *   - trial                    → amber strip with countdown + Manage billing link
 *   - past_due                 → orange strip; payment failed, billing link is prominent
 *   - suspended                → red strip; full app effectively locked elsewhere
 *
 * Cancelled tenants get force-logged-out by middleware, so we don't
 * render a banner for them — they never see this layout.
 *
 * Owner-only links (Manage billing). The banner itself is visible to
 * everyone so they understand workspace state, but only owners can
 * actually act on it. The /org/billing page enforces the permission
 * gate; we just don't render the link for non-owners.
 *
 * Grandfathered tenants are exempt — banner doesn't render for them
 * regardless of nominal status (they never see the trial/past-due
 * workflow; their billing is manual + this UI would be confusing).
 */

'use client';

import { AlertTriangle, CreditCard, Info, XCircle } from 'lucide-react';
import Link from 'next/link';
import { useMemo } from 'react';

import { useCurrentMembership } from '@/lib/auth';
import { cn } from '@/lib/utils';

export function LifecycleBanner() {
  const membership = useCurrentMembership();

  // Compute everything memoized so re-renders from auth refresh don't
  // re-do the date math. Cheap, but the pattern stays consistent with
  // every other tenant-facing widget.
  const view = useMemo(() => buildBannerView(membership), [membership]);

  if (!view) return null;

  const Icon = view.icon;
  const isOwner = membership?.role === 'owner';

  return (
    <div
      className={cn(
        // Thin strip; sticky so scrolling pages keep it visible. z-30
        // sits below dialogs/popovers but above page chrome.
        'sticky top-0 z-30 w-full border-b text-sm',
        view.tone.container,
      )}
      role="status"
      aria-live="polite"
    >
      <div className="mx-auto max-w-screen-2xl px-4 sm:px-6 lg:px-8 py-2 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2.5 min-w-0">
          <Icon className={cn('size-4 shrink-0', view.tone.icon)} aria-hidden />
          <p className="truncate">
            <span className={cn('font-medium', view.tone.headline)}>
              {view.headline}
            </span>
            {view.detail ? (
              <span className={cn('ml-1.5', view.tone.detail)}>{view.detail}</span>
            ) : null}
          </p>
        </div>
        {isOwner ? (
          <Link
            href="/org/billing"
            className={cn(
              'inline-flex items-center gap-1.5 h-7 px-2.5 rounded text-xs font-medium uppercase tracking-wide transition-colors shrink-0',
              view.tone.action,
            )}
          >
            <CreditCard className="size-3.5" />
            {view.actionLabel}
          </Link>
        ) : null}
      </div>
    </div>
  );
}

// ── View resolution ──────────────────────────────────────────────

interface BannerView {
  icon: typeof Info;
  headline: string;
  detail?: string;
  actionLabel: string;
  tone: {
    container: string;
    icon: string;
    headline: string;
    detail: string;
    action: string;
  };
}

const TONE_TRIAL = {
  container: 'border-amber-500/30 bg-amber-50/70 dark:bg-amber-950/30',
  icon: 'text-amber-600 dark:text-amber-400',
  headline: 'text-amber-900 dark:text-amber-100',
  detail: 'text-amber-800/85 dark:text-amber-200/80',
  action: 'bg-amber-600 text-white hover:bg-amber-600/90',
};

const TONE_PAST_DUE = {
  container: 'border-orange-500/40 bg-orange-50/80 dark:bg-orange-950/40',
  icon: 'text-orange-600 dark:text-orange-400',
  headline: 'text-orange-900 dark:text-orange-100',
  detail: 'text-orange-800/85 dark:text-orange-200/80',
  action: 'bg-orange-600 text-white hover:bg-orange-600/90',
};

const TONE_SUSPENDED = {
  container: 'border-rose-500/40 bg-rose-50/80 dark:bg-rose-950/40',
  icon: 'text-rose-600 dark:text-rose-400',
  headline: 'text-rose-900 dark:text-rose-100',
  detail: 'text-rose-800/85 dark:text-rose-200/80',
  action: 'bg-rose-600 text-white hover:bg-rose-600/90',
};

function buildBannerView(
  membership: ReturnType<typeof useCurrentMembership>,
): BannerView | null {
  if (!membership) return null;
  const tenant = membership.tenant;
  // Grandfathered = exempt from all lifecycle UI; their billing is
  // manual + this banner would just confuse them.
  if (tenant.grandfathered) return null;

  switch (tenant.status) {
    case 'trial': {
      const daysLeft = daysUntil(tenant.trial_ends_at);
      if (daysLeft === null) {
        // Trial status without an end date — odd state; render a
        // generic banner rather than blank.
        return {
          icon: Info,
          headline: 'Free trial active.',
          actionLabel: 'Manage billing',
          tone: TONE_TRIAL,
        };
      }
      if (daysLeft <= 0) {
        return {
          icon: AlertTriangle,
          headline: 'Trial ends today.',
          // "Today" is a 24-hour window from the actual trial_ends_at
          // timestamp, not literal midnight. Stripe charges at the
          // exact end-of-trial timestamp; we phrase this softly so
          // we're not pinning the operator to a clock time we don't
          // own.
          detail: 'Your card will be charged when the trial period ends. Cancel anytime before then.',
          actionLabel: 'Manage billing',
          tone: TONE_TRIAL,
        };
      }
      const dayWord = daysLeft === 1 ? 'day' : 'days';
      return {
        icon: Info,
        headline: `${daysLeft} ${dayWord} left in your free trial.`,
        detail: daysLeft <= 7
          ? 'Your card will be charged when the trial ends.'
          : 'Try every Pro feature during the trial — your card isn’t charged until day 31.',
        actionLabel: 'Manage billing',
        tone: TONE_TRIAL,
      };
    }
    case 'past_due':
      return {
        icon: AlertTriangle,
        headline: 'Payment failed.',
        detail:
          'Your last charge couldn’t be processed. Update your payment method to keep your workspace active.',
        actionLabel: 'Update payment',
        tone: TONE_PAST_DUE,
      };
    case 'suspended':
      return {
        icon: XCircle,
        headline: 'Workspace suspended.',
        detail:
          'Read-only access until billing is restored. Update payment to reactivate.',
        actionLabel: 'Reactivate',
        tone: TONE_SUSPENDED,
      };
    case 'active':
    case 'cancelled':
    default:
      return null;
  }
}

// ── Helpers ──────────────────────────────────────────────────────

/** Whole days from now until ``iso``. Negative when the date has
 *  passed. Null when input is null/invalid. Rounds with ceil so the
 *  banner reads "1 day left" until the very last hour (less
 *  surprising than flipping to "0 days" most of the final day). */
function daysUntil(iso: string | null): number | null {
  if (!iso) return null;
  const target = new Date(iso).getTime();
  if (Number.isNaN(target)) return null;
  const ms = target - Date.now();
  if (ms <= 0) return 0;
  return Math.ceil(ms / (24 * 60 * 60 * 1000));
}
