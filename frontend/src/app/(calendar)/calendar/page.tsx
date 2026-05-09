/**
 * `/calendar` — booking calendar workspace.
 *
 * Owns the focus date, view mode, display mode, row height, column width, and
 * the right-rail active tool. Date / view / provider filter / active tool live
 * in URL state (`?date=&view=&provider=&tool=`) so the page is deep-linkable
 * and reload-safe. Row height, column width, and hide-cancelled live in
 * localStorage as personal preferences.
 *
 * Read-only this session for the calendar interactions themselves; clicking an
 * appointment surfaces a toast preview. Tool panels: View Settings + Price
 * Check are functional today. The remaining six are explicit "coming with
 * Phase X" placeholders.
 */

'use client';

import { CalendarClock, X } from 'lucide-react';
import { useRouter, useSearchParams } from 'next/navigation';
import { useCallback, useEffect, useMemo, useState } from 'react';

import { CalendarFilterBar, type DisplayMode } from '../_components/calendar-filter-bar';
import { CalendarTopBar } from '../_components/calendar-top-bar';
import {
  DayView,
  PX_PER_MIN_DEFAULT,
  PX_PER_MIN_MIN,
  PX_PER_MIN_MAX,
  PX_PER_MIN_STEP,
  COLUMN_PX_DEFAULT,
  COLUMN_PX_MIN,
  COLUMN_PX_MAX,
  COLUMN_PX_STEP,
} from '../_components/day-view';
import { DayStatsFooter } from '../_components/day-stats-footer';
import { ListView } from '../_components/list-view';
import { NewAppointmentSheet } from '../_components/new-appointment-sheet';
import { RightToolRail, TOOLS, type CalendarTool } from '../_components/right-tool-rail';
import { ToolPanel } from '../_components/tool-panel';
import { useAppointment, useAppointmentsForDate } from '@/lib/appointments';
import { useActiveLocation } from '@/lib/locations';
import { useBookableMemberships } from '@/lib/memberships';
import { tenantHourFromTime } from '@/lib/tenant';

const DEFAULT_TIMEZONE = 'America/New_York';
const PX_PER_MIN_KEY = 'lume_calendar_px_per_min';
const COLUMN_PX_KEY = 'lume_calendar_column_px';
const HIDE_CANCELLED_KEY = 'lume_calendar_hide_cancelled';

const TOOL_IDS = new Set(TOOLS.map((t) => t.id));

export default function CalendarPage() {
  const router = useRouter();
  const searchParams = useSearchParams();

  // Calendar scoping is per-location (a multi-site business may span
  // timezones; each site has its own business hours). The active
  // location is resolved by `useActiveLocation()` which mirrors the
  // backend `LocationMiddleware` (cookie → tenant default → none).
  // Until it loads we fall back to DEFAULT_TIMEZONE so the day-window
  // calculation has *some* timezone — with no value it would resolve
  // to UTC and shift "today" by hours, which would render the wrong
  // day on first paint.
  const { location: activeLocation } = useActiveLocation();
  const tenantTimezone = activeLocation?.timezone || DEFAULT_TIMEZONE;

  // ── URL-driven state ────────────────────────────────────────────────────
  const requestedDate = searchParams.get('date');
  const date = requestedDate && /^\d{4}-\d{2}-\d{2}$/.test(requestedDate)
    ? requestedDate
    : todayInTimezone(tenantTimezone);
  const providerFilter = searchParams.get('provider') ?? '';
  const toolParam = searchParams.get('tool');
  const activeTool: CalendarTool | null =
    toolParam && TOOL_IDS.has(toolParam as CalendarTool)
      ? (toolParam as CalendarTool)
      : null;

  // Rescheduling mode is URL-driven (?rescheduling=ID&duration=MIN) so the
  // intent persists when the user navigates the calendar to a different
  // day to find a slot. The popover sets it; the banner + DayView read it.
  const reschedulingIdRaw = Number(searchParams.get('rescheduling'));
  const reschedulingId = Number.isFinite(reschedulingIdRaw) && reschedulingIdRaw > 0
    ? reschedulingIdRaw
    : null;
  const reschedulingDurationRaw = Number(searchParams.get('duration'));
  const reschedulingDuration =
    Number.isFinite(reschedulingDurationRaw) && reschedulingDurationRaw > 0
      ? reschedulingDurationRaw
      : null;

  // ── Component-local state (persisted preferences) ───────────────────────
  const [view, setView] = useState<'day' | 'week' | 'month'>('day');
  const [displayMode, setDisplayMode] = useState<DisplayMode>('calendar');
  const [pxPerMin, setPxPerMin] = useState<number>(PX_PER_MIN_DEFAULT);
  const [columnWidthPx, setColumnWidthPx] = useState<number>(COLUMN_PX_DEFAULT);
  const [hideCancelled, setHideCancelled] = useState(false);
  // Mobile clients are forced into list view: the day-view grid is a
  // multi-column timetable that needs ≥ ~640 px to render legibly.
  // We start as `false` (matches SSR's "assume desktop") and flip on
  // mount via matchMedia. The user's `displayMode` preference is
  // preserved untouched; we just override the render decision below.
  const [isNarrow, setIsNarrow] = useState(false);
  useEffect(() => {
    if (typeof window === 'undefined') return;
    const mql = window.matchMedia('(max-width: 639px)');
    const update = () => setIsNarrow(mql.matches);
    update();
    mql.addEventListener('change', update);
    return () => mql.removeEventListener('change', update);
  }, []);

  // Restore preferences on mount. Numeric prefs are clamped to the slider
  // bounds so a stale or hand-edited value can't render the calendar broken.
  useEffect(() => {
    if (typeof window === 'undefined') return;
    const storedPxPerMin = Number(window.localStorage.getItem(PX_PER_MIN_KEY));
    if (Number.isFinite(storedPxPerMin) && storedPxPerMin > 0) {
      setPxPerMin(clamp(storedPxPerMin, PX_PER_MIN_MIN, PX_PER_MIN_MAX));
    }
    const storedColumnPx = Number(window.localStorage.getItem(COLUMN_PX_KEY));
    if (Number.isFinite(storedColumnPx) && storedColumnPx > 0) {
      setColumnWidthPx(clamp(storedColumnPx, COLUMN_PX_MIN, COLUMN_PX_MAX));
    }
    const storedHide = window.localStorage.getItem(HIDE_CANCELLED_KEY);
    if (storedHide === '1') setHideCancelled(true);
  }, []);

  // ── Data ────────────────────────────────────────────────────────────────
  const { data: providers, isLoading: loadingProviders } = useBookableMemberships();
  const { data: appointments, isLoading: loadingAppts, error } = useAppointmentsForDate(date);
  // The active location's business hours drive the day-view's visible
  // time window. Editing a location's hours at /org/locations/[id]
  // refreshes this query (TanStack invalidates the list), so the
  // calendar updates without a reload. Falls back to DayView's
  // defaults (8 AM – 8 PM) while locations are loading or if the
  // parse fails — the calendar still renders on the default window
  // until the data lands.
  const dayStartHour =
    tenantHourFromTime(activeLocation?.business_open_time) ?? undefined;
  const dayEndHour =
    tenantHourFromTime(activeLocation?.business_close_time) ?? undefined;

  const filteredProviders = useMemo(() => {
    const all = providers ?? [];
    if (!providerFilter) return all;
    return all.filter((p) => String(p.id) === providerFilter);
  }, [providers, providerFilter]);

  const filteredAppointments = useMemo(() => {
    let list = appointments ?? [];
    if (providerFilter) {
      list = list.filter((a) => String(a.provider.id) === providerFilter);
    }
    if (hideCancelled) {
      list = list.filter((a) => a.status !== 'cancelled' && a.status !== 'no_show');
    }
    return list;
  }, [appointments, providerFilter, hideCancelled]);

  // ── Setters that sync URL or localStorage ──────────────────────────────
  const updateParam = useCallback(
    (key: string, value: string | null) => {
      const next = new URLSearchParams(searchParams.toString());
      if (value === null || value === '') next.delete(key);
      else next.set(key, value);
      router.replace(`/calendar${next.toString() ? `?${next.toString()}` : ''}`, {
        scroll: false,
      });
    },
    [router, searchParams],
  );

  const setDate = useCallback((next: string) => updateParam('date', next), [updateParam]);
  const setProviderFilter = useCallback(
    (next: string) => updateParam('provider', next || null),
    [updateParam],
  );
  const toggleTool = useCallback(
    (tool: CalendarTool) => {
      updateParam('tool', activeTool === tool ? null : tool);
    },
    [activeTool, updateParam],
  );
  const closeTool = useCallback(() => updateParam('tool', null), [updateParam]);

  const cancelReschedule = useCallback(() => {
    const next = new URLSearchParams(searchParams.toString());
    next.delete('rescheduling');
    next.delete('duration');
    router.replace(`/calendar${next.toString() ? `?${next.toString()}` : ''}`, {
      scroll: false,
    });
  }, [router, searchParams]);

  // Fetch the source appointment so the banner can show meaningful
  // context ("Rescheduling Liv's Hydrafacial …"). Cheap — react-query
  // dedupes against the calendar's main `useAppointmentsForDate` cache
  // when the source happens to be on the focus date.
  const { data: reschedulingSource } = useAppointment(reschedulingId ?? undefined);

  // ── New-appointment modal ───────────────────────────────────────────────
  const [newApptOpen, setNewApptOpen] = useState(false);
  const [newApptDefaults, setNewApptDefaults] = useState<{
    date?: string;
    time?: string;
    providerId?: number;
  }>({});

  const openNewAppointment = useCallback(
    (defaults?: { date?: string; time?: string; providerId?: number }) => {
      setNewApptDefaults(defaults ?? {});
      setNewApptOpen(true);
    },
    [],
  );

  // After a successful create, navigate to the booked date if it differs
  // from the focus date — otherwise the user may not see their new
  // appointment immediately.
  const onAppointmentCreated = useCallback(
    (createdDate: string) => {
      if (createdDate && createdDate !== date) updateParam('date', createdDate);
    },
    [date, updateParam],
  );

  const persistPxPerMin = useCallback((next: number) => {
    const clamped = clamp(next, PX_PER_MIN_MIN, PX_PER_MIN_MAX);
    setPxPerMin(clamped);
    if (typeof window !== 'undefined') {
      window.localStorage.setItem(PX_PER_MIN_KEY, String(clamped));
    }
  }, []);

  const persistColumnWidthPx = useCallback((next: number) => {
    const clamped = clamp(next, COLUMN_PX_MIN, COLUMN_PX_MAX);
    setColumnWidthPx(clamped);
    if (typeof window !== 'undefined') {
      window.localStorage.setItem(COLUMN_PX_KEY, String(clamped));
    }
  }, []);

  const persistHideCancelled = useCallback((next: boolean) => {
    setHideCancelled(next);
    if (typeof window !== 'undefined') {
      window.localStorage.setItem(HIDE_CANCELLED_KEY, next ? '1' : '0');
    }
  }, []);

  return (
    <>
      <CalendarTopBar onNewAppointment={() => openNewAppointment()} />
      <CalendarFilterBar
        date={date}
        onChangeDate={setDate}
        view={view}
        onChangeView={setView}
        displayMode={displayMode}
        onChangeDisplayMode={setDisplayMode}
        providers={providers ?? []}
        providerFilter={providerFilter}
        onChangeProviderFilter={setProviderFilter}
        hideCancelled={hideCancelled}
        onChangeHideCancelled={persistHideCancelled}
      />

      <div className="flex flex-1 min-h-0">
        <main className="flex-1 min-w-0 flex flex-col">
          {reschedulingId && reschedulingDuration ? (
            <ReschedulingBanner
              source={reschedulingSource ?? null}
              durationMinutes={reschedulingDuration}
              onCancel={cancelReschedule}
            />
          ) : null}

          {error ? (
            <div className="flex-1 flex items-center justify-center text-sm text-destructive">
              Failed to load appointments. Try refreshing the page.
            </div>
          ) : loadingProviders || loadingAppts ? (
            <div className="flex-1 flex items-center justify-center text-sm text-muted-foreground">
              Loading calendar…
            </div>
          ) : displayMode === 'list' || isNarrow ? (
            <ListView
              timezone={tenantTimezone}
              appointments={filteredAppointments}
            />
          ) : (
            <>
              <DayView
                date={date}
                timezone={tenantTimezone}
                providers={filteredProviders}
                appointments={filteredAppointments}
                pxPerMin={pxPerMin}
                columnWidthPx={columnWidthPx}
                rescheduling={
                  reschedulingId && reschedulingDuration
                    ? { appointmentId: reschedulingId, durationMinutes: reschedulingDuration }
                    : null
                }
                onCancelReschedule={cancelReschedule}
                onEmptySlotClick={(slot) =>
                  openNewAppointment({
                    date: slot.date,
                    time: slot.time,
                    providerId: slot.providerId,
                  })
                }
                dayStartHour={dayStartHour}
                dayEndHour={dayEndHour}
              />
              {/* Day-summary stats — sits flush at the bottom of the
                  calendar column. Uses the same filtered data the
                  DayView renders so toggling Hide cancelled / changing
                  the provider filter naturally re-derives the stats. */}
              <DayStatsFooter
                appointments={filteredAppointments}
                providers={filteredProviders}
                date={date}
                dayStartHour={dayStartHour ?? 8}
                dayEndHour={dayEndHour ?? 20}
              />
            </>
          )}
        </main>

        <ToolPanel
          active={activeTool}
          onClose={closeTool}
          focusDate={date}
          appointments={appointments ?? []}
          timezone={tenantTimezone}
          viewSettings={{
            pxPerMin,
            pxPerMinMin: PX_PER_MIN_MIN,
            pxPerMinMax: PX_PER_MIN_MAX,
            pxPerMinStep: PX_PER_MIN_STEP,
            onChangePxPerMin: persistPxPerMin,
            columnWidthPx,
            columnPxMin: COLUMN_PX_MIN,
            columnPxMax: COLUMN_PX_MAX,
            columnPxStep: COLUMN_PX_STEP,
            onChangeColumnWidthPx: persistColumnWidthPx,
            displayMode,
            onChangeDisplayMode: setDisplayMode,
          }}
        />
        <RightToolRail active={activeTool} onToggle={toggleTool} />
      </div>

      <NewAppointmentSheet
        open={newApptOpen}
        onOpenChange={setNewApptOpen}
        timezone={tenantTimezone}
        defaultDate={newApptDefaults.date}
        defaultTime={newApptDefaults.time}
        defaultProviderId={newApptDefaults.providerId}
        onCreated={onAppointmentCreated}
      />
    </>
  );
}

// ── Rescheduling banner ──────────────────────────────────────────────────

/**
 * Sticky banner shown across the top of the calendar while a reschedule
 * is in progress. Provides context (which appointment is moving and for
 * how long), a hint about the right-click flow, and a Cancel button.
 *
 * The actual right-click drop-target handling lives in DayView; this
 * banner is informational + escape hatch.
 */
function ReschedulingBanner({
  source,
  durationMinutes,
  onCancel,
}: {
  source: ReturnType<typeof useAppointment>['data'] | null;
  durationMinutes: number;
  onCancel: () => void;
}) {
  const customerName = source?.customer.full_name ?? 'this appointment';
  const serviceName = source?.service.name ?? '';

  return (
    <div className="shrink-0 px-6 py-2.5 bg-accent text-accent-foreground border-b border-accent/40 flex items-center gap-3">
      <CalendarClock className="size-4 shrink-0" aria-hidden />
      <div className="min-w-0 flex-1 text-sm">
        <span className="font-medium">Rescheduling</span>{' '}
        <span className="truncate">
          {customerName}
          {serviceName ? <> · {serviceName}</> : null}
          {' '}({durationMinutes}m)
        </span>
        <span className="hidden sm:inline text-accent-foreground/75 ml-2">
          · Right-click any time slot to drop the appointment there.
        </span>
      </div>
      <button
        type="button"
        onClick={onCancel}
        className="inline-flex items-center gap-1 h-7 px-2.5 rounded-md text-xs text-accent-foreground/90 hover:bg-accent-foreground/15 hover:text-accent-foreground transition-colors shrink-0"
      >
        <X className="size-3.5" />
        Cancel
      </button>
    </div>
  );
}

// ── Helpers ──────────────────────────────────────────────────────────────

function todayInTimezone(timezone: string): string {
  const fmt = new Intl.DateTimeFormat('en-CA', {
    timeZone: timezone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  });
  return fmt.format(new Date());
}

function clamp(value: number, min: number, max: number): number {
  if (value < min) return min;
  if (value > max) return max;
  return value;
}

