import { Stack } from 'expo-router';

import { LockScreen } from '@/components/lock-screen';
import { colors } from '@/constants/theme';
import { useAppLock } from '@/lib/app-lock';

/**
 * Authenticated app shell. A plain stack for now — Phase 5 turns this
 * into the tab navigator (Today / Clients / Check-in / More).
 *
 * When the app-lock engages, the lock screen covers the whole shell
 * until the operator re-authenticates.
 */
export default function AppLayout() {
  const { locked } = useAppLock();

  return (
    <>
      <Stack
        screenOptions={{
          headerShown: false,
          contentStyle: { backgroundColor: colors.background },
        }}
      />
      {locked ? <LockScreen /> : null}
    </>
  );
}
