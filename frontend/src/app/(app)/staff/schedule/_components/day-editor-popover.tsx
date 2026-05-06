/**
 * Per-day schedule editor (popover).
 *
 * Anchored to a `<DayCell>` trigger, this is the form for editing one
 * day's working blocks for one provider. The component itself is
 * presentational — it owns local draft state for the blocks and calls
 * `onSave(updatedBlocks)` on submit. Wiring to the API (PUT the full
 * weekly_hours with this day replaced) lives in the parent row.
 *
 * Validation mirrors the backend — invalid drafts can't be saved, and
 * the user gets inline error text. Single-block-add UX: click "Add
 * shift" to append a default 9–5 block; edit start/end with the
 * existing `<TimePicker>` primitive.
 *
 * Empty state: no blocks shown + "Off this day" header + a "+ Add
 * shift" button. Saving with zero blocks is the explicit "off"
 * intent — distinct from "no schedule set."
 */

'use client';

import { Plus, Trash2 } from 'lucide-react';
import { useEffect, useState } from 'react';

import { Button } from '@/components/ui/button';
import { TimePicker } from '@/components/ui/time-picker';
import {
  formatBlock,
  type ScheduleBlock,
  validateDayBlocks,
} from '@/lib/schedules';

export interface DayEditorPopoverProps {
  /** Current blocks for this day (may be empty). */
  blocks: ScheduleBlock[];
  /** Display label — "Sarah · Monday" or similar. */
  title: string;
  onSave: (next: ScheduleBlock[]) => void;
  onCancel: () => void;
  /** True while the parent's PUT mutation is in flight. */
  isSubmitting: boolean;
}

const DEFAULT_NEW_BLOCK: ScheduleBlock = { start: '09:00', end: '17:00' };

export function DayEditorPopover({
  blocks,
  title,
  onSave,
  onCancel,
  isSubmitting,
}: DayEditorPopoverProps) {
  const [draft, setDraft] = useState<ScheduleBlock[]>(blocks);

  // Re-seed when the source blocks change (e.g. caller passes in
  // a different day's blocks while the popover is mounted).
  useEffect(() => {
    setDraft(blocks);
  }, [blocks]);

  const error = validateDayBlocks(draft);
  const dirty =
    draft.length !== blocks.length ||
    draft.some(
      (b, i) => b.start !== blocks[i]?.start || b.end !== blocks[i]?.end,
    );

  const updateBlock = (index: number, patch: Partial<ScheduleBlock>) => {
    setDraft((prev) =>
      prev.map((b, i) => (i === index ? { ...b, ...patch } : b)),
    );
  };

  const removeBlock = (index: number) => {
    setDraft((prev) => prev.filter((_, i) => i !== index));
  };

  const addBlock = () => {
    setDraft((prev) => [...prev, { ...DEFAULT_NEW_BLOCK }]);
  };

  const handleSave = () => {
    if (error || !dirty) return;
    onSave(draft);
  };

  return (
    <div className="space-y-3 min-w-[260px]">
      <div className="border-b pb-2 mb-1">
        <p className="text-sm font-semibold tracking-tight">{title}</p>
        <p className="text-[11px] text-muted-foreground mt-0.5">
          {draft.length === 0
            ? 'Off this day. Add a shift to make this provider bookable.'
            : `${draft.length} shift${draft.length === 1 ? '' : 's'}`}
        </p>
      </div>

      {draft.length === 0 ? (
        <p className="text-xs text-muted-foreground italic px-1 py-2">
          No working hours scheduled.
        </p>
      ) : (
        <ul className="space-y-2">
          {draft.map((block, i) => (
            <li
              key={i}
              className="flex items-center gap-2 rounded-md bg-muted/30 p-2"
            >
              <TimePicker
                value={block.start}
                onChange={(v) => updateBlock(i, { start: v })}
                step={5}
                ariaLabel={`Block ${i + 1} start time`}
              />
              <span className="text-xs text-muted-foreground">to</span>
              <TimePicker
                value={block.end}
                onChange={(v) => updateBlock(i, { end: v })}
                step={5}
                ariaLabel={`Block ${i + 1} end time`}
              />
              <button
                type="button"
                onClick={() => removeBlock(i)}
                aria-label={`Remove ${formatBlock(block)}`}
                className="ml-auto inline-flex size-7 items-center justify-center rounded-md text-muted-foreground hover:bg-destructive/10 hover:text-destructive transition-colors"
              >
                <Trash2 className="size-3.5" />
              </button>
            </li>
          ))}
        </ul>
      )}

      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={addBlock}
        className="w-full"
      >
        <Plus className="size-3.5" />
        Add shift
      </Button>

      {error ? (
        <p className="text-[11px] text-destructive leading-relaxed">{error}</p>
      ) : null}

      <div className="flex items-center justify-end gap-2 border-t pt-3">
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={onCancel}
          disabled={isSubmitting}
        >
          Cancel
        </Button>
        <Button
          type="button"
          size="sm"
          onClick={handleSave}
          disabled={!dirty || error !== null || isSubmitting}
        >
          {isSubmitting ? 'Saving…' : 'Save'}
        </Button>
      </div>
    </div>
  );
}
