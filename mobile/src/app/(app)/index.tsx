import { useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { Button } from '@/components/ui/button';
import { colors, fonts, fontSize, spacing } from '@/constants/theme';
import { useAuth } from '@/lib/auth';

/**
 * Authenticated home — a placeholder for Phase 3. It proves the full
 * loop (login → workspace → authenticated shell → sign out) and is
 * replaced by the Today screen in Phase 5.
 */
export default function AppHomeScreen() {
  const { user, workspace, signOut } = useAuth();
  const [signingOut, setSigningOut] = useState(false);

  const firstName = user?.first_name?.trim() || user?.email || 'there';

  async function onSignOut() {
    if (signingOut) return;
    setSigningOut(true);
    try {
      await signOut();
    } finally {
      setSigningOut(false);
    }
  }

  return (
    <SafeAreaView style={styles.safe}>
      <View style={styles.content}>
        <View style={styles.header}>
          {workspace ? (
            <Text style={styles.eyebrow}>{workspace.name}</Text>
          ) : null}
          <Text style={styles.greeting}>Hi, {firstName}</Text>
          <Text style={styles.note}>
            The staff app shell is in place. Today, clients, and check-in
            screens arrive in the next phases.
          </Text>
        </View>

        <Button
          label="Sign out"
          variant="secondary"
          onPress={onSignOut}
          loading={signingOut}
        />
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: {
    flex: 1,
    backgroundColor: colors.background,
  },
  content: {
    flex: 1,
    justifyContent: 'space-between',
    paddingHorizontal: spacing.xl,
    paddingVertical: spacing.xxl,
  },
  header: {
    gap: spacing.sm,
  },
  eyebrow: {
    fontFamily: fonts.sans,
    fontSize: fontSize.xs,
    textTransform: 'uppercase',
    letterSpacing: 2,
    color: colors.mutedForeground,
  },
  greeting: {
    fontFamily: fonts.serif,
    fontSize: fontSize.xxl,
    color: colors.foreground,
    letterSpacing: -0.5,
  },
  note: {
    fontFamily: fonts.sans,
    fontSize: fontSize.base,
    color: colors.mutedForeground,
    lineHeight: 22,
  },
});
