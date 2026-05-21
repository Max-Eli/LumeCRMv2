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

import { ApiError, api } from './api';

/** Acquisition source — first-touch attribution per customer. ADR 0027 §8a.
 *  Immutable after create; powers the acquisition reports. */
export type CustomerAcquisitionSource =
  | 'instagram'
  | 'facebook'
  | 'whatsapp'
  | 'online_booking'
  | 'walk_in'
  | 'referral'
  | 'zenoti_import'
  | 'vagaro_import'
  | 'manual'
  | 'other';

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
  /** Social DM provenance — true means the row was auto-created from an
   *  inbound social DM (Instagram, etc.) and hasn't been merged into a
   *  real client record yet. ADR 0027 §6. */
  is_social_guest?: boolean;
  instagram_handle?: string;
  acquisition_source?: CustomerAcquisitionSource;
}

/** Minimal customer reference used by both ends of a referral link —
 *  the `referred_by` pointer and the `referred_customers` list. No PHI. */
export interface ReferralCustomerLink {
  id: number;
  full_name: string;
  referral_code: string;
  status: 'active' | 'inactive' | 'blocked';
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
  /** Who referred this client (1A.2). Null if not referred. */
  referred_by: ReferralCustomerLink | null;
  /** Clients this client referred in — newest first. */
  referred_customers: ReferralCustomerLink[];
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
  /** An existing client's referral code (1A.2). Resolved server-side
   *  to set `referred_by`; an unknown code is a 400 on this field. */
  referred_by_code?: string;
}

/** Role-based UI gate for PHI sections on the customer detail screen.
 *  Mirrors `VIEW_CLIENT_PHI` in `apps/tenants/permissions.py`. The
 *  server is the security boundary; this hook only decides whether to
 *  render the section, since the server already redacts PHI fields
 *  from the response and rejects PHI writes for these roles.
 *
 *  Keep in sync with `ROLE_DEFAULTS` in the backend permission catalog. */
export function canViewClientPHI(
  role: 'owner' | 'manager' | 'front_desk' | 'provider' | 'bookkeeper' | 'marketing' | undefined,
): boolean {
  return role === 'owner' || role === 'manager' || role === 'provider';
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

/** Result of resolving a referral code — the matched client's id + name. */
export interface ReferralResolveResult {
  id: number;
  full_name: string;
}

/**
 * Live-resolve a referral code for the new-client form's "Referred by"
 * field. Returns the matched client on a hit, `null` when the code
 * matches nothing (a 404 from the endpoint). Only fires once the code
 * is a complete 8-character code, so typing doesn't spam the endpoint.
 */
export function useResolveReferral(code: string) {
  const normalized = code.trim().toUpperCase();
  return useQuery<ReferralResolveResult | null>({
    queryKey: ['referral-resolve', normalized],
    enabled: normalized.length === 8,
    staleTime: 60 * 1000,
    retry: false,
    queryFn: async () => {
      try {
        return await api.get<ReferralResolveResult>(
          `/api/customers/resolve-referral/?code=${encodeURIComponent(normalized)}`,
        );
      } catch (err) {
        if (err instanceof ApiError && err.status === 404) return null;
        throw err;
      }
    },
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

/**
 * Merge a social-guest customer into an existing real customer. The source
 * (a row with `is_social_guest=true`) gets soft-deleted; the target inherits
 * the source's social-thread history + acquisition_source (only if the
 * target doesn't already have those fields populated).
 *
 * Backend endpoint: POST /api/customers/{source_id}/merge-into/{target_id}/
 * Gated to owner+manager via MANAGE_CLIENT_RECORDS. ADR 0027 §8b.
 *
 * On success we invalidate both customers + the social-threads list so the
 * inbox refreshes the renamed thread.
 */
export function useMergeIntoCustomer(sourceId: number) {
  const qc = useQueryClient();
  return useMutation<CustomerDetail, Error, { targetId: number }>({
    mutationFn: ({ targetId }) =>
      api.post<CustomerDetail>(
        `/api/customers/${sourceId}/merge-into/${targetId}/`,
        {},
      ),
    onSuccess: (mergedTarget) => {
      qc.invalidateQueries({ queryKey: CUSTOMERS_KEY });
      qc.invalidateQueries({ queryKey: customerKey(sourceId) });
      qc.setQueryData(customerKey(mergedTarget.id), mergedTarget);
      // Social inbox queries also need a refresh since thread customer
      // links got rewired.
      qc.invalidateQueries({ queryKey: ['social-threads'] });
      qc.invalidateQueries({ queryKey: ['social-thread'] });
    },
  });
}
