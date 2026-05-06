import { FeaturePage } from '@/components/feature-page';
import { LocationsMock, CalendarMock } from '@/components/product-mocks';

import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Multi-location management',
  description:
    'One brand, multiple locations, one bill. Per-location calendars, pricing, staff schedules. Org-level rollup dashboard. Single sign-on across sites.',
};

export default function MultiLocationFeaturePage() {
  return (
    <FeaturePage
      eyebrow="Multi-location"
      headline={
        <>
          One brand, multiple locations,{' '}
          <span className="accent-italic">one bill.</span>
        </>
      }
      standfirst="Per-location calendars, pricing, staff schedules, and reports. Org-level dashboard rolls up revenue, appointments, and utilization across every site. The location switcher only appears when there's more than one to switch between."
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
                Every location has its own calendar, its own staff
                schedule, its own service menu pricing, and its own
                business hours. The Manhattan front desk doesn't see
                Brooklyn's appointments unless they explicitly switch.
              </p>
              <p>
                Providers can be assigned to multiple locations with
                different schedules at each. Sarah works 9-5 Monday
                through Friday at Manhattan and Saturday only at
                Brooklyn — Lumè handles both.
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
                The org dashboard shows revenue, appointments, and
                utilization across every location. Compare sites,
                identify the top-performing one, see which is
                underbooked.
              </p>
              <p>
                Every report supports a per-location filter, plus an
                "all locations" rollup option. Same data, scoped to
                whatever question you're asking.
              </p>
            </>
          ),
          bullets: [
            'Cross-location revenue + appointment rollup',
            'Per-location performance comparison',
            'All reports filterable by location',
            'Org-level vs location-level dashboards',
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
                Lumè bills per location, not per seat. Add a front-desk
                hire without re-negotiating. Hire a bookkeeper without
                an upcharge. The price stays predictable as the team
                grows.
              </p>
              <p>
                Location count is the only variable that changes the
                bill — open a new site, the new site gets added to the
                next invoice. Close one, it comes off.
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
