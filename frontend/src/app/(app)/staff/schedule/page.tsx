/**
 * `/staff/schedule` — per-location staff scheduler.
 *
 * Three integrated controls in one surface:
 *
 *   1. **Weekly grid** — rows = staff assigned at active location,
 *      cols = Mon–Sun. Each cell visualises that day's working blocks
 *      against the location's business hours. Click any cell to open
 *      a per-day editor popover.
 *   2. **Assign staff** — sheet picker for adding org-wide employees
 *      to this location.
 *   3. **Remove from location** — per-row action below their name.
 *
 * Schedules persist via `PUT /api/schedules/{membership_location_id}/`.
 * The bookable-providers endpoint embeds the per-location schedule so
 * the calendar's day view dims non-working hours without a separate
 * fetch (Phase 1C session 4).
 *
 * Edit gating: owner + manager (mirrors `MANAGE_STAFF`). Read-only
 * for everyone else — they can see who's scheduled when but can't
 * edit.
 */

'use client';

import { CalendarClock, Search, UserMinus, UserPlus, X } from 'lucide-react';
import Link from 'next/link';
import { useMemo, useState } from 'react';
import { toast } from 'sonner';

import { InitialsAvatar } from '@/components/initials-avatar';
import { LocationSwitcher } from '@/components/location-switcher';
import { PageHeader } from '@/components/page-header';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';
import {
  Sheet,
  SheetBody,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet';
import { ApiError } from '@/lib/api';
import { useCurrentMembership } from '@/lib/auth';
import {
  hasMultipleLocations,
  type Location,
  locationDisplayName,
  useActiveLocation,
  useLocations,
} from '@/lib/locations';
import {
  emptyWeeklyHours,
  formatWeeklyTotal,
  type ScheduleBlock,
  totalWeeklyMinutes,
  useSchedule,
  useUpdateSchedule,
  WEEKDAYS,
  type Weekday,
  type WeeklyHours,
} from '@/lib/schedules';
import {
  ROLE_LABELS,
  type StaffMembership,
  staffDisplayName,
  useAllMemberships,
  useEmployee,
  useUpdateEmployee,
} from '@/lib/tenant';
import { cn } from '@/lib/utils';

import { DayCell } from './_components/day-cell';
import { DayEditorPopover } from './_components/day-editor-popover';

const WEEKDAY_LABELS: Record<Weekday, string> = {
  monday: 'Mon',
  tuesday: 'Tue',
  wednesday: 'Wed',
  thursday: 'Thu',
  friday: 'Fri',
  saturday: 'Sat',
  sunday: 'Sun',
};

export default function StaffSchedulePage() {
  const me = useCurrentMembership();
  const canManage = me?.role === 'owner' || me?.role === 'manager';

  const { data: locations } = useLocations();
  const { location: activeLocation, isLoading: loadingActive } = useActiveLocation();
  const { data: assignedStaff, isLoading: loadingAssigned } = useAllMemberships({ scope: 'current' });
  const { data: allStaff, isLoading: loadingAll } = useAllMemberships({ scope: 'all' });

  const [pickerOpen, setPickerOpen] = useState(false);

  const isMultiLocation = hasMultipleLocations(locations);
  const activeLocationName = activeLocation
    ? locationDisplayName(activeLocation)
    : null;

  const assignedActive = (assignedStaff ?? []).filter((m) => m.is_active);
  const assignedIds = useMemo(
    () => new Set(assignedActive.map((m) => m.id)),
    [assignedActive],
  );
  const unassignedCandidates = (allStaff ?? []).filter(
    (m) => m.is_active && !assignedIds.has(m.id),
  );

  if (loadingActive || loadingAssigned) {
    return (
      <div className="px-10 py-10 text-sm text-muted-foreground">
        Loading schedule…
      </div>
    );
  }
  if (!activeLocation) {
    return (
      <div className="px-10 py-10 max-w-7xl">
        <PageHeader title="Schedule" description="No active location resolved." />
      </div>
    );
  }

  return (
    <div className="px-10 py-10 max-w-[1400px] space-y-6">
      <PageHeader
        title={isMultiLocation ? `Schedule · ${activeLocationName}` : 'Schedule'}
        description={
          isMultiLocation
            ? `Set weekly hours for staff at ${activeLocationName}. Schedules drive the calendar's working-hours overlay and (with Phase 1I) the public booking page's bookable slots.`
            : 'Set weekly hours for your staff. Schedules drive the calendar’s working-hours overlay and (with Phase 1I) the public booking page’s bookable slots.'
        }
        actions={
          <>
            {/* In-context location switcher — hidden for single-
                location tenants. Same control + cookie behavior as the
                sidebar version, just placed where the operator is
                already looking when they think "schedule for a
                different location." */}
            <LocationSwitcher variant="inline" />
            {canManage && unassignedCandidates.length > 0 ? (
              <Button
                type="button"
                size="sm"
                onClick={() => setPickerOpen(true)}
              >
                <UserPlus className="size-4" />
                Assign staff
              </Button>
            ) : null}
          </>
        }
      />

      {assignedActive.length === 0 ? (
        <EmptyState
          locationName={activeLocationName ?? 'this location'}
          canManage={canManage}
          hasCandidates={unassignedCandidates.length > 0}
          onOpenPicker={() => setPickerOpen(true)}
        />
      ) : (
        <WeeklyGrid
          staff={assignedActive}
          activeLocation={activeLocation}
          canManage={canManage}
        />
      )}

      {canManage ? (
        <AssignStaffSheet
          open={pickerOpen}
          onOpenChange={setPickerOpen}
          activeLocation={activeLocation}
          candidates={unassignedCandidates}
          isLoading={loadingAll}
        />
      ) : null}
    </div>
  );
}

// ── Weekly grid ─────────────────────────────────────────────────────

function WeeklyGrid({
  staff,
  activeLocation,
  canManage,
}: {
  staff: StaffMembership[];
  activeLocation: Location;
  canManage: boolean;
}) {
  return (
    <div className="border rounded-lg bg-card overflow-x-auto">
      <table className="w-full border-collapse">
        <colgroup>
          <col className="w-[220px]" />
          {WEEKDAYS.map((d) => (
            <col key={d} />
          ))}
        </colgroup>
        <thead>
          <tr className="border-b bg-muted/30">
            <th className="text-left text-[11px] uppercase tracking-wide text-muted-foreground/80 font-medium px-4 py-2">
              Staff
            </th>
            {WEEKDAYS.map((day) => (
              <th
                key={day}
                className="text-[11px] uppercase tracking-wide text-muted-foreground/80 font-medium px-2 py-2 text-center min-w-[110px]"
              >
                {WEEKDAY_LABELS[day]}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {staff.map((m) => (
            <ScheduleRow
              key={m.id}
              membership={m}
              activeLocation={activeLocation}
              canManage={canManage}
            />
          ))}
        </tbody>
      </table>
      <p className="px-4 py-2.5 text-[11px] text-muted-foreground border-t bg-muted/20 leading-relaxed flex items-start gap-2">
        <CalendarClock className="size-3.5 text-muted-foreground/70 shrink-0 mt-0.5" aria-hidden />
        <span>
          Working hours show as filled bars within {locationDisplayName(activeLocation)}&apos;s
          business hours window.{' '}
          {canManage
            ? 'Click any cell to add or edit shifts.'
            : 'Owners and managers can edit.'}
        </span>
      </p>
    </div>
  );
}

function ScheduleRow({
  membership,
  activeLocation,
  canManage,
}: {
  membership: StaffMembership;
  activeLocation: Location;
  canManage: boolean;
}) {
  const mlId = membership.membership_location_id ?? null;

  // Defensive: if for some reason the API didn't embed the membership-
  // location id (e.g. stale cache after a switch), the row degrades to
  // a non-interactive display rather than throwing.
  if (!mlId) {
    return (
      <tr className="border-b last:border-b-0">
        <td className="px-4 py-3">
          <StaffCell membership={membership} activeLocation={activeLocation} canManage={canManage} mlId={null} />
        </td>
        {WEEKDAYS.map((day) => (
          <td key={day} className="px-2 py-3">
            <DayCell
              blocks={[]}
              locationOpen={activeLocation.business_open_time}
              locationClose={activeLocation.business_close_time}
            />
          </td>
        ))}
      </tr>
    );
  }

  return <ScheduleRowWithSchedule
    membership={membership}
    activeLocation={activeLocation}
    canManage={canManage}
    mlId={mlId}
  />;
}

function ScheduleRowWithSchedule({
  membership,
  activeLocation,
  canManage,
  mlId,
}: {
  membership: StaffMembership;
  activeLocation: Location;
  canManage: boolean;
  mlId: number;
}) {
  const { data: schedule, isLoading } = useSchedule(mlId);
  const update = useUpdateSchedule(mlId);
  const [openDay, setOpenDay] = useState<Weekday | null>(null);

  const weekly: WeeklyHours = schedule?.weekly_hours ?? emptyWeeklyHours();
  const totalMin = totalWeeklyMinutes(weekly);

  const handleDaySave = (day: Weekday, blocks: ScheduleBlock[]) => {
    const next: WeeklyHours = { ...weekly, [day]: blocks };
    update.mutate(next, {
      onSuccess: () => {
        toast.success(`${staffDisplayName(membership)} · ${WEEKDAY_LABELS[day]} updated`);
        setOpenDay(null);
      },
      onError: (err) => {
        if (err instanceof ApiError && err.status === 403) {
          toast.error("You don't have permission to edit schedules.");
        } else if (err instanceof ApiError && err.status === 400 && typeof err.body === 'object' && err.body) {
          const body = err.body as Record<string, string[] | string>;
          const firstField = Object.keys(body)[0];
          const detail = firstField
            ? Array.isArray(body[firstField])
              ? (body[firstField] as string[])[0]
              : String(body[firstField])
            : 'Could not save schedule.';
          toast.error(detail);
        } else {
          toast.error('Could not save schedule.');
        }
      },
    });
  };

  return (
    <tr className="border-b last:border-b-0 hover:bg-muted/10 transition-colors">
      <td className="px-4 py-3 align-top border-r">
        <StaffCell
          membership={membership}
          activeLocation={activeLocation}
          canManage={canManage}
          mlId={mlId}
          weeklyTotalLabel={formatWeeklyTotal(totalMin)}
        />
      </td>
      {WEEKDAYS.map((day) => (
        <td key={day} className="px-2 py-3 align-top">
          {canManage ? (
            <Popover
              open={openDay === day}
              onOpenChange={(next) => setOpenDay(next ? day : null)}
            >
              <PopoverTrigger
                render={
                  <button
                    type="button"
                    aria-label={`Edit ${staffDisplayName(membership)} ${WEEKDAY_LABELS[day]} schedule`}
                    className="group block w-full rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
                  />
                }
              >
                <DayCell
                  blocks={weekly[day]}
                  locationOpen={activeLocation.business_open_time}
                  locationClose={activeLocation.business_close_time}
                  interactive
                  isActive={openDay === day}
                />
              </PopoverTrigger>
              <PopoverContent
                align="center"
                side="bottom"
                sideOffset={6}
                className="w-auto"
              >
                <DayEditorPopover
                  blocks={weekly[day]}
                  title={`${staffDisplayName(membership)} · ${WEEKDAY_LABELS[day]}`}
                  onSave={(blocks) => handleDaySave(day, blocks)}
                  onCancel={() => setOpenDay(null)}
                  isSubmitting={update.isPending}
                />
              </PopoverContent>
            </Popover>
          ) : (
            <DayCell
              blocks={weekly[day]}
              locationOpen={activeLocation.business_open_time}
              locationClose={activeLocation.business_close_time}
            />
          )}
        </td>
      ))}
      {isLoading ? (
        // Subtle indication that the row's schedule is still loading
        // — don't render this as part of the cells (would shift layout).
        // Inline empty (the cells render against `weekly = empty()` while
        // loading, which is fine).
        null
      ) : null}
    </tr>
  );
}

// ── Staff cell (left column of the grid) ────────────────────────────

function StaffCell({
  membership,
  activeLocation,
  canManage,
  mlId,
  weeklyTotalLabel,
}: {
  membership: StaffMembership;
  activeLocation: Location;
  canManage: boolean;
  mlId: number | null;
  weeklyTotalLabel?: string;
}) {
  return (
    <div className="flex items-start gap-3">
      <InitialsAvatar name={staffDisplayName(membership)} size="sm" />
      <div className="min-w-0 flex-1">
        <Link
          href={`/staff/employees/${membership.id}`}
          className="text-sm font-medium hover:underline underline-offset-2 truncate block"
        >
          {staffDisplayName(membership)}
        </Link>
        <p className="text-[11px] text-muted-foreground truncate">
          {ROLE_LABELS[membership.role]}
          {membership.job_title_name ? ` · ${membership.job_title_name}` : ''}
        </p>
        {weeklyTotalLabel ? (
          <p className="text-[11px] text-muted-foreground/80 mt-0.5">
            {weeklyTotalLabel} / week
          </p>
        ) : null}
        {canManage && mlId ? (
          <RemoveStaffButton
            membership={membership}
            activeLocation={activeLocation}
          />
        ) : null}
      </div>
    </div>
  );
}

function RemoveStaffButton({
  membership,
  activeLocation,
}: {
  membership: StaffMembership;
  activeLocation: Location;
}) {
  const { data: detail } = useEmployee(membership.id);
  const update = useUpdateEmployee(membership.id);
  const [confirming, setConfirming] = useState(false);

  if (!detail) return null;

  const remainingLocationIds = detail.location_ids.filter(
    (id) => id !== activeLocation.id,
  );

  const handleRemove = () => {
    update.mutate(
      { set_location_ids: remainingLocationIds },
      {
        onSuccess: () => {
          toast.success(
            `${staffDisplayName(membership)} removed from ${locationDisplayName(activeLocation)}`,
          );
          setConfirming(false);
        },
        onError: (err) => {
          setConfirming(false);
          if (err instanceof ApiError && err.status === 403) {
            toast.error("You don't have permission to change assignments.");
          } else {
            toast.error('Could not update assignment.');
          }
        },
      },
    );
  };

  return confirming ? (
    <div className="flex items-center gap-1 mt-1.5">
      <button
        type="button"
        onClick={() => setConfirming(false)}
        disabled={update.isPending}
        className="text-[11px] text-muted-foreground hover:text-foreground transition-colors px-1"
      >
        Cancel
      </button>
      <button
        type="button"
        onClick={handleRemove}
        disabled={update.isPending}
        className="text-[11px] font-medium text-destructive hover:text-destructive/80 transition-colors px-1"
      >
        Confirm
      </button>
    </div>
  ) : (
    <button
      type="button"
      onClick={() => setConfirming(true)}
      className="inline-flex items-center gap-0.5 text-[11px] text-muted-foreground hover:text-destructive transition-colors mt-1.5"
    >
      <UserMinus className="size-3" />
      Remove
    </button>
  );
}

// ── Empty state ─────────────────────────────────────────────────────

function EmptyState({
  locationName,
  canManage,
  hasCandidates,
  onOpenPicker,
}: {
  locationName: string;
  canManage: boolean;
  hasCandidates: boolean;
  onOpenPicker: () => void;
}) {
  return (
    <div className="border rounded-lg bg-card px-6 py-12 text-center">
      <div className="inline-flex size-12 items-center justify-center rounded-full bg-accent/15 text-accent mb-4">
        <UserPlus className="size-6" />
      </div>
      <p className="text-sm text-foreground font-medium">
        No staff assigned to {locationName} yet
      </p>
      <p className="text-xs text-muted-foreground mt-1.5 max-w-md mx-auto leading-relaxed">
        Assign staff so they appear on this location&apos;s calendar and roster, then set
        their weekly working hours from the grid.
      </p>
      {canManage && hasCandidates ? (
        <Button type="button" className="mt-5" onClick={onOpenPicker}>
          <UserPlus className="size-4" />
          Assign staff
        </Button>
      ) : !canManage ? (
        <p className="text-[11px] text-muted-foreground/80 mt-5">
          Only owners and managers can change assignments.
        </p>
      ) : (
        <p className="text-[11px] text-muted-foreground/80 mt-5">
          No employees available to assign.{' '}
          <Link href="/staff/employees" className="underline-offset-2 hover:underline">
            Add a new employee
          </Link>{' '}
          first.
        </p>
      )}
    </div>
  );
}

// ── Assign-staff picker (sheet) — unchanged from previous version ───

function AssignStaffSheet({
  open,
  onOpenChange,
  activeLocation,
  candidates,
  isLoading,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  activeLocation: Location;
  candidates: StaffMembership[];
  isLoading: boolean;
}) {
  const [search, setSearch] = useState('');

  const filtered = candidates.filter((m) => {
    if (!search.trim()) return true;
    const q = search.trim().toLowerCase();
    return (
      staffDisplayName(m).toLowerCase().includes(q) ||
      m.user_email.toLowerCase().includes(q)
    );
  });

  return (
    <Sheet
      open={open}
      onOpenChange={(next) => {
        onOpenChange(next);
        if (!next) setSearch('');
      }}
    >
      <SheetContent side="right" className="max-w-md">
        <SheetHeader>
          <SheetTitle>
            Assign staff to {locationDisplayName(activeLocation)}
          </SheetTitle>
          <SheetDescription>
            Click an employee to add them to this location. They&apos;ll
            appear on the schedule grid immediately so you can set their
            hours. Picker only shows people not yet assigned here.
          </SheetDescription>
        </SheetHeader>
        <SheetBody className="space-y-3">
          <div className="relative">
            <Search className="absolute left-2 top-1/2 -translate-y-1/2 size-3.5 text-muted-foreground pointer-events-none" />
            <Input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search by name or email…"
              className="pl-7"
              autoFocus
            />
          </div>
          {isLoading ? (
            <p className="text-sm text-muted-foreground">Loading employees…</p>
          ) : filtered.length === 0 ? (
            <p className="text-sm text-muted-foreground italic py-6 text-center">
              {candidates.length === 0
                ? 'Every active employee is already assigned to this location.'
                : `No matches for "${search}".`}
            </p>
          ) : (
            <ul className="border rounded-lg divide-y bg-card max-h-[500px] overflow-y-auto">
              {filtered.map((m) => (
                <PickerRow
                  key={m.id}
                  membership={m}
                  activeLocation={activeLocation}
                />
              ))}
            </ul>
          )}
        </SheetBody>
        <SheetFooter>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            <X className="size-4" />
            Done
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}

function PickerRow({
  membership,
  activeLocation,
}: {
  membership: StaffMembership;
  activeLocation: Location;
}) {
  const { data: detail } = useEmployee(membership.id);
  const update = useUpdateEmployee(membership.id);

  const handleAssign = () => {
    if (!detail || update.isPending) return;
    const next = [...detail.location_ids, activeLocation.id];
    update.mutate(
      { set_location_ids: next },
      {
        onSuccess: () => {
          toast.success(
            `${staffDisplayName(membership)} added to ${locationDisplayName(activeLocation)}`,
          );
        },
        onError: (err) => {
          if (err instanceof ApiError && err.status === 403) {
            toast.error("You don't have permission to change assignments.");
          } else {
            toast.error('Could not assign.');
          }
        },
      },
    );
  };

  const otherLocationCount = (detail?.location_ids ?? []).length;

  return (
    <li>
      <button
        type="button"
        onClick={handleAssign}
        disabled={!detail || update.isPending}
        className={cn(
          'w-full flex items-center gap-3 px-4 py-2.5 text-left transition-colors',
          'hover:bg-muted/40',
          'disabled:cursor-not-allowed disabled:opacity-50',
        )}
      >
        <InitialsAvatar name={staffDisplayName(membership)} size="sm" />
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium truncate">
            {staffDisplayName(membership)}
          </p>
          <p className="text-[11px] text-muted-foreground truncate">
            {ROLE_LABELS[membership.role]}
            {otherLocationCount > 0
              ? ` · works at ${otherLocationCount} other site${otherLocationCount === 1 ? '' : 's'}`
              : ' · not yet assigned anywhere'}
          </p>
        </div>
        <UserPlus
          className={cn(
            'size-4 shrink-0 text-muted-foreground/60',
            update.isPending && 'animate-pulse',
          )}
        />
      </button>
    </li>
  );
}
