/**
 * Date-range picker used at the top of every report page.
 *
 * Bundles two `DatePicker`s + a preset row ("Last 30 days", "This
 * month", etc.). Lifts the controlled state to the parent page so
 * the report query refetches when the range changes.
 */

'use client';

import { DatePicker } from '@/components/ui/date-picker';
import { DATE_PRESETS, toIsoDate } from '@/lib/reports';
import { cn } from '@/lib/utils';

export interface DateRange {
  date_from: string;
  date_to: string;
  // Index signature so `DateRange` satisfies `DateRangeParams` when
  // passed straight to a report hook (lib/reports.ts).
  [k: string]: string | undefined;
}

export interface DateRangePickerProps {
  value: DateRange;
  onChange: (next: DateRange) => void;
  className?: string;
}

export function DateRangePicker({ value, onChange, className }: DateRangePickerProps) {
  const activePreset = DATE_PRESETS.find((p) => {
    const r = p.range();
    return r.date_from === value.date_from && r.date_to === value.date_to;
  })?.id;

  return (
    <div className={cn('flex flex-wrap items-center gap-2', className)}>
      <div className="inline-flex items-center rounded-md border bg-card overflow-hidden divide-x">
        {DATE_PRESETS.map((preset) => (
          <button
            key={preset.id}
            type="button"
            onClick={() => onChange(preset.range())}
            className={cn(
              'inline-flex items-center justify-center h-8 px-3 text-xs transition-colors',
              activePreset === preset.id
                ? 'bg-foreground text-background'
                : 'text-muted-foreground hover:bg-muted hover:text-foreground',
            )}
          >
            {preset.label}
          </button>
        ))}
      </div>

      <div className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
        <span>From</span>
        <DatePicker
          value={value.date_from}
          onChange={(next) => onChange({ ...value, date_from: next })}
          ariaLabel="Start date"
        />
        <span>to</span>
        <DatePicker
          value={value.date_to}
          onChange={(next) => onChange({ ...value, date_to: next })}
          ariaLabel="End date"
        />
      </div>
    </div>
  );
}

/** Default range: last 30 days ending today. */
export function defaultDateRange(): DateRange {
  const today = new Date();
  const start = new Date(today);
  start.setDate(today.getDate() - 29);
  return { date_from: toIsoDate(start), date_to: toIsoDate(today) };
}
