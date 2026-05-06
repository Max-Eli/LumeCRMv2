/**
 * Customer data hooks for the Lumè frontend.
 *
 * Pairs with the Django `apps.customers` API at `/api/customers/`. List vs.
 * detail use different shapes — list returns minimal records (no medical PHI)
 * to keep payloads small and align with HIPAA "minimum necessary" for routine
 * browsing; detail returns the full record.
 */

'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from './api';

/** Minimal customer record returned by the list endpoint. No medical PHI. */
export interface CustomerListItem {
  id: number;
  first_name: string;
  last_name: string;
  preferred_name: string;
  full_name: string;
  email: string;
  phone: string;
  status: 'active' | 'inactive' | 'blocked';
  tags: CustomerTag[];
  created_at: string;
}

/** Full customer record. Includes medical PHI — show only to authorized roles. */
export interface CustomerDetail extends CustomerListItem {
  date_of_birth: string | null;
  sex: string;
  address_line1: string;
  address_line2: string;
  city: string;
  state: string;
  zip_code: string;
  emergency_name: string;
  emergency_phone: string;
  emergency_relationship: string;
  medical_history: string;
  allergies: string;
  medications: string;
  skin_type_fitzpatrick: number | null;
  notes: string;
  referral_source: string;
  email_opt_in: boolean;
  sms_opt_in: boolean;
  /** Promotional marketing opt-in (campaigns + automations).
   *  Distinct from `email_opt_in` (transactional). ADR 0016. */
  email_marketing_opt_in: boolean;
  sms_marketing_opt_in: boolean;
  email_marketing_consent_at: string | null;
  sms_marketing_consent_at: string | null;
  email_marketing_consent_source: string;
  sms_marketing_consent_source: string;
  /** Suppression always wins over opt-in; both flips are
   *  audit-stamped. Backend-managed (unsubscribe token, bounces,
   *  ops actions). */
  email_marketing_suppressed_at: string | null;
  sms_marketing_suppressed_at: string | null;
  email_marketing_suppression_source: string;
  sms_marketing_suppression_source: string;
  referral_code: string;
  external_id: string;
  external_source: string;
  imported_at: string | null;
  updated_at: string;
}

/** Payload accepted by the update endpoint. All fields optional (PATCH semantics). */
export type UpdateCustomerInput = Partial<Omit<CreateCustomerInput, never>>;

export interface CustomerTag {
  id: number;
  name: string;
  color: string;
  sort_order: number;
}

/** Payload accepted by the create endpoint. All fields except first_name/last_name optional. */
export interface CreateCustomerInput {
  first_name: string;
  last_name: string;
  preferred_name?: string;
  email?: string;
  phone?: string;
  date_of_birth?: string | null;
  sex?: string;
  address_line1?: string;
  address_line2?: string;
  city?: string;
  state?: string;
  zip_code?: string;
  emergency_name?: string;
  emergency_phone?: string;
  emergency_relationship?: string;
  medical_history?: string;
  allergies?: string;
  medications?: string;
  skin_type_fitzpatrick?: number | null;
  notes?: string;
  referral_source?: string;
  email_opt_in?: boolean;
  sms_opt_in?: boolean;
  email_marketing_opt_in?: boolean;
  sms_marketing_opt_in?: boolean;
  status?: 'active' | 'inactive' | 'blocked';
  tag_ids?: number[];
}

const CUSTOMERS_KEY = ['customers'] as const;

function customerKey(id: number) {
  return [...CUSTOMERS_KEY, id] as const;
}

/**
 * List customers, optionally filtered by a search string (matched against
 * first/last name, email, phone) and/or status. The server applies tenant scoping.
 */
export function useCustomers(opts?: { q?: string; status?: string }) {
  const params = new URLSearchParams();
  if (opts?.q) params.set('q', opts.q);
  if (opts?.status) params.set('status', opts.status);
  const qs = params.toString();
  const path = qs ? `/api/customers/?${qs}` : '/api/customers/';

  return useQuery<CustomerListItem[]>({
    queryKey: [...CUSTOMERS_KEY, opts?.q ?? '', opts?.status ?? ''],
    queryFn: () => api.get<CustomerListItem[]>(path),
  });
}

/** Fetch a single customer by ID. Returns the full detail (PHI-bearing) record. */
export function useCustomer(id: number | undefined) {
  return useQuery<CustomerDetail>({
    queryKey: id ? customerKey(id) : ['customers', 'disabled'],
    queryFn: () => api.get<CustomerDetail>(`/api/customers/${id}/`),
    enabled: typeof id === 'number' && id > 0,
  });
}

/**
 * Create a new customer. On success, invalidates the list query so the new row
 * appears immediately, and seeds the detail cache for instant navigation.
 */
export function useCreateCustomer() {
  const qc = useQueryClient();
  return useMutation<CustomerDetail, Error, CreateCustomerInput>({
    mutationFn: (input) => api.post<CustomerDetail>('/api/customers/', input),
    onSuccess: (created) => {
      qc.invalidateQueries({ queryKey: CUSTOMERS_KEY });
      qc.setQueryData(customerKey(created.id), created);
    },
  });
}

/**
 * Update an existing customer (PATCH — partial). On success, refreshes the
 * detail cache and invalidates the list so any visible columns update.
 */
export function useUpdateCustomer(id: number) {
  const qc = useQueryClient();
  return useMutation<CustomerDetail, Error, UpdateCustomerInput>({
    mutationFn: (input) => api.patch<CustomerDetail>(`/api/customers/${id}/`, input),
    onSuccess: (updated) => {
      qc.setQueryData(customerKey(updated.id), updated);
      qc.invalidateQueries({ queryKey: CUSTOMERS_KEY });
    },
  });
}
