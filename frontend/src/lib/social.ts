/**
 * Social inbox hooks (ADR 0027 §6 — backs the /social page).
 *
 * Surfaces inbound messages from connected social providers (Instagram
 * Business DMs in Session 1; Facebook Messenger + WhatsApp later).
 * Distinct from `apps.messaging` (SMS/MMS) because:
 *   - Different identifier shape (PSIDs vs E.164 phones)
 *   - Different opt-out semantics (block vs STOP)
 *   - Meta forbids PHI in DMs (we surface a non-PHI banner in the
 *     reply box once Session 2 lands)
 *
 * The thread list is intentionally lightweight — message bodies are
 * NOT carried in the summary payload. Bodies live on the detail
 * endpoint where access is audit-logged.
 */

'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from './api';

export type SocialProvider = 'instagram' | 'facebook' | 'whatsapp';

export type SocialDirection = 'outbound' | 'inbound';

export type SocialMessageStatus =
  | 'received'
  | 'queued'
  | 'sent'
  | 'delivered'
  | 'read'
  | 'failed';

export interface SocialThreadCustomer {
  id: number;
  full_name: string;
  is_social_guest: boolean;
  instagram_handle: string;
  acquisition_source: string;
}

export interface SocialThreadSummary {
  id: number;
  provider: SocialProvider;
  external_username: string;
  /** IG real name (e.g. "Maria Lopez"). Empty until the Graph profile
   *  fetch succeeds; UI falls back to the customer's full_name. */
  external_display_name: string;
  /** Meta-hosted signed CDN URL. EPHEMERAL — Meta rotates signing
   *  keys every ~few weeks, after which the URL 403s. The avatar
   *  component falls back to initials when this is empty or fails. */
  external_profile_pic_url: string;
  last_message_at: string;
  last_inbound_at: string | null;
  read_at: string | null;
  is_unread: boolean;
  customer: SocialThreadCustomer;
}

export interface SocialMessage {
  id: number;
  direction: SocialDirection;
  body: string;
  media_urls: string[];
  status: SocialMessageStatus;
  sent_by_id: number | null;
  /** True when the Instagram AI agent authored this reply. Drives the
   *  violet "AI" bubble so staff can tell AI replies from staff ones. */
  generated_by_ai: boolean;
  ai_conversation_id: number | null;
  received_at: string | null;
  created_at: string;
}

export interface SocialThreadDetail {
  thread: SocialThreadSummary;
  messages: SocialMessage[];
}

const THREADS_KEY = (filter: ThreadFilter) => ['social-threads', filter] as const;
const THREAD_KEY = (id: number) => ['social-thread', id] as const;

export interface ThreadFilter {
  unreadOnly?: boolean;
  provider?: SocialProvider;
}

export function useSocialThreads(filter: ThreadFilter = {}) {
  return useQuery<{ count: number; threads: SocialThreadSummary[] }>({
    queryKey: THREADS_KEY(filter),
    queryFn: () => {
      const params = new URLSearchParams();
      if (filter.unreadOnly) params.set('unread', '1');
      if (filter.provider) params.set('provider', filter.provider);
      const qs = params.toString();
      return api.get(`/api/social/threads/${qs ? `?${qs}` : ''}`);
    },
    // 20s — recent enough that a fresh inbound shows up quickly when
    // the operator switches back to this tab, but not so aggressive
    // that we hammer the backend during active triage.
    staleTime: 20 * 1000,
    refetchOnWindowFocus: true,
  });
}

export function useSocialThread(id: number | null) {
  return useQuery<SocialThreadDetail>({
    queryKey: THREAD_KEY(id ?? -1),
    queryFn: () => api.get(`/api/social/threads/${id}/`),
    enabled: id !== null && id > 0,
    staleTime: 15 * 1000,
    refetchOnWindowFocus: true,
  });
}

export function useMarkThreadRead() {
  const qc = useQueryClient();
  return useMutation<{ read_at: string }, Error, { threadId: number }>({
    mutationFn: ({ threadId }) =>
      api.post(`/api/social/threads/${threadId}/mark-read/`, {}),
    onSuccess: () => {
      // Invalidate every thread-list variant so unread counts refresh
      // regardless of the active filter.
      qc.invalidateQueries({ queryKey: ['social-threads'] });
    },
  });
}

/** Send an outbound DM reply in a thread.
 *
 *  ADR 0027 §7 — Meta restricts outbound DMs to 24 hours after the
 *  last inbound message. The backend enforces this and surfaces a
 *  `reply_window_expired` error code so the UI can render the right
 *  inline message.
 */
export function useReplyToThread() {
  const qc = useQueryClient();
  return useMutation<SocialMessage, Error, { threadId: number; body: string }>({
    mutationFn: ({ threadId, body }) =>
      api.post(`/api/social/threads/${threadId}/reply/`, { body }),
    onSuccess: (_msg, vars) => {
      // Detail query: reload the full thread so the new outbound
      // message appears with the server-assigned ID + status.
      qc.invalidateQueries({ queryKey: THREAD_KEY(vars.threadId) });
      // Inbox list: bump last_message_at + clear unread since
      // replying implies the operator read the thread.
      qc.invalidateQueries({ queryKey: ['social-threads'] });
    },
  });
}

/** The 24h reply-window restriction was removed (ADR 0033) — Meta
 *  governs send eligibility and tools like ManyChat reply beyond 24h.
 *  Kept as an always-true function so existing callers don't break. */
export function canReply(_thread: SocialThreadSummary): boolean {
  return true;
}

// ── Display helpers ─────────────────────────────────────────────────

export const PROVIDER_LABEL: Record<SocialProvider, string> = {
  instagram: 'Instagram',
  facebook: 'Facebook',
  whatsapp: 'WhatsApp',
};

/** Compact tone string per provider (matches Tailwind v4 colour palette). */
export const PROVIDER_TONE: Record<SocialProvider, string> = {
  instagram: 'bg-pink-100 text-pink-900 ring-pink-200 dark:bg-pink-950/40 dark:text-pink-100',
  facebook: 'bg-blue-100 text-blue-900 ring-blue-200 dark:bg-blue-950/40 dark:text-blue-100',
  whatsapp: 'bg-emerald-100 text-emerald-900 ring-emerald-200 dark:bg-emerald-950/40 dark:text-emerald-100',
};

/** Friendly @handle with the `@` prefix re-added for display. */
export function displayHandle(thread: SocialThreadSummary): string {
  const raw = thread.external_username || thread.customer.instagram_handle || '';
  if (!raw) return thread.customer.full_name;
  return raw.startsWith('@') ? raw : `@${raw}`;
}

/** Prefer the IG-fetched display name, then the customer name, then the handle.
 *  This is what shows as the primary heading on inbox rows + thread headers. */
export function displayName(thread: SocialThreadSummary): string {
  if (thread.external_display_name) return thread.external_display_name;
  if (thread.customer.full_name && thread.customer.full_name.trim()) {
    return thread.customer.full_name;
  }
  return displayHandle(thread);
}

/** Initials for the avatar fallback when there's no profile pic. */
export function avatarInitials(thread: SocialThreadSummary): string {
  const name = displayName(thread);
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return '?';
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

/** "5 min ago" / "2 days ago" — terse relative time for inbox rows. */
export function relativeAgo(iso: string): string {
  const ts = new Date(iso).getTime();
  const seconds = Math.floor((Date.now() - ts) / 1000);
  if (seconds < 60) return 'just now';
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days}d ago`;
  return new Date(iso).toLocaleDateString();
}
