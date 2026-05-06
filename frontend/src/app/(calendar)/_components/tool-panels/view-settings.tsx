/**
 * Functional tool panel — calendar view customization.
 *
 * Three settings front desk wants to control:
 *
 *   - **Row height** (px / minute) — driven by a slider. Affects every visible
 *     appointment block proportionally. Below ~2.5 px/min the time axis falls
 *     back from 5-minute labels to 15-minute labels because text would
 *     collide.
 *   - **Column width** (px) — slider. The calendar scrolls horizontally when
 *     the chosen width × number of providers exceeds the available viewport
 *     room — same as Boulevard / Zenoti.
 *   - **Display mode** — Calendar grid / List. Toggles between the time-grid
 *     view and a chronological list of the day's appointments.
 *
 * Settings live on the calendar page (URL or localStorage); this panel just
 * renders the controls and reports changes back through props.
 */

'use client';

import { CalendarDays, List } from 'lucide-react';

import { Slider } from '@/components/ui/slider';
import { cn } from '@/lib/utils';

export type CalendarDisplayMode = 'calendar' | 'list';

export interface ViewSettingsPanelProps {
  pxPerMin: number;
  pxPerMinMin: number;
  pxPerMinMax: number;
  pxPerMinStep: number;
  onChangePxPerMin: (next: number) => void;

  columnWidthPx: number;
  columnPxMin: number;
  columnPxMax: number;
  columnPxStep: number;
  onChangeColumnWidthPx: (next: number) => void;

  displayMode: CalendarDisplayMode;
  onChangeDisplayMode: (next: CalendarDisplayMode) => void;
}

export function ViewSettingsPanel({
  pxPerMin,
  pxPerMinMin,
  pxPerMinMax,
  pxPerMinStep,
  onChangePxPerMin,

  columnWidthPx,
  columnPxMin,
  columnPxMax,
  columnPxStep,
  onChangeColumnWidthPx,

  displayMode,
  onChangeDisplayMode,
}: ViewSettingsPanelProps) {
  const pxPerHour = Math.round(pxPerMin * 60);
  const fiveMinSlotPx = Math.round(pxPerMin * 5);
  const labelsAtFive = pxPerMin >= 2.5;
  const totalDayPx = Math.round((20 - 8) * 60 * pxPerMin);

  return (
    <div className="p-4 space-y-7">
      <Section
        title="Row height"
        description="Pixels per minute on the time axis. Below 2.5 px/min the labels switch from 5-minute to 15-minute increments so they don't collide."
      >
        <Slider
          value={[pxPerMin]}
          min={pxPerMinMin}
          max={pxPerMinMax}
          step={pxPerMinStep}
          onValueChange={(v) =>
            onChangePxPerMin(Array.isArray(v) ? (v[0] ?? pxPerMin) : v)
          }
          aria-label="Row height in pixels per minute"
        />
        <Readout
          primary={`${pxPerHour} px / hour`}
          secondary={`${fiveMinSlotPx} px per 5-min slot · ${
            labelsAtFive ? '5-minute' : '15-minute'
          } labels · day = ${totalDayPx} px`}
        />
      </Section>

      <Section
        title="Column width"
        description="How wide each provider column is. The calendar scrolls horizontally when there are more providers than fit at the chosen width."
      >
        <Slider
          value={[columnWidthPx]}
          min={columnPxMin}
          max={columnPxMax}
          step={columnPxStep}
          onValueChange={(v) =>
            onChangeColumnWidthPx(Array.isArray(v) ? (v[0] ?? columnWidthPx) : v)
          }
          aria-label="Provider column width in pixels"
        />
        <Readout
          primary={`${columnWidthPx} px wide`}
          secondary={
            columnWidthPx < 170
              ? 'Narrow — appointment blocks tighten their content'
              : columnWidthPx < 230
                ? 'Standard — balanced for most spas'
                : 'Wide — extra room for service / customer / category'
          }
        />
      </Section>

      <Section
        title="Display mode"
        description="Calendar grid for spatial overview, list for sequential review."
      >
        <SegmentedRow
          options={[
            {
              id: 'calendar',
              label: 'Calendar grid',
              sub: 'Time × providers',
              icon: <CalendarDays className="size-3.5" />,
            },
            {
              id: 'list',
              label: 'List',
              sub: 'Chronological feed',
              icon: <List className="size-3.5" />,
            },
          ]}
          value={displayMode}
          onChange={(v) => onChangeDisplayMode(v as CalendarDisplayMode)}
        />
      </Section>

      <p className="text-[11px] text-muted-foreground/80 leading-relaxed pt-2 border-t">
        Horizontal layout (time on the X axis) and per-staff visible hours come
        with Phase 1C session 4. Settings are remembered on this device.
      </p>
    </div>
  );
}

// ── Layout helpers ───────────────────────────────────────────────────────

function Section({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="space-y-2.5">
      <header>
        <p className="text-[11px] uppercase tracking-wide font-medium text-foreground">{title}</p>
        {description ? (
          <p className="text-xs text-muted-foreground mt-0.5 leading-relaxed">{description}</p>
        ) : null}
      </header>
      {children}
    </section>
  );
}

function Readout({ primary, secondary }: { primary: string; secondary: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3 text-[11px]">
      <span className="font-mono tabular-nums text-foreground/90">{primary}</span>
      <span className="text-muted-foreground/80 text-right truncate">{secondary}</span>
    </div>
  );
}

function SegmentedRow<T extends string>({
  options,
  value,
  onChange,
}: {
  options: { id: T; label: string; sub?: string; icon?: React.ReactNode }[];
  value: T;
  onChange: (next: T) => void;
}) {
  return (
    <div className="grid grid-cols-2 gap-2">
      {options.map((opt) => {
        const active = opt.id === value;
        return (
          <button
            key={opt.id}
            type="button"
            onClick={() => onChange(opt.id)}
            aria-pressed={active}
            className={cn(
              'rounded-md border p-3 text-left transition-colors',
              active
                ? 'border-accent/60 bg-accent/5'
                : 'border-border hover:border-foreground/20',
            )}
          >
            <div className="flex items-center gap-1.5 text-sm font-medium">
              {opt.icon}
              {opt.label}
            </div>
            {opt.sub ? (
              <p className="text-[11px] text-muted-foreground mt-0.5">{opt.sub}</p>
            ) : null}
          </button>
        );
      })}
    </div>
  );
}
