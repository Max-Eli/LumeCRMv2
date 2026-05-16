import { FeaturePage } from '@/components/feature-page';
import { ChartMock, FormMock } from '@/components/product-mocks';

import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Client charts',
  description:
    'Treatment history, allergies, signed consents, outstanding paperwork, provider notes, invoice history. Two clicks from the calendar. Searchable across every location.',
};

export default function ChartsFeaturePage() {
  return (
    <FeaturePage
      path="/features/charts"
      breadcrumbLabel="Client charts"
      eyebrow="Client charts"
      headline={
        <>
          Every client record in{' '}
          <span className="accent-italic">one place.</span>
        </>
      }
      standfirst="Treatment history, allergies, signed consents, outstanding paperwork, provider notes, invoice history. Two clicks from the calendar. Searchable across every location."
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
                Every booking, payment, signed form, and treatment
                outcome lives on the chart. The Overview tab shows last
                visit, next appointment, outstanding forms, and flagged
                notes.
              </p>
              <p>
                The chart follows the client across locations. Allergies
                entered in Brooklyn appear in Manhattan.
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
          title: 'Internal notes, separated from the front-desk view.',
          body: (
            <>
              <p>
                Provider notes are visible to providers and managers
                only. The front desk never sees them. Useful for
                clinical observations and behavioral notes — anything
                that shouldn't surface on a checkout receipt.
              </p>
              <p>
                Every note is timestamped and authored, so the audit
                trail shows who wrote what and when.
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
                Pending consents show inline on the chart. The front
                desk sees what needs signing before checkout. The
                provider sees it before treatment starts.
              </p>
              <p>
                Per-visit consent (Botox, filler, lasers) auto-assigns
                on booking. Lifetime intake assigns once, on first
                visit.
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
