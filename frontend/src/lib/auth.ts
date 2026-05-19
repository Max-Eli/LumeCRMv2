/**
 * Auth state hooks for the Lumè frontend.
 *
 * Backed by Django session cookies + DRF SessionAuthentication. The
 * `useUser` hook is the single source of truth for "is the visitor logged in"
 * across the app — read it from any client component.
 *
 * Login and logout are mutations that invalidate or set the user query cache
 * directly so the UI updates without a page refresh.
 */

'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { ACTIVE_TENANT_COOKIE, ApiError, api } from './api';

function setActiveTenantCookie(slug: string | undefined) {
  if (typeof document === 'undefined') return;
  if (slug) {
    document.cookie = `${ACTIVE_TENANT_COOKIE}=${encodeURIComponent(slug)}; path=/; SameSite=Lax`;
  } else {
    document.cookie = `${ACTIVE_TENANT_COOKIE}=; path=/; SameSite=Lax; max-age=0`;
  }
}

/** A user's membership in a single tenant — role, job title, bookable flag. */
export interface Membership {
  tenant: { id: number; name: string; slug: string };
  role: 'owner' | 'manager' | 'front_desk' | 'provider' | 'bookkeeper' | 'marketing';
  role_display: string;
  is_bookable: boolean;
}

/** Authenticated user record returned by `/api/auth/me/` and `/api/auth/login/`. */
export interface User {
  id: number;
  email: string;
  first_name: string;
  last_name: string;
  is_superuser: boolean;
  /** True for Lumè-the-platform staff. They authenticate via
   *  `/api/auth/platform/login/` (NOT the regular login endpoint) and
   *  access `/platform/*`. Platform admins are required to have
   *  zero tenant memberships — the customer and platform worlds are
   *  deliberately disjoint. */
  is_platform_admin: boolean;
  memberships: Membership[];
}

const USER_KEY = ['auth', 'me'] as const;

/**
 * Subscribe to the current user's auth state.
 *
 * Returns `data: User` if authenticated, `data: null` if not, `isLoading: true`
 * while the initial check is in flight. Use this to gate routes (see
 * `(app)/layout.tsx`) and to display user info in the UI.
 */
export function useUser() {
  return useQuery<User | null>({
    queryKey: USER_KEY,
    queryFn: async () => {
      try {
        const res = await api.get<{ user: User }>('/api/auth/me/');
        return res.user;
      } catch (e) {
        // 401 (no auth backends) or 403 (not authenticated) both → "no current user"
        if (e instanceof ApiError && (e.status === 401 || e.status === 403)) {
          return null;
        }
        throw e;
      }
    },
    retry: false,
    staleTime: 5 * 60 * 1000,
  });
}

/**
 * Mutation that signs the user in.
 *
 * Ensures the CSRF cookie is set before posting credentials, then writes the
 * returned user into the query cache so `useUser` updates immediately. Throws
 * an `ApiError` with status 401 on bad credentials — caller should use that
 * to render an inline form error rather than a toast.
 */
export function useLogin() {
  const qc = useQueryClient();
  return useMutation<User, Error, { email: string; password: string }>({
    mutationFn: async (creds) => {
      // Ensure the CSRF cookie is set before posting
      await api.get('/api/auth/csrf/');
      const res = await api.post<{ user: User }>('/api/auth/login/', creds);
      return res.user;
    },
    onSuccess: (user) => {
      qc.setQueryData(USER_KEY, user);
      // Pick the first active membership as the active tenant for subsequent
      // API calls. When we add multi-tenant switching UI, this becomes a user choice.
      setActiveTenantCookie(user.memberships[0]?.tenant.slug);
    },
  });
}

/**
 * Resolve the current user's membership in the active tenant.
 *
 * The active tenant is the one in the `lume_active_tenant` cookie (set on
 * login). Returns `null` if not logged in, no membership matches, or
 * we're rendering server-side (no document/cookie access).
 *
 * Use this anywhere you need to gate UI by tenant role — e.g. show a
 * Reopen button only to owners and managers.
 */
export function useCurrentMembership(): Membership | null {
  const { data: user } = useUser();
  if (!user || typeof document === 'undefined') return null;
  const match = document.cookie.match(
    new RegExp(`(?:^|; )${ACTIVE_TENANT_COOKIE}=([^;]*)`),
  );
  const slug = match ? decodeURIComponent(match[1]) : null;
  if (!slug) return user.memberships[0] ?? null;
  return user.memberships.find((m) => m.tenant.slug === slug) ?? null;
}

/**
 * Mutation that signs a platform admin in via the dedicated endpoint.
 *
 * Endpoint: `POST /api/auth/platform/login/`. Strict gate on the
 * backend (is_platform_admin=True + zero memberships); a regular
 * tenant user posting here gets a generic invalid-credentials error
 * with no information leak. On success, redirect target is
 * `/platform`, NOT `/dashboard` — platform admins don't have a
 * customer-facing surface.
 */
export function usePlatformLogin() {
  const qc = useQueryClient();
  return useMutation<User, Error, { email: string; password: string }>({
    mutationFn: async (creds) => {
      await api.get('/api/auth/csrf/');
      const res = await api.post<{ user: User }>('/api/auth/platform/login/', creds);
      return res.user;
    },
    onSuccess: (user) => {
      qc.setQueryData(USER_KEY, user);
      // Platform admins have no active tenant — clear the cookie so a
      // stale slug from a previous tenant session doesn't leak into
      // X-Tenant-Slug headers on platform endpoints (which ignore it,
      // but cleanliness counts).
      setActiveTenantCookie(undefined);
    },
  });
}

/**
 * Mutation that signs the user out.
 *
 * Clears the user from the query cache and removes ALL cached queries — necessary
 * because most cached data is tenant-scoped PHI that the next user (if anyone
 * logs in on the same browser) must not see.
 */
export function useLogout() {
  const qc = useQueryClient();
  return useMutation<void, Error, void>({
    mutationFn: async () => {
      await api.post('/api/auth/logout/');
    },
    onSuccess: () => {
      qc.setQueryData(USER_KEY, null);
      qc.removeQueries();
      setActiveTenantCookie(undefined);
    },
  });
}

/** Change the signed-in user's password. Requires the current
 *  password (defends against a hijacked session). On success the
 *  current browser stays signed in; every other open session is
 *  invalidated by Django's session-key rotation. */
export interface ChangePasswordInput {
  current_password: string;
  new_password: string;
  confirm_password: string;
}

export function useChangePassword() {
  return useMutation<void, Error, ChangePasswordInput>({
    mutationFn: async (input) => {
      await api.post('/api/auth/change-password/', input);
    },
  });
}

/** Verify an email + password belongs to an active staff member at
 *  the tenant, WITHOUT opening a session. Used by the kiosk-unlock
 *  flow on the public form-sign page (`/sign/[token]`): front-desk
 *  hands the iPad to a customer, locks the page, and any staff
 *  member can unlock by typing their CRM credentials.
 *
 *  Returns `{ ok: true, email }` on success or throws an `ApiError`
 *  with status 401 on bad creds / no active membership. */
export function useVerifyCredentials() {
  return useMutation<{ ok: true; email: string }, Error, { email: string; password: string }>({
    mutationFn: async (input) => {
      await api.get('/api/auth/csrf/');
      return api.post<{ ok: true; email: string }>('/api/auth/verify-credentials/', input);
    },
  });
}
