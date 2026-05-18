/**
 * Public branding fetch for unauthenticated surfaces.
 *
 * Used on the login / portal-login / booking landing pages to display
 * the tenant's logo and name (instead of the Lumè default) once they
 * land on `<spa>.lumècrm.com`. Resolved from the request subdomain on
 * the backend so no slug is needed in the URL.
 *
 * Returns `null` when no tenant resolves (bare hostname, marketing
 * pages, unknown subdomain) — surfaces should fall back to Lumè
 * default branding in that case.
 */

'use client';

import { useQuery } from '@tanstack/react-query';

import { api } from './api';

export interface PublicBranding {
  name: string;
  slug: string;
  logo_url: string | null;
  primary_color: string | null;
}

export function usePublicBranding() {
  return useQuery<PublicBranding | null>({
    queryKey: ['public-branding'],
    queryFn: async () => {
      const data = await api.get<PublicBranding | undefined>('/api/public/branding/');
      return data ?? null;
    },
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
  });
}
