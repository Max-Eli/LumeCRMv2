/**
 * Low-level HTTP layer for the Lumè API.
 *
 * This module holds only the pieces that need no auth state: the
 * `ApiError` type, the `request()` primitive, the unauthenticated
 * `mobile*` auth calls, and a JWT-expiry helper. The authenticated
 * fetch wrapper (token header, refresh-on-failure) lives in the auth
 * provider — see `auth.tsx` — because it needs live token state.
 */

import { API_BASE_URL } from './config';
import type { TenantBranding, TokenPair, User } from './types';

/** A non-2xx API response. `code` is the backend's machine-readable
 *  error code when one was supplied (e.g. `token_not_valid`,
 *  `platform_admin_account`). */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string | null;
  readonly data: unknown;

  constructor(status: number, message: string, data: unknown) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.data = data;
    this.code =
      data && typeof data === 'object' && 'code' in data
        ? String((data as { code: unknown }).code)
        : null;
  }
}

/** A token-expiry / token-invalid error — the signal to attempt a
 *  refresh. The backend returns these with `code: 'token_not_valid'`. */
export function isTokenError(error: unknown): boolean {
  return error instanceof ApiError && error.code === 'token_not_valid';
}

/** Core request primitive: fetches, parses JSON, throws `ApiError` on
 *  any non-2xx status. */
export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, init);

  const text = await response.text();
  let data: unknown = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = text;
    }
  }

  if (!response.ok) {
    const detail =
      data && typeof data === 'object' && 'detail' in data
        ? String((data as { detail: unknown }).detail)
        : `Request failed (${response.status})`;
    throw new ApiError(response.status, detail, data);
  }

  return data as T;
}

/** Build a JSON POST init, optionally with extra headers. */
export function jsonPost(
  body: unknown,
  headers?: Record<string, string>,
): RequestInit {
  return {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...headers },
    body: JSON.stringify(body),
  };
}

// ─── Unauthenticated auth endpoints ──────────────────────────────────

/** `POST /api/auth/mobile/login/` */
export function mobileLogin(
  email: string,
  password: string,
): Promise<TokenPair & { user: User }> {
  return request('/api/auth/mobile/login/', jsonPost({ email, password }));
}

/** `POST /api/auth/mobile/refresh/` — rotation returns a new pair. */
export function mobileRefresh(refresh: string): Promise<TokenPair> {
  return request('/api/auth/mobile/refresh/', jsonPost({ refresh }));
}

/** `POST /api/auth/mobile/logout/` — blacklists the refresh token. */
export function mobileLogout(accessToken: string, refresh: string): Promise<void> {
  return request('/api/auth/mobile/logout/', jsonPost({ refresh }, {
    Authorization: `Bearer ${accessToken}`,
  }));
}

/** `POST /api/auth/verify-credentials/` — confirm an email + password
 *  belong to an active staff member, without opening a session. Used
 *  by the consent-form kiosk unlock. Resolves `true` on success. */
export async function verifyCredentials(
  email: string,
  password: string,
): Promise<boolean> {
  try {
    await request('/api/auth/verify-credentials/', jsonPost({ email, password }));
    return true;
  } catch {
    return false;
  }
}

/** `GET /api/public/branding/` — resolve a workspace by slug.
 *
 *  Public + unauthenticated. The tenant is resolved server-side from
 *  the `X-Tenant-Slug` header. Returns the workspace's identity, or
 *  `null` when no active tenant matches (the endpoint answers 204) —
 *  the signal for an unknown workspace slug. */
export async function fetchPublicBranding(
  slug: string,
): Promise<TenantBranding | null> {
  const data = await request<TenantBranding | null>('/api/public/branding/', {
    headers: { 'X-Tenant-Slug': slug },
  });
  return data && typeof data === 'object' ? data : null;
}

// ─── JWT helpers ─────────────────────────────────────────────────────

const B64_ALPHABET =
  'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';

/** Decode a base64url segment to a byte string. Dependency-free — JWT
 *  claim payloads are ASCII JSON, so no UTF-8 handling is needed. */
function base64UrlDecode(input: string): string {
  const normalized = input.replace(/-/g, '+').replace(/_/g, '/');
  let out = '';
  let bits = 0;
  let value = 0;
  for (const char of normalized) {
    if (char === '=') break;
    const index = B64_ALPHABET.indexOf(char);
    if (index === -1) continue;
    value = (value << 6) | index;
    bits += 6;
    if (bits >= 8) {
      bits -= 8;
      out += String.fromCharCode((value >> bits) & 0xff);
    }
  }
  return out;
}

/** The `exp` claim (unix seconds) of a JWT, or null if unreadable. */
export function decodeJwtExp(token: string): number | null {
  try {
    const payload = token.split('.')[1];
    if (!payload) return null;
    const claims = JSON.parse(base64UrlDecode(payload)) as { exp?: unknown };
    return typeof claims.exp === 'number' ? claims.exp : null;
  } catch {
    return null;
  }
}
