import { Feather } from '@expo/vector-icons';
import { router, useLocalSearchParams } from 'expo-router';
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

import { PickerSheet } from '@/components/picker-sheet';
import { SchemaForm } from '@/components/schema-form';
import { Button } from '@/components/ui/button';
import { colors, fonts, fontSize, layout, radius, spacing } from '@/constants/theme';
import {
  useSubmitTreatmentRecord,
  useTreatmentTemplates,
  type TreatmentRecordTemplate,
} from '@/lib/treatments';

function isEmpty(value: unknown): boolean {
  if (value == null || value === '') return true;
  if (Array.isArray(value)) return value.length === 0;
  return false;
}

/** Chart + sign a new treatment record against an appointment. */
export default function NewTreatmentRecordScreen() {
  const params = useLocalSearchParams<{
    appointmentId?: string;
    customerId?: string;
  }>();
  const appointmentId = Number(params.appointmentId) || null;
  const customerId = Number(params.customerId) || 0;

  const templates = useTreatmentTemplates();
  const submit = useSubmitTreatmentRecord();

  const [template, setTemplate] = useState<TreatmentRecordTemplate | null>(null);
  const [answers, setAnswers] = useState<Record<string, unknown>>({});
  const [pickerOpen, setPickerOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function onSubmit() {
    if (submit.isPending) return;
    if (!template) {
      setError('Choose a template to chart from.');
      return;
    }
    if (!customerId) {
      setError('This record is missing its client.');
      return;
    }
    const missing = template.schema.fields.filter(
      (f) => f.required && isEmpty(answers[f.id]),
    );
    if (missing.length > 0) {
      setError(`Please complete: ${missing.map((f) => f.label).join(', ')}`);
      return;
    }
    setError(null);
    submit.mutate(
      {
        customer_id: customerId,
        template_id: template.id,
        appointment_id: appointmentId,
        answers,
      },
      {
        onSuccess: () => router.back(),
        onError: () =>
          setError('Couldn’t save the record. Please try again.'),
      },
    );
  }

  return (
    <SafeAreaView edges={['top']} style={styles.safe}>
      <View style={styles.header}>
        <Pressable
          onPress={() => router.back()}
          accessibilityRole="button"
          hitSlop={10}
        >
          <Text style={styles.cancel}>Cancel</Text>
        </Pressable>
        <Text style={styles.headerTitle}>Treatment record</Text>
        <View style={styles.headerSpacer} />
      </View>

      <KeyboardAvoidingView
        style={styles.flex}
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      >
        <ScrollView
          contentContainerStyle={styles.content}
          keyboardShouldPersistTaps="handled"
          showsVerticalScrollIndicator={false}
        >
          <Pressable
            onPress={() => setPickerOpen(true)}
            accessibilityRole="button"
            style={styles.templateRow}
          >
            <View style={styles.templateText}>
              <Text style={styles.templateLabel}>Template</Text>
              <Text
                style={[
                  styles.templateValue,
                  !template && styles.templatePlaceholder,
                ]}
              >
                {template ? template.name : 'Choose a template'}
              </Text>
            </View>
            <Feather
              name="chevron-right"
              size={18}
              color={colors.mutedForeground}
            />
          </Pressable>

          {template ? (
            <SchemaForm
              fields={template.schema.fields}
              answers={answers}
              onChange={(id, value) =>
                setAnswers((prev) => ({ ...prev, [id]: value }))
              }
            />
          ) : (
            <Text style={styles.hint}>
              Pick a template above to begin charting.
            </Text>
          )}

          {error ? <Text style={styles.error}>{error}</Text> : null}

          {template ? (
            <Button
              label="Sign &amp; save"
              onPress={onSubmit}
              loading={submit.isPending}
            />
          ) : null}
        </ScrollView>
      </KeyboardAvoidingView>

      <PickerSheet<TreatmentRecordTemplate>
        visible={pickerOpen}
        title="Choose a template"
        items={templates.data ?? []}
        loading={templates.isLoading}
        onClose={() => setPickerOpen(false)}
        onSelect={(t) => {
          setTemplate(t);
          setAnswers({});
          setPickerOpen(false);
        }}
        keyOf={(t) => String(t.id)}
        labelOf={(t) => t.name}
        sublabelOf={(t) => t.description || undefined}
        emptyText="No treatment templates yet."
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
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm,
  },
  cancel: {
    fontFamily: fonts.sans,
    fontSize: fontSize.base,
    fontWeight: '600',
    color: colors.accent,
  },
  headerTitle: {
    fontFamily: fonts.sans,
    fontSize: fontSize.md,
    fontWeight: '600',
    color: colors.foreground,
  },
  headerSpacer: { width: 52 },
  content: {
    width: '100%',
    maxWidth: layout.contentMaxWidth,
    alignSelf: 'center',
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.md,
    paddingBottom: spacing.xxl,
    gap: spacing.lg,
  },
  templateRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    backgroundColor: colors.card,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.lg,
    padding: spacing.lg,
  },
  templateText: { flex: 1, gap: 2 },
  templateLabel: {
    fontFamily: fonts.sans,
    fontSize: fontSize.sm,
    color: colors.mutedForeground,
  },
  templateValue: {
    fontFamily: fonts.sans,
    fontSize: fontSize.base,
    fontWeight: '600',
    color: colors.foreground,
  },
  templatePlaceholder: {
    fontWeight: '400',
    color: colors.mutedForeground,
  },
  hint: {
    fontFamily: fonts.sans,
    fontSize: fontSize.sm,
    color: colors.mutedForeground,
  },
  error: {
    fontFamily: fonts.sans,
    fontSize: fontSize.sm,
    color: colors.destructive,
  },
});
