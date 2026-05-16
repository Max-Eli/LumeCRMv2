/**
 * EMR data hooks — TreatmentRecordTemplate (the schema-driven form
 * spec) + TreatmentRecord (the per-appointment provider-signed
 * instance).
 *
 * Pairs with the Django `apps.charts` API at
 * `/api/treatment-record-templates/` and `/api/treatment-records/`.
 *
 * The schema field-type vocabulary mirrors the existing
 * `FormTemplate` field types (short_text, long_text, choice_*,
 * date, signature) plus `number` for medical fields (units used,
 * dosages, side counts).
 */

'use client';

import {
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query';

import { api } from './api';

// ── Schema vocabulary ──────────────────────────────────────────────


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
  /** Free-form helper text shown under the input. */
  hint?: string;
}

export interface TemplateSchema {
  fields: TemplateField[];
}

// ── TreatmentRecordTemplate ────────────────────────────────────────


export interface TreatmentRecordTemplate {
  id: number;
  name: string;
  description: string;
  schema: TemplateSchema;
  version: number;
  is_active: boolean;
  service_ids: number[];
  created_at: string;
  updated_at: string;
}

export interface CreateTemplateInput {
  name: string;
  description?: string;
  schema: TemplateSchema;
  is_active?: boolean;
  set_service_ids?: number[];
}

export type UpdateTemplateInput = Partial<CreateTemplateInput>;

const TEMPLATES_KEY = ['treatment-record-templates'] as const;

function templateKey(id: number) {
  return [...TEMPLATES_KEY, id] as const;
}

export function useTreatmentTemplates(opts?: {
  serviceId?: number;
  active?: boolean;
}) {
  const params = new URLSearchParams();
  if (opts?.serviceId) params.set('service', String(opts.serviceId));
  if (opts?.active !== undefined) {
    params.set('active', opts.active ? 'true' : 'false');
  }
  const qs = params.toString();
  const path = qs
    ? `/api/treatment-record-templates/?${qs}`
    : '/api/treatment-record-templates/';

  return useQuery<TreatmentRecordTemplate[]>({
    queryKey: [...TEMPLATES_KEY, opts?.serviceId ?? 0, opts?.active ?? null],
    queryFn: async () => {
      // The endpoint may or may not paginate depending on viewset
      // config; tolerate both shapes.
      const data = await api.get<
        TreatmentRecordTemplate[] | { results: TreatmentRecordTemplate[] }
      >(path);
      return Array.isArray(data) ? data : data.results;
    },
  });
}

export function useTreatmentTemplate(id: number | undefined) {
  return useQuery<TreatmentRecordTemplate>({
    queryKey: id
      ? templateKey(id)
      : [...TEMPLATES_KEY, 'detail', 'disabled'],
    queryFn: () =>
      api.get<TreatmentRecordTemplate>(
        `/api/treatment-record-templates/${id}/`,
      ),
    enabled: typeof id === 'number' && id > 0,
  });
}

export function useCreateTreatmentTemplate() {
  const qc = useQueryClient();
  return useMutation<TreatmentRecordTemplate, Error, CreateTemplateInput>({
    mutationFn: (input) =>
      api.post<TreatmentRecordTemplate>(
        '/api/treatment-record-templates/',
        input,
      ),
    onSuccess: (created) => {
      qc.invalidateQueries({ queryKey: TEMPLATES_KEY });
      qc.setQueryData(templateKey(created.id), created);
    },
  });
}

export function useUpdateTreatmentTemplate(id: number) {
  const qc = useQueryClient();
  return useMutation<TreatmentRecordTemplate, Error, UpdateTemplateInput>({
    mutationFn: (input) =>
      api.patch<TreatmentRecordTemplate>(
        `/api/treatment-record-templates/${id}/`,
        input,
      ),
    onSuccess: (updated) => {
      qc.setQueryData(templateKey(updated.id), updated);
      qc.invalidateQueries({ queryKey: TEMPLATES_KEY });
    },
  });
}

export function useDeleteTreatmentTemplate() {
  const qc = useQueryClient();
  return useMutation<void, Error, number>({
    mutationFn: (id) =>
      api.delete<void>(`/api/treatment-record-templates/${id}/`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: TEMPLATES_KEY });
    },
  });
}

// ── Starter library (pre-built EMR templates) ──────────────────────


export interface StarterTemplateSummary {
  slug: string;
  name: string;
  description: string;
  category: string;
  field_count: number;
}

export interface StarterTemplateCatalog {
  categories: string[];
  starters: StarterTemplateSummary[];
}

export interface StarterTemplateDetail {
  slug: string;
  name: string;
  description: string;
  category: string;
  fields: TemplateField[];
}

const STARTER_KEY = ['treatment-templates', 'starters'] as const;

/** The catalog of pre-built EMR starter templates. Static for the
 *  app's lifetime — long staleTime so the picker dialog opens
 *  instantly on repeat visits. */
export function useStarterTemplates() {
  return useQuery<StarterTemplateCatalog>({
    queryKey: STARTER_KEY,
    queryFn: () =>
      api.get<StarterTemplateCatalog>(
        '/api/treatment-record-templates/starters/',
      ),
    staleTime: 60 * 60 * 1000, // 1 hour — content only changes on deploy
  });
}

/** Full payload for a single starter (the catalog endpoint omits
 *  `fields` to keep the list payload small). Used for the preview
 *  pane + as the source for the clone-into-tenant flow. */
export function useStarterTemplate(slug: string | undefined) {
  return useQuery<StarterTemplateDetail>({
    queryKey: [...STARTER_KEY, slug ?? ''],
    queryFn: () =>
      api.get<StarterTemplateDetail>(
        `/api/treatment-record-templates/starters/${slug}/`,
      ),
    enabled: !!slug,
    staleTime: 60 * 60 * 1000,
  });
}

/** Clone a starter into a real, editable tenant template.
 *
 *  We just POST a regular create-template call with the starter's
 *  name + schema; the backend doesn't need a dedicated endpoint
 *  because there's nothing tenant-specific about the clone beyond
 *  what the standard create already does. */
export function useCloneStarterTemplate() {
  const qc = useQueryClient();
  return useMutation<TreatmentRecordTemplate, Error, StarterTemplateDetail>({
    mutationFn: (starter) =>
      api.post<TreatmentRecordTemplate>(
        '/api/treatment-record-templates/',
        {
          name: starter.name,
          description: starter.description,
          schema: { fields: starter.fields },
          is_active: true,
        } satisfies CreateTemplateInput,
      ),
    onSuccess: (created) => {
      qc.invalidateQueries({ queryKey: TEMPLATES_KEY });
      qc.setQueryData(templateKey(created.id), created);
    },
  });
}

// ── TreatmentRecord (filled instance) ───────────────────────────────


export interface TreatmentRecord {
  id: number;
  customer: number;
  appointment_id: number | null;
  appointment_date: string | null;
  template_id: number;
  template_name: string;
  template_version_at_signing: number;
  schema_snapshot: TemplateSchema;
  answers: Record<string, unknown>;
  author_id: number;
  author_first_name: string;
  author_last_name: string;
  author_email: string;
  author_job_title: string;
  author_was_clinical: boolean;
  signed_at: string;
  is_locked: boolean;
  edit_window_ends_at: string;
  parent_record_id: number | null;
  is_voided: boolean;
  voided_at: string | null;
  voided_reason: string;
  voided_by_first_name: string;
  voided_by_last_name: string;
  voided_by_email: string;
  created_at: string;
  updated_at: string;
}

export interface SubmitRecordInput {
  customer_id: number;
  template_id: number;
  appointment_id?: number | null;
  answers?: Record<string, unknown>;
}

const RECORDS_KEY = ['treatment-records'] as const;

function recordKey(id: number) {
  return [...RECORDS_KEY, id] as const;
}

export function useCustomerTreatmentRecords(customerId: number | undefined) {
  return useQuery<TreatmentRecord[]>({
    queryKey: customerId
      ? [...RECORDS_KEY, 'customer', customerId]
      : [...RECORDS_KEY, 'customer', 'disabled'],
    queryFn: async () => {
      const data = await api.get<
        TreatmentRecord[] | { results: TreatmentRecord[] }
      >(`/api/treatment-records/?customer=${customerId}`);
      return Array.isArray(data) ? data : data.results;
    },
    enabled: typeof customerId === 'number' && customerId > 0,
  });
}

export function useAppointmentTreatmentRecords(
  appointmentId: number | undefined,
) {
  return useQuery<TreatmentRecord[]>({
    queryKey: appointmentId
      ? [...RECORDS_KEY, 'appointment', appointmentId]
      : [...RECORDS_KEY, 'appointment', 'disabled'],
    queryFn: async () => {
      const data = await api.get<
        TreatmentRecord[] | { results: TreatmentRecord[] }
      >(`/api/treatment-records/?appointment=${appointmentId}`);
      return Array.isArray(data) ? data : data.results;
    },
    enabled: typeof appointmentId === 'number' && appointmentId > 0,
  });
}

export function useSubmitTreatmentRecord() {
  const qc = useQueryClient();
  return useMutation<TreatmentRecord, Error, SubmitRecordInput>({
    mutationFn: (input) =>
      api.post<TreatmentRecord>('/api/treatment-records/', input),
    onSuccess: (created) => {
      qc.invalidateQueries({ queryKey: RECORDS_KEY });
      qc.setQueryData(recordKey(created.id), created);
    },
  });
}

export function useEditTreatmentRecord(id: number) {
  const qc = useQueryClient();
  return useMutation<
    TreatmentRecord,
    Error,
    { answers: Record<string, unknown> }
  >({
    mutationFn: (input) =>
      api.patch<TreatmentRecord>(`/api/treatment-records/${id}/`, input),
    onSuccess: (updated) => {
      qc.setQueryData(recordKey(updated.id), updated);
      qc.invalidateQueries({ queryKey: RECORDS_KEY });
    },
  });
}

export function useAddTreatmentAddendum(parentId: number) {
  const qc = useQueryClient();
  return useMutation<
    TreatmentRecord,
    Error,
    { answers: Record<string, unknown> }
  >({
    mutationFn: (input) =>
      api.post<TreatmentRecord>(
        `/api/treatment-records/${parentId}/addendum/`,
        input,
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: RECORDS_KEY });
    },
  });
}

export function useVoidTreatmentRecord(id: number) {
  const qc = useQueryClient();
  return useMutation<TreatmentRecord, Error, { reason: string }>({
    mutationFn: (input) =>
      api.post<TreatmentRecord>(`/api/treatment-records/${id}/void/`, input),
    onSuccess: (updated) => {
      qc.setQueryData(recordKey(updated.id), updated);
      qc.invalidateQueries({ queryKey: RECORDS_KEY });
    },
  });
}

// ── Display helpers ────────────────────────────────────────────────


export const FIELD_TYPE_LABELS: Record<TemplateFieldType, string> = {
  short_text: 'Short text',
  long_text: 'Long text',
  choice_single: 'Choice (one)',
  choice_multiple: 'Choice (multiple)',
  number: 'Number',
  date: 'Date',
  signature: 'Signature',
};

export function authorDisplayName(record: {
  author_first_name: string;
  author_last_name: string;
  author_email: string;
}): string {
  const full = `${record.author_first_name} ${record.author_last_name}`.trim();
  return full || record.author_email;
}
