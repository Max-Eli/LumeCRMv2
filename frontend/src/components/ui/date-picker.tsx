/**
 * Custom date picker — Popover-anchored, designed to fit the rest of the
 * CRM's chrome rather than the OS's native `<input type="date">` widget
 * (which looks generic and varies wildly across browsers / platforms).
 *
 * Layout inside the popover (top → bottom):
 *
 *   1. Quick-pick row — Today, +2 weeks, +4 weeks, +6 weeks. Front-desk
 *      booking workflow shortcuts ("schedule the follow-up six weeks
 *      out") that are common enough to deserve one-click access.
 *   2. Month header — month/year label with prev/next nav.
 *   3. Day grid — 7-column Sun..Sat grid, leading/trailing days from the
 *      adjacent months are shown in muted text. Today is ringed; the
 *      currently-selected day is filled with the brand accent.
 *
 * Date values cross the API as `YYYY-MM-DD` (matches the backend's
 * date-only format and the URL `?date=` param). All math is done in
 * the *browser's local* timezone — we don't shift to a tenant TZ here
 * because date-only values don't carry an offset and the CRM's
 * day-view layer already handles the local↔tenant TZ translation
 * for time-bearing values.
 */

'use client';

import { CalendarDays, ChevronLeft, ChevronRight } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';

import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { cn } from '@/lib/utils';

export interface DatePickerProps {
  /** Currently selected date as YYYY-MM-DD. */
  value: string;
  /** Called when the user picks a new date — quick-pick or grid click. */
  onChange: (next: string) => void;
  /** Optional aria-label for the trigger button. */
  ariaLabel?: string;
  /** Optional class merged onto the trigger button. */
  className?: string;
}

const QUICK_PICKS: { label: string; addDays: number }[] = [
  { label: 'Today', addDays: 0 },
  { label: '+2 weeks', addDays: 14 },
  { label: '+4 weeks', addDays: 28 },
  { label: '+6 weeks', addDays: 42 },
];

const WEEKDAY_LABELS = ['S', 'M', 'T', 'W', 'T', 'F', 'S'];

export function DatePicker({ value, onChange, ariaLabel = 'Select date', className }: DatePickerProps) {
  const [open, setOpen] = useState(false);

  const selected = useMemo(() => parseISODate(value), [value]);
  // Month being displayed in the grid. Independent of `selected` so the
  // user can navigate months without losing their selection. Resets to
  // the selected month each time the popover opens.
  const [viewMonth, setViewMonth] = useState<Date>(() => firstOfMonth(selected ?? new Date()));

  useEffect(() => {
    if (open) setViewMonth(firstOfMonth(selected ?? new Date()));
  }, [open, selected]);

  const handlePick = (date: Date) => {
    onChange(toISODate(date));
    setOpen(false);
  };

  const handleQuickPick = (addDays: number) => {
    const today = startOfDay(new Date());
    today.setDate(today.getDate() + addDays);
    handlePick(today);
  };

  // Two labels — long form for desktop, short for mobile. The
  // mobile calendar bar has ~370px to share across 5+ controls;
  // "May 17, 2026" doesn't need to compete for those pixels when
  // the year is implicit from context.
  const triggerLabelLong = selected
    ? selected.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
    : 'Pick a date';
  const triggerLabelShort = selected
    ? selected.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
    : 'Pick';

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger
        render={
          <button
            type="button"
            aria-label={ariaLabel}
            className={cn(
              'inline-flex items-center gap-1.5 h-8 rounded-md border bg-card px-2.5 text-sm tabular-nums shrink-0 whitespace-nowrap',
              'hover:bg-muted transition-colors',
              'aria-expanded:bg-muted aria-expanded:border-ring/40',
              'focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 outline-none',
              className,
            )}
          >
            <CalendarDays className="size-3.5 text-muted-foreground" aria-hidden />
            <span className="md:hidden">{triggerLabelShort}</span>
            <span className="hidden md:inline">{triggerLabelLong}</span>
          </button>
        }
      />
      <PopoverContent
        align="start"
        sideOffset={6}
        className="w-[280px] p-0 overflow-hidden"
      >
        <div className="px-3 pt-3 pb-2 grid grid-cols-2 gap-1.5 border-b">
          {QUICK_PICKS.map(({ label, addDays }) => (
            <button
              key={label}
              type="button"
              onClick={() => handleQuickPick(addDays)}
              className="inline-flex items-center justify-center h-7 px-2 rounded-md text-xs border border-border bg-card text-foreground hover:bg-accent hover:text-accent-foreground hover:border-accent transition-colors"
            >
              {label}
            </button>
          ))}
        </div>

        <MonthGrid
          viewMonth={viewMonth}
          selected={selected}
          onChangeMonth={setViewMonth}
          onPick={handlePick}
        />
      </PopoverContent>
    </Popover>
  );
}

// ── Month grid ───────────────────────────────────────────────────────────

function MonthGrid({
  viewMonth,
  selected,
  onChangeMonth,
  onPick,
}: {
  viewMonth: Date;
  selected: Date | null;
  onChangeMonth: (next: Date) => void;
  onPick: (date: Date) => void;
}) {
  const today = startOfDay(new Date());
  const monthLabel = viewMonth.toLocaleDateString('en-US', { month: 'long', year: 'numeric' });

  // Build the 6×7 grid: leading days from the previous month to fill the
  // first week, all days of the current month, then trailing days from
  // the next month. Always 42 cells so the grid height is consistent.
  const cells = useMemo(() => buildMonthCells(viewMonth), [viewMonth]);

  const goPrev = () => onChangeMonth(addMonths(viewMonth, -1));
  const goNext = () => onChangeMonth(addMonths(viewMonth, 1));

  return (
    <div className="px-3 pt-2 pb-3">
      <div className="flex items-center justify-between mb-2">
        <p className="text-sm font-medium font-serif">{monthLabel}</p>
        <div className="inline-flex items-center rounded-md border bg-card">
          <button
            type="button"
            onClick={goPrev}
            aria-label="Previous month"
            className="inline-flex size-7 items-center justify-center text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
          >
            <ChevronLeft className="size-3.5" />
          </button>
          <button
            type="button"
            onClick={goNext}
            aria-label="Next month"
            className="inline-flex size-7 items-center justify-center text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
          >
            <ChevronRight className="size-3.5" />
          </button>
        </div>
      </div>

      <div className="grid grid-cols-7 gap-y-0.5">
        {WEEKDAY_LABELS.map((d, i) => (
          <div
            key={`${d}-${i}`}
            className="text-center text-[10px] uppercase tracking-wide text-muted-foreground/70 font-medium pb-1"
          >
            {d}
          </div>
        ))}
        {cells.map((cell) => {
          const isToday = isSameDate(cell.date, today);
          const isSelected = selected ? isSameDate(cell.date, selected) : false;
          return (
            <button
              key={cell.date.toISOString()}
              type="button"
              onClick={() => onPick(cell.date)}
              className={cn(
                'inline-flex items-center justify-center h-8 w-8 mx-auto rounded-md text-xs font-mono tabular-nums transition-colors',
                'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60',
                cell.inMonth ? 'text-foreground' : 'text-muted-foreground/50',
                !isSelected && 'hover:bg-muted',
                isToday && !isSelected && 'ring-1 ring-foreground/30',
                isSelected && 'bg-accent text-accent-foreground hover:bg-accent/90',
              )}
              aria-pressed={isSelected}
              aria-label={cell.date.toLocaleDateString('en-US', {
                weekday: 'long',
                month: 'long',
                day: 'numeric',
                year: 'numeric',
              })}
            >
              {cell.date.getDate()}
            </button>
          );
        })}
      </div>
    </div>
  );
}

// ── Date math (pure local-time, no timezone conversion) ─────────────────

interface DateCell {
  date: Date;
  inMonth: boolean;
}

/**
 * Build a 42-cell grid covering the given month, including leading days
 * from the previous month and trailing days from the next month so every
 * row is full. Sunday is the week start (matches the Sun..Sat header).
 */
function buildMonthCells(viewMonth: Date): DateCell[] {
  const monthStart = firstOfMonth(viewMonth);
  const startWeekday = monthStart.getDay(); // 0..6 (Sun..Sat)
  // Leading from the previous month
  const gridStart = new Date(monthStart);
  gridStart.setDate(gridStart.getDate() - startWeekday);

  const cells: DateCell[] = [];
  for (let i = 0; i < 42; i += 1) {
    const date = new Date(gridStart);
    date.setDate(gridStart.getDate() + i);
    cells.push({
      date: startOfDay(date),
      inMonth: date.getMonth() === viewMonth.getMonth(),
    });
  }
  return cells;
}

function firstOfMonth(d: Date): Date {
  const out = new Date(d);
  out.setDate(1);
  out.setHours(0, 0, 0, 0);
  return out;
}

function addMonths(d: Date, delta: number): Date {
  const out = new Date(d);
  // Set day=1 first so a delta from e.g. Jan 31 doesn't roll into March
  out.setDate(1);
  out.setMonth(out.getMonth() + delta);
  return out;
}

function startOfDay(d: Date): Date {
  const out = new Date(d);
  out.setHours(0, 0, 0, 0);
  return out;
}

function isSameDate(a: Date, b: Date): boolean {
  return (
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
  );
}

function parseISODate(value: string): Date | null {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
  // Use local-noon to dodge any DST edge cases right at midnight.
  const [y, m, d] = value.split('-').map(Number);
  return new Date(y, m - 1, d, 12, 0, 0, 0);
}

function toISODate(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}
