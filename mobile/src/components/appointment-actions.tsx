import { Alert, StyleSheet, Text, View } from 'react-native';

import { Button } from '@/components/ui/button';
import { colors, fonts, fontSize, spacing } from '@/constants/theme';
import {
  STATUS_TRANSITIONS,
  transitionLabel,
  useUpdateAppointmentStatus,
  type Appointment,
  type AppointmentStatus,
} from '@/lib/appointments';

/**
 * Status-change actions for an appointment — check in, confirm, undo,
 * no-show, cancel. The valid set is driven by the backend state
 * machine; destructive moves ask for confirmation first.
 */
export function AppointmentActions({
  appointment,
}: {
  appointment: Appointment;
}) {
  const mutation = useUpdateAppointmentStatus(appointment.id);
  const transitions = STATUS_TRANSITIONS[appointment.status];

  if (transitions.length === 0) return null;

  const positives = transitions.filter(
    (t) => t === 'confirmed' || t === 'checked_in',
  );
  const negatives = transitions.filter(
    (t) => t === 'cancelled' || t === 'no_show',
  );
  const pending = mutation.isPending;

  function apply(to: AppointmentStatus) {
    mutation.mutate(to);
  }

  function confirmThen(to: AppointmentStatus) {
    Alert.alert(
      to === 'cancelled' ? 'Cancel this appointment?' : 'Mark as no-show?',
      undefined,
      [
        { text: 'Back', style: 'cancel' },
        {
          text: to === 'cancelled' ? 'Cancel appointment' : 'Mark no-show',
          style: 'destructive',
          onPress: () => apply(to),
        },
      ],
    );
  }

  return (
    <View style={styles.container}>
      {positives.map((to) => (
        <Button
          key={to}
          label={transitionLabel(appointment.status, to)}
          variant={to === 'checked_in' ? 'primary' : 'secondary'}
          onPress={() => apply(to)}
          loading={pending && mutation.variables === to}
          disabled={pending}
        />
      ))}

      {negatives.length > 0 ? (
        <View style={styles.row}>
          {negatives.map((to) => (
            <Button
              key={to}
              label={to === 'cancelled' ? 'Cancel' : 'No-show'}
              variant="destructive"
              onPress={() => confirmThen(to)}
              loading={pending && mutation.variables === to}
              disabled={pending}
              style={styles.flex}
            />
          ))}
        </View>
      ) : null}

      {mutation.isError ? (
        <Text style={styles.error}>
          Couldn&apos;t update the appointment. Try again.
        </Text>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    gap: spacing.sm,
  },
  row: {
    flexDirection: 'row',
    gap: spacing.sm,
  },
  flex: {
    flex: 1,
  },
  error: {
    fontFamily: fonts.sans,
    fontSize: fontSize.sm,
    color: colors.destructive,
    textAlign: 'center',
  },
});
