'use client';

import { useState } from 'react';

import {
  type ServiceMixRow,
  formatNumber,
  formatPct,
  useServiceMix,
} from '@/lib/reports';

import { defaultDateRange, type DateRange } from '../../_components/date-range-picker';
import {
  ReportSection,
  ReportShell,
  SummaryTile,
  SummaryTileRow,
} from '../../_components/report-shell';
import { ReportTable, type Column } from '../../_components/report-table';

export default function ServiceMixPage() {
  const [range, setRange] = useState<DateRange>(defaultDateRange);
  const { data, isLoading, error } = useServiceMix(range);

  return (
    <ReportShell
      title="Service mix"
      description="Which services are booked the most. All statuses included — this is demand, not delivery."
      phiTier="none"
      dateRange={range}
      onDateRangeChange={setRange}
      isLoading={isLoading}
      error={error}
      exportPath="/api/reports/operations/service-mix/"
    >
      {data ? (
        <>
          <SummaryTileRow>
            <SummaryTile label="Total appointments" value={formatNumber(data.summary.total_appointments)} />
            <SummaryTile label="Distinct services" value={formatNumber(data.summary.service_count)} />
            <SummaryTile
              label="Top service"
              value={data.rows[0] ? formatNumber(data.rows[0].appointment_count) : '—'}
              hint={data.rows[0]?.service_name}
            />
          </SummaryTileRow>
          <ReportSection title="Per-service mix" description="Ranked highest-first.">
            <Table rows={data.rows} />
          </ReportSection>
        </>
      ) : null}
    </ReportShell>
  );
}

function Table({ rows }: { rows: ServiceMixRow[] }) {
  const columns: Column<ServiceMixRow>[] = [
    { key: 'service', label: 'Service', align: 'left', render: (r) => r.service_name },
    { key: 'count', label: 'Appointments', align: 'right', render: (r) => formatNumber(r.appointment_count) },
    {
      key: 'share',
      label: 'Share',
      align: 'right',
      className: 'font-medium',
      render: (r) => formatPct(r.share_pct),
    },
  ];
  return <ReportTable columns={columns} rows={rows} rowKey={(r) => r.service_id} />;
}
