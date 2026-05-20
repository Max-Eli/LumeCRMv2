/**
 * Encrypted persistence for the auth session.
 *
 * Wraps `expo-secure-store`, which stores values in the iOS Keychain /
 * Android Keystore (hardware-backed where the device supports it) — the
 * HIPAA-appropriate place for credentials at rest. Only the JWT pair
 * and the chosen workspace are persisted; PHI is never written to the
 * device.
 *
 * `WHEN_UNLOCKED_THIS_DEVICE_ONLY`: values are readable only while the
 * device is unlocked, and are excluded from encrypted backups, so a
 * token cannot ride a backup onto a different device.
 */

import * as SecureStore from 'expo-secure-store';

import type { TokenPair, Workspace } from './types';

const ACCESS_KEY = 'lume.auth.access';
const REFRESH_KEY = 'lume.auth.refresh';
const WORKSPACE_KEY = 'lume.auth.workspace';

const OPTIONS: SecureStore.SecureStoreOptions = {
  keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY,
};

export interface StoredSession {
  tokens: TokenPair | null;
  workspace: Workspace | null;
}

/** Read the full persisted session in one pass (called once at launch). */
export async function loadSession(): Promise<StoredSession> {
  const [access, refresh, workspaceRaw] = await Promise.all([
    SecureStore.getItemAsync(ACCESS_KEY),
    SecureStore.getItemAsync(REFRESH_KEY),
    SecureStore.getItemAsync(WORKSPACE_KEY),
  ]);

  let workspace: Workspace | null = null;
  if (workspaceRaw) {
    try {
      const parsed = JSON.parse(workspaceRaw);
      if (parsed?.slug && parsed?.name) {
        workspace = { slug: parsed.slug, name: parsed.name };
      }
    } catch {
      workspace = null;
    }
  }

  return {
    tokens: access && refresh ? { access, refresh } : null,
    workspace,
  };
}

/** Persist a freshly issued token pair (login or refresh-rotation). */
export async function saveTokens(tokens: TokenPair): Promise<void> {
  await Promise.all([
    SecureStore.setItemAsync(ACCESS_KEY, tokens.access, OPTIONS),
    SecureStore.setItemAsync(REFRESH_KEY, tokens.refresh, OPTIONS),
  ]);
}

/** Persist the operator's chosen workspace. */
export async function saveWorkspace(workspace: Workspace): Promise<void> {
  await SecureStore.setItemAsync(
    WORKSPACE_KEY,
    JSON.stringify(workspace),
    OPTIONS,
  );
}

/** Drop the token pair but keep the workspace — used on sign-out, so
 *  the next sign-in opens straight to the same workspace's login. */
export async function clearTokens(): Promise<void> {
  await Promise.all([
    SecureStore.deleteItemAsync(ACCESS_KEY),
    SecureStore.deleteItemAsync(REFRESH_KEY),
  ]);
}

/** Wipe everything — tokens and workspace — used when switching to a
 *  different workspace. */
export async function clearAll(): Promise<void> {
  await Promise.all([
    SecureStore.deleteItemAsync(ACCESS_KEY),
    SecureStore.deleteItemAsync(REFRESH_KEY),
    SecureStore.deleteItemAsync(WORKSPACE_KEY),
  ]);
}
