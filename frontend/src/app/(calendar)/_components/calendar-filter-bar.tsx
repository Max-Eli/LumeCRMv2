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

import { CalendarDays, ChevronLeft, ChevronRight, ChevronDown, EyeOff, List, Users } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { DatePicker } from '@/components/ui/date-picker';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';
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
  providerFilter: number[]; // [] = all; otherwise the allowed provider IDs
  onChangeProviderFilter: (next: number[]) => void;
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

  // Headline + prev/next step adapt to the active view:
  //   day   → "Monday, May 19, 2026"   · step ±1 day
  //   week  → "May 18 – 24, 2026"       · step ±7 days
  //   month → "May 2026"                · step ±1 month
  const headlineLong =
    view === 'month'
      ? focused.toLocaleDateString('en-US', { month: 'long', year: 'numeric' })
      : view === 'week'
        ? formatWeekRange(focused)
        : focused.toLocaleDateString('en-US', {
            weekday: 'long',
            month: 'long',
            day: 'numeric',
            year: 'numeric',
          });

  const shift = (direction: -1 | 1) => {
    const next = new Date(focused);
    if (view === 'month') {
      next.setMonth(next.getMonth() + direction);
    } else if (view === 'week') {
      next.setDate(next.getDate() + direction * 7);
    } else {
      next.setDate(next.getDate() + direction);
    }
    onChangeDate(toISODate(next));
  };

  const stepLabel = view === 'month' ? 'month' : view === 'week' ? 'week' : 'day';

  return (
    <div className="shrink-0 border-b bg-background">
      <div className="flex items-center justify-between gap-2 sm:gap-3 px-3 sm:px-6 py-2.5">
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
              aria-label={`Previous ${stepLabel}`}
            >
              <ChevronLeft className="size-4" />
            </button>
            <button
              type="button"
              onClick={() => shift(1)}
              className="inline-flex size-8 items-center justify-center text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
              aria-label={`Next ${stepLabel}`}
            >
              <ChevronRight className="size-4" />
            </button>
          </div>
          <DatePicker value={date} onChange={onChangeDate} ariaLabel="Select date" />
          {/* Headline: full long form on desktop. On mobile it's the
              only on-screen indicator of which week/month you're in
              (the grid itself doesn't repeat the month name), so it
              shows there too — truncating if the row gets tight. */}
          <span className="font-serif text-sm sm:text-base font-medium tracking-tight ml-1 sm:ml-2 truncate">
            {headlineLong}
          </span>
        </div>

        {/* Filters + display mode + view */}
        <div className="flex items-center gap-2">
          {/* Provider multi-select is meaningful on every screen size
              — on mobile we collapse the trigger to an icon-only
              button (the popover content is identical). */}
          <div className="flex items-center">
            <ProviderMultiSelect
              providers={providers}
              providerFilter={providerFilter}
              onChange={onChangeProviderFilter}
            />
          </div>

          <button
            type="button"
            onClick={() => onChangeHideCancelled(!hideCancelled)}
            aria-pressed={hideCancelled}
            aria-label="Hide cancelled appointments"
            title="Hide cancelled appointments"
            className={cn(
              'inline-flex items-center gap-1.5 h-8 px-2 sm:px-2.5 rounded-md text-xs uppercase tracking-wide transition-colors border',
              hideCancelled
                ? 'border-foreground/30 bg-foreground text-background'
                : 'border-border bg-card text-muted-foreground hover:bg-muted hover:text-foreground',
            )}
          >
            <EyeOff className="size-3.5" />
            <span className="hidden sm:inline">Hide cancelled</span>
          </button>

          {/* DisplayMode toggle (grid vs list) stays desktop-only —
              mobile day view ALWAYS renders the list because the
              time-grid is unusable below 768px. ViewToggle
              (Day/Week/Month) shows on every size now that week +
              month views are built — they're the mobile-friendly
              calendar surfaces. */}
          <div className="hidden md:flex items-center">
            <DisplayModeToggle value={displayMode} onChange={onChangeDisplayMode} />
          </div>
          <div className="flex items-center">
            <ViewToggle value={view} onChange={onChangeView} />
          </div>
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
        return (
          <button
            key={v}
            type="button"
            onClick={() => onChange(v)}
            aria-pressed={active}
            className={cn(
              'px-2.5 sm:px-3 h-8 text-xs uppercase tracking-wide capitalize transition-colors',
              active
                ? 'bg-foreground text-background'
                : 'text-muted-foreground hover:bg-muted hover:text-foreground',
            )}
          >
            {v}
          </button>
        );
      })}
    </div>
  );
}

// ── Provider multi-select ────────────────────────────────────────────────

/**
 * Popover with a checkbox per provider. Empty selection = "All providers"
 * (no filtering). Trigger button label shows the active state:
 *   - 0 selected → "All providers"
 *   - 1 selected → that provider's name
 *   - 2+ selected → "N providers"
 *
 * Keeps URL state as a comma-separated list of provider IDs.
 */
function ProviderMultiSelect({
  providers,
  providerFilter,
  onChange,
}: {
  providers: Membership[];
  providerFilter: number[];
  onChange: (next: number[]) => void;
}) {
  const selected = new Set(providerFilter);
  const label = (() => {
    if (selected.size === 0) return 'All providers';
    if (selected.size === 1) {
      const only = providers.find((p) => p.id === [...selected][0]);
      return only ? membershipName(only) : '1 provider';
    }
    return `${selected.size} providers`;
  })();

  const toggle = (id: number) => {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    onChange([...next].sort((a, b) => a - b));
  };

  // Mobile gets a compact label: just the icon + count ("2") to
  // save horizontal space. Desktop gets the full word treatment.
  const labelShort = selected.size === 0 ? 'All' : String(selected.size);

  return (
    <Popover>
      <PopoverTrigger
        render={(props) => (
          <button
            {...props}
            type="button"
            className="inline-flex items-center gap-1.5 h-8 px-2.5 rounded-md border border-border bg-card text-muted-foreground hover:bg-muted hover:text-foreground transition-colors shrink-0 justify-between md:min-w-[170px]"
          >
            <span className="inline-flex items-center gap-1.5 text-sm">
              <Users className="size-3.5" />
              <span className="hidden md:inline">{label}</span>
              <span className="md:hidden tabular-nums">{labelShort}</span>
            </span>
            <ChevronDown className="size-3.5" />
          </button>
        )}
      />
      <PopoverContent align="start" className="w-64 p-1.5">
        <button
          type="button"
          onClick={() => onChange([])}
          className={cn(
            'w-full flex items-center justify-between gap-2 px-2 py-1.5 rounded text-sm hover:bg-muted',
            selected.size === 0 && 'text-foreground font-medium',
            selected.size > 0 && 'text-muted-foreground',
          )}
        >
          <span>All providers</span>
          {selected.size > 0 ? (
            <span className="text-xs uppercase tracking-wide">Clear</span>
          ) : null}
        </button>
        <div className="my-1 border-t border-border" />
        <div className="max-h-64 overflow-y-auto">
          {providers.length === 0 ? (
            <p className="px-2 py-2 text-xs text-muted-foreground">
              No bookable providers.
            </p>
          ) : (
            providers.map((p) => {
              const checked = selected.has(p.id);
              return (
                <label
                  key={p.id}
                  className="flex items-center gap-2 px-2 py-1.5 rounded hover:bg-muted cursor-pointer"
                >
                  <Checkbox
                    checked={checked}
                    onCheckedChange={() => toggle(p.id)}
                  />
                  <span className="text-sm flex-1 truncate">
                    {membershipName(p)}
                  </span>
                </label>
              );
            })
          )}
        </div>
      </PopoverContent>
    </Popover>
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

/** "May 18 – 24, 2026" for the Sunday-anchored week containing
 *  `focused`. Collapses the month when the week doesn't straddle one
 *  ("May 28 – Jun 3, 2026" when it does). */
function formatWeekRange(focused: Date): string {
  const start = new Date(focused);
  start.setDate(start.getDate() - start.getDay());
  const end = new Date(start);
  end.setDate(end.getDate() + 6);
  const sameMonth = start.getMonth() === end.getMonth();
  const startStr = start.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  const endStr = end.toLocaleDateString('en-US', {
    month: sameMonth ? undefined : 'short',
    day: 'numeric',
  });
  return `${startStr} – ${endStr}, ${end.getFullYear()}`;
}
