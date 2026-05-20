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
const HOUR_PX = 60;
const DEFAULT_START_HOUR = 8;
const DEFAULT_END_HOUR = 20;
const MAX_COLS = 3;
const WEEKDAY = ['S', 'M', 'T', 'W', 'T', 'F', 'S'];
const FALLBACK_COLOR = '#71717a';

interface ApptCell {
  kind: 'appt';
  appt: Appointment;
  topMin: number;
  durationMin: number;
  col: number;
  cols: number;
}
interface OverflowCell {
  kind: 'overflow';
  topMin: number;
  durationMin: number;
  col: number;
  cols: number;
  count: number;
}
type Cell = ApptCell | OverflowCell;

/** Local minutes-from-midnight of an ISO timestamp. */
function minutesOf(iso: string): number {
  const d = new Date(iso);
  return d.getHours() * 60 + d.getMinutes();
}

function hourLabel(h: number): string {
  if (h === 0 || h === 24) return '12 AM';
  if (h === 12) return '12 PM';
  return h < 12 ? `${h} AM` : `${h - 12} PM`;
}

/** Overlap packing — clusters of mutually-overlapping appointments are
 *  packed side-by-side, capped at 3 columns; anything past the cap
 *  collapses into a single "+N" tile. Ported from the web week view. */
function packDay(appts: Appointment[]): Cell[] {
  const items = appts
    .map((appt) => {
      const topMin = minutesOf(appt.start_time);
      const endMin = minutesOf(appt.end_time);
      return { appt, topMin, endMin: Math.max(endMin, topMin + 5) };
    })
    .sort((a, b) => a.topMin - b.topMin || a.endMin - b.endMin);

  const result: Cell[] = [];
  let cluster: typeof items = [];
  let clusterEnd = -1;

  const flush = () => {
    if (cluster.length === 0) return;
    const columnEnds: number[] = [];
    const colOf = new Map<Appointment, number>();
    for (const it of cluster) {
      let placed = -1;
      for (let c = 0; c < columnEnds.length; c++) {
        if (it.topMin >= columnEnds[c]) {
          placed = c;
          break;
        }
      }
      if (placed === -1) {
        placed = columnEnds.length;
        columnEnds.push(it.endMin);
      } else {
        columnEnds[placed] = it.endMin;
      }
      colOf.set(it.appt, placed);
    }
    const neededCols = columnEnds.length;

    if (neededCols <= MAX_COLS) {
      for (const it of cluster) {
        result.push({
          kind: 'appt',
          appt: it.appt,
          topMin: it.topMin,
          durationMin: it.endMin - it.topMin,
          col: colOf.get(it.appt) ?? 0,
          cols: neededCols,
        });
      }
    } else {
      const visibleCol = MAX_COLS - 1;
      const overflow: typeof items = [];
      for (const it of cluster) {
        const c = colOf.get(it.appt) ?? 0;
        if (c < visibleCol) {
          result.push({
            kind: 'appt',
            appt: it.appt,
            topMin: it.topMin,
            durationMin: it.endMin - it.topMin,
            col: c,
            cols: MAX_COLS,
          });
        } else {
          overflow.push(it);
        }
      }
      if (overflow.length > 0) {
        const ovTop = Math.min(...overflow.map((o) => o.topMin));
        const ovEnd = Math.max(...overflow.map((o) => o.endMin));
        result.push({
          kind: 'overflow',
          topMin: ovTop,
          durationMin: ovEnd - ovTop,
          col: visibleCol,
          cols: MAX_COLS,
          count: overflow.length,
        });
      }
    }
    cluster = [];
  };

  for (const it of items) {
    if (cluster.length > 0 && it.topMin >= clusterEnd) {
      flush();
      clusterEnd = -1;
    }
    cluster.push(it);
    clusterEnd = Math.max(clusterEnd, it.endMin);
  }
  flush();
  return result;
}

/** Seven-day time grid, ported from the web calendar's week view. */
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

  // Window: business hours, widened to cover any outlier appointment.
  let lo = DEFAULT_START_HOUR;
  let hi = DEFAULT_END_HOUR;
  for (const a of appts) {
    const s = new Date(a.start_time);
    const e = new Date(a.end_time);
    lo = Math.min(lo, s.getHours());
    hi = Math.max(hi, e.getMinutes() > 0 ? e.getHours() + 1 : e.getHours());
  }
  const startHour = Math.max(0, lo);
  const endHour = Math.min(24, Math.max(hi, startHour + 1));
  const startMin = startHour * 60;
  const bodyHeight = (endHour - startHour) * HOUR_PX;
  const hours = Array.from({ length: endHour - startHour + 1 }, (_, i) => i);

  const today = todayString();
  const now = new Date();
  const nowOffset =
    ((now.getHours() * 60 + now.getMinutes() - startMin) / 60) * HOUR_PX;

  return (
    <View style={styles.container}>
      <View style={styles.headerRow}>
        <View style={{ width: GUTTER }} />
        {days.map((d, i) => {
          const current = isToday(d);
          const count = (byDay.get(d) ?? []).length;
          return (
            <Pressable
              key={d}
              onPress={() => onPickDay(d)}
              accessibilityRole="button"
              style={styles.dayHead}
            >
              <Text style={styles.dowLetter}>{WEEKDAY[i]}</Text>
              <View style={[styles.dateBadge, current && styles.dateBadgeToday]}>
                <Text style={[styles.dateNum, current && styles.dateNumToday]}>
                  {Number(d.split('-')[2])}
                </Text>
              </View>
              <Text style={styles.dayCount}>{count > 0 ? count : ''}</Text>
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
            {hours.map((i) => (
              <Text
                key={i}
                style={[styles.hourLabel, { top: i * HOUR_PX - 6 }]}
              >
                {i === 0 ? '' : hourLabel(startHour + i)}
              </Text>
            ))}
          </View>

          <View style={styles.grid}>
            {hours.map((i) => (
              <View
                key={i}
                style={[styles.hourLine, { top: i * HOUR_PX }]}
              />
            ))}

            <View style={styles.columns}>
              {days.map((d, i) => {
                const current = isToday(d);
                return (
                  <View
                    key={d}
                    style={[styles.dayCol, i < 6 && styles.dayColBorder]}
                  >
                    {packDay(byDay.get(d) ?? []).map((cell, idx) => (
                      <WeekCell
                        key={cell.kind === 'appt' ? cell.appt.id : `ov-${idx}`}
                        cell={cell}
                        startMin={startMin}
                        onOverflow={() => onPickDay(d)}
                      />
                    ))}
                    {current &&
                    nowOffset >= 0 &&
                    nowOffset <= bodyHeight ? (
                      <View style={[styles.nowLine, { top: nowOffset }]}>
                        <View style={styles.nowDot} />
                      </View>
                    ) : null}
                  </View>
                );
              })}
            </View>
          </View>
        </View>
      </ScrollView>
    </View>
  );
}

function WeekCell({
  cell,
  startMin,
  onOverflow,
}: {
  cell: Cell;
  startMin: number;
  onOverflow: () => void;
}) {
  const top = ((cell.topMin - startMin) / 60) * HOUR_PX;
  const height = Math.max(16, (cell.durationMin / 60) * HOUR_PX);
  const widthPct = 100 / cell.cols;
  const position = {
    top,
    height,
    left: `${cell.col * widthPct}%` as const,
    width: `${widthPct}%` as const,
  };

  if (cell.kind === 'overflow') {
    return (
      <Pressable
        onPress={onOverflow}
        accessibilityRole="button"
        style={[styles.overflow, position]}
      >
        <Text style={styles.overflowText}>+{cell.count}</Text>
      </Pressable>
    );
  }

  const { appt } = cell;
  const cancelled = appt.status === 'cancelled' || appt.status === 'no_show';
  const color = appt.service.category_color || FALLBACK_COLOR;
  const showText = height >= 26 && cell.cols <= 2;

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
        position,
        {
          backgroundColor: `${color}26`,
          borderLeftColor: color,
        },
        cancelled && styles.blockCancelled,
      ]}
    >
      {showText ? (
        <Text
          style={[styles.blockText, cancelled && styles.blockTextCancelled]}
          numberOfLines={1}
        >
          {appt.customer.full_name || 'Client'}
        </Text>
      ) : null}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.card,
  },
  headerRow: {
    flexDirection: 'row',
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
    paddingVertical: 4,
  },
  dayHead: {
    flex: 1,
    alignItems: 'center',
    gap: 1,
  },
  dowLetter: {
    fontFamily: fonts.sans,
    fontSize: 10,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
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
    backgroundColor: colors.foreground,
  },
  dateNum: {
    fontFamily: fonts.sans,
    fontSize: fontSize.xs,
    color: colors.foreground,
  },
  dateNumToday: {
    color: colors.background,
    fontWeight: '700',
  },
  dayCount: {
    fontFamily: fonts.sans,
    fontSize: 9,
    color: colors.mutedForeground,
    height: 12,
  },
  body: {
    flex: 1,
    flexDirection: 'row',
  },
  hourLabel: {
    position: 'absolute',
    right: 4,
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
    borderRightWidth: 1,
    borderRightColor: colors.border,
  },
  block: {
    position: 'absolute',
    borderRadius: 4,
    borderLeftWidth: 3,
    overflow: 'hidden',
  },
  blockCancelled: {
    opacity: 0.55,
  },
  blockText: {
    fontFamily: fonts.sans,
    fontSize: 10,
    fontWeight: '500',
    color: colors.foreground,
    paddingHorizontal: 3,
    paddingTop: 1,
  },
  blockTextCancelled: {
    textDecorationLine: 'line-through',
  },
  overflow: {
    position: 'absolute',
    borderRadius: 4,
    backgroundColor: colors.muted,
    borderWidth: 1,
    borderColor: colors.border,
    alignItems: 'center',
    justifyContent: 'center',
  },
  overflowText: {
    fontFamily: fonts.sans,
    fontSize: 10,
    fontWeight: '600',
    color: colors.mutedForeground,
  },
  nowLine: {
    position: 'absolute',
    left: 0,
    right: 0,
    height: 1,
    backgroundColor: '#ef4444',
  },
  nowDot: {
    position: 'absolute',
    left: -3,
    top: -3,
    width: 7,
    height: 7,
    borderRadius: radius.pill,
    backgroundColor: '#ef4444',
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
