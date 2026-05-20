/**
 * Auth provider for the staff app — slug-first.
 *
 * Sign-in is a two-step flow (see ADR 0031):
 *   1. the operator enters their workspace slug; the app validates it
 *      against `GET /api/public/branding/` and remembers it,
 *   2. then signs in with email + password, scoped to that workspace.
 *
 * Owns the session: the chosen workspace, the JWT token pair, and the
 * signed-in user. Persists workspace + tokens to the Keychain/Keystore
 * via `secure-store.ts` and exposes `authedFetch` — the authenticated
 * HTTP wrapper every feature screen uses.
 *
 * Status state machine, which drives routing (see `app/_layout.tsx`):
 *
 *   loading          → reading the Keychain at launch
 *   need-workspace   → no workspace chosen → workspace screen
 *   need-credentials → workspace known, no valid session → login screen
 *   signed-in        → authenticated → the app shell
 *
 * Token lifecycle: `authedFetch` refreshes proactively (decodes the
 * access token's `exp` and rotates before expiry) and reactively (on a
 * `token_not_valid` response). A failed refresh ends the session but
 * keeps the workspace, so the operator lands back on its login screen.
 */

import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type PropsWithChildren,
} from 'react';

import {
  ApiError,
  decodeJwtExp,
  fetchPublicBranding,
  isTokenError,
  mobileLogin,
  mobileLogout,
  mobileRefresh,
  request,
} from './api';
import {
  clearAll,
  clearTokens,
  loadSession,
  saveTokens,
  saveWorkspace,
} from './secure-store';
import type { TokenPair, User, Workspace } from './types';

export type AuthStatus =
  | 'loading'
  | 'need-workspace'
  | 'need-credentials'
  | 'signed-in';

/** Thrown by `setWorkspace` when no active tenant matches the slug. */
export class WorkspaceNotFoundError extends Error {
  constructor(public slug: string) {
    super(`No workspace found for "${slug}".`);
    this.name = 'WorkspaceNotFoundError';
  }
}

/** Thrown by `signIn` when the credentials are valid but the account
 *  has no membership in the selected workspace. */
export class WorkspaceAccessError extends Error {
  constructor(public workspaceName: string) {
    super(`This account doesn't have access to ${workspaceName}.`);
    this.name = 'WorkspaceAccessError';
  }
}

interface AuthContextValue {
  status: AuthStatus;
  workspace: Workspace | null;
  user: User | null;
  /** Validate + select a workspace by slug. Throws
   *  `WorkspaceNotFoundError` for an unknown slug. */
  setWorkspace: (slug: string) => Promise<void>;
  /** Forget the workspace and any session — back to slug entry. */
  changeWorkspace: () => Promise<void>;
  /** Sign in within the selected workspace. Throws `ApiError` on bad
   *  credentials, or `WorkspaceAccessError` when the account is valid
   *  but not a member of this workspace. */
  signIn: (email: string, password: string) => Promise<void>;
  /** End the session but keep the workspace. */
  signOut: () => Promise<void>;
  /** Authenticated request: attaches the bearer token + workspace
   *  header, refreshes on expiry. The fetch layer for feature screens. */
  authedFetch: <T>(path: string, init?: RequestInit) => Promise<T>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) {
    throw new Error('useAuth must be used inside <AuthProvider>');
  }
  return value;
}

/** Refresh this many seconds before the access token actually expires. */
const REFRESH_SKEW_SECONDS = 60;

export function AuthProvider({ children }: PropsWithChildren) {
  const [status, setStatus] = useState<AuthStatus>('loading');
  const [workspace, setWorkspaceState] = useState<Workspace | null>(null);
  const [user, setUser] = useState<User | null>(null);

  // Mutable mirrors so the request helpers always see live values
  // without being recreated on every render.
  const tokensRef = useRef<TokenPair | null>(null);
  const workspaceRef = useRef<Workspace | null>(null);
  const userRef = useRef<User | null>(null);
  const refreshInFlight = useRef<Promise<boolean> | null>(null);

  function rememberUser(next: User | null) {
    userRef.current = next;
    setUser(next);
  }

  function rememberWorkspace(next: Workspace | null) {
    workspaceRef.current = next;
    setWorkspaceState(next);
  }

  /** Drop the token pair + user but keep the workspace. */
  async function endSession() {
    tokensRef.current = null;
    refreshInFlight.current = null;
    rememberUser(null);
    await clearTokens();
    setStatus('need-credentials');
  }

  /** Refresh the token pair. De-duplicated — concurrent callers share
   *  one in-flight refresh. Returns whether a fresh pair was obtained. */
  function refreshTokens(): Promise<boolean> {
    if (refreshInFlight.current) return refreshInFlight.current;

    const attempt = (async () => {
      const current = tokensRef.current;
      if (!current) return false;
      try {
        const next = await mobileRefresh(current.refresh);
        tokensRef.current = next;
        await saveTokens(next);
        return true;
      } catch {
        return false;
      } finally {
        refreshInFlight.current = null;
      }
    })();

    refreshInFlight.current = attempt;
    return attempt;
  }

  /** One authenticated request — bearer token + workspace header. */
  function sendAuthed<T>(path: string, init?: RequestInit): Promise<T> {
    const headers: Record<string, string> = {
      ...(init?.headers as Record<string, string> | undefined),
    };
    const tokens = tokensRef.current;
    if (tokens) headers.Authorization = `Bearer ${tokens.access}`;
    if (workspaceRef.current) {
      headers['X-Tenant-Slug'] = workspaceRef.current.slug;
    }
    return request<T>(path, { ...init, headers });
  }

  async function authedFetch<T>(path: string, init?: RequestInit): Promise<T> {
    // Proactive: rotate before the access token lapses.
    const tokens = tokensRef.current;
    if (tokens) {
      const exp = decodeJwtExp(tokens.access);
      if (exp !== null && Date.now() / 1000 >= exp - REFRESH_SKEW_SECONDS) {
        await refreshTokens();
      }
    }

    try {
      return await sendAuthed<T>(path, init);
    } catch (error) {
      // Reactive: a token-invalid response → refresh once and retry.
      if (isTokenError(error)) {
        const refreshed = await refreshTokens();
        if (refreshed) return await sendAuthed<T>(path, init);
        // Refresh failed — the session is unrecoverable.
        await endSession();
      }
      throw error;
    }
  }

  // Launch: restore the session from the Keychain.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const session = await loadSession();
      if (cancelled) return;

      if (!session.workspace) {
        setStatus('need-workspace');
        return;
      }
      rememberWorkspace(session.workspace);

      if (!session.tokens) {
        setStatus('need-credentials');
        return;
      }
      tokensRef.current = session.tokens;

      try {
        const { user: me } = await authedFetch<{ user: User }>(
          '/api/auth/me/',
        );
        if (cancelled) return;
        const member = me.memberships.some(
          (m) => m.tenant.slug === session.workspace!.slug,
        );
        if (member) {
          rememberUser(me);
          setStatus('signed-in');
        } else {
          // Membership revoked since last launch.
          await endSession();
        }
      } catch {
        if (!cancelled) await endSession();
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function setWorkspace(slugInput: string) {
    const slug = slugInput.trim().toLowerCase();
    const branding = await fetchPublicBranding(slug);
    if (!branding) {
      throw new WorkspaceNotFoundError(slug);
    }
    const next: Workspace = {
      slug: branding.slug,
      name: branding.name,
      logoUrl: branding.logo_url,
    };
    rememberWorkspace(next);
    await saveWorkspace(next);
    setStatus('need-credentials');
  }

  async function changeWorkspace() {
    tokensRef.current = null;
    refreshInFlight.current = null;
    rememberUser(null);
    rememberWorkspace(null);
    await clearAll();
    setStatus('need-workspace');
  }

  async function signIn(email: string, password: string) {
    const ws = workspaceRef.current;
    if (!ws) throw new Error('No workspace selected.');

    const { access, refresh, user: me } = await mobileLogin(email, password);

    // The account must be a member of the workspace it's signing into.
    const member = me.memberships.some((m) => m.tenant.slug === ws.slug);
    if (!member) {
      throw new WorkspaceAccessError(ws.name);
    }

    const tokens: TokenPair = { access, refresh };
    tokensRef.current = tokens;
    await saveTokens(tokens);
    rememberUser(me);
    setStatus('signed-in');
  }

  async function signOut() {
    const tokens = tokensRef.current;
    if (tokens) {
      try {
        await mobileLogout(tokens.access, tokens.refresh);
      } catch {
        // Best-effort — local sign-out happens regardless.
      }
    }
    await endSession();
  }

  const value = useMemo<AuthContextValue>(
    () => ({
      status,
      workspace,
      user,
      setWorkspace,
      changeWorkspace,
      signIn,
      signOut,
      authedFetch,
    }),
    // The functions read refs, so their identity needn't track state;
    // the rendered values are what consumers care about.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [status, workspace, user],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export { ApiError };
