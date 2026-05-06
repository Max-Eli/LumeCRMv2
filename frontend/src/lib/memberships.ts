/**
 * Tenant-membership data hooks.
 *
 * Reads staff memberships (the bridge between User and Tenant). Used by the
 * booking calendar to populate provider columns, and by future admin UIs
 * for staff management.
 *
 * `useBookableMemberships()` is **location-scoped**: passes
 * `?location=current` so the calendar at the active site only shows
 * providers actually assigned to that location. The query key includes the
 * active-location slug so switching sites flips the cache cleanly
 * (TanStack treats different keys as different queries). The shared
 * `['memberships']` namespace also lets `useSwitchLocation()`'s broad
 * invalidate sweep both this query and the all-staff one.
 */

'use client';

import { useQuery } from '@tanstack/react-query';

import { api } from './api';
import { useActiveLocationSlug } from './locations';

export interface Membership {
  id: number;
  user_email: string;
  user_first_name: string;
  user_last_name: string;
  role:
    | 'owner'
    | 'manager'
    | 'front_desk'
    | 'provider'
    | 'bookkeeper'
    | 'marketing';
  /** Used to match against `ServiceCategory.eligible_job_titles` when validating drop targets. */
  job_title_id: number | null;
  job_title_name: string | null;
  job_title_is_clinical: boolean;
  is_bookable: boolean;
  is_active: boolean;
  /** Location-scoped fields — populated only when the request used
   *  `?location=current|<slug>` (which the calendar always does).
   *  Null on org-wide responses (the staff list). */
  membership_location_id?: number | null;
  /** Schedule for the active location. `null` means "no schedule set"
   *  (provider bookable any time within business hours); empty arrays
   *  per day means "explicitly off." Object shape mirrors backend
   *  `ProviderSchedule.weekly_hours`. */
  schedule_for_location?: Record<string, Array<{ start: string; end: string }>> | null;
}

/** Display name for a membership — first + last, falling back to email. */
export function membershipName(m: Membership): string {
  const full = `${m.user_first_name} ${m.user_last_name}`.trim();
  return full || m.user_email;
}

export function useBookableMemberships() {
  // Embed the active-location slug in the key so switching sites
  // re-fetches against the new location. `useActiveLocationSlug()` is
  // a `useSyncExternalStore` over the `lume_active_location` cookie —
  // it re-renders this hook the instant `useSwitchLocation()` writes
  // a new value. Passing `?location=current` to the API tells the
  // backend to filter by the request's active location (resolved from
  // the same cookie via `LocationMiddleware`); both ends agree on
  // which site is in scope.
  const slug = useActiveLocationSlug();
  return useQuery<Membership[]>({
    queryKey: ['memberships', { bookable: true, active: true, location: slug ?? 'default' }],
    queryFn: () =>
      api.get<Membership[]>(
        '/api/memberships/?bookable=true&active=true&location=current',
      ),
    staleTime: 5 * 60 * 1000,
  });
}
