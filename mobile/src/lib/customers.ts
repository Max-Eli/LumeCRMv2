/**
 * Customer data — types and hooks. Pairs with `apps.customers` at
 * `/api/customers/`. The list endpoint returns minimal records (no
 * medical PHI) — HIPAA "minimum necessary" for routine browsing.
 */

import { useQuery } from '@tanstack/react-query';

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
