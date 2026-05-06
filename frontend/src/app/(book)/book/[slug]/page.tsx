/**
 * `/book/[slug]` — service catalog (step 1 of the booking flow).
 *
 * The customer's first stop. Shows the spa's branded header, a
 * location picker (one-tap on single-location tenants — auto-
 * selected), and the catalog of services grouped by category. Click
 * a service → step 2 (provider + slot picker), with the location id
 * carried as a search param.
 *
 * State strategy: location selection lives in the URL (`?location=`)
 * so reload + back-button work cleanly and links are shareable. No
 * client-side form state survives across pages — every step
 * resolves what it needs from the URL + the tenant info fetch.
 */

'use client';

import { ChevronRight } from 'lucide-react';
import { useRouter, useSearchParams } from 'next/navigation';
import { use, useMemo } from 'react';

import { ApiError } from '@/lib/api';
import {
  type BookableService,
  type BookingLocation,
  formatDuration,
  formatPriceCents,
  useBookingServices,
  useBookingTenantInfo,
} from '@/lib/booking';
import { cn } from '@/lib/utils';

import { BrandHeader } from '../../_components/brand-header';
import {
  BookingContainer,
  BookingLoadingState,
  BookingNotFoundState,
} from '../../_components/page-shell';

export default function BookingCatalogPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = use(params);
  const tenantQ = useBookingTenantInfo(slug);
  const servicesQ = useBookingServices(slug);

  if (tenantQ.isLoading || servicesQ.isLoading) {
    return <BookingLoadingState />;
  }
  if (tenantQ.error || !tenantQ.data) {
    const is404 = tenantQ.error instanceof ApiError && tenantQ.error.status === 404;
    return (
      <BookingNotFoundState
        title={is404 ? 'Spa not found' : 'Could not load this booking page'}
        message={
          is404
            ? "This booking link doesn't exist or the spa isn't accepting online bookings right now."
            : 'Please refresh and try again.'
        }
      />
    );
  }

  const tenant = tenantQ.data;
  const services = servicesQ.data ?? [];

  return (
    <>
      <BrandHeader
        tenantName={tenant.name}
        logoUrl={tenant.logo_url}
        primaryColor={tenant.primary_color}
        bookingHref={`/book/${slug}`}
      />
      <CatalogBody
        slug={slug}
        primaryColor={tenant.primary_color}
        locations={tenant.locations}
        services={services}
        welcomeMessage={tenant.welcome_message}
      />
    </>
  );
}

function CatalogBody({
  slug,
  primaryColor,
  locations,
  services,
  welcomeMessage,
}: {
  slug: string;
  primaryColor: string;
  locations: BookingLocation[];
  services: BookableService[];
  welcomeMessage: string;
}) {
  const router = useRouter();
  const searchParams = useSearchParams();

  // Location resolution: URL → only-location → first.
  const urlLocationId = searchParams.get('location');
  const activeLocation = useMemo<BookingLocation | null>(() => {
    if (locations.length === 0) return null;
    if (urlLocationId) {
      const found = locations.find((l) => String(l.id) === urlLocationId);
      if (found) return found;
    }
    return locations[0];
  }, [locations, urlLocationId]);

  // Group services by category for a scannable layout.
  const grouped = useMemo(() => groupByCategory(services), [services]);

  const handlePickService = (serviceId: number) => {
    if (!activeLocation) return;
    router.push(`/book/${slug}/${serviceId}?location=${activeLocation.id}`);
  };

  const handlePickLocation = (locationId: number) => {
    const params = new URLSearchParams(searchParams);
    params.set('location', String(locationId));
    router.replace(`/book/${slug}?${params.toString()}`);
  };

  if (services.length === 0) {
    return (
      <BookingContainer>
        <SectionHeader
          eyebrow="Book online"
          title="No services available right now"
          subtitle="This spa hasn't added bookable services yet. Please check back soon, or contact them directly."
        />
      </BookingContainer>
    );
  }

  return (
    <BookingContainer>
      <SectionHeader
        eyebrow="Book online"
        title="What can we help you with today?"
        subtitle="Pick a service to see availability."
      />

      {welcomeMessage ? (
        <div
          className="rounded-lg px-5 py-4 mb-8 text-sm leading-relaxed"
          style={{
            background: `${primaryColor}0d`,
            color: '#1c1917',
            borderLeft: `3px solid ${primaryColor}`,
          }}
        >
          {welcomeMessage.split('\n').map((line, i) => (
            <p key={i} className={i > 0 ? 'mt-2' : undefined}>
              {line}
            </p>
          ))}
        </div>
      ) : null}

      {locations.length > 1 ? (
        <div className="mb-8">
          <p className="text-[11px] uppercase tracking-wider text-stone-500 font-medium mb-2">
            Location
          </p>
          <div className="flex flex-wrap gap-2">
            {locations.map((loc) => (
              <button
                key={loc.id}
                type="button"
                onClick={() => handlePickLocation(loc.id)}
                className={cn(
                  'rounded-full border px-3.5 py-1.5 text-sm transition-colors',
                  activeLocation?.id === loc.id
                    ? 'border-stone-900 bg-stone-900 text-white'
                    : 'border-stone-300 bg-white text-stone-700 hover:border-stone-400',
                )}
              >
                {loc.name}
              </button>
            ))}
          </div>
        </div>
      ) : null}

      <div className="space-y-8">
        {grouped.map(({ categoryName, items }) => (
          <section key={categoryName}>
            <h2 className="font-serif text-lg font-semibold tracking-tight text-stone-900 mb-3">
              {categoryName}
            </h2>
            <ul className="divide-y divide-stone-200 rounded-lg border border-stone-200 bg-white overflow-hidden">
              {items.map((service) => (
                <li key={service.id}>
                  <button
                    type="button"
                    onClick={() => handlePickService(service.id)}
                    className="w-full text-left px-5 py-4 flex items-center gap-4 hover:bg-stone-50 transition-colors group"
                  >
                    <div className="flex-1 min-w-0">
                      <div className="font-medium text-stone-900">
                        {service.name}
                      </div>
                      {service.description ? (
                        <div className="text-sm text-stone-600 mt-1 line-clamp-2">
                          {service.description}
                        </div>
                      ) : null}
                      <div className="text-xs text-stone-500 mt-2">
                        {formatDuration(service.duration_minutes)}
                        {service.price_cents > 0 ? (
                          <>
                            <span className="mx-1.5">·</span>
                            {formatPriceCents(service.price_cents)}
                          </>
                        ) : null}
                      </div>
                    </div>
                    <ChevronRight
                      className="size-5 text-stone-400 group-hover:text-stone-600 transition-colors shrink-0"
                      style={{ color: undefined }}
                    />
                  </button>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>

      <p className="text-xs text-stone-500 mt-12 text-center">
        Powered by Lumè · {/* tenant name anchor */}
        <span style={{ color: primaryColor }}>book with confidence</span>
      </p>
    </BookingContainer>
  );
}

function SectionHeader({
  eyebrow,
  title,
  subtitle,
}: {
  eyebrow?: string;
  title: string;
  subtitle?: string;
}) {
  return (
    <div className="mb-8">
      {eyebrow ? (
        <p className="text-[11px] uppercase tracking-wider text-stone-500 font-medium mb-2">
          {eyebrow}
        </p>
      ) : null}
      <h1 className="font-serif text-3xl sm:text-4xl font-semibold tracking-tight text-stone-900">
        {title}
      </h1>
      {subtitle ? (
        <p className="text-stone-600 mt-2 leading-relaxed">{subtitle}</p>
      ) : null}
    </div>
  );
}

function groupByCategory(services: BookableService[]) {
  const groups = new Map<string, BookableService[]>();
  for (const s of services) {
    const key = s.category_name || 'Other';
    const list = groups.get(key) ?? [];
    list.push(s);
    groups.set(key, list);
  }
  return Array.from(groups.entries()).map(([categoryName, items]) => ({
    categoryName,
    items,
  }));
}
