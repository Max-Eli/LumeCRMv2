import { Feather } from '@expo/vector-icons';
import { router } from 'expo-router';
import { useEffect, useReducer } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { colors, fonts, fontSize, layout, radius, spacing } from '@/constants/theme';
import { formatTime } from '@/lib/appointments';
import {
  formatDuration,
  useClockIn,
  useClockOut,
  useMyTimeState,
  type TimeEntry,
} from '@/lib/timetracking';

const MONTHS = [
  'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
];

function shortDate(iso: string): string {
  const d = new Date(iso);
  return `${MONTHS[d.getMonth()]} ${d.getDate()}`;
}

/** Employee time clock — clock in / out and review recent shifts. */
export default function ClockInScreen() {
  const { data, isLoading, isError, refetch } = useMyTimeState();
  const clockIn = useClockIn();
  const clockOut = useClockOut();

  // Tick every 30s so the open-shift elapsed time stays current.
  const [, tick] = useReducer((x: number) => x + 1, 0);
  useEffect(() => {
    const t = setInterval(tick, 30000);
    return () => clearInterval(t);
  }, []);

  const open = data?.open_entry ?? null;
  const recent = data?.recent ?? [];
  const elapsed = open
    ? Math.floor((Date.now() - new Date(open.clock_in_at).getTime()) / 1000)
    : 0;
  const busy = clockIn.isPending || clockOut.isPending;

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
        <Text style={styles.headerTitle}>Time clock</Text>
      </View>

      <ScrollView
        contentContainerStyle={styles.content}
        showsVerticalScrollIndicator={false}
      >
        {isLoading ? (
          <Skeleton style={{ height: 160, borderRadius: radius.lg }} />
        ) : isError ? (
          <View style={styles.errorBox}>
            <Feather name="wifi-off" size={24} color={colors.mutedForeground} />
            <Text style={styles.errorText}>Couldn&apos;t load your clock.</Text>
            <Pressable onPress={() => refetch()} accessibilityRole="button" hitSlop={8}>
              <Text style={styles.retry}>Try again</Text>
            </Pressable>
          </View>
        ) : (
          <>
            <View style={[styles.statusCard, open && styles.statusCardOn]}>
              <Text style={[styles.statusLabel, open && styles.statusLabelOn]}>
                {open ? 'On the clock' : 'Off the clock'}
              </Text>
              {open ? (
                <>
                  <Text style={styles.elapsed}>{formatDuration(elapsed)}</Text>
                  <Text style={styles.since}>
                    Since {formatTime(open.clock_in_at)}
                  </Text>
                </>
              ) : (
                <Text style={styles.since}>
                  Clock in to start tracking your shift.
                </Text>
              )}
            </View>

            <Button
              label={open ? 'Clock out' : 'Clock in'}
              onPress={() => (open ? clockOut.mutate() : clockIn.mutate())}
              loading={busy}
            />

            {clockIn.isError || clockOut.isError ? (
              <Text style={styles.errorText}>
                Couldn&apos;t update your clock. Try again.
              </Text>
            ) : null}

            <View style={styles.section}>
              <Text style={styles.sectionTitle}>Recent shifts</Text>
              {recent.length === 0 ? (
                <Text style={styles.empty}>No shifts recorded yet.</Text>
              ) : (
                <View style={styles.card}>
                  {recent.map((entry, i) => (
                    <ShiftRow key={entry.id} entry={entry} divided={i > 0} />
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

function ShiftRow({ entry, divided }: { entry: TimeEntry; divided: boolean }) {
  return (
    <View style={[styles.shift, divided && styles.shiftDivided]}>
      <View>
        <Text style={styles.shiftDate}>{shortDate(entry.clock_in_at)}</Text>
        <Text style={styles.shiftTime}>
          {formatTime(entry.clock_in_at)}
          {entry.clock_out_at ? ` – ${formatTime(entry.clock_out_at)}` : ''}
        </Text>
      </View>
      <Text style={styles.shiftDuration}>
        {formatDuration(entry.duration_seconds)}
      </Text>
    </View>
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
  content: {
    width: '100%',
    maxWidth: layout.contentMaxWidth,
    alignSelf: 'center',
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.md,
    paddingBottom: spacing.xxl,
    gap: spacing.lg,
  },
  statusCard: {
    backgroundColor: colors.card,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.lg,
    padding: spacing.xl,
    alignItems: 'center',
    gap: spacing.xs,
  },
  statusCardOn: {
    borderColor: colors.accent,
  },
  statusLabel: {
    fontFamily: fonts.sans,
    fontSize: fontSize.xs,
    textTransform: 'uppercase',
    letterSpacing: 1.5,
    color: colors.mutedForeground,
  },
  statusLabelOn: {
    color: colors.accent,
  },
  elapsed: {
    fontFamily: fonts.serif,
    fontSize: 40,
    color: colors.foreground,
    letterSpacing: -0.5,
  },
  since: {
    fontFamily: fonts.sans,
    fontSize: fontSize.sm,
    color: colors.mutedForeground,
  },
  section: { gap: spacing.sm },
  sectionTitle: {
    fontFamily: fonts.sans,
    fontSize: fontSize.md,
    fontWeight: '700',
    color: colors.foreground,
  },
  empty: {
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
  shift: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingVertical: spacing.md,
  },
  shiftDivided: {
    borderTopWidth: 1,
    borderTopColor: colors.border,
  },
  shiftDate: {
    fontFamily: fonts.sans,
    fontSize: fontSize.base,
    fontWeight: '600',
    color: colors.foreground,
  },
  shiftTime: {
    fontFamily: fonts.sans,
    fontSize: fontSize.sm,
    color: colors.mutedForeground,
  },
  shiftDuration: {
    fontFamily: fonts.sans,
    fontSize: fontSize.base,
    fontWeight: '600',
    color: colors.foreground,
  },
  errorBox: {
    alignItems: 'center',
    gap: spacing.sm,
    paddingVertical: spacing.xxl,
  },
  errorText: {
    fontFamily: fonts.sans,
    fontSize: fontSize.sm,
    color: colors.destructive,
  },
  retry: {
    fontFamily: fonts.sans,
    fontSize: fontSize.sm,
    fontWeight: '600',
    color: colors.accent,
  },
});
