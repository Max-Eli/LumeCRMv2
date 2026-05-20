import { Feather } from '@expo/vector-icons';
import { router } from 'expo-router';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { colors, fonts, fontSize, radius, spacing } from '@/constants/theme';
import { formatLongDate, type Appointment } from '@/lib/appointments';
import {
  useAppointmentTreatmentRecords,
  type TreatmentRecord,
} from '@/lib/treatments';

/** Treatment-records section for the appointment detail — lists what
 *  has been charted and starts a new record. */
export function AppointmentCharting({
  appointment,
}: {
  appointment: Appointment;
}) {
  const { data, isLoading } = useAppointmentTreatmentRecords(appointment.id);
  const records = data ?? [];

  return (
    <View style={styles.section}>
      <Text style={styles.title}>Treatment records</Text>

      {isLoading ? (
        <Skeleton style={{ height: 60, borderRadius: radius.lg }} />
      ) : records.length === 0 ? (
        <Text style={styles.empty}>Nothing charted for this visit yet.</Text>
      ) : (
        <View style={styles.list}>
          {records.map((record) => (
            <RecordRow key={record.id} record={record} />
          ))}
        </View>
      )}

      <Button
        label="New treatment record"
        variant="secondary"
        onPress={() =>
          router.push({
            pathname: '/treatment-record/new',
            params: {
              appointmentId: String(appointment.id),
              customerId: String(appointment.customer.id),
            },
          })
        }
      />
    </View>
  );
}

function RecordRow({ record }: { record: TreatmentRecord }) {
  return (
    <Pressable
      onPress={() =>
        router.push({
          pathname: '/treatment-record/[id]',
          params: { id: String(record.id) },
        })
      }
      accessibilityRole="button"
      style={({ pressed }) => [styles.row, pressed && styles.rowPressed]}
    >
      <Feather name="file-text" size={18} color={colors.mutedForeground} />
      <View style={styles.rowText}>
        <Text style={styles.rowTitle} numberOfLines={1}>
          {record.template_name}
          {record.is_voided ? ' (voided)' : ''}
        </Text>
        <Text style={styles.rowSub} numberOfLines={1}>
          {record.author_first_name} {record.author_last_name} ·{' '}
          {formatLongDate(record.signed_at)}
        </Text>
      </View>
      <Feather name="chevron-right" size={18} color={colors.mutedForeground} />
    </Pressable>
  );
}

const styles = StyleSheet.create({
  section: {
    gap: spacing.sm,
  },
  title: {
    fontFamily: fonts.sans,
    fontSize: fontSize.md,
    fontWeight: '700',
    color: colors.foreground,
  },
  empty: {
    fontFamily: fonts.sans,
    fontSize: fontSize.sm,
    color: colors.mutedForeground,
  },
  list: {
    gap: spacing.sm,
  },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    padding: spacing.md,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.card,
  },
  rowPressed: {
    backgroundColor: colors.muted,
  },
  rowText: {
    flex: 1,
    gap: 2,
  },
  rowTitle: {
    fontFamily: fonts.sans,
    fontSize: fontSize.base,
    fontWeight: '600',
    color: colors.foreground,
  },
  rowSub: {
    fontFamily: fonts.sans,
    fontSize: fontSize.sm,
    color: colors.mutedForeground,
  },
});
