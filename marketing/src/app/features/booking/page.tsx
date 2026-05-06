import { FeaturePage } from '@/components/feature-page';
import { CalendarMock, ChartMock } from '@/components/product-mocks';

import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Booking calendar',
  description:
    'Multi-provider booking calendar built for medspas: per-provider columns, online booking with deposit, automated reminders, conflict detection.',
};

export default function BookingFeaturePage() {
  return (
    <FeaturePage
      eyebrow="Booking"
      headline={
        <>
          A booking calendar built for{' '}
          <span className="accent-italic">multi-provider spas.</span>
        </>
      }
      standfirst="Per-provider columns, per-location scoping, working-hours awareness, and online booking with deposit-on-book. Lumè handles the way medspas actually schedule — multiple providers, multiple rooms, treatment-cycle awareness, and consent-before-checkin."
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
                The day view splits into per-provider columns, each scoped
                to that provider's working hours and bookable services.
                Block-out times, lunch breaks, and personal-day events
                stay visible — and stay unbookable.
              </p>
              <p>
                Drag any appointment to reschedule. Provider conflicts,
                room conflicts, and equipment conflicts surface
                immediately — no double-booking gets saved.
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
                Your clients book directly through your branded booking
                page — no app to download, no account to create. Pick a
                service, pick a provider, pick a time, pay the deposit.
              </p>
              <p>
                Deposits flow into the invoice automatically. If the
                client cancels inside your policy window, the deposit
                converts to a credit. If they no-show, you keep it.
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
          title: 'Automated SMS and email reminders that reduce no-shows.',
          body: (
            <>
              <p>
                Lumè sends a confirmation immediately after booking, a
                72-hour reminder, and a 24-hour reminder by default.
                Reminder cadence is per-tenant configurable, and clients
                can confirm or reschedule by SMS reply.
              </p>
              <p>
                Automated reminders typically reduce no-show rates by
                30-50% versus manual phone confirmation.
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
