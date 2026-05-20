import { Stack } from 'expo-router';

import { colors } from '@/constants/theme';

/**
 * Authenticated app shell. A plain stack for now — Phase 5 turns this
 * into the tab navigator (Today / Clients / Check-in / More).
 */
export default function AppLayout() {
  return (
    <Stack
      screenOptions={{
        headerShown: false,
        contentStyle: { backgroundColor: colors.background },
      }}
    />
  );
}
