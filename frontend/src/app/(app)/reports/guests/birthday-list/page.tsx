'use client';

import Link from 'next/link';
import { useState } from 'react';

import {
  type BirthdayListRow,
  formatNumber,
  useBirthdayList,
} from '@/lib/reports';

import {
  ReportSection,
  ReportShell,
  SummaryTile,
  SummaryTileRow,
} from '../../_components/report-shell';
import { ReportTable, type Column } from '../../_components/report-table';

const PRESETS = [7, 14, 30, 60, 90];

export default function BirthdayListPage() {
  const [windowDays, setWindowDays] = useState(30);
  const { data, isLoading, error } = useBirthdayList({ window_days: String(windowDays) });

  return (
    <ReportShell
      title="Birthday list"
      description="Clients whose birthday falls in the next N days. Pull this for birthday outreach."
      phiTier="per_customer"
      controls={
        <div className="inline-flex items-center gap-2 text-xs text-muted-foreground">
          <span>Within next</span>
          <div className="inline-flex rounded-md border bg-card overflow-hidden divide-x">
            {PRESETS.map((d) => (
              <button
                key={d}
                type="button"
                onClick={() => setWindowDays(d)}
                className={
                  windowDays === d
                    ? 'h-8 px-3 text-xs bg-foreground text-background'
                    : 'h-8 px-3 text-xs text-muted-foreground hover:bg-muted hover:text-foreground transition-colors'
                }
              >
                {d} days
              </button>
            ))}
          </div>
        </div>
      }
      isLoading={isLoading}
      error={error}
      exportPath="/api/reports/guests/birthday-list/"
      exportParams={{ window_days: String(windowDays) }}
    >
      {data ? (
        <>
          <SummaryTileRow>
            <SummaryTile label="Upcoming birthdays" value={formatNumber(data.summary.upcoming_birthday_count)} hint={`next ${data.summary.window_days} days`} />
            <SummaryTile label="Email opted-in" value={formatNumber(data.summary.opted_in_count)} hint="of the upcoming list" />
          </SummaryTileRow>
          <ReportSection title="Birthdays" description="Soonest first. Customers without a birthday on file are omitted.">
            <Table rows={data.rows} />
          </ReportSection>
        </>
      ) : null}
    </ReportShell>
  );
}

function Table({ rows }: { rows: BirthdayListRow[] }) {
  const columns: Column<BirthdayListRow>[] = [
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
    { key: 'next', label: 'Next birthday', align: 'left', render: (r) => r.next_birthday_date },
    { key: 'days', label: 'In', align: 'right', render: (r) => `${r.days_until_birthday}d` },
    { key: 'turning', label: 'Turning', align: 'right', render: (r) => formatNumber(r.age_turning) },
    {
      key: 'opt_in',
      label: 'Email opt-in',
      align: 'right',
      className: 'text-xs uppercase',
      render: (r) => (
        <span className={r.email_opt_in ? 'text-emerald-700 dark:text-emerald-400' : 'text-muted-foreground'}>
          {r.email_opt_in ? 'yes' : 'no'}
        </span>
      ),
    },
  ];
  return <ReportTable columns={columns} rows={rows} rowKey={(r) => r.customer_id} emptyMessage="No birthdays in the upcoming window." />;
}
