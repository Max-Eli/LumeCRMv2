/**
 * Day view — provider columns × time grid with absolutely-positioned
 * appointment blocks. Drag-and-drop reschedule + reassign live here.
 *
 * Layout math:
 *   - DAY_START_HOUR..DAY_END_HOUR define the visible window (default 8 AM–8 PM)
 *   - `pxPerMin` (driven by the View Settings slider) drives vertical scale.
 *   - Each appointment's top    = (start - DAY_START) * pxPerMin
 *     and    height              = duration * pxPerMin
 *   - Each provider gets one column; appointment blocks are positioned within
 *     their provider's column.
 *
 * Drag-and-drop:
 *   - Each appointment block is `useDraggable`. Pointer activation requires
 *     5 px of movement so a click still opens the popover; only an actual
 *     drag triggers the move flow. Terminal-state appointments (cancelled,
 *     completed, no-show) are not draggable.
 *   - Each provider column body is `useDroppable`. While a drag is active,
 *     the column tints accent for an eligible drop or destructive for an
 *     ineligible one (provider's job_title not in the service category's
 *     `eligible_job_titles`).
 *   - On drop: snap the y-delta to the nearest 5-minute mark, compute the
 *     new start/end times, and optimistically PATCH the appointment. On
 *     backend rejection (eligibility, transition, etc.) we roll the cache
 *     back to its prior snapshot and surface the error in a toast.
 */

'use client';

import {
  DndContext,
  DragOverlay,
  PointerSensor,
  pointerWithin,
  useDndContext,
  useDraggable,
  useDroppable,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragStartEvent,
} from '@dnd-kit/core';
import { useQueryClient } from '@tanstack/react-query';
import { Clock } from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';

import { InitialsAvatar } from '@/components/initials-avatar';
import { ApiError, api } from '@/lib/api';
import {
  STATUS_LABELS,
  type Appointment,
  type AppointmentStatus,
} from '@/lib/appointments';
import { isProviderEligible, type EligibilityResult } from '@/lib/eligibility';
import { membershipName, type Membership } from '@/lib/memberships';
import {
  parseHHMMToMinutes,
  type ScheduleBlock,
  type Weekday,
  weekdayFromDate,
} from '@/lib/schedules';
import { useServiceCategories } from '@/lib/services';
import { cn } from '@/lib/utils';

import { AppointmentPopover } from './appointment-popover';

// ── Constants ────────────────────────────────────────────────────────────

// Defaults used when the calendar page hasn't supplied a day window
// (e.g. tenant settings haven't loaded yet). Once loaded, the calendar
// passes `dayStartHour` / `dayEndHour` based on the tenant's
// `business_open_time` / `business_close_time`. Both are used as
// integer hours [0, 24].
const DEFAULT_DAY_START_HOUR = 8;
const DEFAULT_DAY_END_HOUR = 20;
const SNAP_MINUTES = 5;

/** Sensible slider bounds — wide enough to cover everyone's preference, narrow
 *  enough that no extreme renders the calendar unusable. */
export const PX_PER_MIN_MIN = 1.5;
export const PX_PER_MIN_MAX = 5;
export const PX_PER_MIN_STEP = 0.25;
export const PX_PER_MIN_DEFAULT = 3;

export const COLUMN_PX_MIN = 100;
export const COLUMN_PX_MAX = 320;
export const COLUMN_PX_STEP = 10;
export const COLUMN_PX_DEFAULT = 200;

/** Threshold below which there isn't enough vertical room for a label at every
 *  5-minute mark (rows would collide), so we fall back to 15-minute labels. */
const FIVE_MIN_LABEL_THRESHOLD = 2.5;

/** Threshold below which the column is considered "narrow" — the appointment
 *  block content tightens (smaller text, tighter padding, drops the customer
 *  name when also vertically tight). */
const NARROW_COLUMN_THRESHOLD = 170;

/** Inclusive list of hour numbers for the time axis given a start (inclusive) and end (inclusive). */
function buildHourList(startHour: number, endHour: number): number[] {
  return Array.from({ length: endHour - startHour + 1 }, (_, i) => startHour + i);
}

const TERMINAL_STATUSES: ReadonlySet<AppointmentStatus> = new Set([
  'cancelled',
  'completed',
  'no_show',
]);

// ── Drag-data types passed through @dnd-kit ──────────────────────────────

type AppointmentDragData = {
  type: 'appointment';
  appointment: Appointment;
};

type ColumnDropData = {
  type: 'column';
  provider: Membership;
};

/**
 * Open-context-menu state for the reschedule flow. The menu is a small
 * absolutely-positioned div anchored at the click coords; `newStart` /
 * `newEnd` are the snapped slot times (UTC ISO via `Date`); `slotLabel`
 * is a pre-formatted "10:00 AM (60m)" string for the menu copy.
 */
type RescheduleMenu = {
  clientX: number;
  clientY: number;
  providerId: number;
  newStart: Date;
  newEnd: Date;
  slotLabel: string;
};

/**
 * Open-context-menu state for the new-appointment flow. Right-clicking
 * any empty slot (when NOT in rescheduling mode) opens this menu;
 * confirming hands `(date, time, providerId)` off to the calendar page
 * to pre-fill the New Appointment sheet.
 */
type CreateMenu = {
  clientX: number;
  clientY: number;
  providerId: number;
  date: string;
  time: string;
  slotLabel: string;
};

// ── DayView ──────────────────────────────────────────────────────────────

export interface DayViewProps {
  date: string; // YYYY-MM-DD (kept for future multi-day clipping)
  timezone: string;
  providers: Membership[];
  appointments: Appointment[];
  /** Pixels per minute on the time axis. Driven by the View Settings slider;
   *  see PX_PER_MIN_MIN/MAX/STEP/DEFAULT for the bounds. */
  pxPerMin?: number;
  /** Provider-column width in pixels. See COLUMN_PX_MIN/MAX/STEP/DEFAULT. */
  columnWidthPx?: number;
  /** Active rescheduling target — set by the calendar page from the
   *  `?rescheduling=ID&duration=MIN` URL params. When non-null:
   *    - The matching appointment block fades + gets a burgundy ring.
   *    - Right-clicking any provider column opens a small "reschedule
   *      here / cancel" menu at the click coords. */
  rescheduling?: { appointmentId: number; durationMinutes: number } | null;
  /** Called when the user dismisses the reschedule flow (Cancel button
   *  in the menu, success after confirm, or escape). */
  onCancelReschedule?: () => void;
  /** Called when the user left-clicks an empty space in a provider
   *  column (i.e. *not* on an existing appointment block). Used to open
   *  the New Appointment modal pre-filled with the chosen slot. Skipped
   *  while a reschedule is in progress so the right-click flow isn't
   *  competing with a "create new" intent. */
  onEmptySlotClick?: (slot: { date: string; time: string; providerId: number }) => void;
  /** First hour visible on the time axis (inclusive, 0-23). Comes from
   *  `Tenant.business_open_time`; defaults to 8 AM if the calendar
   *  page hasn't supplied it (tenant settings still loading). */
  dayStartHour?: number;
  /** Last hour visible on the time axis (exclusive, 1-24). Comes from
   *  `Tenant.business_close_time`; defaults to 8 PM. */
  dayEndHour?: number;
}

export function DayView({
  date,
  timezone,
  providers,
  appointments,
  pxPerMin = PX_PER_MIN_DEFAULT,
  columnWidthPx = COLUMN_PX_DEFAULT,
  rescheduling = null,
  onCancelReschedule,
  onEmptySlotClick,
  dayStartHour = DEFAULT_DAY_START_HOUR,
  dayEndHour = DEFAULT_DAY_END_HOUR,
}: DayViewProps) {
  const hourHeight = 60 * pxPerMin;
  const dayHeight = (dayEndHour - dayStartHour) * hourHeight;
  const colPx = columnWidthPx;
  const isNarrow = columnWidthPx < NARROW_COLUMN_THRESHOLD;
  const showFiveMinLabels = pxPerMin >= FIVE_MIN_LABEL_THRESHOLD;
  // Hours array (inclusive both ends) — recomputed when the day window
  // changes via tenant settings. Used by the time axis labels and the
  // hour grid lines.
  const hoursArray = useMemo(
    () => buildHourList(dayStartHour, dayEndHour),
    [dayStartHour, dayEndHour],
  );

  const qc = useQueryClient();
  const { data: categories } = useServiceCategories();

  const [activeAppt, setActiveAppt] = useState<Appointment | null>(null);

  const sensors = useSensors(
    useSensor(PointerSensor, {
      // Require 5 px of pointer movement before a drag activates so a plain
      // click still bubbles up to the popover trigger.
      activationConstraint: { distance: 5 },
    }),
  );

  const moveAppointment = useCallback(
    async (
      appt: Appointment,
      newStart: Date,
      newEnd: Date,
      newProviderId: number,
    ) => {
      // Find the matching appointment-list query key for this date so the
      // optimistic update + rollback target the right cache entry.
      const queryKey = ['appointments', 'date', date] as const;

      await qc.cancelQueries({ queryKey });
      const previous = qc.getQueryData<Appointment[]>(queryKey);

      qc.setQueryData<Appointment[]>(queryKey, (old) =>
        (old ?? []).map((a) =>
          a.id === appt.id
            ? {
                ...a,
                start_time: newStart.toISOString(),
                end_time: newEnd.toISOString(),
                provider:
                  newProviderId !== a.provider.id
                    ? buildProviderSummary(providers, newProviderId, a.provider)
                    : a.provider,
              }
            : a,
        ),
      );

      try {
        await api.patch<Appointment>(`/api/appointments/${appt.id}/`, {
          start_time: newStart.toISOString(),
          end_time: newEnd.toISOString(),
          provider_id: newProviderId,
        });
        toast.success('Appointment moved');
      } catch (err) {
        if (previous) qc.setQueryData(queryKey, previous);
        if (err instanceof ApiError && err.status === 400 && typeof err.body === 'object' && err.body) {
          const body = err.body as Record<string, string[] | string>;
          const firstField = Object.keys(body)[0];
          const detail = firstField
            ? Array.isArray(body[firstField])
              ? (body[firstField] as string[])[0]
              : String(body[firstField])
            : 'Could not move appointment.';
          toast.error(detail);
        } else {
          toast.error('Could not move appointment. Please try again.');
        }
      } finally {
        qc.invalidateQueries({ queryKey });
      }
    },
    [qc, date, providers],
  );

  // ── Right-click context menus (reschedule + create) ─────────────────────
  //
  // Two right-click flows share the same overall pattern (small floating
  // menu anchored at the click coords, escape/outside-click closes):
  //   - Rescheduling mode active → "Reschedule appointment here / Cancel"
  //   - Otherwise                → "Create appointment here / Cancel"
  // Modeled as separate state slots so the types stay narrow; the
  // dismiss / outside-click effect closes whichever is open.

  const [contextMenu, setContextMenu] = useState<RescheduleMenu | null>(null);
  const [createMenu, setCreateMenu] = useState<CreateMenu | null>(null);

  const closeContextMenu = useCallback(() => {
    setContextMenu(null);
    setCreateMenu(null);
  }, []);

  // Close the menus on Escape and on outside click.
  useEffect(() => {
    if (!contextMenu && !createMenu) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') closeContextMenu();
    };
    const onClick = () => closeContextMenu();
    window.addEventListener('keydown', onKey);
    // Wait a tick before listening for clicks so the click that opened
    // the menu doesn't immediately close it.
    const t = setTimeout(() => window.addEventListener('click', onClick), 0);
    return () => {
      window.removeEventListener('keydown', onKey);
      window.removeEventListener('click', onClick);
      clearTimeout(t);
    };
  }, [contextMenu, createMenu, closeContextMenu]);

  const openContextMenu = useCallback(
    (params: {
      clientX: number;
      clientY: number;
      providerId: number;
      yInColumn: number;
    }) => {
      if (!rescheduling) return;
      // Snap the click Y position to the nearest 5-minute mark, derive
      // the wall-clock time, then convert that to a UTC ISO string for
      // the API. The duration is fixed (came from the source appointment
      // via the URL param) so end = start + duration.
      const minutesFromDayStart =
        Math.round(params.yInColumn / pxPerMin / SNAP_MINUTES) * SNAP_MINUTES;
      const totalMinutes = dayStartHour * 60 + minutesFromDayStart;
      const hours = Math.floor(totalMinutes / 60);
      const minutes = totalMinutes % 60;

      // Out-of-window check — if the user right-clicks below the visible
      // day window, ignore (don't open menu for an invalid slot).
      if (totalMinutes + rescheduling.durationMinutes > dayEndHour * 60) {
        toast.error('Appointment would extend past the visible day window.');
        return;
      }

      const newStartIso = localDateTimeToUtcIso(date, hours, minutes, timezone);
      const newStart = new Date(newStartIso);
      const newEnd = new Date(
        newStart.getTime() + rescheduling.durationMinutes * 60_000,
      );

      setContextMenu({
        clientX: params.clientX,
        clientY: params.clientY,
        providerId: params.providerId,
        newStart,
        newEnd,
        slotLabel: formatSlotLabel(hours, minutes, rescheduling.durationMinutes),
      });
    },
    [rescheduling, pxPerMin, date, timezone],
  );

  const openCreateMenu = useCallback(
    (params: {
      clientX: number;
      clientY: number;
      providerId: number;
      yInColumn: number;
    }) => {
      // Don't compete with the reschedule flow — when rescheduling is
      // active, the same right-click opens the reschedule menu instead.
      if (rescheduling) return;
      if (!onEmptySlotClick) return;
      const minutesFromDayStart =
        Math.round(params.yInColumn / pxPerMin / SNAP_MINUTES) * SNAP_MINUTES;
      const totalMinutes = dayStartHour * 60 + minutesFromDayStart;
      const hours = Math.floor(totalMinutes / 60);
      const minutes = totalMinutes % 60;
      // Out-of-window guard — ignore right-clicks past the visible day.
      if (hours < dayStartHour || hours >= dayEndHour) return;

      setCreateMenu({
        clientX: params.clientX,
        clientY: params.clientY,
        providerId: params.providerId,
        date,
        time: `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}`,
        slotLabel: formatStartLabel(hours, minutes),
      });
    },
    [rescheduling, onEmptySlotClick, pxPerMin, date],
  );

  const commitCreateAppointment = useCallback(() => {
    if (!createMenu || !onEmptySlotClick) return;
    onEmptySlotClick({
      date: createMenu.date,
      time: createMenu.time,
      providerId: createMenu.providerId,
    });
    closeContextMenu();
  }, [createMenu, onEmptySlotClick, closeContextMenu]);

  const commitReschedule = useCallback(async () => {
    if (!contextMenu || !rescheduling) return;
    const queryKey = ['appointments', 'date', date] as const;
    try {
      await api.patch<Appointment>(`/api/appointments/${rescheduling.appointmentId}/`, {
        start_time: contextMenu.newStart.toISOString(),
        end_time: contextMenu.newEnd.toISOString(),
        provider_id: contextMenu.providerId,
      });
      toast.success(`Rescheduled to ${contextMenu.slotLabel}`);
      // Blow the appointments cache wide — both the source date and the
      // destination date may have changed.
      qc.invalidateQueries({ queryKey: ['appointments'] });
      void queryKey;
      closeContextMenu();
      onCancelReschedule?.();
    } catch (err) {
      if (err instanceof ApiError && err.status === 400 && typeof err.body === 'object' && err.body) {
        const body = err.body as Record<string, string[] | string>;
        const firstField = Object.keys(body)[0];
        const detail = firstField
          ? Array.isArray(body[firstField])
            ? (body[firstField] as string[])[0]
            : String(body[firstField])
          : 'Could not reschedule.';
        toast.error(detail);
      } else {
        toast.error('Could not reschedule. Please try again.');
      }
    }
  }, [contextMenu, rescheduling, qc, date, closeContextMenu, onCancelReschedule]);

  const onDragStart = (e: DragStartEvent) => {
    const data = e.active.data.current as AppointmentDragData | undefined;
    if (data?.type === 'appointment') {
      setActiveAppt(data.appointment);
    }
  };

  const onDragEnd = (e: DragEndEvent) => {
    const data = e.active.data.current as AppointmentDragData | undefined;
    setActiveAppt(null);
    if (!data || data.type !== 'appointment') return;
    const appt = data.appointment;
    if (TERMINAL_STATUSES.has(appt.status)) return;

    // Vertical delta → minutes, snapped to SNAP_MINUTES grid.
    const rawMinutes = e.delta.y / pxPerMin;
    const deltaMinutes = Math.round(rawMinutes / SNAP_MINUTES) * SNAP_MINUTES;

    // Provider change?
    let newProviderId = appt.provider.id;
    let newProvider: Membership | null = null;
    const overData = e.over?.data.current as ColumnDropData | undefined;
    if (overData?.type === 'column') {
      newProvider = overData.provider;
      newProviderId = newProvider.id;
    }

    if (deltaMinutes === 0 && newProviderId === appt.provider.id) {
      // No-op drag (drop in original spot)
      return;
    }

    // Eligibility — block ineligible drops client-side. Backend re-validates.
    if (newProvider && newProviderId !== appt.provider.id) {
      const eligibility = isProviderEligible(
        { category: appt.service.category_id ? { id: appt.service.category_id } : null },
        newProvider,
        categories ?? [],
      );
      if (!eligibility.ok) {
        toast.error(eligibility.reason);
        return;
      }
    }

    const newStart = new Date(new Date(appt.start_time).getTime() + deltaMinutes * 60_000);
    const newEnd = new Date(new Date(appt.end_time).getTime() + deltaMinutes * 60_000);

    // Out-of-window guard — don't push appointments beyond the visible day.
    const startMinutes =
      minutesIntoLocalDay(newStart.toISOString(), timezone);
    const endMinutes = minutesIntoLocalDay(newEnd.toISOString(), timezone);
    if (
      startMinutes < dayStartHour * 60 ||
      endMinutes > dayEndHour * 60
    ) {
      toast.error('Appointment would fall outside the visible day window.');
      return;
    }

    void moveAppointment(appt, newStart, newEnd, newProviderId);
  };

  if (providers.length === 0) {
    return <EmptyProvidersState />;
  }

  // Group appointments by provider for fast column rendering.
  const byProvider = new Map<number, Appointment[]>();
  for (const appt of appointments) {
    const list = byProvider.get(appt.provider.id);
    if (list) list.push(appt);
    else byProvider.set(appt.provider.id, [appt]);
  }

  return (
    <DndContext
      sensors={sensors}
      collisionDetection={pointerWithin}
      onDragStart={onDragStart}
      onDragEnd={onDragEnd}
      onDragCancel={() => setActiveAppt(null)}
    >
      <div className="flex-1 min-h-0 overflow-auto bg-card">
        <div className="flex min-w-full">
          {/* Time axis (sticky-left so labels stay visible on horizontal scroll) */}
          <div className="sticky left-0 z-20 w-20 shrink-0 bg-card border-r">
            <div className="h-16 border-b bg-card" />
            <div className="relative" style={{ height: dayHeight }}>
              {buildTimeAxisLabels(showFiveMinLabels, hoursArray, dayStartHour).map(({ minutesFromStart, kind, label }) => (
                <div
                  key={`${kind}-${minutesFromStart}`}
                  className={cn(
                    'absolute right-0 pr-2 -translate-y-1/2 select-none font-mono tabular-nums text-right',
                    kind === 'hour' &&
                      'left-0 text-xs font-medium text-foreground tracking-tight',
                    kind === 'half' && 'left-0 text-[11px] text-foreground/70',
                    kind === 'quarter' && 'left-0 text-[10px] text-muted-foreground/70',
                    kind === 'five' && 'left-0 text-[10px] text-muted-foreground/45',
                  )}
                  style={{ top: minutesFromStart * pxPerMin }}
                >
                  {label}
                </div>
              ))}
            </div>
          </div>

          {providers.map((provider) => (
            <ProviderColumn
              key={provider.id}
              provider={provider}
              appointments={byProvider.get(provider.id) ?? []}
              timezone={timezone}
              date={date}
              pxPerMin={pxPerMin}
              hourHeight={hourHeight}
              dayHeight={dayHeight}
              widthPx={colPx}
              isNarrow={isNarrow}
              categories={categories ?? []}
              hours={hoursArray}
              dayStartHour={dayStartHour}
              dayEndHour={dayEndHour}
              reschedulingApptId={rescheduling?.appointmentId ?? null}
              onRescheduleContextMenu={openContextMenu}
              onCreateContextMenu={openCreateMenu}
            />
          ))}

          <FillerColumn dayHeight={dayHeight} hourHeight={hourHeight} hours={hoursArray} />
        </div>
      </div>

      <DragOverlay dropAnimation={{ duration: 160, easing: 'cubic-bezier(0.2, 0, 0, 1)' }}>
        {activeAppt ? (
          <DragOverlayBlock
            appointment={activeAppt}
            timezone={timezone}
            pxPerMin={pxPerMin}
            widthPx={colPx}
            isNarrow={isNarrow}
          />
        ) : null}
      </DragOverlay>

      {contextMenu ? (
        <RescheduleContextMenu
          menu={contextMenu}
          onConfirm={() => void commitReschedule()}
          onCancel={closeContextMenu}
        />
      ) : null}

      {createMenu ? (
        <CreateAppointmentContextMenu
          menu={createMenu}
          onConfirm={commitCreateAppointment}
          onCancel={closeContextMenu}
        />
      ) : null}
    </DndContext>
  );
}

// ── Create-appointment context menu (right-click empty slot) ─────────────

/**
 * Small floating menu shown when the user right-clicks empty space in
 * a provider column outside a reschedule flow. Confirming opens the New
 * Appointment sheet pre-filled with the chosen slot. Same anchoring +
 * dismiss behavior as `RescheduleContextMenu`.
 */
function CreateAppointmentContextMenu({
  menu,
  onConfirm,
  onCancel,
}: {
  menu: CreateMenu;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <div
      style={{
        top: Math.min(menu.clientY, window.innerHeight - 120),
        left: Math.min(menu.clientX, window.innerWidth - 240),
      }}
      className="fixed z-50 w-56 rounded-md border bg-popover text-popover-foreground shadow-lg ring-1 ring-foreground/10 p-1 text-sm"
      onClick={(e) => e.stopPropagation()}
      onContextMenu={(e) => e.preventDefault()}
      role="menu"
    >
      <p className="px-2.5 py-1.5 text-[11px] uppercase tracking-wide text-muted-foreground">
        Slot · {menu.slotLabel}
      </p>
      <button
        type="button"
        role="menuitem"
        onClick={onConfirm}
        className="w-full text-left px-2.5 py-1.5 rounded text-sm hover:bg-accent hover:text-accent-foreground transition-colors"
      >
        Create new appointment here
      </button>
      <button
        type="button"
        role="menuitem"
        onClick={onCancel}
        className="w-full text-left px-2.5 py-1.5 rounded text-sm text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
      >
        Cancel
      </button>
    </div>
  );
}

// ── Reschedule context menu (right-click drop target) ────────────────────

function RescheduleContextMenu({
  menu,
  onConfirm,
  onCancel,
}: {
  menu: RescheduleMenu;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <div
      // Clamp X/Y so the menu doesn't render off-screen near the right
      // or bottom edges. Width/height are approximate; close enough for
      // a small two-button menu.
      style={{
        top: Math.min(menu.clientY, window.innerHeight - 120),
        left: Math.min(menu.clientX, window.innerWidth - 240),
      }}
      className="fixed z-50 w-56 rounded-md border bg-popover text-popover-foreground shadow-lg ring-1 ring-foreground/10 p-1 text-sm"
      // Stop the global click listener (closes the menu) from firing when
      // the user clicks one of these buttons before the handler runs.
      onClick={(e) => e.stopPropagation()}
      onContextMenu={(e) => e.preventDefault()}
      role="menu"
    >
      <p className="px-2.5 py-1.5 text-[11px] uppercase tracking-wide text-muted-foreground">
        Reschedule to {menu.slotLabel}
      </p>
      <button
        type="button"
        role="menuitem"
        onClick={onConfirm}
        className="w-full text-left px-2.5 py-1.5 rounded text-sm hover:bg-accent hover:text-accent-foreground transition-colors"
      >
        Reschedule appointment here
      </button>
      <button
        type="button"
        role="menuitem"
        onClick={onCancel}
        className="w-full text-left px-2.5 py-1.5 rounded text-sm text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
      >
        Cancel reschedule
      </button>
    </div>
  );
}

// ── Provider column (droppable) ──────────────────────────────────────────

function ProviderColumn({
  provider,
  appointments,
  timezone,
  date,
  pxPerMin,
  hourHeight,
  dayHeight,
  widthPx,
  isNarrow,
  categories,
  hours,
  dayStartHour,
  dayEndHour,
  reschedulingApptId,
  onRescheduleContextMenu,
  onCreateContextMenu,
}: {
  provider: Membership;
  appointments: Appointment[];
  timezone: string;
  date: string;
  pxPerMin: number;
  hourHeight: number;
  dayHeight: number;
  widthPx: number;
  isNarrow: boolean;
  categories: ReturnType<typeof useServiceCategories>['data'];
  /** Hour list for the time grid (passed in so column + filler share
   *  the same window from tenant settings). */
  hours: number[];
  /** First / last visible hour — passed down so AppointmentBlock can
   *  position blocks against the right window via `positionFor`. */
  dayStartHour: number;
  dayEndHour: number;
  /** Appointment id currently being rescheduled, or null. Forwarded to
   *  `AppointmentBlock` so the source can render with a faded "moving"
   *  visual treatment and a burgundy ring. */
  reschedulingApptId: number | null;
  /** Right-click handler invoked when the user right-clicks empty
   *  space *during* a reschedule flow. Opens the "Reschedule appointment
   *  here / Cancel" menu at the click coords. */
  onRescheduleContextMenu: (params: {
    clientX: number;
    clientY: number;
    providerId: number;
    yInColumn: number;
  }) => void;
  /** Right-click handler invoked when the user right-clicks empty
   *  space *outside* a reschedule flow. Opens the "Create appointment
   *  here / Cancel" menu at the click coords. */
  onCreateContextMenu: (params: {
    clientX: number;
    clientY: number;
    providerId: number;
    yInColumn: number;
  }) => void;
}) {
  const dropData: ColumnDropData = { type: 'column', provider };
  const { setNodeRef, isOver } = useDroppable({
    id: `column-${provider.id}`,
    data: dropData,
  });

  // Compute drop-target eligibility while a drag is active so the column can
  // tint warningly when the dragged service can't be performed by this provider.
  const { active } = useDndContext();
  const activeAppt = active?.data.current as AppointmentDragData | undefined;
  let eligibility: EligibilityResult = { ok: true, reason: '' };
  let isAnotherProvider = false;
  if (activeAppt?.type === 'appointment') {
    const appt = activeAppt.appointment;
    isAnotherProvider = appt.provider.id !== provider.id;
    if (isAnotherProvider) {
      eligibility = isProviderEligible(
        { category: appt.service.category_id ? { id: appt.service.category_id } : null },
        provider,
        categories ?? [],
      );
    }
  }

  const isDropTarget = isOver && isAnotherProvider;
  const isInvalidTarget = isDropTarget && !eligibility.ok;

  // Lane assignments for overlapping appointments (side-by-side layout
  // when a provider is double-booked). Memoized on the appointments
  // array so the math only re-runs when the day's bookings change.
  const lanesById = useMemo(() => computeLanesForProvider(appointments), [appointments]);

  return (
    <div
      className="flex flex-col shrink-0 border-r last:border-r-0"
      style={{ width: widthPx }}
    >
      <div
        className={cn(
          'h-16 border-b bg-card sticky top-0 z-10 flex items-center gap-3',
          isNarrow ? 'px-2' : 'px-4',
        )}
      >
        <InitialsAvatar name={membershipName(provider)} size="sm" />
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium truncate">{membershipName(provider)}</p>
          {provider.job_title_name ? (
            <p className="text-[11px] text-muted-foreground truncate">
              {provider.job_title_name}
            </p>
          ) : null}
        </div>
      </div>

      <div
        ref={setNodeRef}
        className={cn(
          'relative flex-1 transition-colors',
          isDropTarget && eligibility.ok && 'bg-accent/[0.07]',
          isInvalidTarget && 'bg-destructive/5',
          // Subtle ring while in rescheduling mode so it's clear that
          // every column is a valid right-click target.
          reschedulingApptId !== null && 'bg-accent/[0.04] cursor-context-menu',
        )}
        style={{ height: dayHeight }}
        title={isInvalidTarget ? eligibility.reason : undefined}
        onContextMenu={(e) => {
          // Right-click anywhere in the column — only reacts to empty
          // space (an appointment block's <button> is the target when
          // clicked; TimeGridLines has pointer-events-none so empty
          // space's target is this div). Routes to either the
          // reschedule menu (if rescheduling is in progress) or the
          // create-appointment confirmation menu.
          if (e.target !== e.currentTarget) return;
          e.preventDefault();
          const rect = e.currentTarget.getBoundingClientRect();
          const params = {
            clientX: e.clientX,
            clientY: e.clientY,
            providerId: provider.id,
            yInColumn: e.clientY - rect.top,
          };
          if (reschedulingApptId !== null) {
            onRescheduleContextMenu(params);
          } else {
            onCreateContextMenu(params);
          }
        }}
      >
        <TimeGridLines hourHeight={hourHeight} hours={hours} />
        {/* Working-hours overlay: dims time outside this provider's
            schedule for the current weekday. Renders ABOVE the time
            grid lines but BELOW appointment blocks (which need to
            stay visible even if booked outside working hours — the
            user can still see "Sarah is booked here despite being
            off"). `pointer-events-none` so the column's own
            onContextMenu still triggers on right-click. */}
        <WorkingHoursOverlay
          schedule={provider.schedule_for_location ?? null}
          date={date}
          dayStartHour={dayStartHour}
          dayEndHour={dayEndHour}
          pxPerMin={pxPerMin}
          dayHeight={dayHeight}
        />
        {appointments.map((appt) => {
          const laneInfo = lanesById.get(appt.id) ?? { lane: 0, lanesInCluster: 1 };
          return (
            <AppointmentBlock
              key={appt.id}
              appointment={appt}
              timezone={timezone}
              date={date}
              pxPerMin={pxPerMin}
              isNarrow={isNarrow}
              isReschedulingSource={appt.id === reschedulingApptId}
              lane={laneInfo.lane}
              lanesInCluster={laneInfo.lanesInCluster}
              dayStartHour={dayStartHour}
              dayEndHour={dayEndHour}
            />
          );
        })}

        {/* Subtle X overlay on the entire column when this drop would be invalid */}
        {isInvalidTarget ? (
          <div className="absolute inset-x-0 top-2 px-3 pointer-events-none">
            <div className="rounded-md border border-destructive/40 bg-destructive/10 text-destructive text-[11px] px-2 py-1">
              {eligibility.reason}
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}

// ── Filler column (extends grid to right edge) ───────────────────────────

function FillerColumn({
  dayHeight,
  hourHeight,
  hours,
}: {
  dayHeight: number;
  hourHeight: number;
  hours: number[];
}) {
  return (
    <div className="flex flex-col flex-1 min-w-0 bg-muted/40">
      <div className="h-16 border-b border-border/60" aria-hidden />
      <div className="relative flex-1" style={{ height: dayHeight }} aria-hidden>
        <TimeGridLines hourHeight={hourHeight} hours={hours} />
      </div>
    </div>
  );
}

// ── Time grid (hour / half / quarter / 5-min ticks) ──────────────────────

function TimeGridLines({ hourHeight, hours }: { hourHeight: number; hours: number[] }) {
  const totalSegments = hours.length - 1;
  const ticks: React.ReactNode[] = [];
  for (let h = 0; h < totalSegments; h++) {
    for (let m = 5; m < 60; m += 5) {
      const top = h * hourHeight + (m / 60) * hourHeight;
      const isHalf = m === 30;
      const isQuarter = m === 15 || m === 45;
      ticks.push(
        <div
          key={`h${h}-m${m}`}
          className={cn(
            'absolute left-0 right-0 border-t',
            isHalf
              ? 'border-dashed border-border/45'
              : isQuarter
                ? 'border-dotted border-border/30'
                : 'border-border/15',
          )}
          style={{ top }}
        />,
      );
    }
  }

  return (
    <div className="absolute inset-0 pointer-events-none">
      {hours.map((hour, i) => (
        <div
          key={`hour-${hour}`}
          className="absolute left-0 right-0 border-t border-border"
          style={{ top: i * hourHeight }}
        />
      ))}
      {ticks}
    </div>
  );
}

// ── Appointment block (draggable + popover trigger) ──────────────────────

function AppointmentBlock({
  appointment,
  timezone,
  date,
  pxPerMin,
  isNarrow,
  isReschedulingSource,
  lane,
  lanesInCluster,
  dayStartHour,
  dayEndHour,
}: {
  appointment: Appointment;
  timezone: string;
  date: string;
  pxPerMin: number;
  isNarrow: boolean;
  /** True when this block is the appointment currently being moved via
   *  the right-click reschedule flow. Renders faded with a burgundy
   *  ring and disables drag (the user committed to the right-click path). */
  isReschedulingSource: boolean;
  /** Side-by-side lane index within an overlap cluster (0-based). */
  lane: number;
  /** Total number of lanes in this cluster — divisor for the block width. */
  lanesInCluster: number;
  /** Day-window bounds (from tenant business hours) — passed to
   *  `positionFor` so the block clamps to the right window. */
  dayStartHour: number;
  dayEndHour: number;
}) {
  const { topPx, heightPx, fitsInWindow } = positionFor(
    appointment,
    timezone,
    date,
    pxPerMin,
    dayStartHour,
    dayEndHour,
  );

  const isTerminal = TERMINAL_STATUSES.has(appointment.status);

  const dragData: AppointmentDragData = { type: 'appointment', appointment };
  const { setNodeRef, attributes, listeners, isDragging, transform } = useDraggable({
    id: `appt-${appointment.id}`,
    data: dragData,
    // Disable drag while this block is the rescheduling source — the
    // user picked the right-click flow, so don't let an accidental drag
    // create a competing intent.
    disabled: isTerminal || isReschedulingSource,
  });

  if (!fitsInWindow) return null;

  const color = appointment.service.category_color ?? 'hsl(220 9% 46%)';
  const cancelled = appointment.status === 'cancelled' || appointment.status === 'no_show';

  const tightVertical = heightPx < 50;
  const tight = tightVertical || isNarrow;
  const veryTight = tightVertical && isNarrow;

  const timeText = veryTight
    ? formatStartCompact(appointment.start_time, timezone)
    : formatTimeRange(appointment, timezone);

  // While dragging, hide the original block — DragOverlay renders the floating
  // clone. Use opacity instead of display:none so the popover trigger ref doesn't
  // unmount mid-interaction.
  const transformStyle = transform
    ? `translate3d(${transform.x}px, ${transform.y}px, 0)`
    : undefined;

  // Side-by-side lane positioning. Single booking gets the full column
  // width minus a 4 px outer inset on each side (matches the original
  // look). Multi-booking divides the column into equal lanes with a
  // small visual gap so adjacent blocks don't touch.
  const SIDE_INSET_PX = 4;
  const LANE_GAP_PX = 2;
  const widthPercent = 100 / lanesInCluster;
  const isShared = lanesInCluster > 1;
  const horizontalStyle: React.CSSProperties = isShared
    ? {
        // 2px from the lane's left edge, 2px from the lane's right edge
        // → 4px gap between adjacent lanes total. Outer column edges
        // also get a 2px breath, which reads consistent with the gap.
        left: `calc(${lane * widthPercent}% + ${LANE_GAP_PX}px)`,
        width: `calc(${widthPercent}% - ${LANE_GAP_PX * 2}px)`,
      }
    : { left: `${SIDE_INSET_PX}px`, right: `${SIDE_INSET_PX}px` };

  const trigger = (
    <button
      ref={setNodeRef}
      type="button"
      {...attributes}
      {...listeners}
      className={cn(
        'absolute rounded-md text-left transition-shadow shadow-xs',
        'border bg-card hover:shadow-md focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none',
        cancelled && 'opacity-60',
        isDragging && 'opacity-0',
        // Source-of-reschedule treatment: faded with a burgundy ring so
        // it's obvious which appointment is "in flight."
        isReschedulingSource && 'opacity-50 ring-2 ring-accent ring-offset-1 cursor-not-allowed',
        !isTerminal && !isReschedulingSource && 'cursor-grab active:cursor-grabbing',
      )}
      style={{
        top: `${topPx}px`,
        height: `${heightPx}px`,
        borderLeft: `3px solid ${color}`,
        backgroundColor: cancelled ? 'transparent' : `color-mix(in oklch, ${color} 6%, var(--card))`,
        transform: transformStyle,
        ...horizontalStyle,
      }}
      aria-label={`${appointment.customer.full_name} · ${appointment.service.name} · ${formatTimeRange(appointment, timezone)}`}
      title={`${appointment.customer.full_name} · ${appointment.service.name} · ${formatTimeRange(appointment, timezone)}`}
    >
      <div className={cn('flex items-start gap-1.5', tight ? 'p-1.5' : 'p-2')}>
        <StatusDot status={appointment.status} />
        <div className="min-w-0 flex-1">
          <p
            className={cn(
              'font-mono tabular-nums text-muted-foreground truncate',
              tight ? 'text-[10px]' : 'text-xs',
            )}
          >
            {timeText}
          </p>
          <p
            className={cn(
              'font-medium truncate',
              cancelled && 'line-through',
              tight ? 'text-xs' : 'text-sm',
            )}
            style={{ color }}
          >
            {appointment.service.name}
          </p>
          {!tightVertical ? (
            <p
              className={cn(
                'text-foreground/80 truncate',
                isNarrow ? 'text-[11px]' : 'text-xs',
              )}
            >
              {appointment.customer.full_name}
            </p>
          ) : null}
        </div>
      </div>
    </button>
  );

  return <AppointmentPopover appointment={appointment} timezone={timezone} trigger={trigger} />;
}

// ── Drag overlay block (floats with cursor while dragging) ───────────────

function DragOverlayBlock({
  appointment,
  timezone,
  pxPerMin,
  widthPx,
  isNarrow,
}: {
  appointment: Appointment;
  timezone: string;
  pxPerMin: number;
  widthPx: number;
  isNarrow: boolean;
}) {
  const heightPx = Math.max(24, appointment.duration_minutes * pxPerMin);
  const color = appointment.service.category_color ?? 'hsl(220 9% 46%)';
  const tight = heightPx < 50 || isNarrow;

  return (
    <div
      className="rounded-md border bg-card shadow-lg ring-1 ring-foreground/10"
      style={{
        width: widthPx - 8, // match the in-column block width (left/right inset 1 = 8 total)
        height: heightPx,
        borderLeft: `3px solid ${color}`,
        backgroundColor: `color-mix(in oklch, ${color} 8%, var(--card))`,
      }}
    >
      <div className={cn('flex items-start gap-1.5', tight ? 'p-1.5' : 'p-2')}>
        <StatusDot status={appointment.status} />
        <div className="min-w-0 flex-1">
          <p
            className={cn(
              'font-mono tabular-nums text-muted-foreground truncate',
              tight ? 'text-[10px]' : 'text-xs',
            )}
          >
            {formatTimeRange(appointment, timezone)}
          </p>
          <p
            className={cn('font-medium truncate', tight ? 'text-xs' : 'text-sm')}
            style={{ color }}
          >
            {appointment.service.name}
          </p>
          {heightPx >= 50 ? (
            <p className="text-xs text-foreground/80 truncate">
              {appointment.customer.full_name}
            </p>
          ) : null}
        </div>
      </div>
    </div>
  );
}

// ── Status dot + empty state ─────────────────────────────────────────────

function StatusDot({ status }: { status: AppointmentStatus }) {
  const cls =
    status === 'completed'
      ? 'bg-emerald-500'
      : status === 'checked_in'
        ? 'bg-amber-500'
        : status === 'confirmed'
          ? 'bg-sky-500'
          : status === 'no_show'
            ? 'bg-red-500'
            : status === 'cancelled'
              ? 'bg-muted-foreground/30'
              : 'bg-muted-foreground/60';
  return (
    <span
      className={cn('shrink-0 mt-1 size-1.5 rounded-full', cls)}
      aria-label={STATUS_LABELS[status]}
      title={STATUS_LABELS[status]}
    />
  );
}

function EmptyProvidersState() {
  return (
    <div className="flex-1 flex flex-col items-center justify-center text-center px-6 py-20">
      <div className="inline-flex size-12 items-center justify-center rounded-full bg-muted text-muted-foreground mb-4">
        <Clock className="size-5" />
      </div>
      <h3 className="font-serif text-xl font-semibold tracking-tight">No bookable staff</h3>
      <p className="text-sm text-muted-foreground mt-1.5 max-w-sm">
        The calendar fills in once at least one staff member is assigned to this location and
        marked bookable. Visit Staff → Schedule to assign staff and set their hours.
      </p>
    </div>
  );
}

// ── Working-hours overlay ─────────────────────────────────────────────
//
// Dims the column's time outside the provider's working hours for the
// current weekday. Uses absolutely-positioned divs sized + offset by
// `pxPerMin` to match the time grid. Reads from the schedule the
// bookable-memberships endpoint embedded per provider.
//
// Three states:
//   - schedule = null (provider has no schedule set)        → no overlay
//   - day's blocks = [] (explicitly off that day)           → overlay full day
//   - day has blocks                                        → overlay gaps
//
// Booked appointments stay visible even outside working hours so the
// operator can see "Sarah is booked here despite being off." The
// overlay sits above TimeGridLines but below appointment blocks.

function WorkingHoursOverlay({
  schedule,
  date,
  dayStartHour,
  dayEndHour,
  pxPerMin,
  dayHeight,
}: {
  /** Per-weekday blocks, or null if the provider has no schedule. */
  schedule: Membership['schedule_for_location'];
  /** YYYY-MM-DD — used to derive the weekday key. */
  date: string;
  dayStartHour: number;
  dayEndHour: number;
  pxPerMin: number;
  dayHeight: number;
}) {
  // No schedule set → no overlay (provider treated as available all day).
  if (schedule == null) return null;

  const weekday: Weekday = weekdayFromDate(parseLocalDate(date));
  // Type-safe lookup with fallback to empty in case the API returns a
  // partial dict (shouldn't happen — backend serializer fills all 7
  // weekday keys, but defending against drift).
  const blocks: ScheduleBlock[] = (schedule as Record<string, ScheduleBlock[]>)[weekday] ?? [];

  // Compute the non-working segments within the visible day window.
  const dayStartMin = dayStartHour * 60;
  const dayEndMin = dayEndHour * 60;
  const offSegments: Array<{ startMin: number; endMin: number }> = [];

  if (blocks.length === 0) {
    // Whole visible window is off.
    offSegments.push({ startMin: dayStartMin, endMin: dayEndMin });
  } else {
    // Sort + clip blocks to the visible window, then invert to get
    // the off-segments. Using sorted copies because the API doesn't
    // guarantee order (though the backend's normalize step does).
    const sortedBlocks = [...blocks]
      .map((b) => ({
        startMin: Math.max(parseHHMMToMinutes(b.start), dayStartMin),
        endMin: Math.min(parseHHMMToMinutes(b.end), dayEndMin),
      }))
      .filter((b) => b.endMin > b.startMin)
      .sort((a, b) => a.startMin - b.startMin);

    let cursor = dayStartMin;
    for (const block of sortedBlocks) {
      if (block.startMin > cursor) {
        offSegments.push({ startMin: cursor, endMin: block.startMin });
      }
      cursor = Math.max(cursor, block.endMin);
    }
    if (cursor < dayEndMin) {
      offSegments.push({ startMin: cursor, endMin: dayEndMin });
    }
  }

  if (offSegments.length === 0) return null;

  return (
    <div className="absolute inset-x-0 top-0 pointer-events-none" style={{ height: dayHeight }} aria-hidden>
      {offSegments.map((seg, i) => {
        const top = (seg.startMin - dayStartMin) * pxPerMin;
        const height = (seg.endMin - seg.startMin) * pxPerMin;
        return (
          <div
            key={i}
            className="absolute inset-x-0 bg-muted-foreground/[0.07]"
            style={{ top, height }}
            // Diagonal hatch via inline background for the off pattern —
            // muted enough to read as "unavailable" without competing
            // with appointment blocks for visual weight.
          />
        );
      })}
    </div>
  );
}

/** Parse YYYY-MM-DD as a local-time Date (midnight in the browser's
 *  zone). Used purely to derive the weekday key — the date string
 *  itself is already location-timezone-interpreted upstream. */
function parseLocalDate(dateStr: string): Date {
  const [y, m, d] = dateStr.split('-').map(Number);
  return new Date(y, (m ?? 1) - 1, d ?? 1);
}

// ── Layout math + formatters ─────────────────────────────────────────────

function positionFor(
  appt: Appointment,
  timezone: string,
  date: string,
  pxPerMin: number,
  dayStartHour: number,
  dayEndHour: number,
) {
  const startMin = minutesIntoLocalDay(appt.start_time, timezone);
  const endMin = minutesIntoLocalDay(appt.end_time, timezone);
  const startBoundary = dayStartHour * 60;
  const endBoundary = dayEndHour * 60;

  const visibleStart = Math.max(startMin, startBoundary);
  const visibleEnd = Math.min(endMin, endBoundary);
  if (visibleEnd <= visibleStart) {
    return { topPx: 0, heightPx: 0, fitsInWindow: false };
  }

  // `date` reserved for multi-day clipping when the caller eventually fetches windows.
  void date;
  return {
    topPx: (visibleStart - startBoundary) * pxPerMin,
    heightPx: Math.max(24, (visibleEnd - visibleStart) * pxPerMin),
    fitsInWindow: true,
  };
}

/**
 * Compute side-by-side lane assignments for overlapping appointments
 * within a single provider's column.
 *
 * Algorithm (the standard pattern used by Google Calendar / Boulevard /
 * Zenoti):
 *
 *   1. Sort appointments by start time (ties broken by end time).
 *   2. Walk them in order, grouping into "clusters" — sets of
 *      appointments that transitively overlap. Two appts that share a
 *      lane (don't overlap directly) but both overlap a third must end
 *      up in the same cluster so they all use the same lane count
 *      (otherwise the visual width jumps mid-row, which looks chaotic).
 *   3. Within each cluster, greedily assign the lowest-index lane that
 *      doesn't conflict with what's already in that lane. New lane if
 *      none free.
 *   4. Stamp every appt in the cluster with the cluster's final
 *      lane-count so the renderer can compute `width = 100% / N`.
 *
 * Cancelled / no-show appointments are NOT excluded — they still take
 * up their original time slot, just rendered dimmed. Hiding them via
 * the "Hide cancelled" filter happens upstream; by the time
 * `appointments` reaches here, anything filtered is already gone.
 */
interface LaneInfo {
  lane: number;
  /** Total number of side-by-side lanes in this appointment's overlap
   *  cluster — the divisor for the rendered block's width. */
  lanesInCluster: number;
}

function computeLanesForProvider(appts: Appointment[]): Map<number, LaneInfo> {
  const result = new Map<number, LaneInfo>();
  if (appts.length === 0) return result;

  const sorted = [...appts].sort((a, b) => {
    const sd = new Date(a.start_time).getTime() - new Date(b.start_time).getTime();
    if (sd !== 0) return sd;
    return new Date(a.end_time).getTime() - new Date(b.end_time).getTime();
  });

  let cluster: Appointment[] = [];
  let clusterEndMs = 0;

  const flushCluster = () => {
    if (cluster.length === 0) return;
    assignLanesInCluster(cluster, result);
    cluster = [];
    clusterEndMs = 0;
  };

  for (const appt of sorted) {
    const startMs = new Date(appt.start_time).getTime();
    const endMs = new Date(appt.end_time).getTime();
    if (cluster.length > 0 && startMs >= clusterEndMs) {
      // Gap — close out the previous cluster.
      flushCluster();
    }
    cluster.push(appt);
    clusterEndMs = Math.max(clusterEndMs, endMs);
  }
  flushCluster();

  return result;
}

function assignLanesInCluster(
  cluster: Appointment[],
  result: Map<number, LaneInfo>,
) {
  const laneEnds: number[] = []; // index = lane, value = endMs of latest appt in that lane
  for (const appt of cluster) {
    const startMs = new Date(appt.start_time).getTime();
    const endMs = new Date(appt.end_time).getTime();
    let assigned = -1;
    for (let i = 0; i < laneEnds.length; i += 1) {
      if (laneEnds[i] <= startMs) {
        assigned = i;
        laneEnds[i] = endMs;
        break;
      }
    }
    if (assigned === -1) {
      assigned = laneEnds.length;
      laneEnds.push(endMs);
    }
    // Record the lane now; lanesInCluster gets stamped after the loop
    // (since we don't know the final width until the cluster's settled).
    result.set(appt.id, { lane: assigned, lanesInCluster: 0 });
  }
  const lanesInCluster = laneEnds.length;
  for (const appt of cluster) {
    const info = result.get(appt.id)!;
    result.set(appt.id, { lane: info.lane, lanesInCluster });
  }
}

/** Minutes since local-midnight in the given IANA timezone. */
function minutesIntoLocalDay(iso: string, timezone: string): number {
  const d = new Date(iso);
  const fmt = new Intl.DateTimeFormat('en-US', {
    timeZone: timezone,
    hour12: false,
    hour: '2-digit',
    minute: '2-digit',
  });
  const parts = fmt.formatToParts(d);
  const hour = Number(parts.find((p) => p.type === 'hour')?.value ?? 0);
  const minute = Number(parts.find((p) => p.type === 'minute')?.value ?? 0);
  return ((hour % 24) * 60) + minute;
}

/**
 * Build a UTC ISO string for `<date>` at `<hours>:<minutes>` *as
 * interpreted in `<timezone>`*. The IANA-aware inverse of
 * `minutesIntoLocalDay`.
 *
 * JS doesn't have native "local time + IANA TZ → UTC" — so we use the
 * standard offset-derivation trick: build a naive UTC date with the
 * desired wall-clock, ask `Intl.DateTimeFormat` to render it back in
 * the target TZ, and use the difference between the two as the offset.
 *
 * This is the right pattern for fixed-offset *and* DST-bearing
 * timezones, and matches what date-fns-tz / luxon do internally.
 */
function localDateTimeToUtcIso(
  date: string,
  hours: number,
  minutes: number,
  timezone: string,
): string {
  const naive = new Date(
    `${date}T${pad2(hours)}:${pad2(minutes)}:00Z`,
  );
  const fmt = new Intl.DateTimeFormat('en-US', {
    timeZone: timezone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  });
  const parts: Record<string, string> = {};
  for (const p of fmt.formatToParts(naive)) parts[p.type] = p.value;
  const formattedAsUtcMs = Date.UTC(
    Number(parts.year),
    Number(parts.month) - 1,
    Number(parts.day),
    Number(parts.hour) % 24, // Intl can return "24" for midnight in some locales
    Number(parts.minute),
    Number(parts.second),
  );
  const offsetMs = formattedAsUtcMs - naive.getTime();
  return new Date(naive.getTime() - offsetMs).toISOString();
}

function pad2(n: number): string {
  return String(n).padStart(2, '0');
}

/** "10:00 AM (60m)" — concise label for the reschedule context menu. */
function formatSlotLabel(hours: number, minutes: number, durationMinutes: number): string {
  return `${formatStartLabel(hours, minutes)} (${durationMinutes}m)`;
}

/** "10:00 AM" — wall-clock without the duration parenthetical. Used in
 *  the "Create appointment here" menu (no service picked yet, so no
 *  duration to display). */
function formatStartLabel(hours: number, minutes: number): string {
  const d = new Date();
  d.setHours(hours, minutes, 0, 0);
  return d.toLocaleTimeString('en-US', {
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
  });
}

type TimeLabelKind = 'hour' | 'half' | 'quarter' | 'five';

interface TimeLabelEntry {
  minutesFromStart: number;
  kind: TimeLabelKind;
  label: string;
}

function buildTimeAxisLabels(
  includeFive: boolean,
  hours: number[],
  dayStartHour: number,
): TimeLabelEntry[] {
  const entries: TimeLabelEntry[] = [];
  const totalSegments = hours.length - 1;

  for (let h = 0; h < totalSegments; h++) {
    entries.push({
      minutesFromStart: h * 60,
      kind: 'hour',
      label: formatHourLabel(dayStartHour + h),
    });

    for (let m = 5; m < 60; m += 5) {
      const isHalf = m === 30;
      const isQuarter = m === 15 || m === 45;
      if (!includeFive && !isHalf && !isQuarter) continue;

      entries.push({
        minutesFromStart: h * 60 + m,
        kind: isHalf ? 'half' : isQuarter ? 'quarter' : 'five',
        label: `:${String(m).padStart(2, '0')}`,
      });
    }
  }

  entries.push({
    minutesFromStart: totalSegments * 60,
    kind: 'hour',
    label: formatHourLabel(dayStartHour + totalSegments),
  });

  return entries;
}

function formatHourLabel(hour: number): string {
  const d = new Date();
  d.setHours(hour, 0, 0, 0);
  return d.toLocaleTimeString('en-US', {
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
  });
}

function formatTimeRange(appt: Appointment, timezone: string): string {
  const opts: Intl.DateTimeFormatOptions = {
    timeZone: timezone,
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
  };
  const start = new Date(appt.start_time).toLocaleTimeString('en-US', opts);
  const end = new Date(appt.end_time).toLocaleTimeString('en-US', opts);
  return `${start} – ${end}`;
}

function formatStartCompact(iso: string, timezone: string): string {
  const opts: Intl.DateTimeFormatOptions = {
    timeZone: timezone,
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
  };
  return new Date(iso)
    .toLocaleTimeString('en-US', opts)
    .replace(' AM', 'a')
    .replace(' PM', 'p');
}

// ── Optimistic-update helpers ────────────────────────────────────────────

function buildProviderSummary(
  providers: Membership[],
  newProviderId: number,
  fallback: Appointment['provider'],
): Appointment['provider'] {
  const m = providers.find((p) => p.id === newProviderId);
  if (!m) return fallback;
  return {
    id: m.id,
    user_email: m.user_email,
    user_first_name: m.user_first_name,
    user_last_name: m.user_last_name,
    job_title_id: m.job_title_id,
    job_title_name: m.job_title_name,
    role: m.role,
    is_bookable: m.is_bookable,
  };
}
