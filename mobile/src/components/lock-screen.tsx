import { useCallback, useEffect, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { Button } from '@/components/ui/button';
import { colors, fonts, fontSize, spacing } from '@/constants/theme';
import { useAppLock } from '@/lib/app-lock';
import { useAuth } from '@/lib/auth';

/**
 * Full-screen overlay shown when the signed-in app is locked. Prompts
 * for biometrics / passcode on appearance; "Sign out" is always
 * available so a failed unlock never traps the operator.
 */
export function LockScreen() {
  const { unlock } = useAppLock();
  const { signOut } = useAuth();
  const [busy, setBusy] = useState(false);

  const attempt = useCallback(async () => {
    setBusy(true);
    try {
      await unlock();
    } finally {
      setBusy(false);
    }
  }, [unlock]);

  // Prompt as soon as the lock screen appears.
  useEffect(() => {
    attempt();
  }, [attempt]);

  return (
    <View style={styles.overlay}>
      <SafeAreaView style={styles.safe}>
        <View style={styles.center}>
          <Text style={styles.wordmark}>Lumè</Text>
          <Text style={styles.message}>
            Locked to keep patient information private.
          </Text>
        </View>

        <View style={styles.actions}>
          <Button label="Unlock" onPress={attempt} loading={busy} />
          <Pressable
            onPress={signOut}
            accessibilityRole="button"
            style={styles.signOut}
          >
            <Text style={styles.signOutText}>Sign out</Text>
          </Pressable>
        </View>
      </SafeAreaView>
    </View>
  );
}

const styles = StyleSheet.create({
  overlay: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: colors.background,
    zIndex: 100,
  },
  safe: {
    flex: 1,
    paddingHorizontal: spacing.xl,
    paddingVertical: spacing.xxl,
  },
  center: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    gap: spacing.sm,
  },
  wordmark: {
    fontFamily: fonts.serif,
    fontSize: 44,
    color: colors.foreground,
    letterSpacing: -0.5,
  },
  message: {
    fontFamily: fonts.sans,
    fontSize: fontSize.sm,
    color: colors.mutedForeground,
    textAlign: 'center',
  },
  actions: {
    gap: spacing.sm,
  },
  signOut: {
    alignItems: 'center',
    paddingVertical: spacing.sm,
  },
  signOutText: {
    fontFamily: fonts.sans,
    fontSize: fontSize.sm,
    fontWeight: '600',
    color: colors.accent,
  },
});
