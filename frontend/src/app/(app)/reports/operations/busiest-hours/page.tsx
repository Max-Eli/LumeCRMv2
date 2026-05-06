'use client';

import { useState } from 'react';

import { formatNumber, useBusiestHours } from '@/lib/reports';
import { cn } from '@/lib/utils';

import { defaultDateRange, type DateRange } from '../../_components/date-range-picker';
import {
  ReportSection,
  ReportShell,
  SummaryTile,
  SummaryTileRow,
} from '../../_components/report-shell';

const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

export default function BusiestHoursPage() {
  const [range, setRange] = useState<DateRange>(defaultDateRange);
  const { data, isLoading, error } = useBusiestHours(range);

  return (
    <ReportShell
      title="Busiest hours / days"
      description="Heatmap of appointment counts by hour of day × weekday. Use it to staff up at the right times."
      phiTier="none"
      dateRange={range}
      onDateRangeChange={setRange}
      isLoading={isLoading}
      error={error}
      exportPath="/api/reports/operations/busiest-hours/"
    >
      {data ? (
        <>
          <SummaryTileRow>
            <SummaryTile label="Total appointments" value={formatNumber(data.summary.total_appointments)} />
            <SummaryTile label="Peak weekday" value={data.summary.peak_weekday_label ?? '—'} />
            <SummaryTile label="Peak hour" value={data.summary.peak_hour_label ?? '—'} />
          </SummaryTileRow>
          <ReportSection title="Heatmap" description="Cell intensity scales with the busiest cell in the window.">
            <Heatmap grid={data.summary.grid} />
          </ReportSection>
        </>
      ) : null}
    </ReportShell>
  );
}

function Heatmap({ grid }: { grid: number[][] }) {
  // Find the busiest cell across the whole grid for relative intensity.
  let maxCell = 0;
  for (let w = 0; w < grid.length; w++) {
    for (let h = 0; h < grid[w].length; h++) {
      if (grid[w][h] > maxCell) maxCell = grid[w][h];
    }
  }
  const hours = Array.from({ length: 24 }, (_, i) => i);
  return (
    <div className="border rounded-lg bg-card overflow-x-auto">
      <table className="text-[10px] w-full">
        <thead>
          <tr className="text-muted-foreground border-b bg-muted/20">
            <th className="px-2 py-1.5 text-left font-medium uppercase tracking-wide">Day</th>
            {hours.map((h) => (
              <th key={h} className="px-1 py-1.5 font-mono text-center font-normal w-7">
                {h.toString().padStart(2, '0')}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {WEEKDAYS.map((label, w) => (
            <tr key={label} className="border-t">
              <th className="px-2 py-1 text-left font-medium text-muted-foreground">{label}</th>
              {hours.map((h) => {
                const count = grid[w]?.[h] ?? 0;
                const intensity = maxCell ? count / maxCell : 0;
                return (
                  <td
                    key={h}
                    className="px-0 py-0 align-middle text-center"
                    title={`${label} ${h.toString().padStart(2, '0')}:00 — ${count} appt${count === 1 ? '' : 's'}`}
                  >
                    <div
                      className={cn(
                        'mx-auto h-5 w-7 rounded-sm tabular-nums',
                        count === 0 ? 'bg-muted/30 text-transparent' : 'text-foreground/90',
                      )}
                      style={
                        count === 0
                          ? undefined
                          : { backgroundColor: `color-mix(in oklch, var(--color-accent) ${Math.round(15 + intensity * 75)}%, transparent)` }
                      }
                    >
                      {count > 0 ? count : '·'}
                    </div>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
