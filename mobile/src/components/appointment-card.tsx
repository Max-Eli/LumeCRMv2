import { Pressable, StyleSheet, Text, View } from 'react-native';

import { StatusPill } from '@/components/ui/status-pill';
import { colors, fonts, fontSize, radius, spacing } from '@/constants/theme';
import {
  formatDuration,
  formatTime,
  providerName,
  type Appointment,
} from '@/lib/appointments';

interface AppointmentCardProps {
  appointment: Appointment;
  onPress?: () => void;
}

/** A single appointment row — time, client, service · provider, status.
 *  A category-colour stripe ties it to the calendar's colour scheme. */
export function AppointmentCard({ appointment, onPress }: AppointmentCardProps) {
  const { customer, service, provider, start_time, duration_minutes, status } =
    appointment;

  return (
    <Pressable
      onPress={onPress}
      disabled={!onPress}
      accessibilityRole={onPress ? 'button' : undefined}
      style={({ pressed }) => [styles.card, pressed && onPress && styles.pressed]}
    >
      <View
        style={[
          styles.stripe,
          { backgroundColor: service.category_color || colors.border },
        ]}
      />

      <View style={styles.timeCol}>
        <Text style={styles.time}>{formatTime(start_time)}</Text>
        <Text style={styles.duration}>{formatDuration(duration_minutes)}</Text>
      </View>

      <View style={styles.main}>
        <Text style={styles.client} numberOfLines={1}>
          {customer.full_name || 'Unknown client'}
        </Text>
        <Text style={styles.detail} numberOfLines={1}>
          {service.name}
          {provider ? ` · ${providerName(provider)}` : ''}
        </Text>
      </View>

      <StatusPill status={status} />
    </Pressable>
  );
}

const styles = StyleSheet.create({
  card: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    backgroundColor: colors.card,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.lg,
    paddingVertical: spacing.md,
    paddingLeft: spacing.lg,
    paddingRight: spacing.md,
    overflow: 'hidden',
  },
  pressed: {
    backgroundColor: colors.muted,
  },
  stripe: {
    position: 'absolute',
    left: 0,
    top: 0,
    bottom: 0,
    width: 4,
  },
  timeCol: {
    width: 66,
  },
  time: {
    fontFamily: fonts.sans,
    fontSize: fontSize.base,
    fontWeight: '600',
    color: colors.foreground,
  },
  duration: {
    fontFamily: fonts.sans,
    fontSize: fontSize.xs,
    color: colors.mutedForeground,
    marginTop: 1,
  },
  main: {
    flex: 1,
    gap: 2,
  },
  client: {
    fontFamily: fonts.sans,
    fontSize: fontSize.base,
    fontWeight: '600',
    color: colors.foreground,
  },
  detail: {
    fontFamily: fonts.sans,
    fontSize: fontSize.sm,
    color: colors.mutedForeground,
  },
});
