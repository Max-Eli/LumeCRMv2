'use client';

import Link from 'next/link';
import { useState } from 'react';

import {
  type InactiveClientsRow,
  formatNumber,
  useInactiveClients,
} from '@/lib/reports';

import {
  ReportSection,
  ReportShell,
  SummaryTile,
  SummaryTileRow,
} from '../../_components/report-shell';
import { ReportTable, type Column } from '../../_components/report-table';

const PRESETS = [30, 60, 90, 180, 365];

export default function InactiveClientsPage() {
  const [days, setDays] = useState(90);
  const { data, isLoading, error } = useInactiveClients({ days: String(days) });

  return (
    <ReportShell
      title="Inactive clients"
      description="Clients whose last visit was more than N days ago — pull this for win-back campaigns."
      phiTier="per_customer"
      controls={
        <div className="inline-flex items-center gap-2 text-xs text-muted-foreground">
          <span>Inactive for</span>
          <div className="inline-flex rounded-md border bg-card overflow-hidden divide-x">
            {PRESETS.map((d) => (
              <button
                key={d}
                type="button"
                onClick={() => setDays(d)}
                className={
                  days === d
                    ? 'h-8 px-3 text-xs bg-foreground text-background'
                    : 'h-8 px-3 text-xs text-muted-foreground hover:bg-muted hover:text-foreground transition-colors'
                }
              >
                {d}+ days
              </button>
            ))}
          </div>
        </div>
      }
      isLoading={isLoading}
      error={error}
      exportPath="/api/reports/guests/inactive-clients/"
      exportParams={{ days: String(days) }}
    >
      {data ? (
        <>
          <SummaryTileRow>
            <SummaryTile label="Inactive clients" value={formatNumber(data.summary.inactive_client_count)} hint={`${data.summary.days_threshold}+ days`} />
            <SummaryTile label="Never visited" value={formatNumber(data.summary.never_visited_count)} hint="customers on file with no appt" />
          </SummaryTileRow>
          <ReportSection title="Per-client list" description="Most-stale first. Click a name to open the customer profile.">
            <Table rows={data.rows} />
          </ReportSection>
        </>
      ) : null}
    </ReportShell>
  );
}

function Table({ rows }: { rows: InactiveClientsRow[] }) {
  const columns: Column<InactiveClientsRow>[] = [
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
      key: 'last',
      label: 'Last visit',
      align: 'left',
      render: (r) => (r.never_visited ? <em className="text-muted-foreground">never</em> : r.last_appointment_date),
    },
    {
      key: 'days',
      label: 'Days since',
      align: 'right',
      className: 'font-medium',
      render: (r) => formatNumber(r.days_since_last_visit),
    },
  ];
  return <ReportTable columns={columns} rows={rows} rowKey={(r) => r.customer_id} emptyMessage="No clients inactive that long — your retention is solid." />;
}
