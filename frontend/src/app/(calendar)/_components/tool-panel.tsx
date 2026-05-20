/**
 * Slide-out panel container for the calendar workspace.
 *
 * Renders a 340-px panel between the calendar grid and the right rail when
 * `active` is non-null. The panel has a header (tool name + close X) and a
 * scrollable body. The actual tool contents are dispatched here based on the
 * active tool ID — most are functional now, the rest are explicit placeholders.
 */

'use client';

import { ChevronLeft, X } from 'lucide-react';

import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet';
import type { Appointment } from '@/lib/appointments';
import { cn } from '@/lib/utils';

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

/** The actual tool content — shared by the desktop side panel and
 *  the mobile sheet. No chrome, just the dispatched panel body. */
function ToolPanelBody({
  active,
  viewSettings,
  focusDate,
  appointments,
  timezone,
}: Omit<ToolPanelProps, 'onClose'>) {
  if (active === 'view-settings') return <ViewSettingsPanel {...viewSettings} />;
  if (active === 'price-check') return <PriceCheckPanel />;
  if (active === 'social') return <SocialPanel />;
  if (active === 'check-in') return <CheckInPanel />;
  if (active === 'online-bookings') return <OnlineBookingsPanel />;
  if (active === 'waitlist') return <WaitlistPanel />;
  if (active === 'reports') {
    return (
      <ReportsPanel
        focusDate={focusDate}
        appointments={appointments}
        timezone={timezone}
      />
    );
  }
  return null;
}

/** Desktop-only side panel — between the calendar grid and the right
 *  rail. Hidden below `sm`; mobile uses <MobileToolsSheet> instead. */
export function ToolPanel(props: ToolPanelProps) {
  const { active, onClose } = props;
  if (!active) return null;

  const tool = TOOLS.find((t) => t.id === active);
  if (!tool) return null;

  return (
    <aside
      className="hidden sm:flex shrink-0 w-[340px] border-l bg-card flex-col h-full overflow-hidden"
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
        <ToolPanelBody {...props} />
      </div>
    </aside>
  );
}

export interface MobileToolsSheetProps extends ToolPanelProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Activate a tool from the launcher grid. */
  onSelectTool: (tool: CalendarTool) => void;
}

/** Mobile tools surface — a bottom sheet that first shows a grid of
 *  every calendar tool, then swaps to the selected tool's panel
 *  (with a back arrow). Phone-only operators were locked out of the
 *  tool rail entirely before this. */
export function MobileToolsSheet({
  open,
  onOpenChange,
  active,
  onClose,
  onSelectTool,
  viewSettings,
  focusDate,
  appointments,
  timezone,
}: MobileToolsSheetProps) {
  const tool = active ? TOOLS.find((t) => t.id === active) : null;

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="bottom" className="h-[85vh] p-0 flex flex-col" showCloseButton={false}>
        <SheetHeader className="border-b px-4 py-3 flex-row items-center gap-2 space-y-0">
          {tool ? (
            <button
              type="button"
              onClick={onClose}
              aria-label="Back to tools"
              className="inline-flex size-8 -ml-1 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
            >
              <ChevronLeft className="size-4" />
            </button>
          ) : null}
          <SheetTitle className="font-serif text-base">
            {tool ? tool.label : 'Calendar tools'}
          </SheetTitle>
          <button
            type="button"
            onClick={() => onOpenChange(false)}
            aria-label="Close"
            className="ml-auto inline-flex size-8 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
          >
            <X className="size-4" />
          </button>
        </SheetHeader>

        <div className="flex-1 min-h-0 overflow-y-auto">
          {tool ? (
            <ToolPanelBody
              active={active}
              viewSettings={viewSettings}
              focusDate={focusDate}
              appointments={appointments}
              timezone={timezone}
            />
          ) : (
            <div className="grid grid-cols-2 gap-2 p-3">
              {TOOLS.map((t) => {
                const Icon = t.icon;
                return (
                  <button
                    key={t.id}
                    type="button"
                    onClick={() => {
                      // Popout tools (Messages → /inbox) open their own
                      // window instead of an in-sheet panel — same rule
                      // as the desktop rail.
                      if (t.popoutUrl) {
                        if (typeof window !== 'undefined') {
                          window.open(
                            t.popoutUrl,
                            t.popoutTarget ?? '_blank',
                            t.popoutFeatures,
                          );
                        }
                        onOpenChange(false);
                        return;
                      }
                      onSelectTool(t.id);
                    }}
                    className={cn(
                      'flex flex-col items-start gap-2 rounded-xl border bg-card p-3.5',
                      'hover:border-foreground/30 hover:bg-muted/40 active:bg-muted/60 transition-colors',
                    )}
                  >
                    <span className="inline-flex size-9 items-center justify-center rounded-lg bg-muted text-foreground/80">
                      <Icon className="size-4" />
                    </span>
                    <span className="text-sm font-medium text-left leading-tight">
                      {t.label}
                    </span>
                  </button>
                );
              })}
            </div>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}
