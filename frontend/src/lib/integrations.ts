/**
 * External integration hooks (Phase: Messaging integrations · Session 1).
 *
 * Lists every known provider plus this tenant's connection state for
 * each. The list endpoint is the single source of truth — provider
 * metadata (display name, what-it-enables copy, OAuth scopes) lives
 * server-side so we don't drift between layers.
 *
 * v1 ships with all `oauth_ready: false` because Meta App approval
 * hasn't landed. Connect buttons currently fire a `oauth_not_ready`
 * 501 from the backend; the page handles that with a friendly toast.
 */

'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, ApiError } from './api';

export type IntegrationProviderKey =
  | 'meta_facebook'
  | 'meta_instagram'
  | 'meta_whatsapp';

export type IntegrationStatus =
  | 'disconnected'
  | 'connecting'
  | 'connected'
  | 'error';

export interface IntegrationProviderEntry {
  key: IntegrationProviderKey;
  display_name: string;
  family: 'meta';
  short_description: string;
  enables: string[];
  oauth_ready: boolean;
  // Connection state (null when no connection exists yet)
  connection_id: number | null;
  status: IntegrationStatus;
  external_id: string | null;
  external_name: string | null;
  last_synced_at: string | null;
  last_error_message: string | null;
  connected_at: string | null;
}

const INTEGRATIONS_KEY = ['integrations'] as const;

export function useIntegrations() {
  return useQuery<IntegrationProviderEntry[]>({
    queryKey: INTEGRATIONS_KEY,
    queryFn: () => api.get<IntegrationProviderEntry[]>('/api/integrations/'),
    staleTime: 30 * 1000,
  });
}

/** Begin the OAuth flow for a provider. When ready, returns
 *  `{ authorize_url }` and the page redirects to it. When the
 *  backend has no credentials yet, returns 501 with
 *  `code='oauth_not_ready'` for the page to render the "awaiting
 *  setup" toast. */
export interface ConnectBeginResponse {
  authorize_url?: string;
  state?: string;
  connection_id?: number;
  // Legacy `url` kept for backward compatibility with future providers
  // that might return that shape; redirect logic prefers authorize_url.
  url?: string;
}

export function useConnectIntegration() {
  return useMutation<ConnectBeginResponse, ApiError, { provider: IntegrationProviderKey }>({
    mutationFn: ({ provider }) =>
      api.post(`/api/integrations/${provider}/connect/begin/`, {}),
  });
}

/** Disconnect a provider. Idempotent — already-disconnected returns 200. */
export function useDisconnectIntegration() {
  const qc = useQueryClient();
  return useMutation<IntegrationProviderEntry[], Error, { connectionId: number }>({
    mutationFn: ({ connectionId }) =>
      api.post<IntegrationProviderEntry[]>(
        `/api/integrations/${connectionId}/disconnect/`,
        {},
      ),
    onSuccess: (data) => {
      qc.setQueryData(INTEGRATIONS_KEY, data);
    },
  });
}

// ── Display helpers ─────────────────────────────────────────────────

export const STATUS_LABELS: Record<IntegrationStatus, string> = {
  disconnected: 'Not connected',
  connecting: 'Connecting…',
  connected: 'Connected',
  error: 'Reconnect needed',
};

export const STATUS_TONE: Record<IntegrationStatus, string> = {
  disconnected: 'bg-muted text-muted-foreground ring-border',
  connecting: 'bg-amber-100 text-amber-900 ring-amber-200 dark:bg-amber-950 dark:text-amber-100',
  connected: 'bg-emerald-100 text-emerald-900 ring-emerald-200 dark:bg-emerald-950 dark:text-emerald-100',
  error: 'bg-rose-100 text-rose-900 ring-rose-200 dark:bg-rose-950 dark:text-rose-100',
};

/** Map a provider key to its monochrome glyph used in the card header. */
export const PROVIDER_GLYPH: Record<IntegrationProviderKey, string> = {
  meta_facebook: 'f',
  meta_instagram: '◐',
  meta_whatsapp: '◗',
};
