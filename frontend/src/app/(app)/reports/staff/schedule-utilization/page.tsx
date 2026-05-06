'use client';

import { useState } from 'react';

import { InitialsAvatar } from '@/components/initials-avatar';
import {
  type ScheduleUtilizationRow,
  formatMinutesAsHours,
  formatNumber,
  formatPct,
  useScheduleUtilization,
} from '@/lib/reports';

import { defaultDateRange, type DateRange } from '../../_components/date-range-picker';
import {
  ReportSection,
  ReportShell,
  SummaryTile,
  SummaryTileRow,
} from '../../_components/report-shell';
import { ReportTable, type Column } from '../../_components/report-table';

export default function ScheduleUtilizationPage() {
  const [range, setRange] = useState<DateRange>(defaultDateRange);
  const { data, isLoading, error } = useScheduleUtilization(range);

  return (
    <ReportShell
      title="Schedule utilization"
      description="What share of each provider's scheduled hours actually got delivered. Cancellations and no-shows don't count as utilized."
      phiTier="aggregated"
      dateRange={range}
      onDateRangeChange={setRange}
      isLoading={isLoading}
      error={error}
      exportPath="/api/reports/staff/schedule-utilization/"
    >
      {data ? (
        <>
          <SummaryTileRow>
            <SummaryTile label="Overall utilization" value={formatPct(data.summary.overall_utilization_pct)} />
            <SummaryTile label="Scheduled" value={formatMinutesAsHours(data.summary.total_scheduled_minutes)} />
            <SummaryTile label="Delivered" value={formatMinutesAsHours(data.summary.total_delivered_minutes)} />
            <SummaryTile label="Providers" value={formatNumber(data.summary.provider_count)} />
          </SummaryTileRow>
          <ReportSection title="Per-provider utilization" description="Highest-first. Providers without a saved schedule show 0% scheduled.">
            <Table rows={data.rows} />
          </ReportSection>
        </>
      ) : null}
    </ReportShell>
  );
}

function Table({ rows }: { rows: ScheduleUtilizationRow[] }) {
  const columns: Column<ScheduleUtilizationRow>[] = [
    {
      key: 'provider',
      label: 'Provider',
      align: 'left',
      render: (r) => (
        <div className="flex items-center gap-2.5">
          <InitialsAvatar name={r.provider_name} size="sm" />
          <span className="text-foreground">{r.provider_name}</span>
        </div>
      ),
    },
    { key: 'scheduled', label: 'Scheduled', align: 'right', render: (r) => formatMinutesAsHours(r.scheduled_minutes) },
    { key: 'delivered', label: 'Delivered', align: 'right', render: (r) => formatMinutesAsHours(r.delivered_minutes) },
    {
      key: 'utilization',
      label: 'Utilization',
      align: 'right',
      className: 'font-medium',
      render: (r) => formatPct(r.utilization_pct),
    },
  ];
  return <ReportTable columns={columns} rows={rows} rowKey={(r) => r.provider_id} />;
}
