/**
 * Marketing hooks — Phase 1L session 1.
 *
 * Wraps `/api/marketing/audiences/`. Templates + Campaigns endpoints
 * land in subsequent sessions per ADR 0016.
 *
 * Permission gating: read access requires `VIEW_AUDIENCE_SEGMENTS`,
 * writes (and the preview endpoint, since it refreshes the cached
 * count) require `SEND_MARKETING_CAMPAIGN`. The backend returns 403
 * with a clear message; the UI renders a "no access" state for
 * roles that lack the permission rather than masking the failure.
 */

'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from './api';

// ── Filter spec ─────────────────────────────────────────────────────

/** Allowed filter dimensions in v1. Mirrors the allowlist in
 *  `apps.marketing.audiences.DIMENSIONS`. Adding a new dimension
 *  requires updating BOTH sides — keep them in sync. */
export interface AudienceFilterSpec {
  /** Customer has any of these CustomerTag rows. */
  tag_ids?: number[];
  /** Customer had a COMPLETED appointment in the last N days. */
  last_visit_within_days?: number;
  /** Customer's most recent COMPLETED appointment is older than N
   *  days, OR they have no completed appointments at all (win-back). */
  last_visit_more_than_days?: number;
  /** Customer record created within the last N days. */
  created_within_days?: number;
  /** Filter to customers with explicit email marketing consent. */
  email_marketing_opt_in?: boolean;
  /** Filter to customers with explicit SMS marketing consent. */
  sms_marketing_opt_in?: boolean;
}

// ── Types ───────────────────────────────────────────────────────────

export interface Audience {
  id: number;
  name: string;
  description: string;
  filter_spec: AudienceFilterSpec;
  /** Cached count of all customers matching the filter (no
   *  channel-consent gating). Refreshed on create + on preview. */
  last_member_count: number;
  last_counted_at: string | null;
  /** True when any non-DRAFT non-CANCELLED campaign references this
   *  audience. The UI uses this to disable the filter editor — once
   *  used, audiences are read-only to keep audit attribution stable. */
  is_used_in_campaign: boolean;
  created_by_email: string | null;
  created_at: string;
  updated_at: string;
}

export interface CreateAudienceInput {
  name: string;
  description?: string;
  filter_spec?: AudienceFilterSpec;
}

export type UpdateAudienceInput = Partial<CreateAudienceInput>;

export interface AudiencePreview {
  /** Total customers matching the filter, regardless of channel
   *  consent. This is the operator's "I have X people in this
   *  segment" view. */
  total_count: number;
  /** How many of those will actually receive an email send —
   *  factoring in opt-in + suppression + email-on-file. */
  email_eligible_count: number;
  /** Same for SMS. */
  sms_eligible_count: number;
}

// ── Query keys ──────────────────────────────────────────────────────

const AUDIENCES_KEY = ['marketing', 'audiences'] as const;
const audienceDetailKey = (id: number) => [...AUDIENCES_KEY, id] as const;

// ── Hooks ───────────────────────────────────────────────────────────

export function useAudiences() {
  return useQuery<Audience[]>({
    queryKey: AUDIENCES_KEY,
    queryFn: () => api.get<Audience[]>('/api/marketing/audiences/'),
    staleTime: 30 * 1000,
  });
}

export function useAudience(id: number | undefined) {
  return useQuery<Audience>({
    queryKey: audienceDetailKey(id ?? 0),
    queryFn: () => api.get<Audience>(`/api/marketing/audiences/${id}/`),
    enabled: typeof id === 'number' && id > 0,
  });
}

export function useCreateAudience() {
  const qc = useQueryClient();
  return useMutation<Audience, Error, CreateAudienceInput>({
    mutationFn: (input) =>
      api.post<Audience>('/api/marketing/audiences/', input),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: AUDIENCES_KEY });
    },
  });
}

export function useUpdateAudience(id: number) {
  const qc = useQueryClient();
  return useMutation<Audience, Error, UpdateAudienceInput>({
    mutationFn: (input) =>
      api.patch<Audience>(`/api/marketing/audiences/${id}/`, input),
    onSuccess: (audience) => {
      qc.setQueryData(audienceDetailKey(id), audience);
      qc.invalidateQueries({ queryKey: AUDIENCES_KEY });
    },
  });
}

export function useDeleteAudience() {
  const qc = useQueryClient();
  return useMutation<void, Error, number>({
    mutationFn: (id) => api.delete(`/api/marketing/audiences/${id}/`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: AUDIENCES_KEY });
    },
  });
}

/** Fetch a live count for the audience including the per-channel
 *  eligibility breakdown. The backend also persists the new total
 *  to `last_member_count` as a side-effect, so the list page stays
 *  fresh after a preview. */
export function usePreviewAudience(id: number) {
  const qc = useQueryClient();
  return useMutation<AudiencePreview, Error, void>({
    mutationFn: () =>
      api.post<AudiencePreview>(`/api/marketing/audiences/${id}/preview/`, {}),
    onSuccess: () => {
      // Cache a fresh detail/list — the preview also updates the
      // last_member_count + last_counted_at on the row.
      qc.invalidateQueries({ queryKey: audienceDetailKey(id) });
      qc.invalidateQueries({ queryKey: AUDIENCES_KEY });
    },
  });
}

// ── Display helpers ────────────────────────────────────────────────

/** Role-based UI gate for the Marketing top-level nav. Mirrors
 *  the backend permission catalog — VIEW_AUDIENCE_SEGMENTS is held
 *  by owner + manager + marketing + front_desk by default. */
export function canAccessMarketing(
  role: 'owner' | 'manager' | 'front_desk' | 'provider' | 'bookkeeper' | 'marketing' | undefined,
): boolean {
  return (
    role === 'owner' ||
    role === 'manager' ||
    role === 'marketing' ||
    role === 'front_desk'
  );
}

/** Role-based UI gate for the create / edit / send paths. Tighter
 *  than canAccessMarketing — front desk reads but doesn't write. */
export function canSendMarketing(
  role: 'owner' | 'manager' | 'front_desk' | 'provider' | 'bookkeeper' | 'marketing' | undefined,
): boolean {
  return role === 'owner' || role === 'manager' || role === 'marketing';
}

// ── Templates ───────────────────────────────────────────────────────

export type Channel = 'email' | 'sms';

/** Mirrors the backend `ALLOWED_TOKENS` set in
 *  apps/marketing/templates_tokens.py. Keep in sync. */
export const ALLOWED_TOKENS = [
  'first_name',
  'last_name',
  'tenant_name',
  'last_appointment_date',
  'birthday_month',
  'unsubscribe_url',
] as const;

export interface MarketingTemplate {
  id: number;
  name: string;
  channel: Channel;
  subject: string;
  body: string;
  is_active: boolean;
  discovered_tokens: string[];
  created_by_email: string | null;
  created_at: string;
  updated_at: string;
}

export interface CreateTemplateInput {
  name: string;
  channel: Channel;
  subject?: string;
  body: string;
  is_active?: boolean;
}

export type UpdateTemplateInput = Partial<CreateTemplateInput>;

export interface TemplatePreviewResult {
  subject: string;
  body: string;
  discovered_tokens: string[];
}

const TEMPLATES_KEY = ['marketing', 'templates'] as const;
const templateDetailKey = (id: number) => [...TEMPLATES_KEY, id] as const;

export function useTemplates(filter: { channel?: Channel; activeOnly?: boolean } = {}) {
  const params = new URLSearchParams();
  if (filter.channel) params.set('channel', filter.channel);
  if (filter.activeOnly) params.set('active', 'true');
  const qs = params.toString();
  return useQuery<MarketingTemplate[]>({
    queryKey: [...TEMPLATES_KEY, filter],
    queryFn: () =>
      api.get<MarketingTemplate[]>(`/api/marketing/templates/${qs ? `?${qs}` : ''}`),
    staleTime: 30 * 1000,
  });
}

export function useTemplate(id: number | undefined) {
  return useQuery<MarketingTemplate>({
    queryKey: templateDetailKey(id ?? 0),
    queryFn: () => api.get<MarketingTemplate>(`/api/marketing/templates/${id}/`),
    enabled: typeof id === 'number' && id > 0,
  });
}

export function useCreateTemplate() {
  const qc = useQueryClient();
  return useMutation<MarketingTemplate, Error, CreateTemplateInput>({
    mutationFn: (input) =>
      api.post<MarketingTemplate>('/api/marketing/templates/', input),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: TEMPLATES_KEY });
    },
  });
}

export function useUpdateTemplate(id: number) {
  const qc = useQueryClient();
  return useMutation<MarketingTemplate, Error, UpdateTemplateInput>({
    mutationFn: (input) =>
      api.patch<MarketingTemplate>(`/api/marketing/templates/${id}/`, input),
    onSuccess: (template) => {
      qc.setQueryData(templateDetailKey(id), template);
      qc.invalidateQueries({ queryKey: TEMPLATES_KEY });
    },
  });
}

export function useDeleteTemplate() {
  const qc = useQueryClient();
  return useMutation<void, Error, number>({
    mutationFn: (id) => api.delete(`/api/marketing/templates/${id}/`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: TEMPLATES_KEY });
    },
  });
}

/** Render the template against a sample (or real) customer. Returns
 *  the expanded subject + body so the editor's preview pane can
 *  show what gets dispatched. */
export function usePreviewTemplate(id: number) {
  return useMutation<TemplatePreviewResult, Error, { customer_id?: number }>({
    mutationFn: (input) =>
      api.post<TemplatePreviewResult>(
        `/api/marketing/templates/${id}/preview/`,
        input,
      ),
  });
}

// ── Campaigns ───────────────────────────────────────────────────────

export type CampaignStatus =
  | 'draft'
  | 'scheduled'
  | 'sending'
  | 'sent'
  | 'cancelled';

export interface CampaignListItem {
  id: number;
  name: string;
  audience: number;
  audience_name: string;
  template: number;
  template_name: string;
  channel: Channel;
  status: CampaignStatus;
  scheduled_at: string | null;
  started_at: string | null;
  completed_at: string | null;
  recipient_count_snapshot: number;
  sent_count: number;
  failed_count: number;
  suppressed_count: number;
  created_by_email: string | null;
  created_at: string;
  updated_at: string;
}

export interface Campaign extends CampaignListItem {
  audience_detail: Audience;
  template_detail: MarketingTemplate;
}

export interface CreateCampaignInput {
  name: string;
  audience: number;
  template: number;
  scheduled_at?: string | null;
}

export type UpdateCampaignInput = {
  name?: string;
  scheduled_at?: string | null;
};

export interface SendLogRow {
  id: number;
  campaign: number;
  campaign_name: string;
  customer: number;
  customer_first_name: string;
  customer_last_name: string;
  channel: Channel;
  recipient_email_domain: string;
  recipient_phone_last4: string;
  status: 'pending' | 'sent' | 'delivered' | 'failed' | 'suppressed';
  suppression_reason: string;
  sent_at: string | null;
  delivered_at: string | null;
  failed_at: string | null;
  failure_reason: string;
  created_at: string;
}

const CAMPAIGNS_KEY = ['marketing', 'campaigns'] as const;
const campaignDetailKey = (id: number) => [...CAMPAIGNS_KEY, id] as const;

export function useCampaigns(filter: { status?: CampaignStatus; channel?: Channel } = {}) {
  const params = new URLSearchParams();
  if (filter.status) params.set('status', filter.status);
  if (filter.channel) params.set('channel', filter.channel);
  const qs = params.toString();
  return useQuery<CampaignListItem[]>({
    queryKey: [...CAMPAIGNS_KEY, filter],
    queryFn: () =>
      api.get<CampaignListItem[]>(`/api/marketing/campaigns/${qs ? `?${qs}` : ''}`),
    staleTime: 30 * 1000,
  });
}

export function useCampaign(id: number | undefined) {
  return useQuery<Campaign>({
    queryKey: campaignDetailKey(id ?? 0),
    queryFn: () => api.get<Campaign>(`/api/marketing/campaigns/${id}/`),
    enabled: typeof id === 'number' && id > 0,
  });
}

export function useCampaignSendLog(id: number | undefined) {
  return useQuery<SendLogRow[]>({
    queryKey: [...CAMPAIGNS_KEY, id ?? 0, 'send-log'],
    queryFn: () =>
      api.get<SendLogRow[]>(`/api/marketing/campaigns/${id}/send-log/`),
    enabled: typeof id === 'number' && id > 0,
  });
}

export function useCreateCampaign() {
  const qc = useQueryClient();
  return useMutation<Campaign, Error, CreateCampaignInput>({
    mutationFn: (input) =>
      api.post<Campaign>('/api/marketing/campaigns/', input),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: CAMPAIGNS_KEY });
    },
  });
}

export function useUpdateCampaign(id: number) {
  const qc = useQueryClient();
  return useMutation<Campaign, Error, UpdateCampaignInput>({
    mutationFn: (input) =>
      api.patch<Campaign>(`/api/marketing/campaigns/${id}/`, input),
    onSuccess: (campaign) => {
      qc.setQueryData(campaignDetailKey(id), campaign);
      qc.invalidateQueries({ queryKey: CAMPAIGNS_KEY });
    },
  });
}

export function useDeleteCampaign() {
  const qc = useQueryClient();
  return useMutation<void, Error, number>({
    mutationFn: (id) => api.delete(`/api/marketing/campaigns/${id}/`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: CAMPAIGNS_KEY });
    },
  });
}

export function useScheduleCampaign(id: number) {
  const qc = useQueryClient();
  return useMutation<Campaign, Error, { send_now?: boolean }>({
    mutationFn: (input) =>
      api.post<Campaign>(`/api/marketing/campaigns/${id}/schedule/`, input),
    onSuccess: (campaign) => {
      qc.setQueryData(campaignDetailKey(id), campaign);
      qc.invalidateQueries({ queryKey: CAMPAIGNS_KEY });
    },
  });
}

export function useCancelCampaign(id: number) {
  const qc = useQueryClient();
  return useMutation<Campaign, Error, void>({
    mutationFn: () => api.post<Campaign>(`/api/marketing/campaigns/${id}/cancel/`, {}),
    onSuccess: (campaign) => {
      qc.setQueryData(campaignDetailKey(id), campaign);
      qc.invalidateQueries({ queryKey: CAMPAIGNS_KEY });
    },
  });
}

/** Run the send worker for this campaign right now. Backend
 *  rejects unless status is SCHEDULED (or already SENDING). */
export function useDispatchCampaign(id: number) {
  const qc = useQueryClient();
  return useMutation<Campaign, Error, void>({
    mutationFn: () => api.post<Campaign>(`/api/marketing/campaigns/${id}/dispatch/`, {}),
    onSuccess: (campaign) => {
      qc.setQueryData(campaignDetailKey(id), campaign);
      qc.invalidateQueries({ queryKey: CAMPAIGNS_KEY });
      qc.invalidateQueries({ queryKey: [...CAMPAIGNS_KEY, id, 'send-log'] });
    },
  });
}

// ── Automations ─────────────────────────────────────────────────────

export type TriggerType =
  | 'birthday'
  | 'no_visit_days'
  | 'first_visit_anniversary';

export const TRIGGER_LABELS: Record<TriggerType, string> = {
  birthday: 'Birthday month',
  no_visit_days: 'No visit in N days (win-back)',
  first_visit_anniversary: 'First-visit anniversary',
};

export interface Automation {
  id: number;
  name: string;
  description: string;
  trigger_type: TriggerType;
  trigger_config: Record<string, unknown>;
  template: number;
  template_name: string;
  channel: Channel;
  audience: number | null;
  audience_name: string | null;
  dedup_window_days: number;
  is_active: boolean;
  last_run_at: string | null;
  last_run_eligible_count: number;
  last_run_sent_count: number;
  created_by_email: string | null;
  created_at: string;
  updated_at: string;
}

export interface CreateAutomationInput {
  name: string;
  description?: string;
  trigger_type: TriggerType;
  trigger_config: Record<string, unknown>;
  template: number;
  audience?: number | null;
  dedup_window_days?: number;
  is_active?: boolean;
}

export type UpdateAutomationInput = Partial<CreateAutomationInput>;

export interface AutomationPreview {
  total_count: number;
  consent_eligible_count: number;
  final_count: number;
}

const AUTOMATIONS_KEY = ['marketing', 'automations'] as const;
const automationDetailKey = (id: number) => [...AUTOMATIONS_KEY, id] as const;

export function useAutomations(filter: { active?: boolean } = {}) {
  const params = new URLSearchParams();
  if (filter.active !== undefined) {
    params.set('active', filter.active ? 'true' : 'false');
  }
  const qs = params.toString();
  return useQuery<Automation[]>({
    queryKey: [...AUTOMATIONS_KEY, filter],
    queryFn: () =>
      api.get<Automation[]>(`/api/marketing/automations/${qs ? `?${qs}` : ''}`),
    staleTime: 30 * 1000,
  });
}

export function useAutomation(id: number | undefined) {
  return useQuery<Automation>({
    queryKey: automationDetailKey(id ?? 0),
    queryFn: () => api.get<Automation>(`/api/marketing/automations/${id}/`),
    enabled: typeof id === 'number' && id > 0,
  });
}

export function useCreateAutomation() {
  const qc = useQueryClient();
  return useMutation<Automation, Error, CreateAutomationInput>({
    mutationFn: (input) =>
      api.post<Automation>('/api/marketing/automations/', input),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: AUTOMATIONS_KEY });
    },
  });
}

export function useUpdateAutomation(id: number) {
  const qc = useQueryClient();
  return useMutation<Automation, Error, UpdateAutomationInput>({
    mutationFn: (input) =>
      api.patch<Automation>(`/api/marketing/automations/${id}/`, input),
    onSuccess: (automation) => {
      qc.setQueryData(automationDetailKey(id), automation);
      qc.invalidateQueries({ queryKey: AUTOMATIONS_KEY });
    },
  });
}

export function useDeleteAutomation() {
  const qc = useQueryClient();
  return useMutation<void, Error, number>({
    mutationFn: (id) => api.delete(`/api/marketing/automations/${id}/`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: AUTOMATIONS_KEY });
    },
  });
}

export function usePreviewAutomation(id: number) {
  const qc = useQueryClient();
  return useMutation<AutomationPreview, Error, void>({
    mutationFn: () =>
      api.post<AutomationPreview>(`/api/marketing/automations/${id}/preview/`, {}),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: automationDetailKey(id) });
    },
  });
}

export interface FireAutomationResult {
  automation_id: number;
  eligible_count: number;
  sent_count: number;
  campaign_id: number | null;
}

/** Fire the automation right now — re-evaluates eligibility,
 *  applies dedup, dispatches via the send worker. Returns the
 *  send summary; the operator can navigate to the created
 *  Campaign row via `campaign_id`. */
export function useFireAutomation(id: number) {
  const qc = useQueryClient();
  return useMutation<FireAutomationResult, Error, void>({
    mutationFn: () =>
      api.post<FireAutomationResult>(`/api/marketing/automations/${id}/fire/`, {}),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: automationDetailKey(id) });
      qc.invalidateQueries({ queryKey: AUTOMATIONS_KEY });
      qc.invalidateQueries({ queryKey: CAMPAIGNS_KEY });
    },
  });
}

// ── Customer marketing history ─────────────────────────────────────

/** Per-customer marketing send rows — last 50 sends across all
 *  campaigns/automations. Drives the customer profile Marketing
 *  tab's history list. */
export function useCustomerMarketingHistory(customerId: number | undefined) {
  return useQuery<SendLogRow[]>({
    queryKey: ['marketing', 'customer-sends', customerId ?? 0],
    queryFn: () =>
      api.get<SendLogRow[]>(
        `/api/marketing/customer-sends/?customer=${customerId}`,
      ),
    enabled: typeof customerId === 'number' && customerId > 0,
  });
}
