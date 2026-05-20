import { useState } from 'react';
import {
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { Button } from '@/components/ui/button';
import { TextField } from '@/components/ui/text-field';
import { colors, fonts, fontSize, spacing } from '@/constants/theme';
import { ApiError, useAuth, WorkspaceAccessError } from '@/lib/auth';

/**
 * Step 2 of sign-in (see ADR 0031): email + password, scoped to the
 * workspace chosen on the previous screen. The workspace name is shown
 * so the operator can confirm they're signing into the right spa.
 */
export default function LoginScreen() {
  const { workspace, signIn, changeWorkspace } = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit() {
    if (submitting) return;
    setError(null);

    if (!email.trim() || !password) {
      setError('Enter your email and password.');
      return;
    }

    setSubmitting(true);
    try {
      await signIn(email.trim(), password);
      // On success the auth status flips and the router swaps screens.
    } catch (e) {
      setError(messageFor(e));
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
            <Text style={styles.workspaceName}>
              {workspace?.name ?? ''}
            </Text>
            <Text style={styles.subtitle}>Staff sign-in</Text>
          </View>

          <View style={styles.form}>
            <TextField
              label="Email"
              value={email}
              onChangeText={setEmail}
              autoCapitalize="none"
              autoComplete="email"
              keyboardType="email-address"
              textContentType="username"
              returnKeyType="next"
              editable={!submitting}
              placeholder="you@yourspa.com"
            />
            <TextField
              label="Password"
              value={password}
              onChangeText={setPassword}
              secureTextEntry
              autoCapitalize="none"
              textContentType="password"
              returnKeyType="go"
              editable={!submitting}
              onSubmitEditing={onSubmit}
              placeholder="Your password"
            />

            {error != null ? <Text style={styles.error}>{error}</Text> : null}

            <Button
              label="Sign in"
              onPress={onSubmit}
              loading={submitting}
              style={styles.submit}
            />
          </View>

          <Pressable
            onPress={changeWorkspace}
            disabled={submitting}
            accessibilityRole="button"
            style={styles.changeWorkspace}
          >
            <Text style={styles.changeWorkspaceText}>
              Not {workspace?.name ?? 'this workspace'}? Change workspace
            </Text>
          </Pressable>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

/** Turn an auth failure into operator-facing copy. */
function messageFor(error: unknown): string {
  if (error instanceof WorkspaceAccessError) {
    return error.message;
  }
  if (error instanceof ApiError) {
    if (error.code === 'platform_admin_account') {
      return 'Platform admin accounts sign in on the web console.';
    }
    if (error.code === 'no_membership') {
      return 'This account is not attached to a workspace yet.';
    }
    if (error.status === 401) {
      return 'Incorrect email or password.';
    }
    return error.message;
  }
  return 'Something went wrong. Check your connection and try again.';
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
    gap: spacing.xl,
  },
  header: {
    alignItems: 'center',
    gap: spacing.xs,
  },
  wordmark: {
    fontFamily: fonts.serif,
    fontSize: 40,
    color: colors.foreground,
    letterSpacing: -0.5,
  },
  workspaceName: {
    fontFamily: fonts.sans,
    fontSize: fontSize.md,
    fontWeight: '600',
    color: colors.foreground,
    marginTop: spacing.xs,
  },
  subtitle: {
    fontFamily: fonts.sans,
    fontSize: fontSize.xs,
    textTransform: 'uppercase',
    letterSpacing: 2,
    color: colors.mutedForeground,
  },
  form: {
    gap: spacing.lg,
  },
  error: {
    fontFamily: fonts.sans,
    fontSize: fontSize.sm,
    color: colors.destructive,
  },
  submit: {
    marginTop: spacing.xs,
  },
  changeWorkspace: {
    alignItems: 'center',
    paddingVertical: spacing.sm,
  },
  changeWorkspaceText: {
    fontFamily: fonts.sans,
    fontSize: fontSize.sm,
    color: colors.accent,
    fontWeight: '600',
  },
});
