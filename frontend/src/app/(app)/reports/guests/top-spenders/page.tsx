'use client';

import Link from 'next/link';

import {
  type TopSpendersRow,
  formatCents,
  formatNumber,
  useTopSpenders,
} from '@/lib/reports';

import {
  ReportSection,
  ReportShell,
  SummaryTile,
  SummaryTileRow,
} from '../../_components/report-shell';
import { ReportTable, type Column } from '../../_components/report-table';

export default function TopSpendersPage() {
  const { data, isLoading, error } = useTopSpenders();

  return (
    <ReportShell
      title="Top spenders (lifetime)"
      description="Lifetime revenue per client, ranked highest-first. The book's revenue concentration in one place."
      phiTier="per_customer"
      isLoading={isLoading}
      error={error}
      exportPath="/api/reports/guests/top-spenders/"
    >
      {data ? (
        <>
          <SummaryTileRow>
            <SummaryTile label="Returned" value={formatNumber(data.summary.returned_count)} hint={`top ${data.summary.limit}`} />
            <SummaryTile label="Total LTV (top-N)" value={formatCents(data.summary.total_lifetime_cents)} />
            <SummaryTile label="Avg LTV (top-N)" value={formatCents(data.summary.avg_lifetime_cents)} />
          </SummaryTileRow>
          <ReportSection title="Top clients by lifetime spend" description="PAID invoices only. Click a name to open the customer profile.">
            <Table rows={data.rows} />
          </ReportSection>
        </>
      ) : null}
    </ReportShell>
  );
}

function Table({ rows }: { rows: TopSpendersRow[] }) {
  const columns: Column<TopSpendersRow>[] = [
    {
      key: 'client',
      label: 'Client',
      align: 'left',
      render: (r) => (
        <Link href={`/clients/${r.customer_id}`} className="text-foreground hover:underline">
          {r.customer_name}
        </Link>
      ),
    },
    { key: 'email', label: 'Email', align: 'left', render: (r) => r.customer_email || '—' },
    { key: 'visits', label: 'Paid visits', align: 'right', render: (r) => formatNumber(r.paid_invoice_count) },
    { key: 'last', label: 'Last paid', align: 'left', render: (r) => r.last_paid_date ?? '—' },
    {
      key: 'ltv',
      label: 'Lifetime',
      align: 'right',
      className: 'font-medium',
      render: (r) => formatCents(r.lifetime_cents),
    },
  ];
  return <ReportTable columns={columns} rows={rows} rowKey={(r) => r.customer_id} />;
}
