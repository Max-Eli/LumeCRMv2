/**
 * Calendar filter bar — sits below the top bar.
 *
 * Left: date controls (today / prev / next / picker / long-form headline).
 * Right: provider filter + hide-cancelled toggle + display-mode toggle
 * (calendar / list) + view toggle (Day / Week / Month).
 *
 * All filter state lives on the parent so URL ⇄ component sync stays in one
 * place. Provider IDs are strings here (URL-friendly); convert at the API call
 * site.
 */

'use client';

import { CalendarDays, ChevronLeft, ChevronRight, EyeOff, List } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { DatePicker } from '@/components/ui/date-picker';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { type Membership, membershipName } from '@/lib/memberships';
import { cn } from '@/lib/utils';

export type CalendarView = 'day' | 'week' | 'month';
export type DisplayMode = 'calendar' | 'list';

export interface CalendarFilterBarProps {
  date: string;
  onChangeDate: (next: string) => void;
  view: CalendarView;
  onChangeView: (next: CalendarView) => void;
  displayMode: DisplayMode;
  onChangeDisplayMode: (next: DisplayMode) => void;
  providers: Membership[];
  providerFilter: string; // '' = all, or numeric id as string
  onChangeProviderFilter: (next: string) => void;
  hideCancelled: boolean;
  onChangeHideCancelled: (next: boolean) => void;
}

export function CalendarFilterBar({
  date,
  onChangeDate,
  view,
  onChangeView,
  displayMode,
  onChangeDisplayMode,
  providers,
  providerFilter,
  onChangeProviderFilter,
  hideCancelled,
  onChangeHideCancelled,
}: CalendarFilterBarProps) {
  const focused = new Date(`${date}T00:00:00`);
  const todayStr = todayISO();
  const isToday = date === todayStr;
  const headlineLong = focused.toLocaleDateString('en-US', {
    weekday: 'long',
    month: 'long',
    day: 'numeric',
    year: 'numeric',
  });

  const shift = (days: number) => {
    const next = new Date(focused);
    next.setDate(next.getDate() + days);
    onChangeDate(toISODate(next));
  };

  return (
    <div className="shrink-0 border-b bg-background">
      <div className="flex items-center justify-between gap-3 px-6 py-2.5">
        {/* Date controls */}
        <div className="flex items-center gap-2 min-w-0">
          <Button
            variant="outline"
            size="sm"
            onClick={() => onChangeDate(todayStr)}
            disabled={isToday}
          >
            Today
          </Button>
          <div className="inline-flex items-center rounded-md border bg-card">
            <button
              type="button"
              onClick={() => shift(-1)}
              className="inline-flex size-8 items-center justify-center text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
              aria-label="Previous day"
            >
              <ChevronLeft className="size-4" />
            </button>
            <button
              type="button"
              onClick={() => shift(1)}
              className="inline-flex size-8 items-center justify-center text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
              aria-label="Next day"
            >
              <ChevronRight className="size-4" />
            </button>
          </div>
          <DatePicker value={date} onChange={onChangeDate} ariaLabel="Select date" />
          <span className="font-serif text-base font-medium tracking-tight ml-2 hidden md:inline">
            {headlineLong}
          </span>
        </div>

        {/* Filters + display mode + view */}
        <div className="flex items-center gap-2">
          <div className="hidden md:flex items-center">
            <Select value={providerFilter || 'all'} onValueChange={(v) => onChangeProviderFilter(v === 'all' ? '' : v)}>
              <SelectTrigger size="sm" className="w-[170px]">
                <SelectValue placeholder="All providers" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All providers</SelectItem>
                {providers.map((p) => (
                  <SelectItem key={p.id} value={String(p.id)}>
                    {membershipName(p)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <button
            type="button"
            onClick={() => onChangeHideCancelled(!hideCancelled)}
            aria-pressed={hideCancelled}
            className={cn(
              'inline-flex items-center gap-1.5 h-8 px-2.5 rounded-md text-xs uppercase tracking-wide transition-colors border',
              hideCancelled
                ? 'border-foreground/30 bg-foreground text-background'
                : 'border-border bg-card text-muted-foreground hover:bg-muted hover:text-foreground',
            )}
          >
            <EyeOff className="size-3.5" />
            Hide cancelled
          </button>

          <DisplayModeToggle value={displayMode} onChange={onChangeDisplayMode} />
          <ViewToggle value={view} onChange={onChangeView} />
        </div>
      </div>
    </div>
  );
}

function DisplayModeToggle({
  value,
  onChange,
}: {
  value: DisplayMode;
  onChange: (v: DisplayMode) => void;
}) {
  return (
    <div role="group" className="inline-flex rounded-md border bg-card overflow-hidden">
      {(
        [
          { id: 'calendar', icon: CalendarDays, label: 'Calendar grid' },
          { id: 'list', icon: List, label: 'List' },
        ] as const
      ).map(({ id, icon: Icon, label }) => {
        const active = id === value;
        return (
          <button
            key={id}
            type="button"
            onClick={() => onChange(id)}
            aria-pressed={active}
            aria-label={label}
            title={label}
            className={cn(
              'inline-flex items-center justify-center size-8 transition-colors',
              active
                ? 'bg-foreground text-background'
                : 'text-muted-foreground hover:bg-muted hover:text-foreground',
            )}
          >
            <Icon className="size-4" />
          </button>
        );
      })}
    </div>
  );
}

function ViewToggle({
  value,
  onChange,
}: {
  value: CalendarView;
  onChange: (v: CalendarView) => void;
}) {
  return (
    <div role="group" className="inline-flex rounded-md border bg-card overflow-hidden">
      {(['day', 'week', 'month'] as const).map((v) => {
        const active = v === value;
        const enabled = v === 'day';
        return (
          <button
            key={v}
            type="button"
            disabled={!enabled}
            onClick={() => enabled && onChange(v)}
            className={cn(
              'px-3 h-8 text-xs uppercase tracking-wide capitalize transition-colors',
              active
                ? 'bg-foreground text-background'
                : enabled
                  ? 'text-muted-foreground hover:bg-muted hover:text-foreground'
                  : 'text-muted-foreground/40 cursor-not-allowed',
            )}
          >
            {v}
          </button>
        );
      })}
    </div>
  );
}

// ── Date utils ───────────────────────────────────────────────────────────

function todayISO(): string {
  return toISODate(new Date());
}

function toISODate(d: Date): string {
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, '0');
  const dd = String(d.getDate()).padStart(2, '0');
  return `${yyyy}-${mm}-${dd}`;
}
