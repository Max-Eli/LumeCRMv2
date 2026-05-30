/**
 * Client-side hooks + types for the AI inbox app.
 *
 * The AI agent operates BEHIND the existing messaging inbox UI —
 * every AI message is still a `Message` row, tagged with
 * `generated_by_ai=true`. This module supplies the orthogonal
 * surface: per-conversation status + operator controls (pause /
 * resume), the tenant-level AIConfig, and escalation alerts.
 *
 * All endpoints are gated by `PlanFeatureRequired(F_AI_INBOX)` on
 * the server. Pro + Enterprise tenants (and grandfathered legacy
 * tenants) have access; Starter tenants get a 402 on hit.
 *
 * See backend/apps/ai_inbox/README.md for the HIPAA + safety
 * framing this UI plugs into.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api';

// ── Types ───────────────────────────────────────────────────────────


export type AIConversationStatus =
  | 'active'
  | 'paused'
  | 'escalated'
  | 'closed';

export interface AIConversationStatusResponse {
  id: number;
  customer_id: number;
  status: AIConversationStatus;
  paused_at: string | null;
  paused_by_email: string | null;
  escalated_at: string | null;
  escalation_reason: string;
  last_ai_at: string | null;
  last_inbound_at: string | null;
  message_count: number;
  exchange_count: number;
  pending_proposal_expires_at: string | null;
  updated_at: string;
}

export interface AIConfig {
  enabled: boolean;
  test_mode: boolean;
  test_mode_number: string;
  persona: string;
  business_hours_json: Record<string, unknown>;
  booking_lead_minutes: number;
  propose_slot_count: number;
  daily_send_cap: number;
  monthly_exchange_cap: number;
  escalation_keywords: string[];
  platform_disabled_at: string | null;
  platform_disabled_reason: string;
  created_at: string;
  updated_at: string;
}

export type AIConfigInput = Partial<
  Pick<
    AIConfig,
    | 'enabled'
    | 'test_mode'
    | 'test_mode_number'
    | 'persona'
    | 'business_hours_json'
    | 'booking_lead_minutes'
    | 'propose_slot_count'
    | 'daily_send_cap'
    | 'monthly_exchange_cap'
    | 'escalation_keywords'
  >
>;

export interface EscalationAlert {
  id: number;
  customer_id: number;
  customer_first_name: string;
  customer_last_name: string;
  customer_phone: string;
  reason: string;
  reason_detail: string;
  acknowledged_at: string | null;
  acknowledged_by_email: string | null;
  resolved_at: string | null;
  created_at: string;
}

// ── Query keys ──────────────────────────────────────────────────────


const STATUS_KEY = (customerId: number) =>
  ['ai-inbox', 'conversation', 'status', customerId] as const;
const CONFIG_KEY = ['ai-inbox', 'config'] as const;
const ESCALATIONS_KEY = (statusFilter: 'open' | 'all') =>
  ['ai-inbox', 'escalations', statusFilter] as const;

// ── Hooks ───────────────────────────────────────────────────────────


/**
 * Per-conversation AI status — drives the inbox banner.
 *
 * Polls every 10s when a conversation is open so the operator sees
 * the AI reply land + the escalation badge appear without a
 * websocket layer. Disabled when no customerId is provided so the
 * inbox can keep this hook mounted across thread switches.
 */
export function useAIConversationStatus(customerId: number | undefined) {
  return useQuery<AIConversationStatusResponse>({
    queryKey: customerId
      ? STATUS_KEY(customerId)
      : (['ai-inbox', 'conversation', 'status', 'disabled'] as const),
    queryFn: () =>
      api.get<AIConversationStatusResponse>(
        `/api/ai-inbox/conversations/${customerId}/`,
      ),
    enabled: typeof customerId === 'number' && customerId > 0,
    refetchInterval: 10_000,
    refetchOnWindowFocus: true,
    // Treat 402 (PlanFeatureRequired) as "feature off" — the calling
    // component renders nothing rather than spamming retries.
    retry: false,
  });
}

/** Operator pauses the AI for one conversation. */
export function usePauseAI(customerId: number) {
  const qc = useQueryClient();
  return useMutation<AIConversationStatusResponse, Error, void>({
    mutationFn: () =>
      api.post<AIConversationStatusResponse>(
        `/api/ai-inbox/conversations/${customerId}/pause/`,
      ),
    onSuccess: (data) => {
      qc.setQueryData(STATUS_KEY(customerId), data);
    },
  });
}

/** Operator resumes the AI for one conversation. Auto-resolves any
 * open escalation alerts on this conversation as a side effect on
 * the server. */
export function useResumeAI(customerId: number) {
  const qc = useQueryClient();
  return useMutation<AIConversationStatusResponse, Error, void>({
    mutationFn: () =>
      api.post<AIConversationStatusResponse>(
        `/api/ai-inbox/conversations/${customerId}/resume/`,
      ),
    onSuccess: (data) => {
      qc.setQueryData(STATUS_KEY(customerId), data);
      qc.invalidateQueries({ queryKey: ['ai-inbox', 'escalations'] });
    },
  });
}

/** Tenant-level AIConfig read. */
export function useAIConfig() {
  return useQuery<AIConfig>({
    queryKey: CONFIG_KEY,
    queryFn: () => api.get<AIConfig>('/api/ai-inbox/config/'),
    retry: false,
  });
}

/** Tenant-level AIConfig partial update. */
export function useUpdateAIConfig() {
  const qc = useQueryClient();
  return useMutation<AIConfig, Error, AIConfigInput>({
    mutationFn: (patch) =>
      api.patch<AIConfig>('/api/ai-inbox/config/', patch),
    onSuccess: (data) => {
      qc.setQueryData(CONFIG_KEY, data);
    },
  });
}

/** Open escalation alerts list — drives the dashboard widget. */
export function useEscalationAlerts(statusFilter: 'open' | 'all' = 'open') {
  return useQuery<EscalationAlert[]>({
    queryKey: ESCALATIONS_KEY(statusFilter),
    queryFn: () =>
      api.get<EscalationAlert[]>(
        `/api/ai-inbox/escalations/?status=${statusFilter}`,
      ),
    refetchInterval: 30_000,
    retry: false,
  });
}

/** Acknowledge an escalation alert (mark "we're on it"). */
export function useAcknowledgeAlert() {
  const qc = useQueryClient();
  return useMutation<EscalationAlert, Error, number>({
    mutationFn: (id) =>
      api.post<EscalationAlert>(
        `/api/ai-inbox/escalations/${id}/acknowledge/`,
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['ai-inbox', 'escalations'] });
    },
  });
}

/** Resolve an escalation alert (operator handled the issue). */
export function useResolveAlert() {
  const qc = useQueryClient();
  return useMutation<EscalationAlert, Error, number>({
    mutationFn: (id) =>
      api.post<EscalationAlert>(
        `/api/ai-inbox/escalations/${id}/resolve/`,
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['ai-inbox', 'escalations'] });
    },
  });
}
