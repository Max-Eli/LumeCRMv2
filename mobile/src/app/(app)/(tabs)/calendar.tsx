import { Feather } from '@expo/vector-icons';
import { router } from 'expo-router';
import {
  FlatList,
  Pressable,
  RefreshControl,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { AppointmentCard } from '@/components/appointment-card';
import { Skeleton } from '@/components/ui/skeleton';
import { colors, fonts, fontSize, radius, spacing } from '@/constants/theme';
import {
  formatDayLabel,
  todayString,
  useAppointmentsForDate,
} from '@/lib/appointments';

/** Calendar tab — the full list of today's appointments. */
export default function CalendarScreen() {
  const today = todayString();
  const { data, isLoading, isError, refetch, isRefetching } =
    useAppointmentsForDate(today);

  const appts = [...(data ?? [])].sort((a, b) =>
    a.start_time.localeCompare(b.start_time),
  );
  const count = appts.filter((a) => a.status !== 'cancelled').length;

  return (
    <SafeAreaView edges={['top']} style={styles.safe}>
      <View style={styles.header}>
        <Text style={styles.eyebrow}>Schedule</Text>
        <Text style={styles.title}>Today</Text>
        <Text style={styles.sub}>
          {formatDayLabel(today)}
          {!isLoading && !isError ? `  ·  ${countLabel(count)}` : ''}
        </Text>
      </View>

      {isLoading ? (
        <View style={styles.list}>
          {[0, 1, 2, 3, 4].map((i) => (
            <Skeleton key={i} style={styles.cardSkeleton} />
          ))}
        </View>
      ) : isError ? (
        <View style={styles.centered}>
          <Feather name="wifi-off" size={24} color={colors.mutedForeground} />
          <Text style={styles.centeredText}>
            Couldn&apos;t load the schedule.
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
        <FlatList
          data={appts}
          keyExtractor={(item) => String(item.id)}
          contentContainerStyle={styles.list}
          showsVerticalScrollIndicator={false}
          refreshControl={
            <RefreshControl
              refreshing={isRefetching}
              onRefresh={refetch}
              tintColor={colors.accent}
            />
          }
          renderItem={({ item }) => (
            <AppointmentCard
              appointment={item}
              onPress={() =>
                router.push({
                  pathname: '/appointment/[id]',
                  params: { id: String(item.id) },
                })
              }
            />
          )}
          ListEmptyComponent={
            <View style={styles.centered}>
              <Feather
                name="calendar"
                size={26}
                color={colors.mutedForeground}
              />
              <Text style={styles.centeredText}>
                No appointments today.
              </Text>
              <Text style={styles.centeredSub}>
                Enjoy the quiet — or check back later.
              </Text>
            </View>
          }
        />
      )}
    </SafeAreaView>
  );
}

function countLabel(n: number): string {
  if (n === 0) return 'No appointments';
  return `${n} appointment${n === 1 ? '' : 's'}`;
}

const styles = StyleSheet.create({
  safe: {
    flex: 1,
    backgroundColor: colors.background,
  },
  header: {
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.lg,
    paddingBottom: spacing.md,
    gap: spacing.xs,
  },
  eyebrow: {
    fontFamily: fonts.sans,
    fontSize: fontSize.xs,
    textTransform: 'uppercase',
    letterSpacing: 1.5,
    color: colors.mutedForeground,
  },
  title: {
    fontFamily: fonts.serif,
    fontSize: fontSize.xxl,
    color: colors.foreground,
    letterSpacing: -0.5,
  },
  sub: {
    fontFamily: fonts.sans,
    fontSize: fontSize.sm,
    color: colors.mutedForeground,
  },
  list: {
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.sm,
    paddingBottom: spacing.xxl,
    gap: spacing.sm,
  },
  cardSkeleton: {
    height: 72,
    borderRadius: radius.lg,
  },
  centered: {
    alignItems: 'center',
    gap: spacing.sm,
    paddingVertical: spacing.xxl * 2,
    paddingHorizontal: spacing.xl,
  },
  centeredText: {
    fontFamily: fonts.sans,
    fontSize: fontSize.base,
    color: colors.foreground,
    fontWeight: '600',
  },
  centeredSub: {
    fontFamily: fonts.sans,
    fontSize: fontSize.sm,
    color: colors.mutedForeground,
    textAlign: 'center',
  },
  retry: {
    fontFamily: fonts.sans,
    fontSize: fontSize.sm,
    fontWeight: '600',
    color: colors.accent,
  },
});
