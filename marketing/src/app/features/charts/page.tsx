import { FeaturePage } from '@/components/feature-page';
import { ChartMock, FormMock } from '@/components/product-mocks';

import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Client charts',
  description:
    'Complete client records for medspas: contact, treatment history, allergies, signed consent forms, outstanding paperwork, and provider-only notes — accessible in two taps.',
};

export default function ChartsFeaturePage() {
  return (
    <FeaturePage
      eyebrow="Client charts"
      headline={
        <>
          Every client record in{' '}
          <span className="accent-italic">one place.</span>
        </>
      }
      standfirst="Contact, treatment history, allergies, signed consent forms, outstanding paperwork, provider notes, and invoice history — accessible from the calendar in two taps. Searchable across every chart your spa has, regardless of location."
      heroMock={<ChartMock />}
      heroMockUrl="/clients/sarah-chen"
      highlights={[
        { value: '2 taps', label: 'From calendar block to full chart.' },
        { value: 'All locations', label: 'Search every chart from any site.' },
        { value: 'Provider-only', label: 'Notes thread separated from front-desk view.' },
      ]}
      details={[
        {
          eyebrow: 'Single source of truth',
          title: 'One record, every interaction.',
          body: (
            <>
              <p>
                Every booking, payment, signed form, and treatment outcome
                lives on the client's chart. The Overview tab shows the
                last visit, the next scheduled appointment, outstanding
                forms, and any provider notes flagged as important.
              </p>
              <p>
                If a client visits multiple locations, their chart follows
                them. Allergies entered at one location appear at every
                location.
              </p>
            </>
          ),
          bullets: [
            'Cross-location chart access',
            'Treatment outcomes tracked per visit',
            'Allergies + medical history surfaced on every page',
            'Loyalty / membership status visible at a glance',
          ],
        },
        {
          eyebrow: 'Provider notes',
          title: 'Internal notes separated from the public chart.',
          body: (
            <>
              <p>
                Provider notes are visible to providers and managers only —
                front-desk staff don't see them. Useful for clinical
                observations, behavioral notes, or anything that
                shouldn't surface on a checkout receipt.
              </p>
              <p>
                Notes are timestamped and authored, so the audit trail
                shows who wrote what and when.
              </p>
            </>
          ),
          bullets: [
            'Visible to providers + managers only',
            'Timestamped and authored',
            'Markdown-formatted',
            'Searchable from the chart sidebar',
          ],
          mock: <FormMock />,
          mockUrl: '/sign/9j4k…',
        },
        {
          eyebrow: 'Forms',
          title: 'Outstanding paperwork surfaced where it matters.',
          body: (
            <>
              <p>
                The chart shows pending consent forms inline — the front
                desk sees what needs signing before checkout, and the
                provider sees it before they start the treatment.
              </p>
              <p>
                Per-visit consent (Botox, filler, lasers) auto-assigns
                when the appointment is booked. Lifetime intake forms
                assign once on first appointment.
              </p>
            </>
          ),
          bullets: [
            'Auto-assigned per service or per visit',
            'Pending forms surfaced on chart + appointment popover',
            'One-tap "send tablet link" workflow',
            'Audit trail with IP, user-agent, signature',
          ],
        },
      ]}
      related={[
        { href: '/features/forms', label: 'Consent forms', title: 'E-signed consent with full audit trail.' },
        { href: '/features/booking', label: 'Booking', title: 'Multi-provider calendar with online booking.' },
      ]}
    />
  );
}
