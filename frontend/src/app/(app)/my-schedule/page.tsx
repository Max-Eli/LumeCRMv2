/**
 * `/my-schedule` — a staff member's own weekly availability.
 *
 * Contractors set the days + hours they want to work; the change
 * flows straight to the calendar (the working-hours overlay and
 * drag-drop validation already consume `ProviderSchedule`).
 * Non-contractors see their schedule read-only — theirs stays
 * manager-managed. One card per location the person is assigned to.
 *
 * Mobile-first: a vertical list of days rather than the manager
 * scheduler's wide weekly grid.
 */

'use client';

import { CalendarClock, Loader2 } from 'lucide-react';
import { useState } from 'react';
import { toast } from 'sonner';

import { PageHeader } from '@/components/page-header';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';
import {
  WEEKDAYS,
  type MyScheduleLocation,
  type ScheduleBlock,
  type Weekday,
  type WeeklyHours,
  formatBlock,
  formatWeeklyTotal,
  totalWeeklyMinutes,
  useMySchedules,
  useUpdateSchedule,
} from '@/lib/schedules';

import { DayEditorPopover } from '../staff/schedule/_components/day-editor-popover';

const WEEKDAY_LABELS: Record<Weekday, string> = {
  monday: 'Monday',
  tuesday: 'Tuesday',
  wednesday: 'Wednesday',
  thursday: 'Thursday',
  friday: 'Friday',
  saturday: 'Saturday',
  sunday: 'Sunday',
};

export default function MySchedulePage() {
  const { data, isLoading, error } = useMySchedules();

  return (
    <div className="px-6 py-8 sm:px-10 sm:py-10">
      <PageHeader
        title="My schedule"
        description="The days and hours you're available to work."
      />

      {isLoading ? (
        <div className="flex items-center gap-2 py-12 text-sm text-muted-foreground">
          <Loader2 className="size-4 animate-spin" /> Loading your schedule…
        </div>
      ) : error ? (
        <div className="rounded-md border border-destructive/40 bg-destructive/[0.04] p-4 text-sm text-destructive">
          Couldn&apos;t load your schedule.
        </div>
      ) : !data || data.locations.length === 0 ? (
        <div className="rounded-lg border border-dashed bg-muted/20 p-8 text-center">
          <p className="text-sm font-medium">No location assigned yet</p>
          <p className="mt-1.5 text-xs text-muted-foreground">
            Once you&apos;re assigned to a location, your weekly schedule
            shows up here.
          </p>
        </div>
      ) : (
        <div className="max-w-2xl space-y-6">
          {!data.can_edit ? (
            <p className="rounded-md border bg-muted/30 px-4 py-3 text-sm text-muted-foreground">
              Your schedule is managed by your manager. Reach out to them to
              request a change.
            </p>
          ) : null}
          {data.locations.map((loc) => (
            <LocationScheduleCard
              key={loc.membership_location_id}
              location={loc}
              canEdit={data.can_edit}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function LocationScheduleCard({
  location,
  canEdit,
}: {
  location: MyScheduleLocation;
  canEdit: boolean;
}) {
  const [weekly, setWeekly] = useState<WeeklyHours>(location.weekly_hours);
  const [openDay, setOpenDay] = useState<Weekday | null>(null);
  const update = useUpdateSchedule(location.membership_location_id);

  const handleDaySave = (day: Weekday, blocks: ScheduleBlock[]) => {
    const previous = weekly;
    const next = { ...weekly, [day]: blocks };
    setWeekly(next); // optimistic
    setOpenDay(null);
    update.mutate(next, {
      onSuccess: () => toast.success('Schedule updated'),
      onError: () => {
        setWeekly(previous); // roll back
        toast.error('Couldn’t save — please try again.');
      },
    });
  };

  return (
    <section className="overflow-hidden rounded-xl border bg-card">
      <header className="flex items-center justify-between gap-3 border-b bg-muted/20 px-4 py-3 sm:px-5">
        <div className="flex min-w-0 items-center gap-2">
          <CalendarClock className="size-4 shrink-0 text-muted-foreground" />
          <h2 className="truncate text-sm font-medium">
            {location.location_name}
          </h2>
        </div>
        <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
          {formatWeeklyTotal(totalWeeklyMinutes(weekly))} / week
        </span>
      </header>
      <ul className="divide-y">
        {WEEKDAYS.map((day) => {
          const blocks = weekly[day];
          const row = (
            <div className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left sm:px-5">
              <span className="text-sm font-medium">{WEEKDAY_LABELS[day]}</span>
              <span
                className={
                  blocks.length > 0
                    ? 'text-sm tabular-nums text-foreground'
                    : 'text-sm text-muted-foreground'
                }
              >
                {blocks.length > 0
                  ? blocks.map(formatBlock).join(', ')
                  : 'Off'}
              </span>
            </div>
          );

          if (!canEdit) {
            return <li key={day}>{row}</li>;
          }

          return (
            <li key={day}>
              <Popover
                open={openDay === day}
                onOpenChange={(next) => setOpenDay(next ? day : null)}
              >
                <PopoverTrigger
                  render={
                    <button
                      type="button"
                      aria-label={`Edit ${WEEKDAY_LABELS[day]}`}
                      className="block w-full transition-colors hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
                    />
                  }
                >
                  {row}
                </PopoverTrigger>
                <PopoverContent
                  align="end"
                  side="bottom"
                  sideOffset={6}
                  className="w-auto"
                >
                  <DayEditorPopover
                    blocks={weekly[day]}
                    title={WEEKDAY_LABELS[day]}
                    onSave={(next) => handleDaySave(day, next)}
                    onCancel={() => setOpenDay(null)}
                    isSubmitting={update.isPending}
                  />
                </PopoverContent>
              </Popover>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
