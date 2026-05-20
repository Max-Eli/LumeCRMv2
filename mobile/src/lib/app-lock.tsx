/**
 * App-lock — the device-security layer for PHI on a phone (Phase 4).
 *
 * A signed-in operator who leaves the app must re-authenticate with
 * biometrics (or the device passcode) to get back in. This is the
 * mobile equivalent of the web CRM's idle session timeout — an
 * unattended unlocked phone must not expose patient data.
 *
 * The lock engages:
 *   - on a cold start when a session is restored from the Keychain,
 *   - when the app returns to the foreground after `IDLE_LIMIT_MS` in
 *     the background.
 * It never engages right after a fresh email/password sign-in — the
 * operator just proved who they are.
 *
 * Expo Go cannot run Face ID (its Info.plist has no usage string), so
 * the lock is disabled there — Expo Go is a dev harness, not a
 * deployment target. In development builds and release builds the lock
 * is fully active. See ADR 0031.
 */

import Constants, { ExecutionEnvironment } from 'expo-constants';
import * as LocalAuthentication from 'expo-local-authentication';
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type PropsWithChildren,
} from 'react';
import { AppState } from 'react-native';

import { useAuth } from './auth';

/** Re-lock after this long in the background. */
const IDLE_LIMIT_MS = 5 * 60 * 1000;

const IS_EXPO_GO =
  Constants.executionEnvironment === ExecutionEnvironment.StoreClient;

interface AppLockValue {
  /** True when the signed-in app is covered by the lock screen. */
  locked: boolean;
  /** Prompt for biometrics / passcode. Resolves true once unlocked. */
  unlock: () => Promise<boolean>;
}

const AppLockContext = createContext<AppLockValue | null>(null);

export function useAppLock(): AppLockValue {
  const value = useContext(AppLockContext);
  if (!value) {
    throw new Error('useAppLock must be used inside <AppLockProvider>');
  }
  return value;
}

export function AppLockProvider({ children }: PropsWithChildren) {
  const { status } = useAuth();
  const [locked, setLocked] = useState(false);

  // Whether this device can actually be locked: not Expo Go, and a
  // biometric or passcode is enrolled. Refined once the async check
  // resolves; starts optimistic so a cold start fails secure.
  const lockable = useRef(!IS_EXPO_GO);
  const prevStatus = useRef(status);
  const backgroundedAt = useRef<number | null>(null);

  // Resolve whether the device has any enrolled security.
  useEffect(() => {
    if (IS_EXPO_GO) return;
    let cancelled = false;
    (async () => {
      const level = await LocalAuthentication.getEnrolledLevelAsync();
      if (cancelled) return;
      lockable.current = level !== LocalAuthentication.SecurityLevel.NONE;
      if (!lockable.current) setLocked(false);
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // Lock on a cold-start session restore; clear when signing out.
  useEffect(() => {
    const wasLoading = prevStatus.current === 'loading';
    if (status === 'signed-in' && wasLoading && lockable.current) {
      setLocked(true);
    }
    if (status !== 'signed-in') {
      setLocked(false);
      backgroundedAt.current = null;
    }
    prevStatus.current = status;
  }, [status]);

  // Idle re-lock: too long in the background → lock on return.
  useEffect(() => {
    const sub = AppState.addEventListener('change', (next) => {
      if (status !== 'signed-in' || !lockable.current) return;
      if (next === 'background' || next === 'inactive') {
        if (backgroundedAt.current === null) {
          backgroundedAt.current = Date.now();
        }
      } else if (next === 'active') {
        const since = backgroundedAt.current;
        backgroundedAt.current = null;
        if (since !== null && Date.now() - since > IDLE_LIMIT_MS) {
          setLocked(true);
        }
      }
    });
    return () => sub.remove();
  }, [status]);

  const unlock = useCallback(async () => {
    const result = await LocalAuthentication.authenticateAsync({
      promptMessage: 'Unlock Lumè CRM',
      cancelLabel: 'Cancel',
    });
    if (result.success) {
      setLocked(false);
      return true;
    }
    return false;
  }, []);

  const value = useMemo<AppLockValue>(
    () => ({ locked, unlock }),
    [locked, unlock],
  );

  return (
    <AppLockContext.Provider value={value}>
      {children}
    </AppLockContext.Provider>
  );
}
