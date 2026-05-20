import { Pressable, StyleSheet, Text, View } from 'react-native';

import { colors, fonts, fontSize, radius, spacing } from '@/constants/theme';
import {
  appointmentDate,
  isToday,
  monthGridDays,
  useAppointmentsRange,
  type Appointment,
} from '@/lib/appointments';

const WEEKDAYS = ['S', 'M', 'T', 'W', 'T', 'F', 'S'];
const FALLBACK_COLOR = '#71717a';
/** Mirrors the web month view — two appointment bars per cell on the
 *  phone-width layout, the rest collapsed into a "+N". */
const MAX_BARS = 2;

/** A 6×7 month grid matching the web calendar: each cell shows the
 *  date and up to two appointment bars; tapping a day opens it. */
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

  const byDay = new Map<string, Appointment[]>();
  for (const appt of data ?? []) {
    const d = appointmentDate(appt);
    const list = byDay.get(d) ?? [];
    list.push(appt);
    byDay.set(d, list);
  }
  for (const list of byDay.values()) {
    list.sort((a, b) => a.start_time.localeCompare(b.start_time));
  }

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
        {[0, 1, 2, 3, 4, 5].map((row) => (
          <View key={row} style={styles.row}>
            {days.slice(row * 7, row * 7 + 7).map((day) => {
              const inMonth = day.slice(0, 7) === focusMonth;
              const today = isToday(day);
              const appts = byDay.get(day) ?? [];
              const overflow = appts.length - MAX_BARS;
              return (
                <Pressable
                  key={day}
                  onPress={() => onPickDay(day)}
                  accessibilityRole="button"
                  style={[styles.cell, !inMonth && styles.cellMuted]}
                >
                  <View style={[styles.dayBadge, today && styles.todayBadge]}>
                    <Text
                      style={[
                        styles.dayNum,
                        !inMonth && styles.dayNumMuted,
                        today && styles.dayNumToday,
                      ]}
                    >
                      {Number(day.split('-')[2])}
                    </Text>
                  </View>

                  <View style={styles.bars}>
                    {appts.slice(0, MAX_BARS).map((a) => (
                      <ApptBar key={a.id} appt={a} />
                    ))}
                    {overflow > 0 ? (
                      <Text style={styles.overflow}>+{overflow}</Text>
                    ) : null}
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

function ApptBar({ appt }: { appt: Appointment }) {
  const cancelled = appt.status === 'cancelled' || appt.status === 'no_show';
  const color = appt.service.category_color || FALLBACK_COLOR;
  return (
    <View style={[styles.bar, { backgroundColor: `${color}22` }]}>
      <View style={[styles.barDot, { backgroundColor: color }]} />
      <Text
        style={[styles.barText, cancelled && styles.barTextCancelled]}
        numberOfLines={1}
      >
        {appt.customer.full_name || 'Client'}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.card,
  },
  weekdayRow: {
    flexDirection: 'row',
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  weekday: {
    flex: 1,
    textAlign: 'center',
    paddingVertical: spacing.sm,
    fontFamily: fonts.sans,
    fontSize: 10,
    fontWeight: '600',
    textTransform: 'uppercase',
    letterSpacing: 0.5,
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
    minHeight: 64,
    padding: 3,
    gap: 2,
    overflow: 'hidden',
    borderRightWidth: 1,
    borderBottomWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.card,
  },
  cellMuted: {
    backgroundColor: colors.background,
  },
  dayBadge: {
    width: 20,
    height: 20,
    borderRadius: radius.pill,
    alignItems: 'center',
    justifyContent: 'center',
  },
  todayBadge: {
    backgroundColor: colors.foreground,
  },
  dayNum: {
    fontFamily: fonts.sans,
    fontSize: 11,
    fontWeight: '500',
    color: colors.foreground,
  },
  dayNumMuted: {
    color: colors.mutedForeground,
    opacity: 0.6,
  },
  dayNumToday: {
    color: colors.background,
    fontWeight: '700',
  },
  bars: {
    gap: 2,
  },
  bar: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 3,
    borderRadius: 3,
    paddingHorizontal: 3,
    paddingVertical: 1,
  },
  barDot: {
    width: 5,
    height: 5,
    borderRadius: radius.pill,
  },
  barText: {
    flex: 1,
    fontFamily: fonts.sans,
    fontSize: 9,
    color: '#1c1917',
  },
  barTextCancelled: {
    textDecorationLine: 'line-through',
    opacity: 0.6,
  },
  overflow: {
    fontFamily: fonts.sans,
    fontSize: 9,
    color: colors.mutedForeground,
    paddingLeft: 2,
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
