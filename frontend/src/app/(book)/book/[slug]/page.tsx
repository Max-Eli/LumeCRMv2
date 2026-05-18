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

import { ChevronRight, Search, X } from 'lucide-react';
import { useRouter, useSearchParams } from 'next/navigation';
import { use, useMemo, useState } from 'react';

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

  // Filter UI state. `null` category = All.
  const [query, setQuery] = useState('');
  const [categoryFilter, setCategoryFilter] = useState<string | null>(null);

  const allCategories = useMemo(
    () =>
      Array.from(new Set(services.map((s) => s.category_name || 'Other'))).sort(),
    [services],
  );

  const filteredServices = useMemo(() => {
    const q = query.trim().toLowerCase();
    return services.filter((s) => {
      if (categoryFilter && (s.category_name || 'Other') !== categoryFilter) {
        return false;
      }
      if (!q) return true;
      const hay = `${s.name} ${s.description ?? ''}`.toLowerCase();
      return hay.includes(q);
    });
  }, [services, categoryFilter, query]);

  // Group services by category for a scannable layout.
  const grouped = useMemo(() => groupByCategory(filteredServices), [filteredServices]);
  const showCategoryFilter = allCategories.length > 1;

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
        subtitle="Browse our menu and pick a service to see live availability."
      />

      {welcomeMessage ? (
        <div
          className="rounded-2xl px-6 py-5 mb-10 text-[15px] leading-relaxed shadow-sm"
          style={{
            background: `${primaryColor}0a`,
            color: '#1c1917',
            border: `1px solid ${primaryColor}22`,
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
        <div className="mb-10">
          <p className="text-[11px] uppercase tracking-wider text-stone-500 font-medium mb-2.5">
            Location
          </p>
          <div className="flex flex-wrap gap-2">
            {locations.map((loc) => (
              <button
                key={loc.id}
                type="button"
                onClick={() => handlePickLocation(loc.id)}
                className={cn(
                  'rounded-full border px-4 py-2 text-sm font-medium transition-all',
                  activeLocation?.id === loc.id
                    ? 'border-stone-900 bg-stone-900 text-white shadow-sm'
                    : 'border-stone-300 bg-white text-stone-700 hover:border-stone-900 hover:bg-stone-50',
                )}
              >
                {loc.name}
              </button>
            ))}
          </div>
        </div>
      ) : null}

      {showCategoryFilter ? (
        <div className="sticky top-[72px] sm:top-[80px] z-[9] -mx-4 sm:-mx-6 px-4 sm:px-6 py-3 bg-white/95 backdrop-blur supports-[backdrop-filter]:bg-white/80 border-b border-stone-200/80 mb-8 space-y-2.5">
          <div className="relative">
            <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 size-4 text-stone-400 pointer-events-none" />
            <input
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search services…"
              className="w-full h-10 pl-10 pr-10 rounded-full border border-stone-200 bg-white text-sm placeholder:text-stone-400 focus:outline-none focus:border-stone-900 focus:ring-2 focus:ring-stone-900/5 transition-colors"
            />
            {query ? (
              <button
                type="button"
                onClick={() => setQuery('')}
                aria-label="Clear search"
                className="absolute right-2 top-1/2 -translate-y-1/2 inline-flex size-7 items-center justify-center rounded-full text-stone-400 hover:text-stone-700 hover:bg-stone-100 transition-colors"
              >
                <X className="size-3.5" />
              </button>
            ) : null}
          </div>
          <div className="flex gap-1.5 overflow-x-auto -mx-4 sm:-mx-6 px-4 sm:px-6 pb-0.5 scrollbar-none">
            <CategoryChip
              active={categoryFilter === null}
              onClick={() => setCategoryFilter(null)}
              primaryColor={primaryColor}
            >
              All
            </CategoryChip>
            {allCategories.map((cat) => (
              <CategoryChip
                key={cat}
                active={categoryFilter === cat}
                onClick={() => setCategoryFilter(cat)}
                primaryColor={primaryColor}
              >
                {cat}
              </CategoryChip>
            ))}
          </div>
        </div>
      ) : null}

      {filteredServices.length === 0 ? (
        <div className="rounded-2xl border border-stone-200 bg-stone-50/60 px-6 py-10 text-center">
          <p className="font-serif text-lg font-semibold text-stone-900">No matches</p>
          <p className="text-sm text-stone-600 mt-1.5">
            Try a different search or clear the filters.
          </p>
          <button
            type="button"
            onClick={() => { setQuery(''); setCategoryFilter(null); }}
            className="mt-4 inline-flex items-center gap-1.5 rounded-full border border-stone-300 bg-white px-4 py-1.5 text-xs font-medium text-stone-700 hover:border-stone-900 hover:bg-stone-50 transition-colors"
          >
            Clear filters
          </button>
        </div>
      ) : null}

      <div className="space-y-10">
        {grouped.map(({ categoryName, items }) => (
          <section key={categoryName}>
            <div className="flex items-baseline gap-3 mb-4">
              <h2 className="font-serif text-xl font-semibold tracking-tight text-stone-900">
                {categoryName}
              </h2>
              <span
                className="h-px flex-1"
                style={{ background: `${primaryColor}33` }}
              />
              <span className="text-xs text-stone-500 font-medium">
                {items.length} service{items.length === 1 ? '' : 's'}
              </span>
            </div>
            <ul className="grid grid-cols-1 gap-3">
              {items.map((service) => (
                <li key={service.id}>
                  <button
                    type="button"
                    onClick={() => handlePickService(service.id)}
                    className="w-full text-left rounded-xl border border-stone-200 bg-white px-5 py-5 sm:px-6 sm:py-5 flex flex-col sm:flex-row sm:items-center gap-4 sm:gap-6 transition-all hover:border-stone-900 hover:shadow-md hover:-translate-y-0.5 group"
                  >
                    <div className="flex-1 min-w-0">
                      <div className="font-medium text-stone-900 text-[15px] sm:text-base group-hover:opacity-90">
                        {service.name}
                      </div>
                      {service.description ? (
                        <div className="text-sm text-stone-600 mt-1.5 leading-relaxed line-clamp-2">
                          {service.description}
                        </div>
                      ) : null}
                      <div className="flex items-center gap-1.5 text-[13px] text-stone-500 mt-2.5">
                        <span className="font-medium text-stone-700">
                          {formatDuration(service.duration_minutes)}
                        </span>
                        {service.price_cents > 0 ? (
                          <>
                            <span className="text-stone-300">·</span>
                            <span
                              className="inline-flex items-center font-semibold"
                              style={{ color: primaryColor }}
                            >
                              {formatPriceCents(service.price_cents)}
                            </span>
                          </>
                        ) : null}
                      </div>
                    </div>
                    <div
                      className="inline-flex items-center gap-1 rounded-full border border-stone-200 px-3.5 py-1.5 text-xs font-semibold text-stone-700 self-start sm:self-center group-hover:border-stone-900 group-hover:text-white group-hover:bg-stone-900 transition-colors shrink-0"
                    >
                      Book
                      <ChevronRight className="size-3.5" />
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>

      <footer className="mt-16 pt-6 border-t border-stone-200 flex flex-col sm:flex-row items-center justify-between gap-3">
        <p className="text-xs text-stone-500 inline-flex items-center gap-1.5">
          <span
            className="inline-block size-1.5 rounded-full"
            style={{ background: primaryColor }}
          />
          Secure booking · Cancel free up to 24 hours before
        </p>
        <p className="text-xs text-stone-400">
          Powered by{' '}
          <a
            href="https://www.lumecrm.com"
            target="_blank"
            rel="noreferrer"
            className="font-medium text-stone-600 hover:text-stone-900 transition-colors"
          >
            Lumè
          </a>
        </p>
      </footer>
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
    <div className="mb-10">
      {eyebrow ? (
        <p className="text-[11px] uppercase tracking-[0.18em] text-stone-500 font-semibold mb-3">
          {eyebrow}
        </p>
      ) : null}
      <h1 className="font-serif text-3xl sm:text-[2.5rem] font-semibold tracking-tight text-stone-900 leading-[1.1]">
        {title}
      </h1>
      {subtitle ? (
        <p className="text-stone-600 mt-3 leading-relaxed max-w-prose">{subtitle}</p>
      ) : null}
    </div>
  );
}

function CategoryChip({
  active,
  onClick,
  primaryColor,
  children,
}: {
  active: boolean;
  onClick: () => void;
  primaryColor: string;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        'shrink-0 rounded-full px-3.5 py-1.5 text-xs font-medium transition-all border whitespace-nowrap',
        active
          ? 'text-white shadow-sm border-transparent'
          : 'border-stone-200 bg-white text-stone-700 hover:border-stone-900 hover:bg-stone-50',
      )}
      style={active ? { background: primaryColor } : undefined}
    >
      {children}
    </button>
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
