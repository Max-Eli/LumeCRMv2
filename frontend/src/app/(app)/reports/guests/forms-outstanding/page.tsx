'use client';

import Link from 'next/link';

import {
  type FormsOutstandingRow,
  formatNumber,
  useFormsOutstanding,
} from '@/lib/reports';

import {
  ReportSection,
  ReportShell,
  SummaryTile,
  SummaryTileRow,
} from '../../_components/report-shell';
import { ReportTable, type Column } from '../../_components/report-table';

export default function FormsOutstandingPage() {
  const { data, isLoading, error } = useFormsOutstanding();

  return (
    <ReportShell
      title="Forms outstanding"
      description="Clients with unsigned forms waiting on them. Front-desk's pre-arrival paperwork chase list."
      phiTier="per_customer"
      isLoading={isLoading}
      error={error}
      exportPath="/api/reports/guests/forms-outstanding/"
    >
      {data ? (
        <>
          <SummaryTileRow>
            <SummaryTile label="Clients with pending forms" value={formatNumber(data.summary.customer_count)} />
            <SummaryTile label="Total pending forms" value={formatNumber(data.summary.total_pending_forms)} />
          </SummaryTileRow>
          <ReportSection title="Per-client list" description="Most-pending first. Click a name to open the profile and see which forms.">
            <Table rows={data.rows} />
          </ReportSection>
        </>
      ) : null}
    </ReportShell>
  );
}

function Table({ rows }: { rows: FormsOutstandingRow[] }) {
  const columns: Column<FormsOutstandingRow>[] = [
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
    { key: 'phone', label: 'Phone', align: 'left', render: (r) => r.customer_phone || '—' },
    {
      key: 'count',
      label: 'Pending forms',
      align: 'right',
      className: 'font-medium',
      render: (r) => formatNumber(r.pending_form_count),
    },
  ];
  return <ReportTable columns={columns} rows={rows} rowKey={(r) => r.customer_id} emptyMessage="No outstanding forms — everyone's signed." />;
}
