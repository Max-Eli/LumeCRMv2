import { Feather } from '@expo/vector-icons';
import { router } from 'expo-router';
import { FlatList, Pressable, RefreshControl, StyleSheet, Text, View } from 'react-native';

import { AppointmentCard } from '@/components/appointment-card';
import { Skeleton } from '@/components/ui/skeleton';
import { colors, fonts, fontSize, radius, spacing } from '@/constants/theme';
import { useAppointmentsForDate } from '@/lib/appointments';

/** The list of one day's appointments, sorted by start time. */
export function DayView({ date }: { date: string }) {
  const { data, isLoading, isError, refetch, isRefetching } =
    useAppointmentsForDate(date);

  const appts = [...(data ?? [])].sort((a, b) =>
    a.start_time.localeCompare(b.start_time),
  );

  if (isLoading) {
    return (
      <View style={styles.list}>
        {[0, 1, 2, 3, 4].map((i) => (
          <Skeleton key={i} style={styles.cardSkeleton} />
        ))}
      </View>
    );
  }

  if (isError) {
    return (
      <View style={styles.centered}>
        <Feather name="wifi-off" size={24} color={colors.mutedForeground} />
        <Text style={styles.centeredText}>Couldn&apos;t load the schedule.</Text>
        <Pressable onPress={() => refetch()} accessibilityRole="button" hitSlop={8}>
          <Text style={styles.retry}>Try again</Text>
        </Pressable>
      </View>
    );
  }

  return (
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
          <Feather name="calendar" size={26} color={colors.mutedForeground} />
          <Text style={styles.centeredText}>No appointments.</Text>
          <Text style={styles.centeredSub}>Nothing booked for this day.</Text>
        </View>
      }
    />
  );
}

const styles = StyleSheet.create({
  list: {
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.sm,
    paddingBottom: spacing.xxl,
    gap: spacing.sm,
    flexGrow: 1,
  },
  cardSkeleton: {
    height: 72,
    borderRadius: radius.lg,
  },
  centered: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    gap: spacing.sm,
    paddingVertical: spacing.xxl * 2,
  },
  centeredText: {
    fontFamily: fonts.sans,
    fontSize: fontSize.base,
    fontWeight: '600',
    color: colors.foreground,
  },
  centeredSub: {
    fontFamily: fonts.sans,
    fontSize: fontSize.sm,
    color: colors.mutedForeground,
  },
  retry: {
    fontFamily: fonts.sans,
    fontSize: fontSize.sm,
    fontWeight: '600',
    color: colors.accent,
  },
});
