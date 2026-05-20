import { Feather } from '@expo/vector-icons';
import { router, useLocalSearchParams } from 'expo-router';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { Skeleton } from '@/components/ui/skeleton';
import { colors, fonts, fontSize, layout, radius, spacing } from '@/constants/theme';
import { formatLongDate } from '@/lib/appointments';
import { useTreatmentRecord, type TemplateField } from '@/lib/treatments';

/** Read-only view of a signed treatment record. */
export default function TreatmentRecordScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { data: record, isLoading, isError, refetch } = useTreatmentRecord(
    Number(id),
  );

  return (
    <SafeAreaView edges={['top']} style={styles.safe}>
      <View style={styles.header}>
        <Pressable
          onPress={() => router.back()}
          accessibilityRole="button"
          accessibilityLabel="Back"
          hitSlop={10}
          style={styles.back}
        >
          <Feather name="chevron-left" size={24} color={colors.foreground} />
        </Pressable>
        <Text style={styles.headerTitle}>Treatment record</Text>
      </View>

      {isLoading ? (
        <View style={styles.content}>
          <Skeleton style={{ height: 26, width: '70%' }} />
          <Skeleton style={{ height: 160, borderRadius: radius.lg }} />
        </View>
      ) : isError || !record ? (
        <View style={styles.centered}>
          <Feather name="wifi-off" size={24} color={colors.mutedForeground} />
          <Text style={styles.centeredText}>Couldn&apos;t load this record.</Text>
          <Pressable onPress={() => refetch()} accessibilityRole="button" hitSlop={8}>
            <Text style={styles.retry}>Try again</Text>
          </Pressable>
        </View>
      ) : (
        <ScrollView
          contentContainerStyle={styles.content}
          showsVerticalScrollIndicator={false}
        >
          <View style={styles.hero}>
            <Text style={styles.title}>{record.template_name}</Text>
            <Text style={styles.meta}>
              Signed by {record.author_first_name} {record.author_last_name}
              {record.author_job_title ? ` · ${record.author_job_title}` : ''}
            </Text>
            <Text style={styles.meta}>{formatLongDate(record.signed_at)}</Text>
          </View>

          {record.is_voided ? (
            <View style={styles.voided}>
              <Feather name="x-circle" size={16} color={colors.destructive} />
              <Text style={styles.voidedText}>This record was voided.</Text>
            </View>
          ) : null}

          <View style={styles.card}>
            {record.schema_snapshot.fields.map((field, i) => (
              <View
                key={field.id}
                style={[styles.row, i > 0 && styles.rowDivided]}
              >
                <Text style={styles.fieldLabel}>{field.label}</Text>
                <Text style={styles.fieldValue}>
                  {formatAnswer(field, record.answers[field.id])}
                </Text>
              </View>
            ))}
          </View>
        </ScrollView>
      )}
    </SafeAreaView>
  );
}

/** Render an answer for read-only display. */
function formatAnswer(field: TemplateField, value: unknown): string {
  if (value == null || value === '') return '—';
  if (field.type === 'choice_single') {
    const opt = field.options?.find((o) => o.value === value);
    return opt ? opt.label : String(value);
  }
  if (field.type === 'choice_multiple') {
    const values = Array.isArray(value) ? value : [];
    if (values.length === 0) return '—';
    return values
      .map((v) => field.options?.find((o) => o.value === v)?.label ?? String(v))
      .join(', ');
  }
  return String(value);
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  back: {
    width: 32,
    height: 32,
    alignItems: 'center',
    justifyContent: 'center',
  },
  headerTitle: {
    fontFamily: fonts.sans,
    fontSize: fontSize.md,
    fontWeight: '600',
    color: colors.foreground,
  },
  content: {
    width: '100%',
    maxWidth: layout.contentMaxWidth,
    alignSelf: 'center',
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.md,
    paddingBottom: spacing.xxl,
    gap: spacing.lg,
  },
  hero: { gap: spacing.xs },
  title: {
    fontFamily: fonts.serif,
    fontSize: fontSize.xxl,
    color: colors.foreground,
    letterSpacing: -0.5,
  },
  meta: {
    fontFamily: fonts.sans,
    fontSize: fontSize.sm,
    color: colors.mutedForeground,
  },
  voided: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    backgroundColor: '#FBE7DF',
    borderRadius: radius.md,
    padding: spacing.md,
  },
  voidedText: {
    fontFamily: fonts.sans,
    fontSize: fontSize.sm,
    fontWeight: '600',
    color: colors.destructive,
  },
  card: {
    backgroundColor: colors.card,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.lg,
    paddingHorizontal: spacing.lg,
  },
  row: {
    paddingVertical: spacing.md,
    gap: spacing.xs,
  },
  rowDivided: {
    borderTopWidth: 1,
    borderTopColor: colors.border,
  },
  fieldLabel: {
    fontFamily: fonts.sans,
    fontSize: fontSize.sm,
    color: colors.mutedForeground,
  },
  fieldValue: {
    fontFamily: fonts.sans,
    fontSize: fontSize.base,
    color: colors.foreground,
    lineHeight: 21,
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
