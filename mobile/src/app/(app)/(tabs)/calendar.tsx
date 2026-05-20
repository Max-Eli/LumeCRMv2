import { Feather } from '@expo/vector-icons';
import { useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { DayView } from '@/components/calendar/day-view';
import { MonthView } from '@/components/calendar/month-view';
import { ViewSwitcher, type CalendarView } from '@/components/calendar/view-switcher';
import { WeekView } from '@/components/calendar/week-view';
import { colors, fonts, fontSize, radius, spacing } from '@/constants/theme';
import {
  addDays,
  addMonths,
  formatDayLabel,
  formatMonthLabel,
  formatWeekLabel,
  todayString,
} from '@/lib/appointments';

/** Calendar tab — Day / Week / Month views over the active workspace. */
export default function CalendarScreen() {
  const [view, setView] = useState<CalendarView>('day');
  const [focusDate, setFocusDate] = useState(todayString());

  function step(direction: -1 | 1) {
    if (view === 'day') setFocusDate(addDays(focusDate, direction));
    else if (view === 'week') setFocusDate(addDays(focusDate, direction * 7));
    else setFocusDate(addMonths(focusDate, direction));
  }

  function pickDay(day: string) {
    setFocusDate(day);
    setView('day');
  }

  const title =
    view === 'day'
      ? formatDayLabel(focusDate)
      : view === 'week'
        ? formatWeekLabel(focusDate)
        : formatMonthLabel(focusDate);

  return (
    <SafeAreaView edges={['top']} style={styles.safe}>
      <View style={styles.header}>
        <View style={styles.titleRow}>
          <NavButton icon="chevron-left" onPress={() => step(-1)} />
          <Text style={styles.title} numberOfLines={1}>
            {title}
          </Text>
          <NavButton icon="chevron-right" onPress={() => step(1)} />
        </View>

        <View style={styles.controls}>
          <View style={styles.switcher}>
            <ViewSwitcher value={view} onChange={setView} />
          </View>
          <Pressable
            onPress={() => setFocusDate(todayString())}
            accessibilityRole="button"
            style={styles.todayButton}
          >
            <Text style={styles.todayText}>Today</Text>
          </Pressable>
        </View>
      </View>

      <View style={styles.body}>
        {view === 'day' ? (
          <DayView date={focusDate} />
        ) : view === 'week' ? (
          <WeekView date={focusDate} onPickDay={pickDay} />
        ) : (
          <MonthView date={focusDate} onPickDay={pickDay} />
        )}
      </View>
    </SafeAreaView>
  );
}

function NavButton({
  icon,
  onPress,
}: {
  icon: 'chevron-left' | 'chevron-right';
  onPress: () => void;
}) {
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      hitSlop={8}
      style={styles.navButton}
    >
      <Feather name={icon} size={22} color={colors.foreground} />
    </Pressable>
  );
}

const styles = StyleSheet.create({
  safe: {
    flex: 1,
    backgroundColor: colors.background,
  },
  header: {
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.sm,
    paddingBottom: spacing.md,
    gap: spacing.md,
  },
  titleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: spacing.sm,
  },
  navButton: {
    width: 36,
    height: 36,
    borderRadius: radius.md,
    alignItems: 'center',
    justifyContent: 'center',
  },
  title: {
    flex: 1,
    textAlign: 'center',
    fontFamily: fonts.serif,
    fontSize: fontSize.lg,
    color: colors.foreground,
    letterSpacing: -0.3,
  },
  controls: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
  },
  switcher: {
    flex: 1,
  },
  todayButton: {
    paddingHorizontal: spacing.md,
    paddingVertical: 9,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.card,
  },
  todayText: {
    fontFamily: fonts.sans,
    fontSize: fontSize.sm,
    fontWeight: '600',
    color: colors.foreground,
  },
  body: {
    flex: 1,
  },
});
