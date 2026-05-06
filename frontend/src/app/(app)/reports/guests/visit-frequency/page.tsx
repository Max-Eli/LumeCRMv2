'use client';

import {
  type VisitFrequencyRow,
  formatNumber,
  formatPct,
  useVisitFrequency,
} from '@/lib/reports';

import {
  ReportSection,
  ReportShell,
  SummaryTile,
  SummaryTileRow,
} from '../../_components/report-shell';
import { ReportTable, type Column } from '../../_components/report-table';

export default function VisitFrequencyPage() {
  const { data, isLoading, error } = useVisitFrequency();

  return (
    <ReportShell
      title="Visit frequency distribution"
      description="Histogram of how many lifetime visits each client has. Surfaces the regulars vs the one-and-done crowd."
      phiTier="none"
      isLoading={isLoading}
      error={error}
      exportPath="/api/reports/guests/visit-frequency/"
    >
      {data ? (
        <>
          <SummaryTileRow>
            <SummaryTile label="Clients with visits" value={formatNumber(data.summary.total_unique_clients_with_visits)} />
            <SummaryTile label="Buckets" value={formatNumber(data.summary.bucket_count)} />
          </SummaryTileRow>
          <ReportSection title="Distribution" description="Counts only completed / checked-in appointments — cancellations + no-shows excluded.">
            <Table rows={data.rows} />
          </ReportSection>
        </>
      ) : null}
    </ReportShell>
  );
}

function Table({ rows }: { rows: VisitFrequencyRow[] }) {
  const columns: Column<VisitFrequencyRow>[] = [
    { key: 'bucket', label: 'Visit count', align: 'left', render: (r) => r.label },
    { key: 'clients', label: 'Clients', align: 'right', render: (r) => formatNumber(r.customer_count) },
    {
      key: 'share',
      label: 'Share',
      align: 'right',
      className: 'font-medium',
      render: (r) => formatPct(r.share_pct),
    },
  ];
  return <ReportTable columns={columns} rows={rows} rowKey={(r) => r.bucket_id} />;
}
