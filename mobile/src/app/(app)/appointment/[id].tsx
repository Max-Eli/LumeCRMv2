import { Feather } from '@expo/vector-icons';
import { router, useLocalSearchParams } from 'expo-router';
import {
  Linking,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { AppointmentActions } from '@/components/appointment-actions';
import { AppointmentCharting } from '@/components/appointment-charting';
import { Skeleton } from '@/components/ui/skeleton';
import { StatusPill } from '@/components/ui/status-pill';
import { colors, fonts, fontSize, radius, spacing } from '@/constants/theme';
import {
  formatDuration,
  formatLongDate,
  formatPrice,
  formatTime,
  providerName,
  useAppointment,
} from '@/lib/appointments';

/** Read-only appointment detail. Status actions land in Phase 7. */
export default function AppointmentDetailScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { data: appt, isLoading, isError, refetch } = useAppointment(
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
        <Text style={styles.headerTitle}>Appointment</Text>
      </View>

      {isLoading ? (
        <View style={styles.body}>
          <Skeleton style={{ height: 28, width: '70%' }} />
          <Skeleton style={{ height: 18, width: '45%' }} />
          <Skeleton style={{ height: 200, borderRadius: radius.lg }} />
        </View>
      ) : isError || !appt ? (
        <View style={styles.centered}>
          <Feather name="wifi-off" size={24} color={colors.mutedForeground} />
          <Text style={styles.centeredText}>
            Couldn&apos;t load this appointment.
          </Text>
          <Pressable
            onPress={() => refetch()}
            accessibilityRole="button"
            hitSlop={8}
          >
            <Text style={styles.retry}>Try again</Text>
          </Pressable>
        </View>
      ) : (
        <ScrollView
          contentContainerStyle={styles.body}
          showsVerticalScrollIndicator={false}
        >
          <View style={styles.hero}>
            <Text style={styles.client}>
              {appt.customer.full_name || 'Unknown client'}
            </Text>
            <Text style={styles.service}>{appt.service.name}</Text>
            <View style={styles.statusRow}>
              <StatusPill status={appt.status} />
            </View>
          </View>

          <View style={styles.card}>
            <DetailRow
              label="When"
              value={`${formatLongDate(appt.start_time)}`}
            />
            <Divider />
            <DetailRow
              label="Time"
              value={`${formatTime(appt.start_time)} – ${formatTime(appt.end_time)}`}
            />
            <Divider />
            <DetailRow
              label="Duration"
              value={formatDuration(appt.duration_minutes)}
            />
            <Divider />
            <DetailRow label="Provider" value={providerName(appt.provider)} />
            <Divider />
            <DetailRow
              label="Phone"
              value={appt.customer.phone || '—'}
              onPress={
                appt.customer.phone
                  ? () => Linking.openURL(`tel:${appt.customer.phone}`)
                  : undefined
              }
            />
            <Divider />
            <DetailRow
              label="Price"
              value={formatPrice(appt.quoted_price_cents)}
            />
          </View>

          <AppointmentActions appointment={appt} />

          <AppointmentCharting appointment={appt} />

          {appt.notes ? (
            <View style={styles.card}>
              <Text style={styles.notesLabel}>Notes</Text>
              <Text style={styles.notesText}>{appt.notes}</Text>
            </View>
          ) : null}
        </ScrollView>
      )}
    </SafeAreaView>
  );
}

function DetailRow({
  label,
  value,
  onPress,
}: {
  label: string;
  value: string;
  onPress?: () => void;
}) {
  return (
    <Pressable
      onPress={onPress}
      disabled={!onPress}
      style={styles.row}
      accessibilityRole={onPress ? 'button' : undefined}
    >
      <Text style={styles.rowLabel}>{label}</Text>
      <Text
        style={[styles.rowValue, onPress && { color: colors.accent }]}
        numberOfLines={1}
      >
        {value}
      </Text>
    </Pressable>
  );
}

function Divider() {
  return <View style={styles.divider} />;
}

const styles = StyleSheet.create({
  safe: {
    flex: 1,
    backgroundColor: colors.background,
  },
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
  body: {
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.md,
    paddingBottom: spacing.xxl,
    gap: spacing.lg,
  },
  hero: {
    gap: spacing.xs,
  },
  client: {
    fontFamily: fonts.serif,
    fontSize: fontSize.xxl,
    color: colors.foreground,
    letterSpacing: -0.5,
  },
  service: {
    fontFamily: fonts.sans,
    fontSize: fontSize.base,
    color: colors.mutedForeground,
  },
  statusRow: {
    marginTop: spacing.sm,
  },
  card: {
    backgroundColor: colors.card,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.lg,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.xs,
  },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: spacing.md,
    paddingVertical: spacing.md,
  },
  rowLabel: {
    fontFamily: fonts.sans,
    fontSize: fontSize.sm,
    color: colors.mutedForeground,
  },
  rowValue: {
    fontFamily: fonts.sans,
    fontSize: fontSize.base,
    fontWeight: '600',
    color: colors.foreground,
    flexShrink: 1,
  },
  divider: {
    height: 1,
    backgroundColor: colors.border,
  },
  notesLabel: {
    fontFamily: fonts.sans,
    fontSize: fontSize.sm,
    color: colors.mutedForeground,
    paddingTop: spacing.md,
  },
  notesText: {
    fontFamily: fonts.sans,
    fontSize: fontSize.base,
    color: colors.foreground,
    lineHeight: 22,
    paddingVertical: spacing.sm,
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
