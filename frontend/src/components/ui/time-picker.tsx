/**
 * Time picker — Popover-anchored, two-column hour + minute grid styled
 * to match the rest of the chrome (sister to `<DatePicker>`).
 *
 * Why custom: the native `<input type="time">` looks generic and
 * inconsistent across browsers/OS, and the spa workflow benefits from
 * a two-column popup that's faster to use than a long single dropdown.
 *
 * Behavior:
 *   - Trigger button shows the value in 12-hour format ("9:30 AM").
 *   - Clicking an hour updates only the hour and keeps the popover
 *     open so the user can pick a minute.
 *   - Clicking a minute commits the full value and closes the popover.
 *   - Internal value is `HH:MM` 24-hour for clean API serialization.
 *   - `step` controls minute granularity (5 by default; matches the
 *     calendar's drag-snap).
 *   - Both columns scroll independently. Defaults cover the full 24-
 *     hour day (overnight clinics, late-night last-call appointments)
 *     unless the caller passes a narrower `minHour` / `maxHour` window.
 *   - On open, both columns auto-scroll the currently-selected slot
 *     into view so the user always lands in context — no manual hunt
 *     for "where am I now" before picking the next value.
 */

'use client';

import { Clock } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';

import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { cn } from '@/lib/utils';

export interface TimePickerProps {
  /** HH:MM (24-hour). */
  value: string;
  onChange: (next: string) => void;
  /** Minute step. `1` for every minute (full granularity), `5` for the
   *  calendar's drag-snap default, larger values for coarser pickers
   *  (every-15 / every-30 are common for shift schedules). */
  step?: 1 | 5 | 10 | 15 | 30;
  /** First selectable hour (0–23). Default 0 — full day. */
  minHour?: number;
  /** First UN-selectable hour (1–24). Default 24 — full day. */
  maxHour?: number;
  ariaLabel?: string;
  className?: string;
}

export function TimePicker({
  value,
  onChange,
  step = 5,
  minHour = 0,
  maxHour = 24,
  ariaLabel = 'Select time',
  className,
}: TimePickerProps) {
  const [open, setOpen] = useState(false);
  const [parsedH, parsedM] = parseHHMM(value);

  const hours = useMemo(() => range(minHour, maxHour), [minHour, maxHour]);
  const minutes = useMemo(() => range(0, 60, step), [step]);

  const triggerLabel = formatTime12(parsedH, parsedM);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger
        render={
          <button
            type="button"
            aria-label={ariaLabel}
            className={cn(
              'inline-flex items-center gap-1.5 h-8 rounded-md border bg-card px-2.5 text-sm tabular-nums',
              'hover:bg-muted transition-colors',
              'aria-expanded:bg-muted aria-expanded:border-ring/40',
              'focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 outline-none',
              className,
            )}
          >
            <Clock className="size-3.5 text-muted-foreground" aria-hidden />
            <span>{triggerLabel}</span>
          </button>
        }
      />
      <PopoverContent align="start" sideOffset={6} className="w-[200px] p-0 overflow-hidden">
        <div className="grid grid-cols-2 h-72">
          <ScrollColumn
            label="Hour"
            open={open}
            items={hours}
            selected={parsedH}
            renderLabel={(h) => formatHour12(h)}
            onPick={(h) => onChange(toHHMM(h, parsedM))}
          />
          <ScrollColumn
            label="Min"
            open={open}
            leftBorder
            items={minutes}
            selected={parsedM}
            renderLabel={(m) => `:${pad2(m)}`}
            onPick={(m) => {
              onChange(toHHMM(parsedH, m));
              setOpen(false);
            }}
          />
        </div>
      </PopoverContent>
    </Popover>
  );
}

// ── Scroll column ────────────────────────────────────────────────────────
//
// Layout discipline: the column itself is a flex column with `min-h-0` so
// it can be shorter than its content (the CSS Grid + flex `min-height:
// auto` trap that prevents `overflow-y-auto` from kicking in). The header
// is a `shrink-0` sibling of the scrollable list, NOT inside the scroll
// container — keeps the header pinned without `position: sticky` (which
// reintroduces the same min-height fight) and lets the list be the only
// thing that scrolls.
//
// Auto-scroll-to-selected runs after the popover opens. Without this the
// user opens at the top of a 24-hour list and has to scroll to find their
// current value, which is the opposite of useful.

function ScrollColumn<T extends number>({
  label,
  open,
  leftBorder,
  items,
  selected,
  renderLabel,
  onPick,
}: {
  label: string;
  open: boolean;
  leftBorder?: boolean;
  items: T[];
  selected: T;
  renderLabel: (item: T) => React.ReactNode;
  onPick: (item: T) => void;
}) {
  const listRef = useRef<HTMLDivElement>(null);
  const selectedRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    // Run after the popover's positioning has settled so scrollIntoView
    // measures against the final layout. A double-rAF is enough — first
    // frame paints the popover, second frame the scroll lands cleanly.
    const id1 = requestAnimationFrame(() => {
      const id2 = requestAnimationFrame(() => {
        const el = selectedRef.current;
        const list = listRef.current;
        if (!el || !list) return;
        // Center the selected slot in the visible viewport. Manual offset
        // calc instead of `el.scrollIntoView({ block: 'center' })` —
        // scrollIntoView would also scroll the page (the popover sits
        // in a portal at document.body) which is a jarring side effect.
        const offset = el.offsetTop - list.clientHeight / 2 + el.clientHeight / 2;
        list.scrollTop = Math.max(0, offset);
      });
      // Keep the cancel id reachable so the outer cleanup can drop it.
      (listRef as { _id?: number })._id = id2;
    });
    return () => {
      cancelAnimationFrame(id1);
      const stored = (listRef as { _id?: number })._id;
      if (stored) cancelAnimationFrame(stored);
    };
  }, [open]);

  return (
    <div className={cn('flex flex-col min-h-0', leftBorder && 'border-l')}>
      <p className="shrink-0 border-b px-2 py-1 text-[10px] uppercase tracking-wide text-muted-foreground/70 font-medium text-center bg-popover">
        {label}
      </p>
      <div
        ref={listRef}
        className="overflow-y-auto flex-1 min-h-0 py-1 [scrollbar-width:thin]"
      >
        {items.map((item) => {
          const active = item === selected;
          return (
            <SlotButton
              key={item}
              ref={active ? selectedRef : undefined}
              active={active}
              onClick={() => onPick(item)}
            >
              {renderLabel(item)}
            </SlotButton>
          );
        })}
      </div>
    </div>
  );
}

// ── Slot button ─────────────────────────────────────────────────────────

interface SlotButtonProps {
  ref?: React.Ref<HTMLButtonElement>;
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}

function SlotButton({ ref, active, onClick, children }: SlotButtonProps) {
  return (
    <button
      ref={ref}
      type="button"
      onClick={onClick}
      className={cn(
        'block w-[calc(100%-12px)] mx-1.5 h-7 rounded text-xs font-mono tabular-nums transition-colors',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60',
        active
          ? 'bg-accent text-accent-foreground'
          : 'text-foreground hover:bg-muted',
      )}
      aria-pressed={active}
    >
      {children}
    </button>
  );
}

// ── Helpers ──────────────────────────────────────────────────────────────

function parseHHMM(value: string): [number, number] {
  if (!/^\d{1,2}:\d{2}$/.test(value)) return [9, 0];
  const [h, m] = value.split(':').map(Number);
  return [h ?? 9, m ?? 0];
}

function toHHMM(h: number, m: number): string {
  return `${pad2(h)}:${pad2(m)}`;
}

function pad2(n: number): string {
  return String(n).padStart(2, '0');
}

function formatTime12(h24: number, m: number): string {
  const period = h24 >= 12 ? 'PM' : 'AM';
  const h12 = ((h24 + 11) % 12) + 1;
  return `${h12}:${pad2(m)} ${period}`;
}

function formatHour12(h24: number): string {
  const period = h24 >= 12 ? 'PM' : 'AM';
  const h12 = ((h24 + 11) % 12) + 1;
  return `${h12} ${period}`;
}

function range(start: number, endExclusive: number, step = 1): number[] {
  const out: number[] = [];
  for (let n = start; n < endExclusive; n += step) out.push(n);
  return out;
}
