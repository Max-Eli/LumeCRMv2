import { useState } from 'react';
import {
  KeyboardAvoidingView,
  Platform,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { Button } from '@/components/ui/button';
import { TextField } from '@/components/ui/text-field';
import { colors, fonts, fontSize, spacing } from '@/constants/theme';
import { useAuth, WorkspaceNotFoundError } from '@/lib/auth';

/**
 * Step 1 of sign-in (see ADR 0031): the operator enters their
 * workspace slug. It's validated against the public branding endpoint
 * before the app advances to the credentials screen, so a typo is
 * caught here rather than after a password attempt.
 */
export default function WorkspaceScreen() {
  const { setWorkspace } = useAuth();
  const [slug, setSlug] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit() {
    if (submitting) return;
    setError(null);

    const value = slug.trim().toLowerCase();
    if (!value) {
      setError('Enter your workspace name.');
      return;
    }

    setSubmitting(true);
    try {
      await setWorkspace(value);
      // On success the auth status flips to need-credentials.
    } catch (e) {
      setError(
        e instanceof WorkspaceNotFoundError
          ? `We couldn't find a workspace called "${value}".`
          : 'Something went wrong. Check your connection and try again.',
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <SafeAreaView style={styles.safe}>
      <KeyboardAvoidingView
        style={styles.flex}
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      >
        <ScrollView
          contentContainerStyle={styles.scroll}
          keyboardShouldPersistTaps="handled"
        >
          <View style={styles.header}>
            <Text style={styles.wordmark}>Lumè</Text>
            <Text style={styles.subtitle}>Staff app</Text>
          </View>

          <View style={styles.form}>
            <Text style={styles.title}>Find your workspace</Text>
            <Text style={styles.help}>
              Enter the short workspace name your spa uses. Ask your
              manager if you&apos;re not sure.
            </Text>

            <TextField
              label="Workspace"
              value={slug}
              onChangeText={setSlug}
              autoCapitalize="none"
              autoCorrect={false}
              autoComplete="off"
              returnKeyType="go"
              editable={!submitting}
              onSubmitEditing={onSubmit}
              placeholder="your-spa-name"
            />

            {error != null ? <Text style={styles.error}>{error}</Text> : null}

            <Button
              label="Continue"
              onPress={onSubmit}
              loading={submitting}
              style={styles.submit}
            />
          </View>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: {
    flex: 1,
    backgroundColor: colors.background,
  },
  flex: {
    flex: 1,
  },
  scroll: {
    flexGrow: 1,
    justifyContent: 'center',
    paddingHorizontal: spacing.xl,
    paddingVertical: spacing.xxl,
    gap: spacing.xxl,
  },
  header: {
    alignItems: 'center',
    gap: spacing.xs,
  },
  wordmark: {
    fontFamily: fonts.serif,
    fontSize: 44,
    color: colors.foreground,
    letterSpacing: -0.5,
  },
  subtitle: {
    fontFamily: fonts.sans,
    fontSize: fontSize.sm,
    textTransform: 'uppercase',
    letterSpacing: 2,
    color: colors.mutedForeground,
  },
  form: {
    gap: spacing.md,
  },
  title: {
    fontFamily: fonts.serif,
    fontSize: fontSize.xl,
    color: colors.foreground,
    letterSpacing: -0.3,
  },
  help: {
    fontFamily: fonts.sans,
    fontSize: fontSize.sm,
    color: colors.mutedForeground,
    lineHeight: 20,
    marginBottom: spacing.xs,
  },
  error: {
    fontFamily: fonts.sans,
    fontSize: fontSize.sm,
    color: colors.destructive,
  },
  submit: {
    marginTop: spacing.xs,
  },
});
