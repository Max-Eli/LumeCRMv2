import { FeaturePage } from '@/components/feature-page';
import { InvoiceMock, ReportsMock } from '@/components/product-mocks';

import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Payments & invoicing',
  description:
    'Card, cash, and check recorded with payment reference. Integrated card processing inside the appointment flow. Daily close-out matches the drawer. Sixty-day reopen window.',
};

export default function PaymentsFeaturePage() {
  return (
    <FeaturePage
      path="/features/payments"
      breadcrumbLabel="Payments & invoicing"
      eyebrow="Payments"
      headline={
        <>
          Invoicing built for{' '}
          <span className="accent-italic">end-of-day reconciliation.</span>
        </>
      }
      standfirst="Card, cash, and check recorded with payment reference. Integrated card processing inside the appointment flow — no separate terminal to reconcile against. Daily close-out matches the drawer. Sixty-day reopen window."
      heroMock={<InvoiceMock />}
      heroMockUrl="/appointments/4218/invoice"
      highlights={[
        { value: 'Integrated', label: 'Card processing inside the appointment flow.' },
        { value: '60 days', label: 'Owner-only reopen window for closed invoices.' },
        { value: '4 methods', label: 'Card, cash, check, and other tracked together.' },
      ]}
      details={[
        {
          eyebrow: 'How invoices work',
          title: 'One invoice per appointment, opened automatically.',
          body: (
            <>
              <p>
                Every appointment opens an invoice on booking. Service
                prices snapshot at booking, so future price changes
                don't retroactively alter quoted appointments. The
                appointment moves to "completed" only when the invoice
                closes.
              </p>
              <p>
                Tax calculates per line item; multi-state spas configure
                rates per location.
              </p>
            </>
          ),
          bullets: [
            'Auto-opened on appointment booking',
            'Snapshot pricing — protected against future changes',
            'Per-line-item tax rate',
            'Closing the invoice closes the appointment',
          ],
        },
        {
          eyebrow: 'Reconciliation',
          title: 'The numbers match the cash drawer.',
          body: (
            <>
              <p>
                Daily close-out breaks gross by method: card, cash,
                check, other. The four totals reconcile against a
                single ledger — not a CRM ledger plus a separate
                terminal report.
              </p>
              <p>
                Card payments process through Lumè's licensed payment
                partner inside the appointment flow. Specific rates
                are quoted at contracting based on your card-present
                versus card-not-present mix.
              </p>
            </>
          ),
          bullets: [
            'Per-payment-method daily close-out report',
            'CSV export for accounting',
            'Card processing through a licensed payment partner',
            'PCI DSS-compliant payment partner',
          ],
          mock: <ReportsMock />,
          mockUrl: '/reports/financial/daily-close-out',
        },
        {
          eyebrow: 'Reopens + voids',
          title: 'Mistakes happen. The system handles them with a paper trail.',
          body: (
            <>
              <p>
                Owners and managers can reopen a closed invoice within
                sixty days. The reopen records who, when, and why.
                Voiding requires a written reason and never deletes the
                record.
              </p>
              <p>
                The reopen permission is locked at the role level — no
                per-user overrides, no end-runs around separation of
                duties.
              </p>
            </>
          ),
          bullets: [
            '60-day reopen window from initial close',
            'Required void reason; void never deletes',
            'Owner/manager-only reopen permission',
            'Full audit trail on every transition',
          ],
        },
      ]}
      related={[
        { href: '/features/reports', label: 'Reports', title: 'Where the daily close-out lives.' },
        { href: '/features/booking', label: 'Booking', title: 'How appointments turn into invoices.' },
      ]}
    />
  );
}
