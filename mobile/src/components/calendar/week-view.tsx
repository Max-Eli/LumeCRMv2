import { router } from 'expo-router';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

import { colors, fonts, fontSize, radius } from '@/constants/theme';
import {
  appointmentDate,
  isToday,
  todayString,
  useAppointmentsRange,
  weekDays,
  type Appointment,
} from '@/lib/appointments';

const GUTTER = 44;
const HOUR_PX = 56;
const WEEKDAY = ['S', 'M', 'T', 'W', 'T', 'F', 'S'];

interface Packed {
  appt: Appointment;
  col: number;
  cols: number;
}

/** Local minutes-from-midnight of an ISO timestamp. */
function minutesOf(iso: string): number {
  const d = new Date(iso);
  return d.getHours() * 60 + d.getMinutes();
}

/** Greedy overlap packing — clusters of overlapping appointments share
 *  side-by-side sub-columns. */
function packDay(appts: Appointment[]): Packed[] {
  const sorted = [...appts].sort((a, b) =>
    a.start_time.localeCompare(b.start_time),
  );
  const out: Packed[] = [];
  let cluster: Appointment[] = [];
  let clusterEnd = -1;

  const flush = () => {
    const colEnd: number[] = [];
    const placed = cluster.map((a) => {
      const s = minutesOf(a.start_time);
      const e = s + a.duration_minutes;
      let col = colEnd.findIndex((end) => end <= s);
      if (col === -1) {
        col = colEnd.length;
        colEnd.push(e);
      } else {
        colEnd[col] = e;
      }
      return { a, col };
    });
    for (const p of placed) {
      out.push({ appt: p.a, col: p.col, cols: colEnd.length });
    }
    cluster = [];
    clusterEnd = -1;
  };

  for (const a of sorted) {
    const s = minutesOf(a.start_time);
    if (cluster.length && s >= clusterEnd) flush();
    cluster.push(a);
    clusterEnd = Math.max(clusterEnd, s + a.duration_minutes);
  }
  if (cluster.length) flush();
  return out;
}

function hourLabel(h: number): string {
  const period = h >= 12 ? 'PM' : 'AM';
  return `${h % 12 || 12} ${period}`;
}

/** Seven-day time grid, faithful to the web calendar's week view. */
export function WeekView({
  date,
  onPickDay,
}: {
  date: string;
  onPickDay: (day: string) => void;
}) {
  const days = weekDays(date);
  const { data, isError, refetch } = useAppointmentsRange(days[0], days[6]);
  const appts = data ?? [];

  const byDay = new Map<string, Appointment[]>(days.map((d) => [d, []]));
  for (const a of appts) {
    const d = appointmentDate(a);
    if (a.status !== 'cancelled' && byDay.has(d)) byDay.get(d)!.push(a);
  }

  // Hour window: 8–20 by default, widened to fit the week's data.
  let lo = 8;
  let hi = 20;
  for (const a of appts) {
    const s = minutesOf(a.start_time);
    lo = Math.min(lo, Math.floor(s / 60));
    hi = Math.max(hi, Math.ceil((s + a.duration_minutes) / 60));
  }
  lo = Math.max(0, lo);
  hi = Math.min(24, hi);
  const hours = hi - lo;
  const bodyHeight = hours * HOUR_PX;

  const today = todayString();
  const nowMin = new Date().getHours() * 60 + new Date().getMinutes();
  const showNow =
    days.includes(today) && nowMin >= lo * 60 && nowMin <= hi * 60;
  const nowTop = ((nowMin - lo * 60) / 60) * HOUR_PX;

  return (
    <View style={styles.container}>
      <View style={styles.headerRow}>
        <View style={{ width: GUTTER }} />
        {days.map((d, i) => {
          const isCurrent = isToday(d);
          return (
            <Pressable
              key={d}
              onPress={() => onPickDay(d)}
              accessibilityRole="button"
              style={styles.dayHead}
            >
              <Text style={styles.dowLetter}>{WEEKDAY[i]}</Text>
              <View
                style={[styles.dateBadge, isCurrent && styles.dateBadgeToday]}
              >
                <Text
                  style={[
                    styles.dateNum,
                    isCurrent && styles.dateNumToday,
                  ]}
                >
                  {Number(d.split('-')[2])}
                </Text>
              </View>
            </Pressable>
          );
        })}
      </View>

      {isError ? (
        <Pressable
          onPress={() => refetch()}
          style={styles.errorBanner}
          accessibilityRole="button"
        >
          <Text style={styles.errorText}>
            Couldn&apos;t load this week — tap to retry.
          </Text>
        </Pressable>
      ) : null}

      <ScrollView
        contentContainerStyle={{ height: bodyHeight }}
        showsVerticalScrollIndicator={false}
      >
        <View style={styles.body}>
          <View style={{ width: GUTTER }}>
            {Array.from({ length: hours + 1 }).map((_, i) => (
              <Text
                key={i}
                style={[styles.hourLabel, { top: Math.max(0, i * HOUR_PX - 7) }]}
              >
                {hourLabel(lo + i)}
              </Text>
            ))}
          </View>

          <View style={styles.grid}>
            {Array.from({ length: hours + 1 }).map((_, i) => (
              <View
                key={i}
                style={[styles.hourLine, { top: i * HOUR_PX }]}
              />
            ))}

            <View style={styles.columns}>
              {days.map((d, i) => (
                <View
                  key={d}
                  style={[styles.dayCol, i > 0 && styles.dayColBorder]}
                >
                  {packDay(byDay.get(d) ?? []).map((p) => (
                    <WeekBlock key={p.appt.id} packed={p} lo={lo} />
                  ))}
                </View>
              ))}
            </View>

            {showNow ? (
              <View style={[styles.nowLine, { top: nowTop }]} />
            ) : null}
          </View>
        </View>
      </ScrollView>
    </View>
  );
}

function WeekBlock({ packed, lo }: { packed: Packed; lo: number }) {
  const { appt, col, cols } = packed;
  const top = ((minutesOf(appt.start_time) - lo * 60) / 60) * HOUR_PX;
  const height = Math.max(18, (appt.duration_minutes / 60) * HOUR_PX);
  const firstName = (appt.customer.full_name || 'Client').split(' ')[0];

  return (
    <Pressable
      onPress={() =>
        router.push({
          pathname: '/appointment/[id]',
          params: { id: String(appt.id) },
        })
      }
      style={[
        styles.block,
        {
          top,
          height: height - 2,
          left: `${(col * 100) / cols}%`,
          width: `${100 / cols}%`,
          borderLeftColor: appt.service.category_color || colors.accent,
        },
      ]}
    >
      {height >= 34 && cols === 1 ? (
        <Text style={styles.blockText} numberOfLines={1}>
          {firstName}
        </Text>
      ) : null}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
  headerRow: {
    flexDirection: 'row',
    paddingBottom: 6,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  dayHead: {
    flex: 1,
    alignItems: 'center',
    gap: 2,
  },
  dowLetter: {
    fontFamily: fonts.sans,
    fontSize: 10,
    fontWeight: '700',
    color: colors.mutedForeground,
  },
  dateBadge: {
    width: 24,
    height: 24,
    borderRadius: radius.pill,
    alignItems: 'center',
    justifyContent: 'center',
  },
  dateBadgeToday: {
    backgroundColor: colors.accent,
  },
  dateNum: {
    fontFamily: fonts.sans,
    fontSize: fontSize.sm,
    fontWeight: '600',
    color: colors.foreground,
  },
  dateNumToday: {
    color: colors.accentForeground,
  },
  body: {
    flex: 1,
    flexDirection: 'row',
  },
  hourLabel: {
    position: 'absolute',
    right: 6,
    fontFamily: fonts.sans,
    fontSize: 10,
    color: colors.mutedForeground,
  },
  grid: {
    flex: 1,
  },
  hourLine: {
    position: 'absolute',
    left: 0,
    right: 0,
    height: 1,
    backgroundColor: colors.border,
  },
  columns: {
    flex: 1,
    flexDirection: 'row',
  },
  dayCol: {
    flex: 1,
  },
  dayColBorder: {
    borderLeftWidth: 1,
    borderLeftColor: colors.border,
  },
  block: {
    position: 'absolute',
    backgroundColor: colors.card,
    borderWidth: 1,
    borderColor: colors.border,
    borderLeftWidth: 3,
    borderRadius: radius.sm,
    paddingHorizontal: 3,
    paddingTop: 2,
    overflow: 'hidden',
  },
  blockText: {
    fontFamily: fonts.sans,
    fontSize: 9,
    fontWeight: '600',
    color: colors.foreground,
  },
  nowLine: {
    position: 'absolute',
    left: 0,
    right: 0,
    height: 2,
    backgroundColor: colors.destructive,
  },
  errorBanner: {
    paddingVertical: 6,
    alignItems: 'center',
  },
  errorText: {
    fontFamily: fonts.sans,
    fontSize: fontSize.xs,
    color: colors.destructive,
  },
});
