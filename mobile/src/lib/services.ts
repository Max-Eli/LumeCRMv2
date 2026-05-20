/**
 * Service catalog data. Pairs with `apps.services` at `/api/services/`.
 * Pricing is stored in cents; `price_dollars` is the preformatted
 * display string.
 */

import { useQuery } from '@tanstack/react-query';

import { useAuth } from './auth';

export interface ServiceCategorySummary {
  id: number;
  name: string;
  color: string;
}

export interface Service {
  id: number;
  name: string;
  duration_minutes: number;
  price_cents: number;
  price_dollars: string;
  category: ServiceCategorySummary | null;
  is_active: boolean;
}

/** List the active, bookable services for the workspace. */
export function useServices() {
  const { authedFetch } = useAuth();
  return useQuery({
    queryKey: ['services', 'list'],
    queryFn: () => authedFetch<Service[]>('/api/services/?active=true'),
    staleTime: 5 * 60 * 1000,
  });
}
