/**
 * `/book/[slug]` — service catalog (step 1 of the booking flow).
 *
 * The customer's first stop. Brand header (sticky) → optional welcome
 * card + location picker → sticky search + category-chip filter →
 * service grid grouped by category. Tapping a service advances to
 * step 2 (provider + slot picker) carrying the location id as a
 * search param.
 *
 * Visual goals: high-end medspa, generous whitespace, serif headings
 * with a sans body, tenant primary color used sparingly for accents.
 *
 * State strategy: location selection lives in the URL (`?location=`)
 * so reload + back-button work cleanly and links are shareable. The
 * search query and active category chip are component-local since
 * they don't need to round-trip.
 */

'use client';

import { ChevronRight, Clock, MapPin, Search, X } from 'lucide-react';
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

  const urlLocationId = searchParams.get('location');
  const activeLocation = useMemo<BookingLocation | null>(() => {
    if (locations.length === 0) return null;
    if (urlLocationId) {
      const found = locations.find((l) => String(l.id) === urlLocationId);
      if (found) return found;
    }
    return locations[0];
  }, [locations, urlLocationId]);

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
      <main className="max-w-4xl mx-auto px-4 sm:px-6 py-16">
        <header className="text-center">
          <p className="text-[11px] uppercase tracking-[0.22em] text-stone-500 font-semibold">
            Book online
          </p>
          <h1 className="font-serif text-3xl sm:text-4xl font-semibold tracking-tight text-stone-900 mt-3">
            No services available right now
          </h1>
          <p className="text-stone-600 mt-3 leading-relaxed">
            This spa hasn't added bookable services yet. Please check back soon,
            or contact them directly.
          </p>
        </header>
      </main>
    );
  }

  return (
    <>
      <section>
        <div className="max-w-4xl mx-auto px-4 sm:px-6 pt-12 sm:pt-16 pb-10 sm:pb-12">
          <p className="text-[11px] uppercase tracking-[0.22em] text-stone-500 font-semibold mb-3.5">
            Book online
          </p>
          <h1 className="font-serif text-[2rem] leading-[1.08] sm:text-5xl sm:leading-[1.05] font-semibold tracking-tight text-stone-900 max-w-2xl">
            What can we help you with today?
          </h1>
          <p className="text-stone-600 mt-4 text-[15px] sm:text-base leading-relaxed max-w-xl">
            Browse the menu, pick a service, and choose a time that works for you.
          </p>

          {welcomeMessage ? (
            <div
              className="mt-7 rounded-2xl px-5 py-4 text-[14px] leading-relaxed max-w-2xl"
              style={{
                background: `${primaryColor}0a`,
                color: '#1c1917',
                border: `1px solid ${primaryColor}1f`,
              }}
            >
              {welcomeMessage.split('\n').map((line, i) => (
                <p key={i} className={i > 0 ? 'mt-1.5' : undefined}>
                  {line}
                </p>
              ))}
            </div>
          ) : null}

          {locations.length > 1 ? (
            <div className="mt-7">
              <p className="text-[11px] uppercase tracking-wider text-stone-500 font-semibold mb-2.5 inline-flex items-center gap-1.5">
                <MapPin className="size-3.5" aria-hidden />
                Choose a location
              </p>
              <div className="flex flex-wrap gap-2">
                {locations.map((loc) => (
                  <button
                    key={loc.id}
                    type="button"
                    onClick={() => handlePickLocation(loc.id)}
                    className={cn(
                      'rounded-full border px-4 py-1.5 text-sm font-medium transition-all',
                      activeLocation?.id === loc.id
                        ? 'border-stone-900 bg-stone-900 text-white shadow-sm'
                        : 'border-stone-200 bg-white text-stone-700 hover:border-stone-400 hover:bg-stone-50',
                    )}
                  >
                    {loc.name}
                  </button>
                ))}
              </div>
            </div>
          ) : null}
        </div>
      </section>

      {showCategoryFilter ? (
        <div className="sticky top-20 sm:top-[88px] z-[9] border-b border-stone-200/70 bg-white/85 backdrop-blur-md supports-[backdrop-filter]:bg-white/70">
          <div className="max-w-4xl mx-auto px-4 sm:px-6 py-3 flex flex-col sm:flex-row sm:items-center gap-2.5 sm:gap-4">
            <div className="relative sm:w-72 sm:shrink-0">
              <Search
                className="absolute left-3.5 top-1/2 -translate-y-1/2 size-[15px] text-stone-400 pointer-events-none"
                aria-hidden
              />
              <input
                type="search"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search services"
                className="w-full h-10 pl-10 pr-10 rounded-full border border-stone-200 bg-stone-50 text-sm text-stone-900 placeholder:text-stone-400 focus:outline-none focus:bg-white focus:border-stone-400 focus:ring-4 focus:ring-stone-900/5 transition-all"
              />
              {query ? (
                <button
                  type="button"
                  onClick={() => setQuery('')}
                  aria-label="Clear search"
                  className="absolute right-1.5 top-1/2 -translate-y-1/2 inline-flex size-7 items-center justify-center rounded-full text-stone-400 hover:text-stone-700 hover:bg-stone-100 transition-colors"
                >
                  <X className="size-3.5" />
                </button>
              ) : null}
            </div>
            <div className="flex gap-1.5 overflow-x-auto -mx-4 px-4 sm:mx-0 sm:px-0 sm:flex-1 [&::-webkit-scrollbar]:hidden [scrollbar-width:none]">
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
        </div>
      ) : null}

      <main className="max-w-4xl mx-auto px-4 sm:px-6 pt-10 sm:pt-12 pb-16 sm:pb-20">
        {filteredServices.length === 0 ? (
          <div className="rounded-2xl border border-stone-200 bg-white px-8 py-14 text-center">
            <p className="font-serif text-lg font-semibold text-stone-900">
              No services match your search
            </p>
            <p className="text-sm text-stone-600 mt-1.5">
              Try a different search or clear the filters.
            </p>
            <button
              type="button"
              onClick={() => {
                setQuery('');
                setCategoryFilter(null);
              }}
              className="mt-5 inline-flex items-center gap-1.5 rounded-full border border-stone-300 bg-white px-4 py-1.5 text-xs font-medium text-stone-700 hover:border-stone-900 hover:bg-stone-50 transition-colors"
            >
              Clear filters
            </button>
          </div>
        ) : (
          <div className="space-y-12 sm:space-y-14">
            {grouped.map(({ categoryName, items }) => (
              <section key={categoryName}>
                <header className="flex items-baseline justify-between gap-3 mb-5">
                  <h2 className="font-serif text-xl sm:text-2xl font-semibold tracking-tight text-stone-900">
                    {categoryName}
                  </h2>
                  <span className="text-xs text-stone-400 font-medium tabular-nums">
                    {items.length} service{items.length === 1 ? '' : 's'}
                  </span>
                </header>
                <ul className="grid grid-cols-1 sm:grid-cols-2 gap-3 sm:gap-4">
                  {items.map((service) => (
                    <li key={service.id}>
                      <ServiceCard
                        service={service}
                        primaryColor={primaryColor}
                        onPick={() => handlePickService(service.id)}
                      />
                    </li>
                  ))}
                </ul>
              </section>
            ))}
          </div>
        )}

        <footer className="mt-20 pt-6 border-t border-stone-200/70 flex flex-col sm:flex-row items-center justify-between gap-3">
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
      </main>
    </>
  );
}

function ServiceCard({
  service,
  primaryColor,
  onPick,
}: {
  service: BookableService;
  primaryColor: string;
  onPick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onPick}
      className="group w-full h-full text-left rounded-2xl border border-stone-200 bg-white p-5 sm:p-6 transition-all hover:border-stone-300 hover:shadow-[0_4px_24px_-12px_rgba(28,25,23,0.18)] hover:-translate-y-0.5 focus:outline-none focus-visible:ring-2 focus-visible:ring-stone-900 focus-visible:ring-offset-2"
    >
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <h3 className="font-medium text-stone-900 text-[15px] sm:text-base leading-tight">
            {service.name}
          </h3>
          {service.description ? (
            <p className="text-[13px] text-stone-600 mt-2 leading-relaxed line-clamp-2">
              {service.description}
            </p>
          ) : null}
        </div>
        <ChevronRight
          className="size-4 text-stone-400 mt-0.5 shrink-0 transition-all group-hover:text-stone-900 group-hover:translate-x-0.5"
          aria-hidden
        />
      </div>
      <div className="mt-4 sm:mt-5 flex items-center gap-3 text-[13px]">
        <span className="inline-flex items-center gap-1.5 text-stone-500">
          <Clock className="size-3.5" aria-hidden />
          <span className="tabular-nums">{formatDuration(service.duration_minutes)}</span>
        </span>
        {service.price_cents > 0 ? (
          <>
            <span className="text-stone-300" aria-hidden>·</span>
            <span
              className="font-semibold tabular-nums"
              style={{ color: primaryColor }}
            >
              {formatPriceCents(service.price_cents)}
            </span>
          </>
        ) : null}
      </div>
    </button>
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
          : 'border-stone-200 bg-white text-stone-700 hover:border-stone-400 hover:bg-stone-50',
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
