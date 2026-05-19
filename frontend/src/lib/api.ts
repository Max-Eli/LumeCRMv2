/**
 * Thin fetch wrapper that talks to the Django backend.
 *
 * Uses session cookies (credentials: 'include') so login state is shared between
 * subdomains under the same parent domain (e.g. *.lume-crm.com).
 *
 * For state-changing methods (POST/PUT/PATCH/DELETE) we attach the CSRF token
 * Django sets in the `csrftoken` cookie. Frontend should hit `/api/auth/csrf/`
 * once on mount before any login attempt to ensure the cookie is set.
 *
 * When we move to Cognito in Phase 0c, this is the file to swap.
 */

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

const MUTATING_METHODS = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);

/**
 * Cookie name used to communicate the active tenant slug to the backend.
 * Set on login (`useLogin`), cleared on logout (`useLogout`). The api wrapper
 * reads it and forwards it as `X-Tenant-Slug` header on every request.
 *
 * In production with subdomain routing (acmespa.lume-crm.com) this is unused —
 * the backend resolves tenant from the request host. In dev where both
 * frontend and backend run on `localhost`, we need an out-of-band signal.
 */
export const ACTIVE_TENANT_COOKIE = 'lume_active_tenant';

/**
 * Thrown by the `api` helper when the backend returns a non-2xx response.
 * Inspect `status` (HTTP code) and `body` (parsed JSON if present) to handle
 * specific error cases — e.g. 401/403 for unauthenticated, 400 for validation.
 */
export class ApiError extends Error {
  constructor(
    public status: number,
    public body: unknown,
    message: string,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

function getCookie(name: string): string | null {
  if (typeof document === 'undefined') return null;
  const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
  return match ? decodeURIComponent(match[1]) : null;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const method = (init.method ?? 'GET').toUpperCase();

  // For FormData bodies the browser sets `Content-Type` with the
  // correct multipart boundary — overriding it breaks the upload.
  const isFormData = typeof FormData !== 'undefined' && init.body instanceof FormData;

  const headers: Record<string, string> = {
    Accept: 'application/json',
    ...(isFormData ? {} : { 'Content-Type': 'application/json' }),
    ...(init.headers as Record<string, string> | undefined),
  };

  if (MUTATING_METHODS.has(method)) {
    const csrf = getCookie('csrftoken');
    if (csrf) headers['X-CSRFToken'] = csrf;
  }

  const tenantSlug = getCookie(ACTIVE_TENANT_COOKIE);
  if (tenantSlug) headers['X-Tenant-Slug'] = tenantSlug;

  const res = await fetch(`${API_URL}${path}`, {
    credentials: 'include',
    ...init,
    method,
    headers,
  });

  if (!res.ok) {
    let body: unknown = null;
    try {
      body = await res.json();
    } catch {
      // response had no JSON body — fine
    }
    throw new ApiError(res.status, body, `Request failed: ${res.status} ${res.statusText}`);
  }

  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export const api = {
  get: <T = unknown>(path: string) => request<T>(path),
  post: <T = unknown>(path: string, body?: unknown) =>
    request<T>(path, {
      method: 'POST',
      body: body !== undefined ? JSON.stringify(body) : undefined,
    }),
  put: <T = unknown>(path: string, body?: unknown) =>
    request<T>(path, {
      method: 'PUT',
      body: body !== undefined ? JSON.stringify(body) : undefined,
    }),
  patch: <T = unknown>(path: string, body?: unknown) =>
    request<T>(path, {
      method: 'PATCH',
      body: body !== undefined ? JSON.stringify(body) : undefined,
    }),
  delete: <T = unknown>(path: string) => request<T>(path, { method: 'DELETE' }),
  /** POST a multipart/form-data body (e.g. file uploads). The caller
   *  builds the FormData; the request wrapper leaves Content-Type
   *  unset so the browser supplies the multipart boundary. */
  upload: <T = unknown>(path: string, form: FormData) =>
    request<T>(path, { method: 'POST', body: form }),
};
