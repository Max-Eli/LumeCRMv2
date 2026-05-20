import { router } from 'expo-router';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

import { colors, fonts, fontSize, radius } from '@/constants/theme';
import {
  todayString,
  useAppointmentsForDate,
  type Appointment,
} from '@/lib/appointments';
import {
  computeHourWindow,
  FALLBACK_COLOR,
  GUTTER_PX,
  HOUR_PX,
  hourLabel,
  packDay,
  type Cell,
} from '@/lib/calendar-pack';
import { providerDisplayName, useBookableProviders } from '@/lib/staff';

const COL_WIDTH = 150;

/** Desktop-style day view — a column per provider, time grid — shown
 *  on wide screens (iPad landscape). Horizontally scrollable when
 *  there are more providers than fit. */
export function DayGridView({ date }: { date: string }) {
  const { data, isError, refetch } = useAppointmentsForDate(date);
  const providersQuery = useBookableProviders();

  const appts = (data ?? []).filter((a) => a.status !== 'cancelled');

  // Columns: bookable providers, plus any provider with an
  // appointment today who isn't on the bookable list.
  const columnNames = new Map<number, string>();
  for (const p of providersQuery.data ?? []) {
    columnNames.set(p.id, providerDisplayName(p));
  }
  for (const a of appts) {
    if (!columnNames.has(a.provider.id)) {
      const name =
        `${a.provider.user_first_name} ${a.provider.user_last_name}`.trim();
      columnNames.set(a.provider.id, name || 'Provider');
    }
  }
  const columns = [...columnNames.entries()].map(([id, name]) => ({ id, name }));

  const byProvider = new Map<number, Appointment[]>();
  for (const c of columns) byProvider.set(c.id, []);
  for (const a of appts) byProvider.get(a.provider.id)?.push(a);

  const { startHour, endHour } = computeHourWindow(appts);
  const startMin = startHour * 60;
  const bodyHeight = (endHour - startHour) * HOUR_PX;
  const hours = Array.from({ length: endHour - startHour + 1 }, (_, i) => i);

  const now = new Date();
  const nowOffset =
    ((now.getHours() * 60 + now.getMinutes() - startMin) / 60) * HOUR_PX;
  const showNow =
    date === todayString() && nowOffset >= 0 && nowOffset <= bodyHeight;

  if (isError) {
    return (
      <View style={styles.centered}>
        <Text style={styles.centeredText}>Couldn&apos;t load the schedule.</Text>
        <Pressable onPress={() => refetch()} accessibilityRole="button" hitSlop={8}>
          <Text style={styles.retry}>Try again</Text>
        </Pressable>
      </View>
    );
  }

  const gridWidth = columns.length * COL_WIDTH;

  return (
    <ScrollView horizontal contentContainerStyle={styles.hScroll}>
      <View style={{ width: GUTTER_PX + gridWidth }}>
        <View style={styles.headerRow}>
          <View style={{ width: GUTTER_PX }} />
          {columns.map((c) => (
            <View key={c.id} style={[styles.colHead, { width: COL_WIDTH }]}>
              <Text style={styles.colHeadText} numberOfLines={1}>
                {c.name}
              </Text>
            </View>
          ))}
        </View>

        <ScrollView
          style={styles.vScroll}
          contentContainerStyle={{ height: bodyHeight }}
          showsVerticalScrollIndicator={false}
        >
          <View style={styles.body}>
            <View style={{ width: GUTTER_PX }}>
              {hours.map((i) => (
                <Text
                  key={i}
                  style={[
                    styles.hourLabel,
                    { top: Math.max(0, i * HOUR_PX - 6) },
                  ]}
                >
                  {i === 0 ? '' : hourLabel(startHour + i)}
                </Text>
              ))}
            </View>

            <View style={{ width: gridWidth }}>
              {hours.map((i) => (
                <View key={i} style={[styles.hourLine, { top: i * HOUR_PX }]} />
              ))}

              <View style={styles.columns}>
                {columns.map((c) => (
                  <View key={c.id} style={[styles.col, { width: COL_WIDTH }]}>
                    {packDay(byProvider.get(c.id) ?? []).map((cell, idx) => (
                      <GridBlock
                        key={cell.kind === 'appt' ? cell.appt.id : `ov-${idx}`}
                        cell={cell}
                        startMin={startMin}
                      />
                    ))}
                  </View>
                ))}
              </View>

              {showNow ? (
                <View style={[styles.nowLine, { top: nowOffset }]} />
              ) : null}
            </View>
          </View>
        </ScrollView>
      </View>
    </ScrollView>
  );
}

function GridBlock({ cell, startMin }: { cell: Cell; startMin: number }) {
  const top = ((cell.topMin - startMin) / 60) * HOUR_PX;
  const height = Math.max(16, (cell.durationMin / 60) * HOUR_PX);
  const width = COL_WIDTH / cell.cols;
  const left = cell.col * width;

  if (cell.kind === 'overflow') {
    return (
      <View style={[styles.overflow, { top, height, left, width }]}>
        <Text style={styles.overflowText}>+{cell.count}</Text>
      </View>
    );
  }

  const { appt } = cell;
  const cancelled = appt.status === 'cancelled' || appt.status === 'no_show';
  const color = appt.service.category_color || FALLBACK_COLOR;

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
        { top, height, left, width: width - 2 },
        { backgroundColor: `${color}26`, borderLeftColor: color },
        cancelled && styles.blockCancelled,
      ]}
    >
      <Text
        style={[styles.blockText, cancelled && styles.blockTextCancelled]}
        numberOfLines={2}
      >
        {appt.customer.full_name || 'Client'}
      </Text>
      {height >= 44 ? (
        <Text style={styles.blockSub} numberOfLines={1}>
          {appt.service.name}
        </Text>
      ) : null}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  hScroll: {
    flexGrow: 1,
  },
  headerRow: {
    flexDirection: 'row',
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
    backgroundColor: colors.card,
  },
  colHead: {
    paddingVertical: 8,
    paddingHorizontal: 6,
    alignItems: 'center',
    borderRightWidth: 1,
    borderRightColor: colors.border,
  },
  colHeadText: {
    fontFamily: fonts.sans,
    fontSize: fontSize.sm,
    fontWeight: '600',
    color: colors.foreground,
  },
  vScroll: {
    flex: 1,
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
  col: {
    borderRightWidth: 1,
    borderRightColor: colors.border,
  },
  block: {
    position: 'absolute',
    borderRadius: 4,
    borderLeftWidth: 3,
    overflow: 'hidden',
    paddingHorizontal: 4,
    paddingTop: 2,
  },
  blockCancelled: {
    opacity: 0.55,
  },
  blockText: {
    fontFamily: fonts.sans,
    fontSize: 11,
    fontWeight: '600',
    color: colors.foreground,
  },
  blockTextCancelled: {
    textDecorationLine: 'line-through',
  },
  blockSub: {
    fontFamily: fonts.sans,
    fontSize: 10,
    color: colors.mutedForeground,
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
    fontSize: 11,
    fontWeight: '600',
    color: colors.mutedForeground,
  },
  nowLine: {
    position: 'absolute',
    left: 0,
    right: 0,
    height: 2,
    backgroundColor: '#ef4444',
  },
  centered: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
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
