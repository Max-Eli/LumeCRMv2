import { FeaturePage } from '@/components/feature-page';
import { InvoiceMock, ReportsMock } from '@/components/product-mocks';

import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Payments & invoicing',
  description:
    'Invoicing built for end-of-day reconciliation: cash, check, card-on-terminal, owner-only sixty-day reopen, and zero platform fee on card volume.',
};

export default function PaymentsFeaturePage() {
  return (
    <FeaturePage
      eyebrow="Payments"
      headline={
        <>
          Invoicing built for{' '}
          <span className="accent-italic">end-of-day reconciliation.</span>
        </>
      }
      standfirst="Cash, check, card-on-terminal, and other methods recorded with payment reference. Owner-only sixty-day reopen window. Daily close-out matches the cash drawer at end of shift. No platform fee on card volume — your processor stays your processor."
      heroMock={<InvoiceMock />}
      heroMockUrl="/appointments/4218/invoice"
      highlights={[
        { value: '0%', label: 'Platform fee on card volume.' },
        { value: '60 days', label: 'Owner-only reopen window for closed invoices.' },
        { value: '4 methods', label: 'Cash, check, card-on-terminal, other.' },
      ]}
      details={[
        {
          eyebrow: 'How invoices work',
          title: 'One invoice per appointment, opened automatically.',
          body: (
            <>
              <p>
                Every appointment gets an invoice the moment it's booked.
                Service line items snapshot the price at booking time so
                future price changes don't retroactively alter quoted
                appointments. The front desk takes payment when the
                client checks out; the appointment moves to "completed"
                only after the invoice closes.
              </p>
              <p>
                Tax calculates per line item using the service's
                configured rate. Multi-state spas can configure different
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
                The daily close-out report breaks gross down by payment
                method — cash, check, card-on-terminal, other — for any
                date range. Front-desk reconciles the cash drawer
                against the cash column; the manager reconciles the
                terminal against the card column.
              </p>
              <p>
                No platform fee on card volume. Lumè doesn't process
                payments — your existing terminal stays your terminal.
                We record what you collected, not what we charged for it.
              </p>
            </>
          ),
          bullets: [
            'Per-payment-method daily close-out report',
            'CSV export for accounting',
            'Card terminal stays separate (no markup)',
            'Tip handling on a per-tenant toggle',
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
                sixty days of close — useful for refunds, payment
                method corrections, and legitimate disputes. The reopen
                action records who, when, and why. Voiding an invoice
                requires a written reason and never deletes the record.
              </p>
              <p>
                Reopens are gated by a dedicated permission that's
                locked against per-user override — separation of duties
                at the role level, not at the individual.
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
