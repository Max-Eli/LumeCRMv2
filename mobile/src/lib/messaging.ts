/**
 * Customer SMS messaging. Pairs with `apps.messaging`:
 *   - `/api/messaging/threads/`                    inbox (one row / customer)
 *   - `/api/messaging/conversations/<id>/`         full history
 *   - `/api/messaging/conversations/<id>/send/`    operator send
 *
 * The inbox + open conversation poll on an interval so inbound texts
 * appear without a manual refresh.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { useAuth } from './auth';

export type MessageDirection = 'outbound' | 'inbound';

export interface Message {
  id: number;
  direction: MessageDirection;
  body: string;
  status: string;
  sent_by_name: string | null;
  sent_at: string | null;
  created_at: string;
}

export interface ThreadSummary {
  customer_id: number;
  customer_first_name: string;
  customer_last_name: string;
  customer_phone: string;
  last_message_body: string;
  last_message_direction: MessageDirection;
  last_message_at: string;
  unread_inbound_count: number;
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

/** Inbox — one row per customer with messaging activity. */
export function useThreads() {
  const { authedFetch } = useAuth();
  return useQuery({
    queryKey: ['messaging', 'threads'],
    queryFn: () => authedFetch<ThreadSummary[]>('/api/messaging/threads/'),
    refetchInterval: 20000,
  });
}

/** Full conversation history with one customer. */
export function useConversation(customerId: number) {
  const { authedFetch } = useAuth();
  return useQuery({
    queryKey: ['messaging', 'conversation', customerId],
    queryFn: () =>
      authedFetch<ConversationResponse>(
        `/api/messaging/conversations/${customerId}/`,
      ),
    enabled: Number.isFinite(customerId) && customerId > 0,
    refetchInterval: 15000,
  });
}

/** Send an operator SMS to a customer. */
export function useSendMessage(customerId: number) {
  const { authedFetch } = useAuth();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: string) =>
      authedFetch<Message>(
        `/api/messaging/conversations/${customerId}/send/`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ body }),
        },
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['messaging', 'conversation', customerId],
      });
      queryClient.invalidateQueries({ queryKey: ['messaging', 'threads'] });
    },
  });
}

/** Clear the unread badge on a thread. */
export function useMarkThreadRead(customerId: number) {
  const { authedFetch } = useAuth();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () =>
      authedFetch<{ rows_updated: number }>(
        `/api/messaging/conversations/${customerId}/mark-read/`,
        { method: 'POST' },
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['messaging', 'threads'] });
    },
  });
}
