import { QueryClient } from '@tanstack/react-query';

/**
 * Shared React Query client. Conservative defaults for a mobile data
 * surface — data is briefly fresh so tab-switching doesn't refetch,
 * one retry to ride out a flaky connection, and no window-focus
 * refetch (there is no window on a phone; screens refetch explicitly).
 */
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30 * 1000,
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});
