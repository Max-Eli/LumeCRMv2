import { FeaturePage } from '@/components/feature-page';
import { LocationsMock, CalendarMock } from '@/components/product-mocks';

import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Multi-location management',
  description:
    'Per-location calendars, pricing, staff schedules, and reports. An org-level dashboard shows every site alongside cross-location revenue. Bills per location, not per seat.',
};

export default function MultiLocationFeaturePage() {
  return (
    <FeaturePage
      path="/features/multi-location"
      breadcrumbLabel="Multi-location management"
      eyebrow="Multi-location"
      headline={
        <>
          One brand, multiple locations,{' '}
          <span className="accent-italic">one bill.</span>
        </>
      }
      standfirst="Per-location calendars, pricing, staff schedules, and reports. An org-level dashboard shows every site alongside cross-location revenue. The bill scales by location, not by seat."
      heroMock={<LocationsMock />}
      heroMockUrl="/org/dashboard"
      highlights={[
        { value: 'Unlimited', label: 'Locations on one Lumè account.' },
        { value: 'Single', label: 'Sign-on across every site.' },
        { value: 'Org-level', label: 'Rollup dashboard for owners and managers.' },
      ]}
      details={[
        {
          eyebrow: 'Per-location operations',
          title: 'Each site runs independently.',
          body: (
            <>
              <p>
                Every site has its own calendar, staff schedule, service
                pricing, and business hours. The Manhattan front desk
                doesn't see Brooklyn unless they switch.
              </p>
              <p>
                Providers can work different schedules at different
                locations. Sarah works 9-to-5 weekdays in Manhattan and
                Saturdays in Brooklyn — Lumè handles both.
              </p>
            </>
          ),
          bullets: [
            'Per-location service pricing',
            'Per-location staff schedules',
            'Per-location business hours',
            'Per-location reporting filters',
          ],
        },
        {
          eyebrow: 'Org-level rollup',
          title: 'See the whole business in one dashboard.',
          body: (
            <>
              <p>
                The org dashboard shows every site at a glance, with
                cross-location revenue surfaced inline. Compare
                locations side-by-side; spot the top performer and the
                underbooked one.
              </p>
              <p>
                Per-location filtering runs across the reports that
                support it — revenue, appointments, utilization —
                scoped to a single site or rolled up across the org.
              </p>
            </>
          ),
          bullets: [
            'Cross-location revenue surfaced in the org dashboard',
            'Per-location filters on key reports',
            'Multi-location data model (per-site pricing, staff, hours)',
            'Org-level vs location-level views',
          ],
          mock: <CalendarMock />,
          mockUrl: '/calendar?location=brooklyn',
        },
        {
          eyebrow: 'One bill',
          title: 'Pricing scales with locations, not with seats.',
          body: (
            <>
              <p>
                Lumè bills per location, not per seat. Hire a bookkeeper
                or a second receptionist without re-negotiating.
              </p>
              <p>
                Open a new site, it gets added to the next invoice.
                Close one, it comes off. No contract amendment.
              </p>
            </>
          ),
          bullets: [
            'Per-location pricing (not per-seat)',
            'Unlimited staff seats per location',
            'No "tier" upgrade required for new sites',
            'Open / close locations without contract amendment',
          ],
        },
      ]}
      related={[
        { href: '/features/reports', label: 'Reports', title: 'Per-location revenue and utilization.' },
        { href: '/features/booking', label: 'Booking', title: 'Per-location calendars + staff.' },
      ]}
    />
  );
}
