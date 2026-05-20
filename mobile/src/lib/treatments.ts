/**
 * EMR / charting data. Pairs with `apps.charts` at
 * `/api/treatment-record-templates/` and `/api/treatment-records/`.
 *
 * A TreatmentRecordTemplate is a schema-driven form spec; a
 * TreatmentRecord is the per-appointment, provider-signed instance.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { useAuth } from './auth';

export type TemplateFieldType =
  | 'short_text'
  | 'long_text'
  | 'choice_single'
  | 'choice_multiple'
  | 'number'
  | 'date'
  | 'signature';

export interface TemplateFieldOption {
  value: string;
  label: string;
}

export interface TemplateField {
  id: string;
  type: TemplateFieldType;
  label: string;
  required?: boolean;
  options?: TemplateFieldOption[];
  hint?: string;
}

export interface TemplateSchema {
  fields: TemplateField[];
}

export interface TreatmentRecordTemplate {
  id: number;
  name: string;
  description: string;
  schema: TemplateSchema;
  is_active: boolean;
}

export interface TreatmentRecord {
  id: number;
  customer: number;
  appointment_id: number | null;
  template_id: number;
  template_name: string;
  schema_snapshot: TemplateSchema;
  answers: Record<string, unknown>;
  author_first_name: string;
  author_last_name: string;
  author_job_title: string;
  signed_at: string;
  is_voided: boolean;
}

export interface SubmitRecordInput {
  customer_id: number;
  template_id: number;
  appointment_id?: number | null;
  answers: Record<string, unknown>;
}

/** Some list endpoints paginate, some don't — tolerate both shapes. */
function unwrap<T>(data: T[] | { results: T[] }): T[] {
  return Array.isArray(data) ? data : data.results;
}

/** Active EMR templates the provider can chart from. */
export function useTreatmentTemplates() {
  const { authedFetch } = useAuth();
  return useQuery({
    queryKey: ['treatment-templates'],
    queryFn: async () =>
      unwrap(
        await authedFetch<
          TreatmentRecordTemplate[] | { results: TreatmentRecordTemplate[] }
        >('/api/treatment-record-templates/?active=true'),
      ),
    staleTime: 5 * 60 * 1000,
  });
}

/** Treatment records charted against one appointment. */
export function useAppointmentTreatmentRecords(appointmentId: number) {
  const { authedFetch } = useAuth();
  return useQuery({
    queryKey: ['treatment-records', 'appointment', appointmentId],
    queryFn: async () =>
      unwrap(
        await authedFetch<
          TreatmentRecord[] | { results: TreatmentRecord[] }
        >(`/api/treatment-records/?appointment=${appointmentId}`),
      ),
    enabled: Number.isFinite(appointmentId) && appointmentId > 0,
  });
}

/** A single signed treatment record. */
export function useTreatmentRecord(id: number) {
  const { authedFetch } = useAuth();
  return useQuery({
    queryKey: ['treatment-records', 'detail', id],
    queryFn: () =>
      authedFetch<TreatmentRecord>(`/api/treatment-records/${id}/`),
    enabled: Number.isFinite(id) && id > 0,
  });
}

/** Sign a new treatment record (`POST /api/treatment-records/`). */
export function useSubmitTreatmentRecord() {
  const { authedFetch } = useAuth();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: SubmitRecordInput) =>
      authedFetch<TreatmentRecord>('/api/treatment-records/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(input),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['treatment-records'] });
    },
  });
}
