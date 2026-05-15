/**
 * Customer-messaging data hooks.
 *
 * Pairs with Django `apps.messaging` at `/api/messaging/…`. The inbox
 * surface is read-heavy: thread list + one-thread detail polling for
 * new inbound messages. Send and mark-read are the only mutations.
 *
 * Polling cadence is conservative (15s) — Twilio inbound webhooks
 * arrive within a second of the carrier delivering the SMS, but our
 * own UI doesn't yet open a websocket. Front-desk staff don't expect
 * sub-second freshness; a 15-second tick is invisible-feeling. We'll
 * swap to SSE / websockets when we add live-typing or DM channels.
 */

'use client';

import {
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query';

import { api } from './api';

// ── Shapes ──────────────────────────────────────────────────────────


export type MessageDirection = 'outbound' | 'inbound';

export type MessageStatus =
  | 'queued'
  | 'sent'
  | 'delivered'
  | 'failed'
  | 'received';

export type MessageKind =
  | 'manual'
  | 'confirmation'
  | 'reminder'
  | 'review_request';

export interface ThreadSummary {
  customer_id: number;
  customer_first_name: string;
  customer_last_name: string;
  customer_phone: string;
  last_message_id: number;
  last_message_body: string;
  last_message_direction: MessageDirection;
  last_message_at: string;
  unread_inbound_count: number;
}

export interface Message {
  id: number;
  direction: MessageDirection;
  kind: MessageKind;
  body: string;
  status: MessageStatus;
  provider_message_id: string;
  from_number: string;
  to_number: string;
  media_urls: string[];
  sent_by_email: string | null;
  sent_by_name: string | null;
  read_at: string | null;
  failure_reason: string;
  sent_at: string | null;
  delivered_at: string | null;
  failed_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface ConversationResponse {
  customer: {
    id: number;
    first_name: string;
    last_name: string;
    phone: string;
    sms_opt_in: boolean;
  };
  messages: Message[];
}

// ── Query keys ──────────────────────────────────────────────────────


const THREADS_KEY = ['messaging', 'threads'] as const;
function conversationKey(customerId: number) {
  return ['messaging', 'conversation', customerId] as const;
}

// ── Hooks ───────────────────────────────────────────────────────────


/**
 * Inbox list. One row per customer with messaging activity. Polls
 * every 15s while the page is focused so unread counts stay fresh
 * without a websocket layer.
 */
export function useThreads() {
  return useQuery<ThreadSummary[]>({
    queryKey: THREADS_KEY,
    queryFn: () => api.get<ThreadSummary[]>('/api/messaging/threads/'),
    refetchInterval: 15_000,
    refetchOnWindowFocus: true,
  });
}

/**
 * Full thread for a single customer (chronological). Disabled when
 * no customer is selected.
 */
export function useConversation(customerId: number | undefined) {
  return useQuery<ConversationResponse>({
    queryKey: customerId ? conversationKey(customerId) : ['messaging', 'conversation', 'disabled'],
    queryFn: () =>
      api.get<ConversationResponse>(
        `/api/messaging/conversations/${customerId}/`,
      ),
    enabled: typeof customerId === 'number' && customerId > 0,
    refetchInterval: 15_000,
    refetchOnWindowFocus: true,
  });
}

/**
 * Send an outbound SMS to a customer. On success, both the thread
 * list (unread/preview) and the active conversation are invalidated
 * so the optimistic row from the response is reconciled with the
 * post-write state.
 */
export function useSendMessage(customerId: number) {
  const qc = useQueryClient();
  return useMutation<Message, Error, { body: string }>({
    mutationFn: ({ body }) =>
      api.post<Message>(
        `/api/messaging/conversations/${customerId}/send/`,
        { body },
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: THREADS_KEY });
      qc.invalidateQueries({ queryKey: conversationKey(customerId) });
    },
  });
}

/**
 * Mark every unread inbound message in this thread as read. Fires
 * automatically when the operator opens the thread; the backend
 * stamps `read_at = now`.
 */
export function useMarkThreadRead(customerId: number) {
  const qc = useQueryClient();
  return useMutation<{ rows_updated: number }, Error, void>({
    mutationFn: () =>
      api.post<{ rows_updated: number }>(
        `/api/messaging/conversations/${customerId}/mark-read/`,
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: THREADS_KEY });
    },
  });
}

// ── Saved replies (canned templates) ───────────────────────────────


export interface SavedReply {
  id: number;
  name: string;
  body: string;
  created_by_email: string | null;
  created_at: string;
  updated_at: string;
}

export interface SavedReplyInput {
  name: string;
  body: string;
}

const SAVED_REPLIES_KEY = ['messaging', 'saved-replies'] as const;

/** All saved replies for the active tenant, alphabetised. Used by
 *  the composer's quick-reply popover + the manage-replies dialog. */
export function useSavedReplies() {
  return useQuery<SavedReply[]>({
    queryKey: SAVED_REPLIES_KEY,
    queryFn: () => api.get<SavedReply[]>('/api/messaging/saved-replies/'),
    refetchOnWindowFocus: false,
  });
}

export function useCreateSavedReply() {
  const qc = useQueryClient();
  return useMutation<SavedReply, Error, SavedReplyInput>({
    mutationFn: (input) =>
      api.post<SavedReply>('/api/messaging/saved-replies/', input),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: SAVED_REPLIES_KEY });
    },
  });
}

export function useUpdateSavedReply(id: number) {
  const qc = useQueryClient();
  return useMutation<SavedReply, Error, Partial<SavedReplyInput>>({
    mutationFn: (input) =>
      api.patch<SavedReply>(`/api/messaging/saved-replies/${id}/`, input),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: SAVED_REPLIES_KEY });
    },
  });
}

export function useDeleteSavedReply() {
  const qc = useQueryClient();
  return useMutation<void, Error, number>({
    mutationFn: (id) =>
      api.delete<void>(`/api/messaging/saved-replies/${id}/`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: SAVED_REPLIES_KEY });
    },
  });
}

// ── Automated SMS templates ─────────────────────────────────────────


export interface AutomatedTemplates {
  confirmation_sms_template: string;
  reminder_sms_template: string;
  review_request_sms_template: string;
  review_request_enabled: boolean;
  review_request_hours_after: number;
  google_review_url: string;
  default_confirmation_body: string;
  default_reminder_body: string;
  default_review_request_body: string;
}

export type AutomatedTemplatesInput = Partial<
  Omit<
    AutomatedTemplates,
    'default_confirmation_body' | 'default_reminder_body' | 'default_review_request_body'
  >
>;

const AUTOMATED_TEMPLATES_KEY = ['messaging', 'automated-templates'] as const;

export function useAutomatedTemplates() {
  return useQuery<AutomatedTemplates>({
    queryKey: AUTOMATED_TEMPLATES_KEY,
    queryFn: () =>
      api.get<AutomatedTemplates>('/api/messaging/automated-templates/'),
    refetchOnWindowFocus: false,
  });
}

export function useUpdateAutomatedTemplates() {
  const qc = useQueryClient();
  return useMutation<AutomatedTemplates, Error, AutomatedTemplatesInput>({
    mutationFn: (input) =>
      api.patch<AutomatedTemplates>('/api/messaging/automated-templates/', input),
    onSuccess: (fresh) => {
      qc.setQueryData(AUTOMATED_TEMPLATES_KEY, fresh);
    },
  });
}
