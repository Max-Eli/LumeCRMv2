import { Feather } from '@expo/vector-icons';
import { router } from 'expo-router';
import {
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { AppointmentCard } from '@/components/appointment-card';
import { Skeleton } from '@/components/ui/skeleton';
import { colors, fonts, fontSize, radius, spacing } from '@/constants/theme';
import {
  ACTIVE_STATUSES,
  formatDayLabel,
  greeting,
  todayString,
  useAppointmentsForDate,
} from '@/lib/appointments';
import { useAuth } from '@/lib/auth';

/**
 * Dashboard — the home tab. Answers "is the day running well" at a
 * glance: today's key counts and the next few appointments. Every
 * number is derived from the single day-appointments query.
 */
export default function DashboardScreen() {
  const { user, workspace } = useAuth();
  const today = todayString();
  const { data, isLoading, isError, refetch, isRefetching } =
    useAppointmentsForDate(today);

  const appts = data ?? [];
  const stats = {
    total: appts.filter((a) => a.status !== 'cancelled').length,
    checkedIn: appts.filter((a) => a.status === 'checked_in').length,
    completed: appts.filter((a) => a.status === 'completed').length,
    noShow: appts.filter((a) => a.status === 'no_show').length,
  };
  const upNext = [...appts]
    .filter((a) => ACTIVE_STATUSES.includes(a.status))
    .sort((a, b) => a.start_time.localeCompare(b.start_time))
    .slice(0, 3);

  const firstName = user?.first_name?.trim() || 'there';

  return (
    <SafeAreaView edges={['top']} style={styles.safe}>
      <ScrollView
        contentContainerStyle={styles.content}
        showsVerticalScrollIndicator={false}
        refreshControl={
          <RefreshControl
            refreshing={isRefetching}
            onRefresh={refetch}
            tintColor={colors.accent}
          />
        }
      >
        <View style={styles.header}>
          {workspace ? (
            <Text style={styles.eyebrow}>{workspace.name}</Text>
          ) : null}
          <Text style={styles.greeting}>
            {greeting()}, {firstName}
          </Text>
          <Text style={styles.date}>{formatDayLabel(today)}</Text>
        </View>

        {isLoading ? (
          <DashboardSkeleton />
        ) : isError ? (
          <ErrorState onRetry={refetch} />
        ) : (
          <>
            <View style={styles.grid}>
              <StatTile label="Appointments" value={stats.total} />
              <StatTile label="Checked in" value={stats.checkedIn} />
              <StatTile label="Completed" value={stats.completed} />
              <StatTile
                label="No-shows"
                value={stats.noShow}
                alert={stats.noShow > 0}
              />
            </View>

            <View style={styles.section}>
              <View style={styles.sectionHead}>
                <Text style={styles.sectionTitle}>Up next</Text>
                <Pressable
                  onPress={() => router.navigate('/calendar')}
                  accessibilityRole="button"
                  hitSlop={8}
                >
                  <Text style={styles.sectionLink}>Calendar</Text>
                </Pressable>
              </View>

              {upNext.length === 0 ? (
                <View style={styles.emptyCard}>
                  <Feather
                    name="check-circle"
                    size={22}
                    color={colors.mutedForeground}
                  />
                  <Text style={styles.emptyText}>
                    Nothing left on the schedule today.
                  </Text>
                </View>
              ) : (
                <View style={styles.list}>
                  {upNext.map((appt) => (
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
          </>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

function StatTile({
  label,
  value,
  alert = false,
}: {
  label: string;
  value: number;
  alert?: boolean;
}) {
  return (
    <View style={styles.tile}>
      <Text
        style={[styles.tileValue, alert && { color: colors.destructive }]}
      >
        {value}
      </Text>
      <Text style={styles.tileLabel}>{label}</Text>
    </View>
  );
}

function DashboardSkeleton() {
  return (
    <>
      <View style={styles.grid}>
        {[0, 1, 2, 3].map((i) => (
          <Skeleton key={i} style={styles.tileSkeleton} />
        ))}
      </View>
      <View style={styles.section}>
        <Skeleton style={{ width: 90, height: 16, marginBottom: spacing.md }} />
        <View style={styles.list}>
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} style={styles.cardSkeleton} />
          ))}
        </View>
      </View>
    </>
  );
}

function ErrorState({ onRetry }: { onRetry: () => void }) {
  return (
    <View style={styles.errorBox}>
      <Feather name="wifi-off" size={24} color={colors.mutedForeground} />
      <Text style={styles.errorText}>Couldn&apos;t load today&apos;s data.</Text>
      <Pressable onPress={onRetry} accessibilityRole="button" hitSlop={8}>
        <Text style={styles.retry}>Try again</Text>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  safe: {
    flex: 1,
    backgroundColor: colors.background,
  },
  content: {
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.lg,
    paddingBottom: spacing.xxl,
    gap: spacing.xl,
  },
  header: {
    gap: spacing.xs,
  },
  eyebrow: {
    fontFamily: fonts.sans,
    fontSize: fontSize.xs,
    textTransform: 'uppercase',
    letterSpacing: 1.5,
    color: colors.mutedForeground,
  },
  greeting: {
    fontFamily: fonts.serif,
    fontSize: fontSize.xxl,
    color: colors.foreground,
    letterSpacing: -0.5,
  },
  date: {
    fontFamily: fonts.sans,
    fontSize: fontSize.sm,
    color: colors.mutedForeground,
  },
  grid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: spacing.sm,
  },
  tile: {
    flexGrow: 1,
    flexBasis: '47%',
    backgroundColor: colors.card,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.lg,
    paddingVertical: spacing.lg,
    paddingHorizontal: spacing.lg,
    gap: 2,
  },
  tileValue: {
    fontFamily: fonts.serif,
    fontSize: 30,
    color: colors.foreground,
    letterSpacing: -0.5,
  },
  tileLabel: {
    fontFamily: fonts.sans,
    fontSize: fontSize.sm,
    color: colors.mutedForeground,
  },
  tileSkeleton: {
    flexGrow: 1,
    flexBasis: '47%',
    height: 96,
    borderRadius: radius.lg,
  },
  section: {
    gap: spacing.md,
  },
  sectionHead: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  sectionTitle: {
    fontFamily: fonts.sans,
    fontSize: fontSize.md,
    fontWeight: '700',
    color: colors.foreground,
  },
  sectionLink: {
    fontFamily: fonts.sans,
    fontSize: fontSize.sm,
    fontWeight: '600',
    color: colors.accent,
  },
  list: {
    gap: spacing.sm,
  },
  cardSkeleton: {
    height: 72,
    borderRadius: radius.lg,
  },
  emptyCard: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    backgroundColor: colors.card,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.lg,
    padding: spacing.lg,
  },
  emptyText: {
    fontFamily: fonts.sans,
    fontSize: fontSize.sm,
    color: colors.mutedForeground,
    flex: 1,
  },
  errorBox: {
    alignItems: 'center',
    gap: spacing.sm,
    paddingVertical: spacing.xxl,
  },
  errorText: {
    fontFamily: fonts.sans,
    fontSize: fontSize.base,
    color: colors.mutedForeground,
  },
  retry: {
    fontFamily: fonts.sans,
    fontSize: fontSize.sm,
    fontWeight: '600',
    color: colors.accent,
  },
});
