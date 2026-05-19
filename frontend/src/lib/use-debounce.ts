/**
 * Tiny debounce hook for search inputs.
 *
 * Use it to delay propagating a fast-changing value (typing into a
 * search box) so dependents — usually a React Query whose `queryKey`
 * embeds the value — don't refetch on every keystroke.
 *
 * Pattern:
 *   const [search, setSearch] = useState('');
 *   const debounced = useDebounce(search, 250);
 *   const { data } = useCustomers({ q: debounced });
 *
 * The input stays controlled + responsive; only the network call is
 * debounced.
 */

'use client';

import { useEffect, useState } from 'react';

export function useDebounce<T>(value: T, delay = 250): T {
  const [debounced, setDebounced] = useState(value);

  useEffect(() => {
    const id = window.setTimeout(() => setDebounced(value), delay);
    return () => window.clearTimeout(id);
  }, [value, delay]);

  return debounced;
}
