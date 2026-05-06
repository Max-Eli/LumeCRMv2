/**
 * Form template hooks (Phase 1D session 1).
 *
 * Wraps `/api/form-templates/`. Two form types:
 *
 *   - **intake**: assigned to a customer's first-ever appointment (any
 *     service). Default recurrence: signed once forever.
 *   - **consent**: per-service consent (Botox consent applies to Botox
 *     bookings). Mapped via `set_service_ids`. Default recurrence:
 *     signed every visit (CYA default for clinical).
 *
 * The schema field types supported in v1 — keep this in sync with
 * `apps/forms/serializers.py:ALLOWED_FIELD_TYPES`:
 *
 *   short_text       — single-line text input
 *   long_text        — textarea
 *   choice_single    — radio group (requires 2+ options)
 *   choice_multiple  — checkbox group (requires 2+ options)
 *   date             — calendar input
 *   signature        — canvas signature pad (Session 2 fill page)
 *
 * `version` auto-bumps on schema changes; cosmetic edits (rename,
 * description) leave the version alone.
 */

'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from './api';

export type FormType = 'intake' | 'consent';
export type Recurrence = 'once' | 'per_visit';

export const FORM_TYPE_LABELS: Record<FormType, string> = {
  intake: 'Intake',
  consent: 'Consent',
};

export const RECURRENCE_LABELS: Record<Recurrence, string> = {
  once: 'Once per customer',
  per_visit: 'Every visit',
};

export const FIELD_TYPES = [
  'short_text',
  'long_text',
  'choice_single',
  'choice_multiple',
  'date',
  'signature',
] as const;

export type FieldType = (typeof FIELD_TYPES)[number];

export const FIELD_TYPE_LABELS: Record<FieldType, string> = {
  short_text: 'Short text',
  long_text: 'Long text',
  choice_single: 'Single choice',
  choice_multiple: 'Multiple choice',
  date: 'Date',
  signature: 'Signature',
};

/** A single option in a choice field. `value` is the stored answer
 *  key; `label` is what the client sees. */
export interface FieldOption {
  value: string;
  label: string;
}

/** Discriminated union for fields. Optional props are typed on each
 *  variant so the builder can render the right config UI per type. */
export type FormField =
  | { id: string; type: 'short_text'; label: string; required: boolean; help_text?: string; placeholder?: string }
  | { id: string; type: 'long_text'; label: string; required: boolean; help_text?: string; placeholder?: string }
  | { id: string; type: 'choice_single'; label: string; required: boolean; help_text?: string; options: FieldOption[] }
  | { id: string; type: 'choice_multiple'; label: string; required: boolean; help_text?: string; options: FieldOption[] }
  | { id: string; type: 'date'; label: string; required: boolean; help_text?: string }
  | { id: string; type: 'signature'; label: string; required: boolean; help_text?: string };

export interface FormSchema {
  fields: FormField[];
}

export interface FormTemplate {
  id: number;
  name: string;
  description: string;
  form_type: FormType;
  recurrence: Recurrence;
  schema: FormSchema;
  version: number;
  is_active: boolean;
  /** IDs of services this consent form is assigned to. Always [] for
   *  intake forms (the backend rejects mappings on intake). */
  service_ids: number[];
  created_at: string;
  updated_at: string;
}

export interface CreateFormTemplateInput {
  name: string;
  description?: string;
  form_type: FormType;
  recurrence?: Recurrence;
  schema: FormSchema;
  is_active?: boolean;
  set_service_ids?: number[];
}

export type UpdateFormTemplateInput = Partial<
  Omit<FormTemplate, 'id' | 'version' | 'service_ids' | 'created_at' | 'updated_at'>
> & {
  set_service_ids?: number[];
};

const FORM_TEMPLATES_KEY = ['form-templates'] as const;
const detailKey = (id: number) => [...FORM_TEMPLATES_KEY, 'detail', id] as const;

/** List form templates for the current tenant. Optional filters:
 *  `formType` (intake/consent) and `activeOnly`. */
export function useFormTemplates(options: {
  formType?: FormType;
  activeOnly?: boolean;
} = {}) {
  const params = new URLSearchParams();
  if (options.formType) params.set('form_type', options.formType);
  if (options.activeOnly) params.set('active', 'true');
  const qs = params.toString();
  return useQuery<FormTemplate[]>({
    queryKey: [
      ...FORM_TEMPLATES_KEY,
      { formType: options.formType ?? 'all', activeOnly: !!options.activeOnly },
    ],
    queryFn: () => api.get<FormTemplate[]>(`/api/form-templates/${qs ? `?${qs}` : ''}`),
    staleTime: 60 * 1000,
  });
}

export function useFormTemplate(id: number | undefined) {
  return useQuery<FormTemplate>({
    queryKey: detailKey(id ?? 0),
    queryFn: () => api.get<FormTemplate>(`/api/form-templates/${id}/`),
    enabled: typeof id === 'number' && id > 0,
  });
}

export function useCreateFormTemplate() {
  const qc = useQueryClient();
  return useMutation<FormTemplate, Error, CreateFormTemplateInput>({
    mutationFn: (input) =>
      api.post<FormTemplate>('/api/form-templates/', input),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: FORM_TEMPLATES_KEY });
    },
  });
}

export function useUpdateFormTemplate(id: number) {
  const qc = useQueryClient();
  return useMutation<FormTemplate, Error, UpdateFormTemplateInput>({
    mutationFn: (input) =>
      api.patch<FormTemplate>(`/api/form-templates/${id}/`, input),
    onSuccess: (updated) => {
      qc.setQueryData(detailKey(id), updated);
      qc.invalidateQueries({ queryKey: FORM_TEMPLATES_KEY });
    },
  });
}

// ── Display helpers ────────────────────────────────────────────────

export function isChoiceField(field: FormField): field is Extract<FormField, { type: 'choice_single' | 'choice_multiple' }> {
  return field.type === 'choice_single' || field.type === 'choice_multiple';
}

/** Generate a unique field id for a freshly-added field. Pattern
 *  matches the backend's FIELD_ID_RE (alphanumeric + underscore). */
export function generateFieldId(existing: FormField[]): string {
  const usedIds = new Set(existing.map((f) => f.id));
  for (let i = 1; i < 10_000; i++) {
    const candidate = `field_${i}`;
    if (!usedIds.has(candidate)) return candidate;
  }
  // Effectively unreachable — 10k fields on one form is a bug.
  return `field_${Date.now()}`;
}

/** Build a sensible default for a freshly-added field of any type.
 *  Used by the builder's "+ Add field" picker. */
export function defaultField(type: FieldType, existing: FormField[]): FormField {
  const id = generateFieldId(existing);
  switch (type) {
    case 'short_text':
      return { id, type: 'short_text', label: 'Short answer', required: false };
    case 'long_text':
      return { id, type: 'long_text', label: 'Long answer', required: false };
    case 'choice_single':
      return {
        id, type: 'choice_single', label: 'Pick one', required: false,
        options: [
          { value: 'option_1', label: 'Option 1' },
          { value: 'option_2', label: 'Option 2' },
        ],
      };
    case 'choice_multiple':
      return {
        id, type: 'choice_multiple', label: 'Pick all that apply', required: false,
        options: [
          { value: 'option_1', label: 'Option 1' },
          { value: 'option_2', label: 'Option 2' },
        ],
      };
    case 'date':
      return { id, type: 'date', label: 'Pick a date', required: false };
    case 'signature':
      return {
        id, type: 'signature',
        label: 'I have read and consent to this treatment.',
        required: true,
      };
  }
}
