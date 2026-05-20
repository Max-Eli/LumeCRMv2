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

import { Skeleton } from '@/components/ui/skeleton';
import { colors, fonts, fontSize, radius, spacing } from '@/constants/theme';
import { formatTime, todayString } from '@/lib/appointments';
import { useThreads, type ThreadSummary } from '@/lib/messaging';

const MONTHS = [
  'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
];

/** "2:30 PM" if today, otherwise "May 18". */
function threadTime(iso: string): string {
  const d = new Date(iso);
  const ymd = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  if (ymd === todayString()) return formatTime(iso);
  return `${MONTHS[d.getMonth()]} ${d.getDate()}`;
}

/** Inbox tab — SMS conversations with clients. */
export default function InboxScreen() {
  const { data, isLoading, isError, refetch, isRefetching } = useThreads();
  const threads = data ?? [];

  return (
    <SafeAreaView edges={['top']} style={styles.safe}>
      <View style={styles.header}>
        <Text style={styles.title}>Inbox</Text>
      </View>

      {isLoading ? (
        <View style={styles.list}>
          {[0, 1, 2, 3, 4].map((i) => (
            <Skeleton key={i} style={styles.rowSkeleton} />
          ))}
        </View>
      ) : isError ? (
        <View style={styles.centered}>
          <Feather name="wifi-off" size={24} color={colors.mutedForeground} />
          <Text style={styles.centeredText}>Couldn&apos;t load messages.</Text>
          <Pressable onPress={() => refetch()} accessibilityRole="button" hitSlop={8}>
            <Text style={styles.retry}>Try again</Text>
          </Pressable>
        </View>
      ) : (
        <FlatList
          data={threads}
          keyExtractor={(t) => String(t.customer_id)}
          contentContainerStyle={styles.list}
          showsVerticalScrollIndicator={false}
          refreshControl={
            <RefreshControl
              refreshing={isRefetching}
              onRefresh={refetch}
              tintColor={colors.accent}
            />
          }
          renderItem={({ item }) => <ThreadRow thread={item} />}
          ListEmptyComponent={
            <View style={styles.centered}>
              <Feather
                name="message-circle"
                size={26}
                color={colors.mutedForeground}
              />
              <Text style={styles.centeredText}>No conversations yet.</Text>
            </View>
          }
        />
      )}
    </SafeAreaView>
  );
}

function ThreadRow({ thread }: { thread: ThreadSummary }) {
  const name =
    `${thread.customer_first_name} ${thread.customer_last_name}`.trim() ||
    thread.customer_phone;
  const unread = thread.unread_inbound_count > 0;
  const preview =
    (thread.last_message_direction === 'outbound' ? 'You: ' : '') +
    thread.last_message_body;

  return (
    <Pressable
      onPress={() =>
        router.push({
          pathname: '/conversation/[customerId]',
          params: { customerId: String(thread.customer_id) },
        })
      }
      accessibilityRole="button"
      style={({ pressed }) => [styles.row, pressed && styles.rowPressed]}
    >
      <View style={styles.avatar}>
        <Text style={styles.avatarText}>
          {(thread.customer_first_name[0] ?? '·').toUpperCase()}
        </Text>
      </View>
      <View style={styles.rowText}>
        <View style={styles.rowTop}>
          <Text style={styles.name} numberOfLines={1}>
            {name}
          </Text>
          <Text style={styles.time}>{threadTime(thread.last_message_at)}</Text>
        </View>
        <Text
          style={[styles.preview, unread && styles.previewUnread]}
          numberOfLines={1}
        >
          {preview}
        </Text>
      </View>
      {unread ? (
        <View style={styles.unreadBadge}>
          <Text style={styles.unreadText}>{thread.unread_inbound_count}</Text>
        </View>
      ) : null}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  header: {
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.sm,
    paddingBottom: spacing.md,
  },
  title: {
    fontFamily: fonts.serif,
    fontSize: fontSize.xxl,
    color: colors.foreground,
    letterSpacing: -0.5,
  },
  list: {
    paddingHorizontal: spacing.lg,
    paddingBottom: spacing.xxl,
    gap: spacing.sm,
    flexGrow: 1,
  },
  rowSkeleton: {
    height: 68,
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
  retry: {
    fontFamily: fonts.sans,
    fontSize: fontSize.sm,
    fontWeight: '600',
    color: colors.accent,
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
  avatar: {
    width: 42,
    height: 42,
    borderRadius: radius.pill,
    backgroundColor: colors.muted,
    alignItems: 'center',
    justifyContent: 'center',
  },
  avatarText: {
    fontFamily: fonts.sans,
    fontSize: fontSize.sm,
    fontWeight: '700',
    color: colors.foreground,
  },
  rowText: {
    flex: 1,
    gap: 2,
  },
  rowTop: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: spacing.sm,
  },
  name: {
    flex: 1,
    fontFamily: fonts.sans,
    fontSize: fontSize.base,
    fontWeight: '600',
    color: colors.foreground,
  },
  time: {
    fontFamily: fonts.sans,
    fontSize: fontSize.xs,
    color: colors.mutedForeground,
  },
  preview: {
    fontFamily: fonts.sans,
    fontSize: fontSize.sm,
    color: colors.mutedForeground,
  },
  previewUnread: {
    color: colors.foreground,
    fontWeight: '600',
  },
  unreadBadge: {
    minWidth: 20,
    height: 20,
    borderRadius: radius.pill,
    backgroundColor: colors.accent,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 6,
  },
  unreadText: {
    fontFamily: fonts.sans,
    fontSize: 11,
    fontWeight: '700',
    color: colors.accentForeground,
  },
});
