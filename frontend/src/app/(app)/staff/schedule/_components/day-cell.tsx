/**
 * Visual cell showing one provider's blocks for one day.
 *
 * Purely presentational — always renders a `<div>`. The parent decides
 * whether to wrap it in an interactive element (a `<button>` for the
 * editor trigger; nothing for read-only display). Keeping the cell
 * non-interactive avoids two Base UI footguns: nested buttons (when a
 * `PopoverTrigger` wraps a button-rendering child) and the "expected
 * native <button> because nativeButton prop is true" warning that
 * fires when a Base UI trigger sees a non-button render target.
 *
 * Visual language:
 *   - Background bar: full cell width = full business-hours window of
 *     the location. Subtle muted fill represents "available but not
 *     scheduled."
 *   - Working segments: accent-tinted absolute-positioned bars at the
 *     correct % offsets, with HH:MM labels for the first block.
 *   - Off (no blocks): the cell shows "Off" centered.
 *   - `interactive` (visual-only flag) opts into hover affordances —
 *     hint icon on empty state, border emphasis on hover. The actual
 *     click behavior comes from whatever the parent wraps this in.
 */

'use client';

import { Plus } from 'lucide-react';

import {
  formatBlock,
  type ScheduleBlock,
  parseHHMMToMinutes,
} from '@/lib/schedules';
import { cn } from '@/lib/utils';

export interface DayCellProps {
  blocks: ScheduleBlock[];
  /** Open / close in HH:MM (or HH:MM:SS — we trim) for the location's
   *  business hours. Used as the visible bounds of the timeline bar. */
  locationOpen: string;
  locationClose: string;
  /** Visual-only: enables hover affordances (border emphasis, "+ Add"
   *  hint on empty state). Click behavior is the parent wrapper's
   *  job — DayCell never installs an onClick handler itself. */
  interactive?: boolean;
  /** Highlights the cell as the source of an open editor — accent
   *  border + ring. Driven by the parent's open-popover state. */
  isActive?: boolean;
}

export function DayCell({
  blocks,
  locationOpen,
  locationClose,
  interactive = false,
  isActive = false,
}: DayCellProps) {
  const openMin = parseHHMMToMinutes(trimSec(locationOpen));
  const closeMin = parseHHMMToMinutes(trimSec(locationClose));
  const windowMin = Math.max(closeMin - openMin, 1);

  // Clip blocks to the visible window. Out-of-window portions get
  // dropped silently — the operator sees what's actually within
  // business hours. (Booking outside business hours is its own
  // concern; this cell's visual scope is in-window only.)
  const visibleSegments = blocks
    .map((block) => {
      const start = Math.max(parseHHMMToMinutes(block.start), openMin);
      const end = Math.min(parseHHMMToMinutes(block.end), closeMin);
      if (end <= start) return null;
      return {
        block,
        leftPct: ((start - openMin) / windowMin) * 100,
        widthPct: ((end - start) / windowMin) * 100,
      };
    })
    .filter((s): s is NonNullable<typeof s> => s !== null);

  const isEmpty = blocks.length === 0;

  return (
    <div
      className={cn(
        'group relative w-full h-12 rounded-md border bg-background overflow-hidden transition-colors',
        interactive && 'group-hover:border-foreground/20',
        isActive && 'border-accent ring-2 ring-accent/30',
      )}
    >
      {/* Background "off-hours" track — subtle hatching could go here
          for extra polish; for v1 a flat muted fill is enough. */}
      <div className="absolute inset-0 bg-muted/30" aria-hidden />

      {/* Working segments */}
      {visibleSegments.map((seg, i) => (
        <div
          key={i}
          className="absolute top-0 bottom-0 bg-accent/20 border-l border-r border-accent/40"
          style={{
            left: `${seg.leftPct}%`,
            width: `${seg.widthPct}%`,
          }}
          title={formatBlock(seg.block)}
        >
          {/* Show the time text on the FIRST visible segment, in the
              segment if it's wide enough; otherwise rely on the title. */}
          {i === 0 && seg.widthPct > 25 ? (
            <span className="absolute inset-0 flex items-center justify-center text-[10px] font-mono tabular-nums text-accent leading-none px-1 truncate">
              {formatBlock(seg.block)}
            </span>
          ) : null}
        </div>
      ))}

      {/* Empty / off state — centered "Off" label + hover hint */}
      {isEmpty ? (
        <span className="absolute inset-0 flex items-center justify-center text-[10px] uppercase tracking-wide text-muted-foreground/70">
          {interactive ? (
            <span className="flex items-center gap-1 group-hover:text-foreground transition-colors">
              <Plus className="size-3 opacity-0 group-hover:opacity-100 transition-opacity" />
              Off
            </span>
          ) : (
            'Off'
          )}
        </span>
      ) : null}

      {/* Multi-block badge for narrow cells where labels are hidden */}
      {visibleSegments.length > 1 && visibleSegments[0].widthPct <= 25 ? (
        <span className="absolute top-0.5 right-1 text-[9px] font-medium text-accent bg-background/80 px-1 rounded">
          {visibleSegments.length}
        </span>
      ) : null}
    </div>
  );
}

function trimSec(time: string): string {
  const m = /^(\d{1,2}:\d{2})/.exec(time);
  return m ? m[1] : time;
}
