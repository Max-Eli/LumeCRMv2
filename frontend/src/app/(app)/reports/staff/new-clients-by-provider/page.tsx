'use client';

import { useState } from 'react';

import { InitialsAvatar } from '@/components/initials-avatar';
import {
  type NewClientsByProviderRow,
  formatNumber,
  useNewClientsByProvider,
} from '@/lib/reports';

import { defaultDateRange, type DateRange } from '../../_components/date-range-picker';
import {
  ReportSection,
  ReportShell,
  SummaryTile,
  SummaryTileRow,
} from '../../_components/report-shell';
import { ReportTable, type Column } from '../../_components/report-table';

export default function NewClientsByProviderPage() {
  const [range, setRange] = useState<DateRange>(defaultDateRange);
  const { data, isLoading, error } = useNewClientsByProvider(range);

  return (
    <ReportShell
      title="New clients acquired by provider"
      description="Who's bringing in new business: clients whose first-ever appointment was with this provider in the window."
      phiTier="aggregated"
      dateRange={range}
      onDateRangeChange={setRange}
      isLoading={isLoading}
      error={error}
      exportPath="/api/reports/staff/new-clients-by-provider/"
    >
      {data ? (
        <>
          <SummaryTileRow>
            <SummaryTile label="Total new clients" value={formatNumber(data.summary.total_new_clients)} />
            <SummaryTile label="Acquiring providers" value={formatNumber(data.summary.provider_count)} />
            <SummaryTile
              label="Top acquirer"
              value={data.rows[0] ? formatNumber(data.rows[0].new_client_count) : '—'}
              hint={data.rows[0]?.provider_name}
            />
          </SummaryTileRow>
          <ReportSection title="Per-provider acquisition" description="Highest-first. Cancellations + no-shows still count.">
            <Table rows={data.rows} />
          </ReportSection>
        </>
      ) : null}
    </ReportShell>
  );
}

function Table({ rows }: { rows: NewClientsByProviderRow[] }) {
  const columns: Column<NewClientsByProviderRow>[] = [
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
    {
      key: 'count',
      label: 'New clients',
      align: 'right',
      className: 'font-medium',
      render: (r) => formatNumber(r.new_client_count),
    },
  ];
  return <ReportTable columns={columns} rows={rows} rowKey={(r) => r.provider_id} />;
}
