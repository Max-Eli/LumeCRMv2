/**
 * Slide-out panel container for the calendar workspace.
 *
 * Renders a 340-px panel between the calendar grid and the right rail when
 * `active` is non-null. The panel has a header (tool name + close X) and a
 * scrollable body. The actual tool contents are dispatched here based on the
 * active tool ID — most are functional now, the rest are explicit placeholders.
 */

'use client';

import { X } from 'lucide-react';

import type { Appointment } from '@/lib/appointments';

import { TOOLS, type CalendarTool } from './right-tool-rail';
import { CheckInPanel } from './tool-panels/check-in';
import { OnlineBookingsPanel } from './tool-panels/online-bookings';
import { PriceCheckPanel } from './tool-panels/price-check';
import { ReportsPanel } from './tool-panels/reports';
import { SocialPanel } from './tool-panels/social';
import { ViewSettingsPanel, type ViewSettingsPanelProps } from './tool-panels/view-settings';
// Note: there is no in-rail panel for `'messages'` — that tile opens
// the standalone /inbox popout window (see `right-tool-rail.tsx`).
import { WaitlistPanel } from './tool-panels/waitlist';

export interface ToolPanelProps {
  active: CalendarTool | null;
  onClose: () => void;
  /** Settings shared with the calendar grid — row height, column width, display mode. */
  viewSettings: ViewSettingsPanelProps;
  /** Focus date in YYYY-MM-DD form. Passed through to the Reports
   *  panel so its daily stats track the day the operator is viewing. */
  focusDate: string;
  /** The day's appointments, already loaded for the calendar grid.
   *  Reports panel derives stats from these without a second fetch. */
  appointments: Appointment[];
  /** Active location's timezone for any date formatting in panels. */
  timezone: string;
}

export function ToolPanel({
  active,
  onClose,
  viewSettings,
  focusDate,
  appointments,
  timezone,
}: ToolPanelProps) {
  if (!active) return null;

  const tool = TOOLS.find((t) => t.id === active);
  if (!tool) return null;

  return (
    <aside
      className="shrink-0 w-[340px] border-l bg-card flex flex-col h-full overflow-hidden"
      aria-label={`${tool.label} panel`}
    >
      <header className="shrink-0 flex items-center justify-between gap-2 px-4 py-3 border-b">
        <div>
          <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Tool</p>
          <h2 className="font-serif text-base font-semibold tracking-tight">{tool.label}</h2>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="inline-flex size-8 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
          aria-label="Close panel"
        >
          <X className="size-4" />
        </button>
      </header>

      <div className="flex-1 min-h-0 overflow-y-auto">
        {active === 'view-settings' ? (
          <ViewSettingsPanel {...viewSettings} />
        ) : active === 'price-check' ? (
          <PriceCheckPanel />
        ) : active === 'social' ? (
          <SocialPanel />
        ) : active === 'check-in' ? (
          <CheckInPanel />
        ) : active === 'online-bookings' ? (
          <OnlineBookingsPanel />
        ) : active === 'waitlist' ? (
          <WaitlistPanel />
        ) : active === 'reports' ? (
          <ReportsPanel
            focusDate={focusDate}
            appointments={appointments}
            timezone={timezone}
          />
        ) : null}
      </div>
    </aside>
  );
}
