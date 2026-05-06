import { FeaturePage } from '@/components/feature-page';
import { ReportsMock, LocationsMock } from '@/components/product-mocks';

import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Reporting',
  description:
    'Twenty-two pre-built reports across financial, staff, guests, and operations. Live data, CSV export with HIPAA confirmation, audit-logged on every run.',
};

export default function ReportsFeaturePage() {
  return (
    <FeaturePage
      eyebrow="Reports"
      headline={
        <>
          Twenty-two reports.{' '}
          <span className="accent-italic">No spreadsheet wrestling.</span>
        </>
      }
      standfirst="Daily close-out, AR aging, revenue by service / provider / location, schedule utilization, no-show rates, top spenders, booking lead time. All running against live data; CSV export with HIPAA confirmation gate; audit-logged on every run."
      heroMock={<ReportsMock />}
      heroMockUrl="/reports/financial/sales-by-date-range"
      highlights={[
        { value: '22', label: 'Pre-built reports — no custom report-builder required.' },
        { value: 'Live', label: 'Real-time data — no nightly refresh delay.' },
        { value: 'CSV', label: 'Streaming export with PHI confirmation gate.' },
      ]}
      details={[
        {
          eyebrow: 'Categories',
          title: 'Four categories, each with five-plus reports.',
          body: (
            <>
              <p>
                <strong className="text-foreground">Financial</strong> —
                Sales by date range, daily close-out, revenue by service,
                revenue by location, tax collected, AR aging.
              </p>
              <p>
                <strong className="text-foreground">Staff</strong> —
                Revenue by provider, schedule utilization, no-show rate
                by provider, new clients by provider, repeat-rate by
                provider.
              </p>
              <p>
                <strong className="text-foreground">Guests</strong> —
                New vs returning, top spenders, inactive clients,
                visit frequency, birthday list, forms outstanding.
              </p>
              <p>
                <strong className="text-foreground">Operations</strong> —
                Appointments by status, no-show rate, cancellation rate,
                booking lead time, service mix, busiest hours.
              </p>
            </>
          ),
        },
        {
          eyebrow: 'Permissions',
          title: 'Each category gates by role.',
          body: (
            <>
              <p>
                Financial reports require the financial-reports
                permission (owner, manager, bookkeeper by default).
                Guest reports gate to owner, manager, and marketing.
                Operations reports are open to the whole staff,
                including front desk.
              </p>
              <p>
                Per-category gating means you can hire a bookkeeper and
                give them the financials without exposing the medical
                history of every patient on the chart side.
              </p>
            </>
          ),
          bullets: [
            'Per-category role gating',
            'Audit log on every report run',
            'Server-filtered catalog (you only see what you can run)',
            'PHI confirmation modal on per-customer exports',
          ],
          mock: <LocationsMock />,
          mockUrl: '/reports',
        },
        {
          eyebrow: 'Export',
          title: 'CSV export, with a PHI gate where it matters.',
          body: (
            <>
              <p>
                Every report exports to CSV in one click. Server-side
                streaming means a 100,000-row export doesn't lock up
                the browser or the backend.
              </p>
              <p>
                Reports that include per-customer data — top spenders,
                inactive clients, AR aging — fire a PHI confirmation
                modal before the download. The confirmation is logged
                in the audit trail with the operator's name. SOC 2
                attestation evidence built in.
              </p>
            </>
          ),
          bullets: [
            'Server-rendered streaming CSV',
            'PHI confirmation modal on per-customer exports',
            'EXPORT audit-log entry with phi_confirmed flag',
            'Filename includes the report ID + date range',
          ],
        },
      ]}
      related={[
        { href: '/features/payments', label: 'Payments', title: 'Where the financial reports get their data.' },
        { href: '/security', label: 'Security', title: 'How the PHI gate fits the SOC 2 picture.' },
      ]}
    />
  );
}
