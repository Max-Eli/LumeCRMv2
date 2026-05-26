/**
 * Block-out bottom sheet.
 *
 * Opens from the right-click context menu on an empty calendar slot
 * with provider/date/time pre-filled. Used to mark non-bookable time
 * (lunch, personal, training) on a single provider's day.
 *
 * Mirrors the layout idiom of `NewAppointmentSheet` (same `Sheet` shell,
 * same date/time pickers, same submit-button positioning) so the staff
 * member doesn't have to learn a second pattern.
 *
 * Pairs with `useCreateTimeBlock` (`lib/time-blocks.ts`) → POST
 * `/api/time-blocks/`. The backend audit-logs the create with the
 * reason + provider, satisfying the HIPAA-aware trail we keep for any
 * mutation on the appointment calendar (§164.312(b)).
 */

'use client';

import { useEffect, useState } from 'react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { DatePicker } from '@/components/ui/date-picker';
import { Field, FieldError, FieldLabel } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  Sheet,
  SheetBody,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet';
import { TimePicker } from '@/components/ui/time-picker';
import { ApiError } from '@/lib/api';
import {
  defaultStartTimeLabel,
  localDateTimeToUtcIso,
  parseHHMM,
  todayLocalISODate,
} from '@/lib/calendar-datetime';
import { membershipName, useBookableMemberships } from '@/lib/memberships';
import {
  TIME_BLOCK_REASON_PRESETS,
  useCreateTimeBlock,
} from '@/lib/time-blocks';
import { cn } from '@/lib/utils';

const CUSTOM_REASON_KEY = 'Other';

export interface BlockOutSheetProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Tenant timezone — used to convert local date/time into UTC. */
  timezone: string;
  /** Pre-filled date YYYY-MM-DD (defaults to today). */
  defaultDate?: string;
  /** Pre-filled start time HH:MM 24h (defaults to next-hour
   *  business-hours-clamped). */
  defaultTime?: string;
  /** Pre-filled provider id (the column the operator right-clicked). */
  defaultProviderId?: number;
  /** Called after a successful create — typically to bump the
   *  calendar to the block's date if it differs from focus. */
  onCreated?: (createdDate: string) => void;
}

export function BlockOutSheet({
  open,
  onOpenChange,
  timezone,
  defaultDate,
  defaultTime,
  defaultProviderId,
  onCreated,
}: BlockOutSheetProps) {
  const create = useCreateTimeBlock();
  const { data: providers } = useBookableMemberships();

  const [providerId, setProviderId] = useState(defaultProviderId ?? 0);
  const [date, setDate] = useState(defaultDate ?? todayLocalISODate());
  const [time, setTime] = useState(defaultTime ?? defaultStartTimeLabel());
  // Block-outs default to 60 min — covers most lunches and meetings.
  const [durationMinutes, setDurationMinutes] = useState(60);
  const [reasonPreset, setReasonPreset] = useState<string>(
    TIME_BLOCK_REASON_PRESETS[0],
  );
  const [customReason, setCustomReason] = useState('');
  const [errors, setErrors] = useState<Record<string, string>>({});

  // Reset whenever the sheet (re)opens so a closed-and-reopened sheet
  // doesn't inherit prior state from a different right-click.
  useEffect(() => {
    if (open) {
      setProviderId(defaultProviderId ?? 0);
      setDate(defaultDate ?? todayLocalISODate());
      setTime(defaultTime ?? defaultStartTimeLabel());
      setDurationMinutes(60);
      setReasonPreset(TIME_BLOCK_REASON_PRESETS[0]);
      setCustomReason('');
      setErrors({});
    }
  }, [open, defaultDate, defaultTime, defaultProviderId]);

  const reason =
    reasonPreset === CUSTOM_REASON_KEY ? customReason.trim() : reasonPreset;

  const canSubmit =
    providerId > 0 && durationMinutes > 0 && reason.length > 0;

  const validate = (): boolean => {
    const next: Record<string, string> = {};
    if (!providerId) next.provider = 'Pick a provider.';
    if (!date) next.date = 'Pick a date.';
    if (!time) next.time = 'Pick a time.';
    if (!durationMinutes || durationMinutes < 1) {
      next.duration = 'Duration must be at least 1 minute.';
    }
    if (durationMinutes > 24 * 60) {
      next.duration = 'Duration cannot exceed 24 hours.';
    }
    if (!reason.trim()) next.reason = 'Reason is required.';
    setErrors(next);
    return Object.keys(next).length === 0;
  };

  const onSubmit = () => {
    if (!validate()) return;
    const startUtc = localDateTimeToUtcIso(
      date, ...parseHHMM(time), timezone,
    );
    const start = new Date(startUtc);
    const end = new Date(start.getTime() + durationMinutes * 60_000);

    create.mutate(
      {
        provider_id: providerId,
        start_time: start.toISOString(),
        end_time: end.toISOString(),
        reason,
      },
      {
        onSuccess: () => {
          toast.success('Time blocked');
          onOpenChange(false);
          onCreated?.(date);
        },
        onError: (err) => {
          if (
            err instanceof ApiError
            && err.status === 400
            && err.body
            && typeof err.body === 'object'
          ) {
            const body = err.body as Record<string, unknown>;
            const firstField = Object.keys(body)[0];
            const value = firstField ? body[firstField] : undefined;
            const detail =
              typeof value === 'string'
                ? value
                : Array.isArray(value) && typeof value[0] === 'string'
                  ? value[0]
                  : 'Could not block this time.';
            toast.error(detail);
          } else {
            toast.error('Could not block this time. Please try again.');
          }
        },
      },
    );
  };

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="bottom">
        <SheetHeader>
          <SheetTitle>Block out time</SheetTitle>
          <SheetDescription>
            Mark a provider&rsquo;s time as unavailable — lunch, training,
            personal time. The block shows on the calendar and is logged
            with your name and the reason.
          </SheetDescription>
        </SheetHeader>

        <SheetBody className="space-y-4">
          <Field>
            <FieldLabel>Provider</FieldLabel>
            <Select
              value={providerId ? String(providerId) : ''}
              onValueChange={(v) => setProviderId(Number(v))}
            >
              <SelectTrigger>
                <SelectValue placeholder="Pick a provider">
                  {(v) => {
                    if (!v) return 'Pick a provider';
                    const picked = (providers ?? []).find(
                      (p) => String(p.id) === v,
                    );
                    return picked ? membershipName(picked) : v;
                  }}
                </SelectValue>
              </SelectTrigger>
              <SelectContent>
                {(providers ?? []).map((p) => (
                  <SelectItem key={p.id} value={String(p.id)}>
                    {membershipName(p)}
                    {p.job_title_name ? (
                      <span className="text-muted-foreground">
                        {' '}· {p.job_title_name}
                      </span>
                    ) : null}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {errors.provider ? (
              <FieldError>{errors.provider}</FieldError>
            ) : null}
          </Field>

          <div className="grid grid-cols-2 gap-3">
            <Field>
              <FieldLabel>Date</FieldLabel>
              <DatePicker
                value={date}
                onChange={setDate}
                ariaLabel="Block date"
                className="w-full justify-start"
              />
              {errors.date ? <FieldError>{errors.date}</FieldError> : null}
            </Field>
            <Field>
              <FieldLabel>Start time</FieldLabel>
              <TimePicker
                value={time}
                onChange={setTime}
                ariaLabel="Block start time"
                className="w-full justify-start"
              />
              {errors.time ? <FieldError>{errors.time}</FieldError> : null}
            </Field>
          </div>

          <Field>
            <FieldLabel>Duration (minutes)</FieldLabel>
            <div className="flex items-center gap-2">
              <Input
                type="number"
                min={5}
                max={24 * 60}
                step={5}
                value={String(durationMinutes)}
                onChange={(e) =>
                  setDurationMinutes(Number(e.target.value) || 0)
                }
                className="w-28"
                aria-label="Block duration in minutes"
              />
              <div className="flex flex-wrap gap-1">
                {[30, 60, 90, 120].map((preset) => (
                  <button
                    key={preset}
                    type="button"
                    onClick={() => setDurationMinutes(preset)}
                    className={cn(
                      'rounded-md border px-2 py-1 text-xs transition-colors',
                      durationMinutes === preset
                        ? 'bg-accent text-accent-foreground border-accent'
                        : 'hover:bg-muted',
                    )}
                  >
                    {preset}m
                  </button>
                ))}
              </div>
            </div>
            {errors.duration ? (
              <FieldError>{errors.duration}</FieldError>
            ) : null}
          </Field>

          <Field>
            <FieldLabel>Reason</FieldLabel>
            <div className="flex flex-wrap gap-1.5">
              {TIME_BLOCK_REASON_PRESETS.map((preset) => (
                <button
                  key={preset}
                  type="button"
                  onClick={() => setReasonPreset(preset)}
                  className={cn(
                    'rounded-full border px-3 py-1 text-xs transition-colors',
                    reasonPreset === preset
                      ? 'bg-accent text-accent-foreground border-accent'
                      : 'hover:bg-muted',
                  )}
                >
                  {preset}
                </button>
              ))}
              <button
                type="button"
                onClick={() => setReasonPreset(CUSTOM_REASON_KEY)}
                className={cn(
                  'rounded-full border px-3 py-1 text-xs transition-colors',
                  reasonPreset === CUSTOM_REASON_KEY
                    ? 'bg-accent text-accent-foreground border-accent'
                    : 'hover:bg-muted',
                )}
              >
                Other
              </button>
            </div>
            {reasonPreset === CUSTOM_REASON_KEY ? (
              <Input
                type="text"
                value={customReason}
                onChange={(e) => setCustomReason(e.target.value)}
                placeholder="Describe the reason…"
                maxLength={200}
                className="mt-2"
                aria-label="Custom reason"
                autoFocus
              />
            ) : null}
            {errors.reason ? (
              <FieldError>{errors.reason}</FieldError>
            ) : null}
          </Field>
        </SheetBody>

        <SheetFooter>
          <Button
            type="button"
            variant="outline"
            disabled={create.isPending}
            onClick={() => onOpenChange(false)}
          >
            Cancel
          </Button>
          <Button
            type="button"
            disabled={!canSubmit || create.isPending}
            onClick={onSubmit}
          >
            {create.isPending ? 'Blocking…' : 'Block out time'}
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}
