/**
 * Customer data — types and hooks. Pairs with `apps.customers` at
 * `/api/customers/`. The list endpoint returns minimal records (no
 * medical PHI) — HIPAA "minimum necessary" for routine browsing.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { useAuth } from './auth';

export interface CustomerListItem {
  id: number;
  first_name: string;
  last_name: string;
  full_name: string;
  email: string;
  phone: string;
  status: 'active' | 'inactive' | 'blocked';
}

/** Full customer record. The PHI fields are optional because the
 *  backend omits them from the response for roles without
 *  `VIEW_CLIENT_PHI` (HIPAA minimum-necessary). */
export interface CustomerDetail extends CustomerListItem {
  created_at: string;
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
  referral_code?: string;
}

export interface CreateCustomerInput {
  first_name: string;
  last_name: string;
  phone?: string;
  email?: string;
}

/** Roles cleared to see clinical PHI — mirrors `VIEW_CLIENT_PHI` in the
 *  backend permission catalog. The server is the real boundary (it
 *  redacts PHI from the response); this only decides what to render. */
export function canViewClientPHI(role: string | undefined): boolean {
  return role === 'owner' || role === 'manager' || role === 'provider';
}

/** List customers, optionally filtered by a search string (name /
 *  email / phone). `enabled` lets callers hold the request — the
 *  unfiltered list can be thousands of rows, so the appointment
 *  client-picker only fetches once a search term is entered. */
export function useCustomers(query: string, enabled = true) {
  const { authedFetch } = useAuth();
  const q = query.trim();
  return useQuery({
    queryKey: ['customers', 'list', q],
    queryFn: () =>
      authedFetch<CustomerListItem[]>(
        q
          ? `/api/customers/?q=${encodeURIComponent(q)}`
          : '/api/customers/',
      ),
    enabled,
  });
}

/** Full detail for one customer. */
export function useCustomer(id: number) {
  const { authedFetch } = useAuth();
  return useQuery({
    queryKey: ['customers', 'detail', id],
    queryFn: () => authedFetch<CustomerDetail>(`/api/customers/${id}/`),
    enabled: Number.isFinite(id) && id > 0,
  });
}

/** Create a customer (`POST /api/customers/`). Invalidates the list. */
export function useCreateCustomer() {
  const { authedFetch } = useAuth();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: CreateCustomerInput) =>
      authedFetch<CustomerDetail>('/api/customers/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(input),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['customers'] });
    },
  });
}
