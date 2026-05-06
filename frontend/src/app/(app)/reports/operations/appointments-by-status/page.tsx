'use client';

import { useState } from 'react';

import {
  type AppointmentsByStatusRow,
  formatNumber,
  useAppointmentsByStatus,
} from '@/lib/reports';

import { defaultDateRange, type DateRange } from '../../_components/date-range-picker';
import {
  ReportSection,
  ReportShell,
  SummaryTile,
  SummaryTileRow,
} from '../../_components/report-shell';
import { ReportTable, type Column } from '../../_components/report-table';

export default function AppointmentsByStatusPage() {
  const [range, setRange] = useState<DateRange>(defaultDateRange);
  const { data, isLoading, error } = useAppointmentsByStatus(range);

  return (
    <ReportShell
      title="Appointments by status"
      description="Booked, confirmed, checked-in, completed, no-show, cancelled — counts over the window."
      phiTier="none"
      dateRange={range}
      onDateRangeChange={setRange}
      isLoading={isLoading}
      error={error}
      exportPath="/api/reports/operations/appointments-by-status/"
    >
      {data ? (
        <>
          <SummaryTileRow>
            <SummaryTile label="Total appointments" value={formatNumber(data.summary.total_appointments)} />
            <SummaryTile label="Statuses present" value={formatNumber(data.summary.status_count)} />
          </SummaryTileRow>
          <ReportSection title="Per-status counts" description="Filter window is on appointment start time, not booking time.">
            <Table rows={data.rows} total={data.summary.total_appointments} />
          </ReportSection>
        </>
      ) : null}
    </ReportShell>
  );
}

function Table({ rows, total }: { rows: AppointmentsByStatusRow[]; total: number }) {
  const columns: Column<AppointmentsByStatusRow>[] = [
    { key: 'status', label: 'Status', align: 'left', render: (r) => r.status_label },
    { key: 'count', label: 'Count', align: 'right', className: 'font-medium', render: (r) => formatNumber(r.appointment_count) },
    {
      key: 'share',
      label: 'Share',
      align: 'right',
      render: (r) => (total ? `${((r.appointment_count / total) * 100).toFixed(1)}%` : '—'),
    },
  ];
  return <ReportTable columns={columns} rows={rows} rowKey={(r) => r.status} />;
}
