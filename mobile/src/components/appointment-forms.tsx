import { Feather } from '@expo/vector-icons';
import { router } from 'expo-router';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { Skeleton } from '@/components/ui/skeleton';
import { colors, fonts, fontSize, radius, spacing } from '@/constants/theme';
import type { Appointment } from '@/lib/appointments';
import {
  statusLabel,
  useFormSubmissions,
  type FormSubmissionListItem,
} from '@/lib/forms';

const STATUS_COLOR: Record<string, string> = {
  pending: '#B7791F',
  completed: '#2F7D52',
  voided: colors.mutedForeground,
};

/** Consent / intake forms for the appointment's client. Tapping a
 *  form opens the sign surface (with the optional kiosk lock). */
export function AppointmentForms({
  appointment,
}: {
  appointment: Appointment;
}) {
  const { data, isLoading } = useFormSubmissions({
    customerId: appointment.customer.id,
  });
  const forms = data ?? [];

  return (
    <View style={styles.section}>
      <Text style={styles.title}>Forms</Text>

      {isLoading ? (
        <Skeleton style={{ height: 56, borderRadius: radius.lg }} />
      ) : forms.length === 0 ? (
        <Text style={styles.empty}>No forms assigned to this client.</Text>
      ) : (
        <View style={styles.list}>
          {forms.map((form) => (
            <FormRow key={form.id} form={form} />
          ))}
        </View>
      )}
    </View>
  );
}

function FormRow({ form }: { form: FormSubmissionListItem }) {
  return (
    <Pressable
      onPress={() =>
        router.push({
          pathname: '/sign/[token]',
          params: { token: form.token },
        })
      }
      accessibilityRole="button"
      style={({ pressed }) => [styles.row, pressed && styles.rowPressed]}
    >
      <Feather name="file-text" size={18} color={colors.mutedForeground} />
      <View style={styles.rowText}>
        <Text style={styles.rowTitle} numberOfLines={1}>
          {form.template_name}
        </Text>
        <Text
          style={[
            styles.rowStatus,
            { color: STATUS_COLOR[form.status] ?? colors.mutedForeground },
          ]}
        >
          {statusLabel(form.status)}
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
  rowStatus: {
    fontFamily: fonts.sans,
    fontSize: fontSize.sm,
    fontWeight: '600',
  },
});
