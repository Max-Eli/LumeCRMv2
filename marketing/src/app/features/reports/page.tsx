import { FeaturePage } from '@/components/feature-page';
import { ReportsMock, LocationsMock } from '@/components/product-mocks';

import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Reporting',
  description:
    'Daily close-out, AR aging, revenue by service / provider / location, schedule utilization, no-show rate, booking lead time. Live data, CSV export, audit-logged.',
};

export default function ReportsFeaturePage() {
  return (
    <FeaturePage
      path="/features/reports"
      breadcrumbLabel="Reporting"
      eyebrow="Reports"
      headline={
        <>
          Twenty-two reports.{' '}
          <span className="accent-italic">No spreadsheet wrestling.</span>
        </>
      }
      standfirst="Daily close-out, AR aging, revenue by service / provider / location, schedule utilization, no-show rate, top spenders, booking lead time. Live data. CSV export. Audit-logged on every run."
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
                Financial reports gate to owner, manager, and bookkeeper.
                Guest reports gate to owner, manager, and marketing.
                Operations is open to the whole staff.
              </p>
              <p>
                Hire a bookkeeper. They see revenue without seeing the
                medical history attached to it.
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
                streaming handles 100k-row exports without locking up
                the browser.
              </p>
              <p>
                Reports with per-customer data — top spenders, inactive
                clients, AR aging — fire a PHI confirmation modal
                first. The confirmation is audit-logged with the
                operator's name. SOC 2 evidence built in.
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
