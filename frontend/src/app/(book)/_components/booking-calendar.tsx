/**
 * Inline month-grid date picker for the public booking flow.
 *
 * Different from the staff-side `<DatePicker>` (popover-anchored,
 * compact) — this one is rendered inline because the customer is on
 * a single-purpose page and a full month view is the dominant
 * pattern across booking competitors (Boulevard, Square, Calendly).
 *
 * Disabled state: dates before today and dates beyond
 * `today + windowDays`. The customer can navigate through any
 * month, but only valid dates are clickable. The calendar caps the
 * "Next month" arrow at the last month containing a valid date so
 * the customer can't wander into 2030.
 *
 * All math is done in the browser's local timezone — `toISODate`
 * stringifies the date the user touched. The backend interprets the
 * YYYY-MM-DD param in the location's timezone, which is the right
 * thing semantically (a customer thinks "Tuesday" in their local
 * sense, and the spa thinks "Tuesday" in their local sense, and the
 * date-only string round-trips correctly between them).
 */

'use client';

import { ChevronLeft, ChevronRight } from 'lucide-react';
import { useMemo, useState } from 'react';

import { cn } from '@/lib/utils';

const WEEKDAY_LABELS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

export interface BookingCalendarProps {
  /** Currently selected date as YYYY-MM-DD. */
  value: string;
  onChange: (next: string) => void;
  /** Minimum selectable date (YYYY-MM-DD). Defaults to today. */
  minDate?: string;
  /** Maximum selectable date (YYYY-MM-DD). Beyond this is disabled. */
  maxDate?: string;
  /** Brand color applied to the selected day fill. */
  primaryColor: string;
}

export function BookingCalendar({
  value,
  onChange,
  minDate,
  maxDate,
  primaryColor,
}: BookingCalendarProps) {
  const today = startOfDay(new Date());
  const min = minDate ? parseISODate(minDate) : today;
  const max = maxDate ? parseISODate(maxDate) : null;
  const selected = parseISODate(value);

  const [viewMonth, setViewMonth] = useState<Date>(() =>
    firstOfMonth(selected ?? min ?? today),
  );

  const cells = useMemo(() => buildMonthCells(viewMonth), [viewMonth]);
  const monthLabel = viewMonth.toLocaleDateString('en-US', {
    month: 'long',
    year: 'numeric',
  });

  // Disable nav arrows when the adjacent month wouldn't contain any
  // selectable date.
  const minMonth = min ? firstOfMonth(min) : null;
  const maxMonth = max ? firstOfMonth(max) : null;
  const canGoPrev = !minMonth || viewMonth > minMonth;
  const canGoNext = !maxMonth || viewMonth < maxMonth;

  const goPrev = () => canGoPrev && setViewMonth(addMonths(viewMonth, -1));
  const goNext = () => canGoNext && setViewMonth(addMonths(viewMonth, 1));

  return (
    <div className="rounded-lg border border-stone-200 bg-white p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-stone-900">{monthLabel}</h3>
        <div className="inline-flex items-center rounded-md border border-stone-200 bg-white">
          <button
            type="button"
            onClick={goPrev}
            disabled={!canGoPrev}
            aria-label="Previous month"
            className={cn(
              'inline-flex size-8 items-center justify-center transition-colors',
              canGoPrev
                ? 'text-stone-700 hover:bg-stone-100'
                : 'text-stone-300 cursor-not-allowed',
            )}
          >
            <ChevronLeft className="size-4" />
          </button>
          <button
            type="button"
            onClick={goNext}
            disabled={!canGoNext}
            aria-label="Next month"
            className={cn(
              'inline-flex size-8 items-center justify-center transition-colors',
              canGoNext
                ? 'text-stone-700 hover:bg-stone-100'
                : 'text-stone-300 cursor-not-allowed',
            )}
          >
            <ChevronRight className="size-4" />
          </button>
        </div>
      </div>

      <div className="grid grid-cols-7 gap-y-1">
        {WEEKDAY_LABELS.map((d) => (
          <div
            key={d}
            className="text-center text-[10px] uppercase tracking-wider text-stone-500 font-medium pb-2"
          >
            {d}
          </div>
        ))}
        {cells.map((cell) => {
          const iso = toISODate(cell.date);
          const isToday = isSameDate(cell.date, today);
          const isSelected = selected ? isSameDate(cell.date, selected) : false;
          const beforeMin = min ? cell.date < min : false;
          const afterMax = max ? cell.date > max : false;
          const disabled = beforeMin || afterMax;

          return (
            <button
              key={iso}
              type="button"
              onClick={() => !disabled && onChange(iso)}
              disabled={disabled}
              aria-pressed={isSelected}
              aria-label={cell.date.toLocaleDateString('en-US', {
                weekday: 'long',
                month: 'long',
                day: 'numeric',
                year: 'numeric',
              })}
              className={cn(
                'mx-auto inline-flex items-center justify-center h-9 w-9 rounded-md text-sm tabular-nums transition-colors',
                !cell.inMonth && 'text-stone-300',
                cell.inMonth && !disabled && !isSelected && 'text-stone-800 hover:bg-stone-100',
                disabled && cell.inMonth && 'text-stone-300 cursor-not-allowed',
                isToday && !isSelected && cell.inMonth && !disabled && 'ring-1 ring-stone-300',
                isSelected && 'text-white font-semibold',
              )}
              style={isSelected ? { background: primaryColor } : undefined}
            >
              {cell.date.getDate()}
            </button>
          );
        })}
      </div>
    </div>
  );
}

// ── Date helpers (browser local tz) ─────────────────────────────────

function startOfDay(d: Date): Date {
  const out = new Date(d);
  out.setHours(0, 0, 0, 0);
  return out;
}

function firstOfMonth(d: Date): Date {
  return new Date(d.getFullYear(), d.getMonth(), 1);
}

function addMonths(d: Date, count: number): Date {
  return new Date(d.getFullYear(), d.getMonth() + count, 1);
}

function isSameDate(a: Date, b: Date): boolean {
  return (
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
  );
}

function parseISODate(iso: string): Date | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  if (!m) return null;
  return startOfDay(new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3])));
}

function toISODate(d: Date): string {
  const y = d.getFullYear();
  const mo = String(d.getMonth() + 1).padStart(2, '0');
  const da = String(d.getDate()).padStart(2, '0');
  return `${y}-${mo}-${da}`;
}

function buildMonthCells(viewMonth: Date): { date: Date; inMonth: boolean }[] {
  // Always 6×7 = 42 cells so the grid height is consistent across
  // months. Leading days come from the previous month, trailing from
  // the next.
  const first = firstOfMonth(viewMonth);
  const startWeekday = first.getDay(); // 0=Sun
  const gridStart = new Date(first);
  gridStart.setDate(first.getDate() - startWeekday);

  const cells: { date: Date; inMonth: boolean }[] = [];
  for (let i = 0; i < 42; i++) {
    const d = new Date(gridStart);
    d.setDate(gridStart.getDate() + i);
    cells.push({
      date: startOfDay(d),
      inMonth: d.getMonth() === viewMonth.getMonth(),
    });
  }
  return cells;
}
