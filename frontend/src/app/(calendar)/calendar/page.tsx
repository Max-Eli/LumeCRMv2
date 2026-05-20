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

import { CalendarClock, Wrench, X } from 'lucide-react';
import { useRouter, useSearchParams } from 'next/navigation';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

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
import { MonthView } from '../_components/month-view';
import { NewAppointmentSheet } from '../_components/new-appointment-sheet';
import { RightToolRail, TOOLS, type CalendarTool } from '../_components/right-tool-rail';
import { MobileToolsSheet, ToolPanel } from '../_components/tool-panel';
import { WeekView } from '../_components/week-view';
import {
  useAppointment,
  useAppointmentsForDate,
  useAppointmentsRange,
} from '@/lib/appointments';
import { useCurrentMembership, useUser } from '@/lib/auth';
import { useActiveLocation } from '@/lib/locations';
import { useBookableMemberships } from '@/lib/memberships';
import { tenantHourFromTime } from '@/lib/tenant';
import { cn } from '@/lib/utils';

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
  // Provider filter is a comma-separated list of provider IDs. Empty
  // string OR missing param = all providers. Multi-select is the
  // common operator workflow (e.g. "show me only the two injectors
  // today"); the previous single-string form is a strict subset.
  const providerFilterRaw = searchParams.get('provider') ?? '';
  const providerFilter: number[] = providerFilterRaw
    ? providerFilterRaw
        .split(',')
        .map((s) => Number(s.trim()))
        .filter((n) => Number.isFinite(n) && n > 0)
    : [];
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
  // Default ON — cancelled + no-show appointments clutter the day
  // view (especially after a bulk migration import); operators that
  // want them visible can flip the toggle off and the choice
  // persists in localStorage.
  const [hideCancelled, setHideCancelled] = useState(true);

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
    // Default is true; only flip to false when the operator
    // explicitly stored '0' (chose to show cancelled).
    const storedHide = window.localStorage.getItem(HIDE_CANCELLED_KEY);
    if (storedHide === '0') setHideCancelled(false);
  }, []);

  // ── Data ────────────────────────────────────────────────────────────────
  const { data: providers, isLoading: loadingProviders } = useBookableMemberships();
  const { data: currentUser } = useUser();
  const currentMembership = useCurrentMembership();

  // Day view fetches the single-day window; week + month fetch a
  // range. Both hooks are always called (React rules-of-hooks) — the
  // inactive one is disabled via an `undefined` arg so it doesn't
  // fetch. `appointments` then resolves from whichever is active.
  const { rangeStart, rangeEnd } = useMemo(
    () => computeRange(view, date),
    [view, date],
  );
  const dayQuery = useAppointmentsForDate(view === 'day' ? date : undefined);
  const rangeQuery = useAppointmentsRange(
    view === 'day' ? undefined : rangeStart,
    view === 'day' ? undefined : rangeEnd,
  );
  const appointments = view === 'day' ? dayQuery.data : rangeQuery.data;
  const loadingAppts = view === 'day' ? dayQuery.isLoading : rangeQuery.isLoading;
  const error = view === 'day' ? dayQuery.error : rangeQuery.error;

  // Provider-role default: when a "provider" role user opens the
  // calendar for the first time in this session, narrow the provider
  // filter to their own appointments. Multi-provider tenants (5+
  // injectors per day) overwhelm a single provider trying to find
  // "my day" in the wall of other people's blocks.
  //
  // Behaviour rules:
  //   - Fires once per page load, after both `useUser` and
  //     `useBookableMemberships` have resolved.
  //   - Skipped when the URL already has `?provider=` (deep-link,
  //     reload, or the user has manually picked a filter — all are
  //     respected).
  //   - Skipped for any role other than `provider`.
  //   - Match by email (the bookable-memberships payload is the
  //     authoritative provider list; the current user's membership
  //     doesn't carry an id we could use directly).
  const didProviderDefault = useRef(false);
  useEffect(() => {
    if (didProviderDefault.current) return;
    if (!providers || providers.length === 0) return;
    if (!currentUser || !currentMembership) return;
    didProviderDefault.current = true;
    if (currentMembership.role !== 'provider') return;
    if (providerFilter.length > 0) return;
    const me = providers.find((p) => p.user_email === currentUser.email);
    if (me) {
      const next = new URLSearchParams(searchParams.toString());
      next.set('provider', String(me.id));
      router.replace(`/calendar${next.toString() ? `?${next.toString()}` : ''}`, {
        scroll: false,
      });
    }
    // The deps cover the data we read; we still gate with the ref so
    // an intentional clear-filter doesn't re-trigger.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [providers, currentUser, currentMembership]);
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

  // Day-aware schedule filter: in day view, drop providers who aren't
  // scheduled for the current weekday. Operators were seeing "ghost
  // columns" for bookable staff who weren't on the schedule (e.g. a
  // nurse who only works Mon + Fri showing up in every Tue–Thu view).
  // Rules (strict — Option A):
  //   - schedule_for_location is null/undefined → hide (no schedule
  //     set = not scheduled)
  //   - schedule_for_location[weekday] missing or empty array → hide
  //   - schedule_for_location[weekday] has at least one entry → show
  // Week / month views show everyone (each day inside those views can
  // make its own schedule decision rendering-side).
  const weekday = useMemo(() => weekdayKey(date), [date]);
  const scheduledProviders = useMemo(() => {
    const all = providers ?? [];
    if (view !== 'day') return all;
    return all.filter((p) => {
      const sched = p.schedule_for_location;
      if (!sched) return false;
      const todayHours = sched[weekday];
      return Array.isArray(todayHours) && todayHours.length > 0;
    });
  }, [providers, view, weekday]);

  const filteredProviders = useMemo(() => {
    const base = scheduledProviders;
    if (providerFilter.length === 0) return base;
    const allowed = new Set(providerFilter);
    return base.filter((p) => allowed.has(p.id));
  }, [scheduledProviders, providerFilter]);

  // Appointments use the same provider set as the column list, so a
  // provider hidden by the schedule filter also hides their cards —
  // otherwise you'd get appointment chips floating with no column to
  // anchor against.
  const filteredAppointments = useMemo(() => {
    let list = appointments ?? [];
    const allowedIds = new Set(filteredProviders.map((p) => p.id));
    if (view === 'day' || providerFilter.length > 0) {
      list = list.filter((a) => allowedIds.has(a.provider.id));
    }
    if (hideCancelled) {
      list = list.filter((a) => a.status !== 'cancelled' && a.status !== 'no_show');
    }
    return list;
  }, [appointments, filteredProviders, providerFilter, hideCancelled, view]);

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
    (next: number[]) => updateParam('provider', next.length === 0 ? null : next.join(',')),
    [updateParam],
  );
  const toggleTool = useCallback(
    (tool: CalendarTool) => {
      updateParam('tool', activeTool === tool ? null : tool);
    },
    [activeTool, updateParam],
  );
  const closeTool = useCallback(() => updateParam('tool', null), [updateParam]);

  // Mobile-only: the tool rail is desktop chrome; phones reach the
  // same tools through a bottom-sheet launcher (FAB → grid → panel).
  const [mobileToolsOpen, setMobileToolsOpen] = useState(false);

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
          ) : view === 'month' ? (
            <MonthView
              date={date}
              timezone={tenantTimezone}
              appointments={filteredAppointments}
              onSelectDay={(d) => {
                setDate(d);
                setView('day');
              }}
            />
          ) : view === 'week' ? (
            <WeekView
              date={date}
              timezone={tenantTimezone}
              appointments={filteredAppointments}
              onSelectDay={(d) => {
                setDate(d);
                setView('day');
              }}
              dayStartHour={dayStartHour}
              dayEndHour={dayEndHour}
            />
          ) : (
            <>
              {/* Day view — mobile-first: ListView is ALWAYS shown on
                  phones (the time-grid breaks down below 768px no
                  matter how cleverly we columnize). On desktop,
                  ListView honors the operator's display-mode toggle.
                  Pure-CSS responsive so there's no hydration-mismatch
                  risk from a client-only useMediaQuery flip. */}
              <div
                className={cn(
                  'flex-1 min-h-0 flex flex-col',
                  displayMode === 'calendar' && 'md:hidden',
                )}
              >
                <ListView
                  timezone={tenantTimezone}
                  appointments={filteredAppointments}
                />
              </div>

              {/* Desktop-only: time-grid day view + day-stats footer.
                  The stats footer is hidden on mobile (per operator
                  request — irrelevant at phone-screen sizes where
                  the list view IS the surface). */}
              <div
                className={cn(
                  'hidden flex-1 min-h-0 flex-col',
                  displayMode === 'calendar' && 'md:flex',
                )}
              >
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
                <DayStatsFooter
                  appointments={filteredAppointments}
                  providers={filteredProviders}
                  date={date}
                  dayStartHour={dayStartHour ?? 8}
                  dayEndHour={dayEndHour ?? 20}
                />
              </div>
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

      {/* Mobile-only tools launcher — the desktop right rail is
          hidden below sm; this FAB opens the same tools in a sheet. */}
      <button
        type="button"
        onClick={() => setMobileToolsOpen(true)}
        aria-label="Calendar tools"
        className="sm:hidden fixed bottom-4 right-4 z-30 inline-flex size-12 items-center justify-center rounded-full bg-foreground text-background shadow-lg active:scale-95 transition-transform"
      >
        <Wrench className="size-5" />
      </button>

      <MobileToolsSheet
        open={mobileToolsOpen}
        onOpenChange={(open) => {
          setMobileToolsOpen(open);
          if (!open) closeTool();
        }}
        active={activeTool}
        onClose={closeTool}
        onSelectTool={toggleTool}
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

/** Lowercase weekday name matching the keys used by
 *  `ProviderSchedule.weekly_hours` on the backend
 *  (`monday`, `tuesday`, …). Date string is parsed as a local
 *  calendar date (not UTC) so a Sunday in California stays Sunday. */
function weekdayKey(dateStr: string): string {
  const d = new Date(`${dateStr}T00:00:00`);
  return ['sunday', 'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday'][d.getDay()];
}

/** ISO datetime window for a calendar view.
 *
 *   - day:   the day query handles its own window — returns nulls.
 *   - week:  Sunday 00:00 → following Sunday 00:00.
 *   - month: the visible 6-week grid (Sunday on/before the 1st →
 *            42 days later) so a month view's leading / trailing
 *            days from adjacent months still show their appointments.
 *
 *  Boundaries are computed in the browser's local time and serialized
 *  with `toISOString()`; the backend treats `start`/`end` as plain
 *  ISO-8601 instants, so a few hours of timezone drift at the very
 *  edge of the window is harmless (the grid cells re-bucket by each
 *  appointment's own local date anyway). */
function computeRange(
  view: 'day' | 'week' | 'month',
  dateStr: string,
): { rangeStart?: string; rangeEnd?: string } {
  if (view === 'day') return {};
  const focus = new Date(`${dateStr}T00:00:00`);
  if (view === 'week') {
    const start = new Date(focus);
    start.setDate(start.getDate() - start.getDay());
    const end = new Date(start);
    end.setDate(end.getDate() + 7);
    return { rangeStart: start.toISOString(), rangeEnd: end.toISOString() };
  }
  // month
  const firstOfMonth = new Date(focus.getFullYear(), focus.getMonth(), 1);
  const start = new Date(firstOfMonth);
  start.setDate(start.getDate() - start.getDay());
  const end = new Date(start);
  end.setDate(end.getDate() + 42);
  return { rangeStart: start.toISOString(), rangeEnd: end.toISOString() };
}

