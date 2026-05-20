import { Feather } from '@expo/vector-icons';
import { Image } from 'expo-image';
import { router, useLocalSearchParams, useNavigation } from 'expo-router';
import { useEffect, useState } from 'react';
import {
  BackHandler,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { FormRenderer } from '@/components/form-renderer';
import { KioskUnlockModal } from '@/components/kiosk-unlock-modal';
import { SignaturePad } from '@/components/signature-pad';
import { Skeleton } from '@/components/ui/skeleton';
import { Button } from '@/components/ui/button';
import { colors, fonts, fontSize, layout, radius, spacing } from '@/constants/theme';
import { usePublicSubmission, useSubmitForm } from '@/lib/forms';

function isEmpty(value: unknown): boolean {
  if (value == null || value === '') return true;
  if (Array.isArray(value)) return value.length === 0;
  return false;
}

/**
 * Consent / intake form sign surface. Staff can engage a kiosk lock
 * before handing the device to a guest — while locked, there is no way
 * back into the CRM without a staff member re-entering their
 * credentials.
 */
export default function SignFormScreen() {
  const { token } = useLocalSearchParams<{ token: string }>();
  const navigation = useNavigation();
  const { data: form, isLoading, isError, refetch } = usePublicSubmission(
    token,
  );
  const submit = useSubmitForm(token);

  const [answers, setAnswers] = useState<Record<string, unknown>>({});
  const [signature, setSignature] = useState<string | null>(null);
  const [locked, setLocked] = useState(false);
  const [unlockOpen, setUnlockOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const completed = form?.status === 'completed' || submit.isSuccess;

  // Kiosk lock — disable the iOS swipe-back gesture while locked.
  useEffect(() => {
    navigation.setOptions({ gestureEnabled: !locked });
  }, [locked, navigation]);

  // Kiosk lock — swallow the Android hardware back button while locked.
  useEffect(() => {
    const sub = BackHandler.addEventListener('hardwareBackPress', () => locked);
    return () => sub.remove();
  }, [locked]);

  function onSubmit() {
    if (!form || submit.isPending) return;
    const fields = form.schema_snapshot.fields;
    const missing = fields.filter(
      (f) =>
        f.required &&
        f.type !== 'paragraph' &&
        f.type !== 'signature' &&
        isEmpty(answers[f.id]),
    );
    if (missing.length > 0) {
      setError(`Please complete: ${missing.map((f) => f.label).join(', ')}`);
      return;
    }
    if (!signature) {
      setError('A signature is required to submit this form.');
      return;
    }
    setError(null);
    submit.mutate(
      { answers, signature_data: signature },
      {
        onError: () =>
          setError('Couldn’t submit the form. Please try again.'),
      },
    );
  }

  const fields = form?.schema_snapshot.fields ?? [];
  const hasSignatureField = fields.some((f) => f.type === 'signature');

  return (
    <SafeAreaView edges={['top']} style={styles.safe}>
      <View style={styles.header}>
        {locked ? (
          <View style={styles.lockedTag}>
            <Feather name="lock" size={14} color={colors.accent} />
            <Text style={styles.lockedText}>Locked</Text>
          </View>
        ) : (
          <Pressable
            onPress={() => router.back()}
            accessibilityRole="button"
            hitSlop={10}
          >
            <Text style={styles.headerAction}>
              {completed ? 'Done' : 'Cancel'}
            </Text>
          </Pressable>
        )}

        <Text style={styles.headerTitle} numberOfLines={1}>
          {form?.template_name ?? 'Form'}
        </Text>

        {locked ? (
          <Pressable
            onPress={() => setUnlockOpen(true)}
            accessibilityRole="button"
            hitSlop={10}
          >
            <Text style={styles.headerAction}>Unlock</Text>
          </Pressable>
        ) : completed ? (
          <View style={styles.headerSpacer} />
        ) : (
          <Pressable
            onPress={() => setLocked(true)}
            accessibilityRole="button"
            hitSlop={10}
          >
            <Text style={styles.headerAction}>Lock</Text>
          </Pressable>
        )}
      </View>

      <KeyboardAvoidingView
        style={styles.flex}
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      >
        {isLoading ? (
          <View style={styles.content}>
            <Skeleton style={{ height: 28, width: '70%' }} />
            <Skeleton style={{ height: 180, borderRadius: radius.lg }} />
          </View>
        ) : isError || !form ? (
          <View style={styles.centered}>
            <Feather name="wifi-off" size={24} color={colors.mutedForeground} />
            <Text style={styles.centeredText}>Couldn&apos;t load this form.</Text>
            <Pressable onPress={() => refetch()} accessibilityRole="button" hitSlop={8}>
              <Text style={styles.retry}>Try again</Text>
            </Pressable>
          </View>
        ) : (
          <ScrollView
            contentContainerStyle={styles.content}
            keyboardShouldPersistTaps="handled"
            showsVerticalScrollIndicator={false}
          >
            <View style={styles.brand}>
              {form.tenant_logo_url ? (
                <Image
                  source={{ uri: form.tenant_logo_url }}
                  style={styles.logo}
                  contentFit="contain"
                  accessibilityLabel={form.tenant_name}
                />
              ) : (
                <Text style={styles.tenantName}>{form.tenant_name}</Text>
              )}
              <Text style={styles.title}>{form.template_name}</Text>
            </View>

            {completed ? (
              <View style={styles.done}>
                <Feather name="check-circle" size={40} color="#2F7D52" />
                <Text style={styles.doneTitle}>Signed</Text>
                <Text style={styles.doneText}>
                  Thank you, {form.customer_first_name}. This form has been
                  recorded.
                </Text>
              </View>
            ) : (
              <>
                <FormRenderer
                  fields={fields}
                  answers={answers}
                  onAnswer={(id, value) =>
                    setAnswers((prev) => ({ ...prev, [id]: value }))
                  }
                  onSignature={setSignature}
                />

                {!hasSignatureField ? (
                  <View style={styles.field}>
                    <Text style={styles.signLabel}>
                      Signature<Text style={styles.required}> *</Text>
                    </Text>
                    <SignaturePad onChange={setSignature} />
                  </View>
                ) : null}

                {error ? <Text style={styles.error}>{error}</Text> : null}

                <Button
                  label="Submit &amp; sign"
                  onPress={onSubmit}
                  loading={submit.isPending}
                />
              </>
            )}
          </ScrollView>
        )}
      </KeyboardAvoidingView>

      <KioskUnlockModal
        visible={unlockOpen}
        onClose={() => setUnlockOpen(false)}
        onUnlocked={() => {
          setUnlockOpen(false);
          setLocked(false);
        }}
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  flex: { flex: 1 },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: spacing.md,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  headerAction: {
    fontFamily: fonts.sans,
    fontSize: fontSize.base,
    fontWeight: '600',
    color: colors.accent,
  },
  headerSpacer: { width: 52 },
  headerTitle: {
    flex: 1,
    textAlign: 'center',
    fontFamily: fonts.sans,
    fontSize: fontSize.md,
    fontWeight: '600',
    color: colors.foreground,
  },
  lockedTag: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
  },
  lockedText: {
    fontFamily: fonts.sans,
    fontSize: fontSize.sm,
    fontWeight: '600',
    color: colors.accent,
  },
  content: {
    width: '100%',
    maxWidth: layout.contentMaxWidth,
    alignSelf: 'center',
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.lg,
    paddingBottom: spacing.xxl,
    gap: spacing.xl,
  },
  brand: {
    alignItems: 'center',
    gap: spacing.sm,
  },
  logo: {
    width: 180,
    height: 60,
  },
  tenantName: {
    fontFamily: fonts.sans,
    fontSize: fontSize.md,
    fontWeight: '600',
    color: colors.mutedForeground,
  },
  title: {
    fontFamily: fonts.serif,
    fontSize: fontSize.xxl,
    color: colors.foreground,
    letterSpacing: -0.5,
    textAlign: 'center',
  },
  field: {
    gap: spacing.xs,
  },
  signLabel: {
    fontFamily: fonts.sans,
    fontSize: fontSize.sm,
    fontWeight: '600',
    color: colors.foreground,
  },
  required: {
    color: colors.destructive,
  },
  error: {
    fontFamily: fonts.sans,
    fontSize: fontSize.sm,
    color: colors.destructive,
  },
  done: {
    alignItems: 'center',
    gap: spacing.sm,
    paddingVertical: spacing.xxl,
  },
  doneTitle: {
    fontFamily: fonts.serif,
    fontSize: fontSize.xl,
    color: colors.foreground,
  },
  doneText: {
    fontFamily: fonts.sans,
    fontSize: fontSize.base,
    color: colors.mutedForeground,
    textAlign: 'center',
    lineHeight: 22,
  },
  centered: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    gap: spacing.sm,
    padding: spacing.xl,
  },
  centeredText: {
    fontFamily: fonts.sans,
    fontSize: fontSize.base,
    fontWeight: '600',
    color: colors.foreground,
  },
  retry: {
    fontFamily: fonts.sans,
    fontSize: fontSize.sm,
    fontWeight: '600',
    color: colors.accent,
  },
});
