'use client';

import { InitialsAvatar } from '@/components/initials-avatar';
import {
  type RepeatRateByProviderRow,
  formatNumber,
  formatPct,
  useRepeatRateByProvider,
} from '@/lib/reports';

import {
  ReportSection,
  ReportShell,
  SummaryTile,
  SummaryTileRow,
} from '../../_components/report-shell';
import { ReportTable, type Column } from '../../_components/report-table';

export default function RepeatRateByProviderPage() {
  const { data, isLoading, error } = useRepeatRateByProvider();

  return (
    <ReportShell
      title="Repeat rate by provider"
      description="Lifetime metric: of every unique client a provider saw, what share came back. Higher = stickier book."
      phiTier="aggregated"
      isLoading={isLoading}
      error={error}
      exportPath="/api/reports/staff/repeat-rate-by-provider/"
    >
      {data ? (
        <>
          <SummaryTileRow>
            <SummaryTile label="Overall rate" value={formatPct(data.summary.overall_repeat_rate_pct)} />
            <SummaryTile label="Unique clients" value={formatNumber(data.summary.total_unique_clients)} />
            <SummaryTile label="Repeat clients" value={formatNumber(data.summary.total_repeat_clients)} />
            <SummaryTile label="Providers" value={formatNumber(data.summary.provider_count)} />
          </SummaryTileRow>
          <ReportSection title="Per-provider lifetime book" description="Ranked by repeat rate, then by unique-client volume.">
            <Table rows={data.rows} />
          </ReportSection>
        </>
      ) : null}
    </ReportShell>
  );
}

function Table({ rows }: { rows: RepeatRateByProviderRow[] }) {
  const columns: Column<RepeatRateByProviderRow>[] = [
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
    { key: 'unique', label: 'Unique clients', align: 'right', render: (r) => formatNumber(r.unique_client_count) },
    { key: 'repeat', label: 'Returners', align: 'right', render: (r) => formatNumber(r.repeat_client_count) },
    {
      key: 'rate',
      label: 'Repeat rate',
      align: 'right',
      className: 'font-medium',
      render: (r) => formatPct(r.repeat_rate_pct),
    },
  ];
  return <ReportTable columns={columns} rows={rows} rowKey={(r) => r.provider_id} />;
}
