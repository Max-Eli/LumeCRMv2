import { FeaturePage } from '@/components/feature-page';
import { CalendarMock, ChartMock } from '@/components/product-mocks';

import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Booking calendar',
  description:
    'Per-provider columns, online booking with deposit, SMS + email reminders, and conflict detection at submit. The booking calendar for multi-provider medspas.',
};

export default function BookingFeaturePage() {
  return (
    <FeaturePage
      path="/features/booking"
      breadcrumbLabel="Booking calendar"
      eyebrow="Booking"
      headline={
        <>
          A booking calendar built for{' '}
          <span className="accent-italic">multi-provider spas.</span>
        </>
      }
      standfirst="Per-provider columns. Working hours and breaks honored at the booking layer. Online booking with deposit-on-book. Consent flagged before check-in."
      heroMock={<CalendarMock />}
      heroMockUrl="/calendar"
      highlights={[
        { value: '3 taps', label: 'From client search to booked appointment.' },
        { value: '24/7', label: 'Online booking with deposit-on-book.' },
        { value: '0', label: 'Double-bookings — provider conflicts blocked at submit.' },
      ]}
      details={[
        {
          eyebrow: 'Multi-provider columns',
          title: 'See every provider\'s day in one view.',
          body: (
            <>
              <p>
                The day view splits into per-provider columns. Each
                provider's working hours, lunch breaks, and personal-day
                blocks are honored automatically — and stay unbookable.
              </p>
              <p>
                Drag to reschedule. Provider, room, and equipment
                conflicts get caught at submit, so a double-booking
                never saves.
              </p>
            </>
          ),
          bullets: [
            'Per-provider working hours',
            'Drag-to-reschedule with conflict detection',
            'Lunch breaks + block-outs honored',
            'Color-coded by service category',
          ],
        },
        {
          eyebrow: 'Online booking',
          title: 'Self-serve booking with a deposit on every appointment.',
          body: (
            <>
              <p>
                Clients book through your branded page. No app to
                download. No account to create. Pick service, provider,
                time. Pay the deposit.
              </p>
              <p>
                Deposits flow into the invoice automatically. Cancel
                inside the policy window, the deposit converts to a
                credit. No-show, you keep it.
              </p>
            </>
          ),
          bullets: [
            'Branded booking page (no Lumè branding required)',
            'Deposit-on-book applied to invoice',
            'Cancellation policy enforcement',
            'Service-level provider eligibility',
          ],
          mock: <ChartMock />,
          mockUrl: '/clients/sarah-chen',
        },
        {
          eyebrow: 'Reminders',
          title: 'SMS and email reminders that cut no-shows 30-50%.',
          body: (
            <>
              <p>
                Confirmation on booking. 72-hour reminder. 24-hour
                reminder. Clients confirm or reschedule by SMS reply.
                Cadence is configurable per tenant.
              </p>
              <p>
                Automated reminders typically cut no-show rates 30-50%
                versus manual phone calls.
              </p>
            </>
          ),
          bullets: [
            'SMS + email confirmation on booking',
            'Configurable reminder cadence',
            'Reply-to-confirm via SMS',
            'TCPA-compliant opt-out handling',
          ],
        },
      ]}
      related={[
        { href: '/features/charts', label: 'Client charts', title: 'Every client record in one place.' },
        { href: '/features/forms', label: 'Consent forms', title: 'E-signed consent that holds up under audit.' },
      ]}
    />
  );
}
