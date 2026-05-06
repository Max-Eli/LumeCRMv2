'use client';

import { useState } from 'react';

import { InitialsAvatar } from '@/components/initials-avatar';
import {
  type NoShowByProviderRow,
  formatNumber,
  formatPct,
  useNoShowByProvider,
} from '@/lib/reports';

import { defaultDateRange, type DateRange } from '../../_components/date-range-picker';
import {
  ReportSection,
  ReportShell,
  SummaryTile,
  SummaryTileRow,
} from '../../_components/report-shell';
import { ReportTable, type Column } from '../../_components/report-table';

export default function NoShowByProviderPage() {
  const [range, setRange] = useState<DateRange>(defaultDateRange);
  const { data, isLoading, error } = useNoShowByProvider(range);

  return (
    <ReportShell
      title="No-show rate by provider"
      description="Per-provider no-show count and rate over the window. Often a reminder-cadence signal rather than a provider one."
      phiTier="aggregated"
      dateRange={range}
      onDateRangeChange={setRange}
      isLoading={isLoading}
      error={error}
      exportPath="/api/reports/staff/no-show-rate-by-provider/"
    >
      {data ? (
        <>
          <SummaryTileRow>
            <SummaryTile label="Overall rate" value={formatPct(data.summary.overall_no_show_rate_pct)} />
            <SummaryTile label="Total appointments" value={formatNumber(data.summary.total_appointments)} />
            <SummaryTile label="Total no-shows" value={formatNumber(data.summary.total_no_shows)} />
            <SummaryTile label="Providers" value={formatNumber(data.summary.provider_count)} />
          </SummaryTileRow>
          <ReportSection title="Per-provider breakdown" description="Highest no-show count first.">
            <Table rows={data.rows} />
          </ReportSection>
        </>
      ) : null}
    </ReportShell>
  );
}

function Table({ rows }: { rows: NoShowByProviderRow[] }) {
  const columns: Column<NoShowByProviderRow>[] = [
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
    { key: 'total', label: 'Appointments', align: 'right', render: (r) => formatNumber(r.total_appointments) },
    { key: 'no_show', label: 'No-shows', align: 'right', render: (r) => formatNumber(r.no_show_count) },
    {
      key: 'rate',
      label: 'No-show rate',
      align: 'right',
      className: 'font-medium',
      render: (r) => formatPct(r.no_show_rate_pct),
    },
  ];
  return <ReportTable columns={columns} rows={rows} rowKey={(r) => r.provider_id} />;
}
