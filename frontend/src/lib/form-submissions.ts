/**
 * Form-submission hooks (Phase 1D session 2/3).
 *
 * Three surfaces:
 *
 *   - **Tenant-scoped read** (`/api/form-submissions/`) — used by
 *     the customer profile Forms tab + the appointment popover
 *     Forms section. List omits PHI; detail returns it. Auth required.
 *   - **Tenant-scoped void** (`POST .../void/`) — operator
 *     invalidates a submission with a required reason.
 *     Owner+manager only.
 *   - **Public token sign** (`/api/forms/sign/<token>/`) — the
 *     unauthenticated fill flow that the client (or front desk on
 *     iPad) uses to sign. See ADR 0011 for token security rationale.
 *
 * The public hooks (`usePublicSubmission`, `useSubmitPublicForm`)
 * MUST NOT pull in any auth-related context — the fill page is
 * served without a session and shouldn't trigger any auth-dependent
 * data fetching.
 */

'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from './api';
import type { FormSchema, FormType } from './form-templates';

export type SubmissionStatus = 'pending' | 'completed' | 'voided';

/** Compact submission shape — what list endpoints return.
 *  Deliberately omits PHI (`answers`, `signature_data`,
 *  `schema_snapshot`); fetch the detail endpoint to get those. */
export interface FormSubmissionListItem {
  id: number;
  template_name: string;
  template_form_type: FormType;
  template_version_at_assignment: number;
  customer_id: number;
  customer_name: string;
  appointment_id: number | null;
  token: string;
  status: SubmissionStatus;
  signed_at: string | null;
  voided_at: string | null;
  created_at: string;
}

/** Detail shape — includes PHI. Treat as sensitive in any UI that
 *  renders this; only the per-submission view needs it. */
export interface FormSubmissionDetail extends FormSubmissionListItem {
  schema_snapshot: FormSchema;
  answers: Record<string, unknown>;
  signature_data: string;
  ip_address: string | null;
  user_agent: string;
  voided_reason: string;
  updated_at: string;
}

/** Public-side payload — used by the unauthenticated fill page. */
export interface PublicFormSubmission {
  token: string;
  template_name: string;
  template_version_at_assignment: number;
  schema_snapshot: FormSchema;
  customer_first_name: string;
  status: SubmissionStatus;
  answers: Record<string, unknown>;
  signed_at: string | null;
}

const SUBMISSIONS_KEY = ['form-submissions'] as const;
const submissionDetailKey = (id: number) =>
  [...SUBMISSIONS_KEY, 'detail', id] as const;
const publicSubmissionKey = (token: string) =>
  ['public-form-submission', token] as const;

// ── Tenant-scoped hooks (auth required) ─────────────────────────────

/** List submissions, filtered by customer / appointment / status. */
export function useFormSubmissions(filter: {
  customerId?: number;
  appointmentId?: number;
  status?: SubmissionStatus;
} = {}) {
  const params = new URLSearchParams();
  if (filter.customerId) params.set('customer', String(filter.customerId));
  if (filter.appointmentId) params.set('appointment', String(filter.appointmentId));
  if (filter.status) params.set('status', filter.status);
  const qs = params.toString();
  return useQuery<FormSubmissionListItem[]>({
    queryKey: [
      ...SUBMISSIONS_KEY,
      {
        customer: filter.customerId ?? null,
        appointment: filter.appointmentId ?? null,
        status: filter.status ?? null,
      },
    ],
    queryFn: () =>
      api.get<FormSubmissionListItem[]>(`/api/form-submissions/${qs ? `?${qs}` : ''}`),
    enabled: filter.customerId !== undefined || filter.appointmentId !== undefined || filter.status !== undefined,
    staleTime: 30 * 1000,
  });
}

/** Fetch one submission's full detail — includes PHI. Reading this
 *  triggers an audit log entry on the backend (HIPAA §164.312(b)). */
export function useFormSubmission(id: number | undefined) {
  return useQuery<FormSubmissionDetail>({
    queryKey: submissionDetailKey(id ?? 0),
    queryFn: () => api.get<FormSubmissionDetail>(`/api/form-submissions/${id}/`),
    enabled: typeof id === 'number' && id > 0,
  });
}

/** Void a submission with a required reason. Owner+manager only. */
export function useVoidSubmission(id: number) {
  const qc = useQueryClient();
  return useMutation<FormSubmissionDetail, Error, { reason: string }>({
    mutationFn: (input) =>
      api.post<FormSubmissionDetail>(`/api/form-submissions/${id}/void/`, input),
    onSuccess: (updated) => {
      qc.setQueryData(submissionDetailKey(id), updated);
      qc.invalidateQueries({ queryKey: SUBMISSIONS_KEY });
    },
  });
}

export interface EmailSubmissionResponse {
  detail: string;
  recipient: string;
}

/** Operator-initiated send of a signed copy to the customer's email
 *  on file. Owner+manager only — the backend re-validates. Audit-
 *  logged (recipient domain only, no full address). See ADR 0012.
 *
 *  v1 uses the dev console backend so emails print to the runserver
 *  terminal rather than actually sending; production switches to SES
 *  via env var. The hook's contract is identical either way. */
export function useEmailSubmission(id: number) {
  return useMutation<EmailSubmissionResponse, Error, void>({
    mutationFn: () =>
      api.post<EmailSubmissionResponse>(`/api/form-submissions/${id}/email/`, {}),
  });
}

// ── Public token hooks (NO auth) ────────────────────────────────────

/** Load the public fill view. No auth — token in URL is the bearer
 *  credential. Returns the schema snapshot + the customer's first
 *  name (for the "Hi {name}" greeting on the fill page). Doesn't
 *  return tenant or full customer details. */
export function usePublicSubmission(token: string | undefined) {
  return useQuery<PublicFormSubmission>({
    queryKey: publicSubmissionKey(token ?? ''),
    queryFn: () =>
      api.get<PublicFormSubmission>(`/api/forms/sign/${token}/`),
    enabled: !!token,
    // Don't refetch on focus — once loaded, the fill page is stable.
    refetchOnWindowFocus: false,
    retry: false,
  });
}

export interface SignFormInput {
  answers: Record<string, unknown>;
  /** Base64-encoded PNG of the canvas signature (data URL acceptable). */
  signature_data: string;
}

/** Submit answers + signature. Single-use — subsequent POSTs to the
 *  same token return 409. */
export function useSubmitPublicForm(token: string) {
  const qc = useQueryClient();
  return useMutation<PublicFormSubmission, Error, SignFormInput>({
    mutationFn: (input) =>
      api.post<PublicFormSubmission>(`/api/forms/sign/${token}/`, input),
    onSuccess: (updated) => {
      qc.setQueryData(publicSubmissionKey(token), updated);
    },
  });
}

// ── Display helpers ────────────────────────────────────────────────

export function statusLabel(status: SubmissionStatus): string {
  switch (status) {
    case 'pending':
      return 'Pending signature';
    case 'completed':
      return 'Signed';
    case 'voided':
      return 'Voided';
  }
}

export function statusTone(status: SubmissionStatus): 'pending' | 'success' | 'muted' {
  switch (status) {
    case 'pending':
      return 'pending';
    case 'completed':
      return 'success';
    case 'voided':
      return 'muted';
  }
}
