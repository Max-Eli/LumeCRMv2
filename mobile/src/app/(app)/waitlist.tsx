import { Feather } from '@expo/vector-icons';
import { router } from 'expo-router';
import {
  Alert,
  FlatList,
  Pressable,
  RefreshControl,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { Skeleton } from '@/components/ui/skeleton';
import { colors, fonts, fontSize, layout, radius, spacing } from '@/constants/theme';
import { formatDayLabel } from '@/lib/appointments';
import {
  useUpdateWaitlistEntry,
  useWaitlistEntries,
  WAITLIST_STATUS_LABEL,
  type WaitlistEntry,
  type WaitlistStatus,
} from '@/lib/waitlist';

const STATUS_STYLE: Record<WaitlistStatus, { fg: string; bg: string }> = {
  waiting: { fg: '#B7791F', bg: '#FBF0E0' },
  contacted: { fg: '#2D5A8A', bg: '#E7EEF6' },
  booked: { fg: '#2F7D52', bg: '#E5F0EA' },
  declined: { fg: '#9A9B9C', bg: '#ECEDEE' },
};

const NEXT: Record<WaitlistStatus, WaitlistStatus[]> = {
  waiting: ['contacted', 'booked', 'declined'],
  contacted: ['booked', 'declined'],
  booked: [],
  declined: [],
};

/** Waitlist — clients waiting for a slot. Tap an entry to advance it. */
export default function WaitlistScreen() {
  const { data, isLoading, isError, refetch, isRefetching } =
    useWaitlistEntries();

  const order: Record<WaitlistStatus, number> = {
    waiting: 0,
    contacted: 1,
    booked: 2,
    declined: 3,
  };
  const entries = [...(data ?? [])].sort(
    (a, b) => order[a.status] - order[b.status],
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
        <Text style={styles.headerTitle}>Waitlist</Text>
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
          <Text style={styles.centeredText}>Couldn&apos;t load the waitlist.</Text>
          <Pressable onPress={() => refetch()} accessibilityRole="button" hitSlop={8}>
            <Text style={styles.retry}>Try again</Text>
          </Pressable>
        </View>
      ) : (
        <FlatList
          data={entries}
          keyExtractor={(e) => String(e.id)}
          contentContainerStyle={styles.list}
          showsVerticalScrollIndicator={false}
          refreshControl={
            <RefreshControl
              refreshing={isRefetching}
              onRefresh={refetch}
              tintColor={colors.accent}
            />
          }
          renderItem={({ item }) => <WaitlistCard entry={item} />}
          ListEmptyComponent={
            <View style={styles.centered}>
              <Feather name="list" size={26} color={colors.mutedForeground} />
              <Text style={styles.centeredText}>The waitlist is empty.</Text>
            </View>
          }
        />
      )}
    </SafeAreaView>
  );
}

function WaitlistCard({ entry }: { entry: WaitlistEntry }) {
  const update = useUpdateWaitlistEntry(entry.id);
  const next = NEXT[entry.status];
  const name =
    `${entry.customer_first_name} ${entry.customer_last_name}`.trim() ||
    entry.customer_phone;

  function onPress() {
    if (next.length === 0 || update.isPending) return;
    Alert.alert(name, 'Update waitlist status', [
      ...next.map((status) => ({
        text: WAITLIST_STATUS_LABEL[status],
        onPress: () => update.mutate(status),
      })),
      { text: 'Cancel', style: 'cancel' as const },
    ]);
  }

  const tone = STATUS_STYLE[entry.status];

  return (
    <Pressable
      onPress={onPress}
      disabled={next.length === 0}
      accessibilityRole="button"
      style={({ pressed }) => [styles.card, pressed && next.length > 0 && styles.cardPressed]}
    >
      <View style={styles.cardText}>
        <Text style={styles.name} numberOfLines={1}>
          {name}
        </Text>
        <Text style={styles.detail} numberOfLines={1}>
          {entry.service_name}
          {entry.provider_display_name ? ` · ${entry.provider_display_name}` : ''}
        </Text>
        <Text style={styles.detail}>
          Prefers {formatDayLabel(entry.preferred_date)}
        </Text>
      </View>
      <View style={[styles.pill, { backgroundColor: tone.bg }]}>
        <Text style={[styles.pillText, { color: tone.fg }]}>
          {WAITLIST_STATUS_LABEL[entry.status]}
        </Text>
      </View>
    </Pressable>
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
    gap: spacing.sm,
    flexGrow: 1,
  },
  cardSkeleton: {
    height: 88,
    borderRadius: radius.lg,
  },
  card: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: spacing.md,
    padding: spacing.lg,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.card,
  },
  cardPressed: {
    backgroundColor: colors.muted,
  },
  cardText: {
    flex: 1,
    gap: 2,
  },
  name: {
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
  pill: {
    paddingHorizontal: 9,
    paddingVertical: 4,
    borderRadius: radius.pill,
  },
  pillText: {
    fontFamily: fonts.sans,
    fontSize: 11,
    fontWeight: '600',
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
  retry: {
    fontFamily: fonts.sans,
    fontSize: fontSize.sm,
    fontWeight: '600',
    color: colors.accent,
  },
});
