'use client';

import Link from 'next/link';

import {
  type ARAgingRow,
  formatCents,
  formatNumber,
  useARAging,
} from '@/lib/reports';

import {
  ReportSection,
  ReportShell,
  SummaryTile,
  SummaryTileRow,
} from '../../_components/report-shell';
import { ReportTable, type Column } from '../../_components/report-table';

export default function ARAgingPage() {
  const { data, isLoading, error } = useARAging();

  return (
    <ReportShell
      title="Accounts receivable aging"
      description="Open (unpaid) invoices grouped by how old they are. Snapshot — no date range; today is the aging anchor."
      phiTier="per_customer"
      isLoading={isLoading}
      error={error}
      exportPath="/api/reports/financial/ar-aging/"
    >
      {data ? (
        <>
          <SummaryTileRow>
            <SummaryTile label="Total open" value={formatCents(data.summary.total_open_cents)} hint={`${formatNumber(data.summary.open_invoice_count)} invoices`} />
            {data.summary.buckets.map((b) => (
              <SummaryTile
                key={b.id}
                label={b.label}
                value={formatCents(b.gross_cents)}
                hint={`${formatNumber(b.invoice_count)} invoice${b.invoice_count === 1 ? '' : 's'}`}
              />
            ))}
          </SummaryTileRow>
          <ReportSection title="Open invoice list" description="Most-stale first. Click a name to open the customer profile.">
            <ARTable rows={data.rows} />
          </ReportSection>
        </>
      ) : null}
    </ReportShell>
  );
}

function ARTable({ rows }: { rows: ARAgingRow[] }) {
  const columns: Column<ARAgingRow>[] = [
    {
      key: 'customer',
      label: 'Client',
      align: 'left',
      render: (r) => (
        <Link href={`/clients/${r.customer_id}`} className="text-foreground hover:underline">
          {r.customer_name}
        </Link>
      ),
    },
    { key: 'email', label: 'Email', align: 'left', render: (r) => r.customer_email || '—' },
    { key: 'created', label: 'Billed', align: 'left', render: (r) => r.created_date },
    { key: 'age', label: 'Age', align: 'right', render: (r) => `${r.age_days}d` },
    {
      key: 'amount',
      label: 'Amount',
      align: 'right',
      className: 'font-medium',
      render: (r) => formatCents(r.gross_cents),
    },
  ];
  return <ReportTable columns={columns} rows={rows} rowKey={(r) => r.invoice_id} emptyMessage="No outstanding invoices — nice." />;
}
