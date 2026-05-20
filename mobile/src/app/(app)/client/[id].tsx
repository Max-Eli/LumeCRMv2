import { Feather } from '@expo/vector-icons';
import { router, useLocalSearchParams } from 'expo-router';
import { Linking, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { AppointmentCard } from '@/components/appointment-card';
import { Skeleton } from '@/components/ui/skeleton';
import { colors, fonts, fontSize, radius, spacing } from '@/constants/theme';
import { formatLongDate, useCustomerAppointments } from '@/lib/appointments';
import { useAuth } from '@/lib/auth';
import { canViewClientPHI, useCustomer } from '@/lib/customers';

/** Client detail — contact, clinical info (PHI-gated by role), and the
 *  full appointment history. */
export default function ClientDetailScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const customerId = Number(id);
  const { user, workspace } = useAuth();
  const { data: client, isLoading, isError, refetch } = useCustomer(customerId);
  const history = useCustomerAppointments(customerId);

  const role = user?.memberships.find(
    (m) => m.tenant.slug === workspace?.slug,
  )?.role;
  const showPHI = canViewClientPHI(role);

  const appointments = [...(history.data ?? [])].sort((a, b) =>
    b.start_time.localeCompare(a.start_time),
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
        <Text style={styles.headerTitle}>Client</Text>
      </View>

      {isLoading ? (
        <View style={styles.body}>
          <Skeleton style={{ height: 28, width: '65%' }} />
          <Skeleton style={{ height: 140, borderRadius: radius.lg }} />
          <Skeleton style={{ height: 120, borderRadius: radius.lg }} />
        </View>
      ) : isError || !client ? (
        <View style={styles.centered}>
          <Feather name="wifi-off" size={24} color={colors.mutedForeground} />
          <Text style={styles.centeredText}>Couldn&apos;t load this client.</Text>
          <Pressable onPress={() => refetch()} accessibilityRole="button" hitSlop={8}>
            <Text style={styles.retry}>Try again</Text>
          </Pressable>
        </View>
      ) : (
        <ScrollView
          contentContainerStyle={styles.body}
          showsVerticalScrollIndicator={false}
        >
          <View style={styles.hero}>
            <Text style={styles.name}>
              {client.full_name || 'Unnamed client'}
            </Text>
            <Text style={styles.since}>
              Client since {formatLongDate(client.created_at)}
            </Text>
          </View>

          <View style={styles.card}>
            <InfoRow
              label="Phone"
              value={client.phone || '—'}
              onPress={
                client.phone
                  ? () => Linking.openURL(`tel:${client.phone}`)
                  : undefined
              }
            />
            <Divider />
            <InfoRow
              label="Email"
              value={client.email || '—'}
              onPress={
                client.email
                  ? () => Linking.openURL(`mailto:${client.email}`)
                  : undefined
              }
            />
          </View>

          <View style={styles.section}>
            <Text style={styles.sectionTitle}>Medical</Text>
            {showPHI ? (
              <View style={styles.card}>
                <InfoRow
                  label="Date of birth"
                  value={formatBirthDate(client.date_of_birth)}
                />
                <Divider />
                <InfoRow
                  label="Fitzpatrick"
                  value={
                    client.skin_type_fitzpatrick
                      ? `Type ${client.skin_type_fitzpatrick}`
                      : '—'
                  }
                />
                <Divider />
                <InfoBlock label="Allergies" value={client.allergies} />
                <Divider />
                <InfoBlock label="Medications" value={client.medications} />
                <Divider />
                <InfoBlock
                  label="Medical history"
                  value={client.medical_history}
                />
              </View>
            ) : (
              <View style={styles.restricted}>
                <Feather name="lock" size={16} color={colors.mutedForeground} />
                <Text style={styles.restrictedText}>
                  Clinical details are limited to clinical staff.
                </Text>
              </View>
            )}
          </View>

          <View style={styles.section}>
            <Text style={styles.sectionTitle}>Appointment history</Text>
            {history.isLoading ? (
              <Skeleton style={{ height: 72, borderRadius: radius.lg }} />
            ) : appointments.length === 0 ? (
              <View style={styles.restricted}>
                <Text style={styles.restrictedText}>No appointments yet.</Text>
              </View>
            ) : (
              <View style={styles.historyList}>
                {appointments.map((appt) => (
                  <AppointmentCard
                    key={appt.id}
                    appointment={appt}
                    onPress={() =>
                      router.push({
                        pathname: '/appointment/[id]',
                        params: { id: String(appt.id) },
                      })
                    }
                  />
                ))}
              </View>
            )}
          </View>
        </ScrollView>
      )}
    </SafeAreaView>
  );
}

const MONTHS = [
  'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
];

function formatBirthDate(value: string | null | undefined): string {
  if (!value) return '—';
  const [y, m, d] = value.split('-').map(Number);
  if (!y || !m || !d) return value;
  return `${MONTHS[m - 1]} ${d}, ${y}`;
}

function InfoRow({
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

function InfoBlock({
  label,
  value,
}: {
  label: string;
  value: string | undefined;
}) {
  return (
    <View style={styles.block}>
      <Text style={styles.rowLabel}>{label}</Text>
      <Text style={styles.blockValue}>
        {value && value.trim() ? value : 'None recorded'}
      </Text>
    </View>
  );
}

function Divider() {
  return <View style={styles.divider} />;
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
  body: {
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.md,
    paddingBottom: spacing.xxl,
    gap: spacing.lg,
  },
  hero: { gap: spacing.xs },
  name: {
    fontFamily: fonts.serif,
    fontSize: fontSize.xxl,
    color: colors.foreground,
    letterSpacing: -0.5,
  },
  since: {
    fontFamily: fonts.sans,
    fontSize: fontSize.sm,
    color: colors.mutedForeground,
  },
  card: {
    backgroundColor: colors.card,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.lg,
    paddingHorizontal: spacing.lg,
  },
  section: { gap: spacing.sm },
  sectionTitle: {
    fontFamily: fonts.sans,
    fontSize: fontSize.md,
    fontWeight: '700',
    color: colors.foreground,
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
  block: {
    paddingVertical: spacing.md,
    gap: spacing.xs,
  },
  blockValue: {
    fontFamily: fonts.sans,
    fontSize: fontSize.base,
    color: colors.foreground,
    lineHeight: 21,
  },
  divider: { height: 1, backgroundColor: colors.border },
  restricted: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    backgroundColor: colors.card,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.lg,
    padding: spacing.lg,
  },
  restrictedText: {
    fontFamily: fonts.sans,
    fontSize: fontSize.sm,
    color: colors.mutedForeground,
    flex: 1,
  },
  historyList: { gap: spacing.sm },
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
