/**
 * Staff / provider data. Pairs with `apps.tenants` memberships at
 * `/api/memberships/`. Used to populate the provider picker.
 */

import { useQuery } from '@tanstack/react-query';

import { useAuth } from './auth';

export interface Provider {
  id: number;
  user_first_name: string;
  user_last_name: string;
  job_title_name: string | null;
  role: string;
}

/** "Jane Lee" — provider display name. */
export function providerDisplayName(p: Provider): string {
  return `${p.user_first_name} ${p.user_last_name}`.trim() || 'Provider';
}

/** The workspace's bookable, active providers. */
export function useBookableProviders() {
  const { authedFetch } = useAuth();
  return useQuery({
    queryKey: ['providers', 'bookable'],
    queryFn: () =>
      authedFetch<Provider[]>(
        '/api/memberships/?bookable=true&active=true',
      ),
    staleTime: 5 * 60 * 1000,
  });
}
