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
import { colors, fonts, fontSize, layout, radius, spacing } from '@/constants/theme';
import { formatLongDate, useUpcomingOnlineBookings } from '@/lib/appointments';

/** Online bookings — upcoming appointments booked through the public
 *  site, for staff to review and confirm. */
export default function OnlineBookingsScreen() {
  const { data, isLoading, isError, refetch, isRefetching } =
    useUpcomingOnlineBookings();

  const bookings = [...(data ?? [])].sort((a, b) =>
    a.start_time.localeCompare(b.start_time),
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
        <Text style={styles.headerTitle}>Online bookings</Text>
      </View>

      {isLoading ? (
        <View style={styles.list}>
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} style={styles.cardSkeleton} />
          ))}
        </View>
      ) : isError ? (
        <View style={styles.centered}>
          <Feather name="wifi-off" size={24} color={colors.mutedForeground} />
          <Text style={styles.centeredText}>
            Couldn&apos;t load online bookings.
          </Text>
          <Pressable onPress={() => refetch()} accessibilityRole="button" hitSlop={8}>
            <Text style={styles.retry}>Try again</Text>
          </Pressable>
        </View>
      ) : (
        <FlatList
          data={bookings}
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
            <View style={styles.item}>
              <Text style={styles.itemDate}>
                {formatLongDate(item.start_time)}
              </Text>
              <AppointmentCard
                appointment={item}
                onPress={() =>
                  router.push({
                    pathname: '/appointment/[id]',
                    params: { id: String(item.id) },
                  })
                }
              />
            </View>
          )}
          ListEmptyComponent={
            <View style={styles.centered}>
              <Feather name="globe" size={26} color={colors.mutedForeground} />
              <Text style={styles.centeredText}>No online bookings.</Text>
              <Text style={styles.centeredSub}>
                Appointments booked on your public site appear here.
              </Text>
            </View>
          }
        />
      )}
    </SafeAreaView>
  );
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
  list: {
    width: '100%',
    maxWidth: layout.contentMaxWidth,
    alignSelf: 'center',
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.sm,
    paddingBottom: spacing.xxl,
    gap: spacing.md,
    flexGrow: 1,
  },
  cardSkeleton: {
    height: 72,
    borderRadius: radius.lg,
  },
  item: {
    gap: 4,
  },
  itemDate: {
    fontFamily: fonts.sans,
    fontSize: fontSize.xs,
    fontWeight: '600',
    textTransform: 'uppercase',
    letterSpacing: 0.5,
    color: colors.mutedForeground,
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
    textAlign: 'center',
  },
  retry: {
    fontFamily: fonts.sans,
    fontSize: fontSize.sm,
    fontWeight: '600',
    color: colors.accent,
  },
});
