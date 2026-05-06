/**
 * Location hooks — read + write the per-tenant locations list.
 *
 * Wraps `/api/locations/` (list, create, retrieve, update). A tenant
 * always has at least one location; multi-site businesses add more
 * via the `/org/locations` page (owner-only, gated by
 * `MANAGE_TENANT_SETTINGS` on the backend).
 *
 * Backend invariants the UI mirrors:
 *
 *   - A tenant always has exactly one default location.
 *   - The default location can't be deactivated (the LocationMiddleware
 *     fallback depends on it).
 *   - "Switching defaults" is a single PATCH with `is_default: true` —
 *     the backend atomically demotes the previous default in the same
 *     transaction.
 *
 * Active-location switching (the cookie that tells the backend which
 * site the operator picked from the location switcher) lands with
 * Phase 4E session 3 — a separate concern from this CRUD surface.
 */

'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useSyncExternalStore } from 'react';

import { api } from './api';

export interface Location {
  id: number;
  tenant_id: number;
  name: string;
  /** URL-safe identifier scoped to the tenant. Used by the active-
   *  location cookie (Phase 4E session 3). */
  slug: string;
  is_default: boolean;
  is_active: boolean;
  timezone: string;
  phone: string;
  email: string;
  address_line1: string;
  address_line2: string;
  city: string;
  state: string;
  zip_code: string;
  /** `HH:MM:SS` (DRF TimeField default). The calendar reads these to
   *  set its visible day window per location. */
  business_open_time: string;
  business_close_time: string;
  created_at: string;
  updated_at: string;
}

export interface CreateLocationInput {
  name: string;
  /** Optional — backend slugifies `name` when omitted. */
  slug?: string;
  is_default?: boolean;
  timezone?: string;
  phone?: string;
  email?: string;
  address_line1?: string;
  address_line2?: string;
  city?: string;
  state?: string;
  zip_code?: string;
  business_open_time?: string;
  business_close_time?: string;
}

export type UpdateLocationInput = Partial<
  Omit<Location, 'id' | 'tenant_id' | 'created_at' | 'updated_at'>
>;

const LOCATIONS_KEY = ['locations'] as const;
const locationDetailKey = (id: number) =>
  [...LOCATIONS_KEY, 'detail', id] as const;

/** List all locations for the current tenant. Read-only access is open
 *  to anyone in the tenant (front-desk needs this for the location
 *  switcher); the backend gates write endpoints separately. */
export function useLocations() {
  return useQuery<Location[]>({
    queryKey: LOCATIONS_KEY,
    queryFn: () => api.get<Location[]>('/api/locations/'),
    staleTime: 60 * 1000,
  });
}

/** Fetch one location's full detail. Returns 404 for cross-tenant ids. */
export function useLocation(id: number | undefined) {
  return useQuery<Location>({
    queryKey: locationDetailKey(id ?? 0),
    queryFn: () => api.get<Location>(`/api/locations/${id}/`),
    enabled: typeof id === 'number' && id > 0,
  });
}

/** Create a new location for the current tenant. Owner-only. */
export function useCreateLocation() {
  const qc = useQueryClient();
  return useMutation<Location, Error, CreateLocationInput>({
    mutationFn: (input) => api.post<Location>('/api/locations/', input),
    onSuccess: () => {
      // Promoting the new one to default also flips the previous
      // default's row, so invalidate the whole list.
      qc.invalidateQueries({ queryKey: LOCATIONS_KEY });
    },
  });
}

/** Patch a location. Owner-only. Setting `is_default: true` here
 *  triggers the backend's atomic-demote-previous-default flow, so we
 *  invalidate the list (not just the detail) on success. */
export function useUpdateLocation(locationId: number) {
  const qc = useQueryClient();
  return useMutation<Location, Error, UpdateLocationInput>({
    mutationFn: (input) =>
      api.patch<Location>(`/api/locations/${locationId}/`, input),
    onSuccess: (updated) => {
      qc.setQueryData(locationDetailKey(locationId), updated);
      qc.invalidateQueries({ queryKey: LOCATIONS_KEY });
    },
  });
}

/** Display label for a location. Falls back to the slug if name is
 *  somehow blank (shouldn't happen — backend requires it). */
export function locationDisplayName(location: Location): string {
  return location.name.trim() || location.slug;
}

/** True when the tenant has more than one active location. The
 *  organization-level UI surfaces (sidebar Org section, location
 *  switcher) only appear when this is true — single-location tenants
 *  get the original unified IA. */
export function hasMultipleLocations(locations: Location[] | undefined): boolean {
  if (!locations) return false;
  return locations.filter((l) => l.is_active).length > 1;
}

/** Cookie name shared with `LocationMiddleware` on the backend. The
 *  cookie value is a per-tenant location slug; a slug from the wrong
 *  tenant is silently ignored on both sides (frontend below + backend
 *  middleware), so a stale cookie can't ever resolve to a different
 *  tenant's site. */
export const ACTIVE_LOCATION_COOKIE = 'lume_active_location';

function readActiveLocationCookie(): string | null {
  if (typeof document === 'undefined') return null;
  const match = document.cookie.match(
    new RegExp(`(?:^|; )${ACTIVE_LOCATION_COOKIE}=([^;]*)`),
  );
  return match ? decodeURIComponent(match[1]) : null;
}

function writeActiveLocationCookie(slug: string): void {
  if (typeof document === 'undefined') return;
  // Path=/ so every route reads it; SameSite=Lax matches the active-
  // tenant cookie pattern. No explicit Max-Age — session cookie that
  // persists across browser tabs but expires on browser close (the
  // operator's intent on the next login is treated as fresh).
  document.cookie = `${ACTIVE_LOCATION_COOKIE}=${encodeURIComponent(slug)}; path=/; SameSite=Lax`;
  notifyActiveLocationChanged();
}

// ── Reactive cookie subscription ────────────────────────────────────
//
// `document.cookie` is not reactive, so writing to it doesn't cause
// React components that derived state from it to re-render. We bridge
// that gap with a tiny pub/sub: `useSwitchLocation` writes the cookie
// and then notifies subscribers; `useActiveLocation` subscribes via
// `useSyncExternalStore`. Result: switching sites in the sidebar makes
// the calendar (and any other consumer) re-render against the new
// location instantly, without a full reload.

const cookieSubscribers = new Set<() => void>();

function notifyActiveLocationChanged(): void {
  cookieSubscribers.forEach((fn) => {
    try {
      fn();
    } catch {
      // A subscriber throwing must not stop the others from running.
    }
  });
}

function subscribeActiveLocationCookie(callback: () => void): () => void {
  cookieSubscribers.add(callback);
  return () => {
    cookieSubscribers.delete(callback);
  };
}

function getActiveLocationCookieSnapshot(): string | null {
  return readActiveLocationCookie();
}

function getActiveLocationCookieServerSnapshot(): string | null {
  // SSR has no document; `useActiveLocation` falls back to the tenant
  // default in that case. The hydration pass picks up the real cookie
  // after the first client render.
  return null;
}

/** Subscribe to the active-location cookie value. Re-renders the
 *  caller whenever `useSwitchLocation()` writes a new slug. */
export function useActiveLocationSlug(): string | null {
  return useSyncExternalStore(
    subscribeActiveLocationCookie,
    getActiveLocationCookieSnapshot,
    getActiveLocationCookieServerSnapshot,
  );
}

/** Resolve the active location for the current tenant.
 *
 * Resolution order — mirrors `LocationMiddleware`:
 *   1. The location whose slug matches the `lume_active_location` cookie,
 *      if it exists in the tenant and is active.
 *   2. The tenant's default active location.
 *   3. `undefined` while the locations list is loading or if the tenant
 *      somehow has no active default (shouldn't happen — DB constraint
 *      enforces exactly one default per tenant).
 *
 * Wraps `useLocations()` so the result is cached and re-renders when the
 * list refreshes (e.g. after editing a location's hours, the calendar's
 * day-window updates without a full page reload).
 *
 * Returns the loading state too so callers can render the calendar /
 * dashboard with placeholder bounds while the request is in flight,
 * rather than rendering with the wrong default.
 */
export function useActiveLocation(): {
  location: Location | undefined;
  isLoading: boolean;
} {
  const { data: locations, isLoading } = useLocations();
  // Reactive subscription — re-renders when `useSwitchLocation()`
  // writes a new value, so the calendar / dashboard / any consumer
  // updates without a reload.
  const cookieSlug = useActiveLocationSlug();
  if (!locations) {
    return { location: undefined, isLoading };
  }
  if (cookieSlug) {
    const fromCookie = locations.find(
      (l) => l.slug === cookieSlug && l.is_active,
    );
    if (fromCookie) return { location: fromCookie, isLoading };
  }
  const fallback = locations.find((l) => l.is_default && l.is_active);
  return { location: fallback, isLoading };
}

/** Switch the active location for the current tenant.
 *
 *   const switchLocation = useSwitchLocation();
 *   switchLocation('manhattan');
 *
 * Writes the `lume_active_location` cookie, notifies every component
 * using `useActiveLocation()` to re-render, and invalidates queries
 * that depend on the active location (currently appointments — the
 * day-window timezone shifts per site). Future location-scoped
 * resources (Phase 4E session 4: Appointment.location FK; later:
 * provider working hours, location-specific service availability)
 * should add their query keys to the invalidation list here so the UI
 * stays consistent.
 *
 * The hook does NOT validate the slug against the locations list —
 * the caller (the LocationSwitcher popover) only offers slugs that
 * already belong to the tenant. The backend `LocationMiddleware`
 * silently ignores cross-tenant or stale cookie values anyway, so a
 * bad slug degrades gracefully to "fall back to default".
 */
export function useSwitchLocation(): (slug: string) => void {
  const qc = useQueryClient();
  return (slug: string) => {
    writeActiveLocationCookie(slug);
    // Location-scoped queries: appointments (day-window timezone +
    // location-scoped queryset) and memberships (bookable providers
    // are filtered by location assignment). The bookable hook also
    // embeds the location slug in its query key so it would refetch
    // anyway; the explicit invalidate keeps both code paths
    // consistent and covers any future location-scoped query that
    // forgets to include the slug.
    qc.invalidateQueries({ queryKey: ['appointments'] });
    qc.invalidateQueries({ queryKey: ['memberships'] });
  };
}
