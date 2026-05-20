/**
 * Consent / intake form data. Pairs with `apps.forms`:
 *   - `/api/form-submissions/`        tenant-scoped list of assigned forms
 *   - `/api/forms/sign/<token>/`      token-scoped fill + sign surface
 *
 * The detail/PHI shapes (`answers`, `signature_data`) only ride on the
 * token sign endpoint, used when the operator hands the device over.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { useAuth } from './auth';

export type FormType = 'intake' | 'consent';
export type SubmissionStatus = 'pending' | 'completed' | 'voided';

export interface FieldOption {
  value: string;
  label: string;
}

/** A consent/intake form field. `paragraph` is display-only — it
 *  carries the legal/clinical body of a consent form. */
export interface FormField {
  id: string;
  type:
    | 'short_text'
    | 'long_text'
    | 'choice_single'
    | 'choice_multiple'
    | 'date'
    | 'signature'
    | 'paragraph';
  label: string;
  required?: boolean;
  help_text?: string;
  placeholder?: string;
  options?: FieldOption[];
  body?: string;
}

export interface FormSchema {
  fields: FormField[];
}

export interface FormSubmissionListItem {
  id: number;
  template_name: string;
  template_form_type: FormType;
  customer_id: number;
  customer_name: string;
  appointment_id: number | null;
  token: string;
  status: SubmissionStatus;
  signed_at: string | null;
  created_at: string;
}

export interface PublicFormSubmission {
  token: string;
  template_name: string;
  schema_snapshot: FormSchema;
  customer_first_name: string;
  tenant_name: string;
  tenant_logo_url: string;
  status: SubmissionStatus;
  answers: Record<string, unknown>;
  signed_at: string | null;
}

export interface SignFormInput {
  answers: Record<string, unknown>;
  /** Base64 PNG data URL of the drawn signature. */
  signature_data: string;
}

export function statusLabel(status: SubmissionStatus): string {
  if (status === 'pending') return 'Pending signature';
  if (status === 'completed') return 'Signed';
  return 'Voided';
}

/** Assigned forms for a customer and/or appointment. */
export function useFormSubmissions(filter: {
  customerId?: number;
  appointmentId?: number;
}) {
  const { authedFetch } = useAuth();
  const params = new URLSearchParams();
  if (filter.customerId) params.set('customer', String(filter.customerId));
  if (filter.appointmentId) {
    params.set('appointment', String(filter.appointmentId));
  }
  const qs = params.toString();
  return useQuery({
    queryKey: ['form-submissions', qs],
    queryFn: () =>
      authedFetch<FormSubmissionListItem[]>(
        `/api/form-submissions/${qs ? `?${qs}` : ''}`,
      ),
    enabled:
      filter.customerId !== undefined || filter.appointmentId !== undefined,
  });
}

/** The token-scoped fill view for one form. */
export function usePublicSubmission(token: string) {
  const { authedFetch } = useAuth();
  return useQuery({
    queryKey: ['form-sign', token],
    queryFn: () =>
      authedFetch<PublicFormSubmission>(`/api/forms/sign/${token}/`),
    enabled: token.length > 0,
    retry: false,
  });
}

/** Submit answers + signature for a form. Single-use per token. */
export function useSubmitForm(token: string) {
  const { authedFetch } = useAuth();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: SignFormInput) =>
      authedFetch<PublicFormSubmission>(`/api/forms/sign/${token}/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(input),
      }),
    onSuccess: (updated) => {
      queryClient.setQueryData(['form-sign', token], updated);
      queryClient.invalidateQueries({ queryKey: ['form-submissions'] });
    },
  });
}
