import { Pressable, StyleSheet, Text, View } from 'react-native';

import { colors, fonts, fontSize, radius, spacing } from '@/constants/theme';
import {
  appointmentDate,
  isToday,
  monthGridDays,
  useAppointmentsRange,
} from '@/lib/appointments';

const WEEKDAYS = ['S', 'M', 'T', 'W', 'T', 'F', 'S'];

/** A 6×7 month grid. Each cell shows the date and up to three dots for
 *  that day's appointments; tapping a day hands back its date. */
export function MonthView({
  date,
  onPickDay,
}: {
  date: string;
  onPickDay: (day: string) => void;
}) {
  const days = monthGridDays(date);
  const { data, isError, refetch } = useAppointmentsRange(days[0], days[41]);
  const focusMonth = date.slice(0, 7);

  const counts = new Map<string, number>();
  for (const appt of data ?? []) {
    if (appt.status === 'cancelled') continue;
    const d = appointmentDate(appt);
    counts.set(d, (counts.get(d) ?? 0) + 1);
  }

  const rows = [0, 1, 2, 3, 4, 5];

  return (
    <View style={styles.container}>
      <View style={styles.weekdayRow}>
        {WEEKDAYS.map((w, i) => (
          <Text key={i} style={styles.weekday}>
            {w}
          </Text>
        ))}
      </View>

      {isError ? (
        <Pressable
          onPress={() => refetch()}
          style={styles.errorBanner}
          accessibilityRole="button"
        >
          <Text style={styles.errorText}>
            Couldn&apos;t load this month — tap to retry.
          </Text>
        </Pressable>
      ) : null}

      <View style={styles.grid}>
        {rows.map((row) => (
          <View key={row} style={styles.row}>
            {days.slice(row * 7, row * 7 + 7).map((day) => {
              const inMonth = day.slice(0, 7) === focusMonth;
              const today = isToday(day);
              const count = counts.get(day) ?? 0;
              const dayNum = Number(day.split('-')[2]);
              return (
                <Pressable
                  key={day}
                  onPress={() => onPickDay(day)}
                  accessibilityRole="button"
                  style={styles.cell}
                >
                  <View style={[styles.dayBadge, today && styles.todayBadge]}>
                    <Text
                      style={[
                        styles.dayNum,
                        !inMonth && styles.dayNumMuted,
                        today && styles.dayNumToday,
                      ]}
                    >
                      {dayNum}
                    </Text>
                  </View>
                  <View style={styles.dots}>
                    {Array.from({ length: Math.min(count, 3) }).map((_, i) => (
                      <View key={i} style={styles.dot} />
                    ))}
                  </View>
                </Pressable>
              );
            })}
          </View>
        ))}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    paddingHorizontal: spacing.md,
  },
  weekdayRow: {
    flexDirection: 'row',
    paddingVertical: spacing.sm,
  },
  weekday: {
    flex: 1,
    textAlign: 'center',
    fontFamily: fonts.sans,
    fontSize: fontSize.xs,
    fontWeight: '700',
    color: colors.mutedForeground,
  },
  grid: {
    flex: 1,
  },
  row: {
    flex: 1,
    flexDirection: 'row',
  },
  cell: {
    flex: 1,
    alignItems: 'center',
    paddingTop: spacing.xs,
    gap: 4,
    borderTopWidth: 1,
    borderTopColor: colors.border,
  },
  dayBadge: {
    width: 28,
    height: 28,
    borderRadius: radius.pill,
    alignItems: 'center',
    justifyContent: 'center',
  },
  todayBadge: {
    backgroundColor: colors.accent,
  },
  dayNum: {
    fontFamily: fonts.sans,
    fontSize: fontSize.sm,
    fontWeight: '600',
    color: colors.foreground,
  },
  dayNumMuted: {
    color: colors.border,
  },
  dayNumToday: {
    color: colors.accentForeground,
  },
  dots: {
    flexDirection: 'row',
    gap: 3,
  },
  dot: {
    width: 5,
    height: 5,
    borderRadius: radius.pill,
    backgroundColor: colors.accent,
  },
  errorBanner: {
    paddingVertical: spacing.sm,
    alignItems: 'center',
  },
  errorText: {
    fontFamily: fonts.sans,
    fontSize: fontSize.xs,
    color: colors.destructive,
  },
});
