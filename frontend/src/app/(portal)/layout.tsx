/**
 * Customer-portal route-group shell.
 *
 * Sibling of `(app)`, `(calendar)`, `(auth)`, `(book)`, `(popout)`.
 * Customers — not staff — sign into the portal via the magic-link
 * cookie; this layout intentionally does NOT use the staff auth gate
 * or the staff sidebar.
 *
 * Responsibilities:
 *
 *   1. **Tenant-branded chrome.** Once a customer is signed in, every
 *      portal page renders with the spa's primary color + logo. The
 *      layout fetches `/api/portal/me/` once and applies the brand
 *      via CSS custom properties so individual pages don't have to
 *      thread the tenant down through props.
 *   2. **Responsive navigation.** Desktop gets an inline top-bar nav;
 *      mobile — where most customers are — gets a fixed bottom tab
 *      bar (Home / Book / Appointments / Packages / More), the
 *      native app pattern. "More" opens a sheet with the secondary
 *      destinations + sign out.
 *   3. **Auth-aware routing.** Unauthenticated customers on a
 *      protected route are redirected to login; already-authenticated
 *      customers landing on `/portal/login` get bounced to the home.
 */

'use client';

import {
  BadgeCheck,
  CalendarClock,
  CalendarPlus,
  FileText,
  Home,
  LogOut,
  MoreHorizontal,
  Package,
  UserRound,
  X,
} from 'lucide-react';
import { usePathname, useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';

import { ApiError } from '@/lib/api';
import { useLogout, usePortalMe } from '@/lib/portal';
import { cn } from '@/lib/utils';

/** Routes that don't require an authenticated portal session. */
const PUBLIC_PORTAL_ROUTES = ['/portal/login', '/portal/magic'];

export default function PortalLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const isPublicRoute = PUBLIC_PORTAL_ROUTES.some((r) => pathname?.startsWith(r));

  const { data: customer, isLoading, error } = usePortalMe();

  const authError =
    error instanceof ApiError && (error.status === 401 || error.status === 403);

  useEffect(() => {
    if (isLoading) return;
    if (!isPublicRoute && (authError || !customer)) {
      router.replace('/portal/login');
    } else if (isPublicRoute && customer && !authError && pathname === '/portal/login') {
      router.replace('/portal');
    }
  }, [isLoading, isPublicRoute, customer, authError, router, pathname]);

  const brand = customer?.tenant.primary_color || '#1f2937';
  const logoUrl = customer?.tenant.logo_url || '';
  const spaName = customer?.tenant.name || '';
  const showChrome = Boolean(!isPublicRoute && customer);

  if (isLoading && !customer) {
    return (
      <div className="flex h-screen items-center justify-center text-sm text-muted-foreground">
        Loading…
      </div>
    );
  }

  return (
    <div
      className="min-h-screen flex flex-col bg-background"
      style={{ ['--portal-brand' as string]: brand }}
    >
      {showChrome ? <PortalTopBar spaName={spaName} logoUrl={logoUrl} /> : null}
      {/* Bottom padding on mobile clears the fixed bottom nav. */}
      <main className={cn('flex-1 flex flex-col', showChrome && 'pb-20 sm:pb-0')}>
        {children}
      </main>
      {showChrome ? <PortalBottomNav /> : null}
    </div>
  );
}

// ── Top bar (desktop nav + branding) ────────────────────────────────


const TOP_LINKS = [
  { href: '/portal', label: 'Home' },
  { href: '/portal/book', label: 'Book' },
  { href: '/portal/appointments', label: 'Appointments' },
  { href: '/portal/memberships', label: 'Memberships' },
  { href: '/portal/packages', label: 'Packages' },
  { href: '/portal/forms', label: 'Forms' },
  { href: '/portal/profile', label: 'Profile' },
];

function PortalTopBar({
  spaName,
  logoUrl,
}: {
  spaName: string;
  logoUrl: string;
}) {
  const pathname = usePathname();
  const router = useRouter();

  return (
    <header className="border-b bg-card sticky top-0 z-30">
      <div className="max-w-5xl mx-auto px-4 sm:px-6 h-14 flex items-center justify-between gap-6">
        <button
          type="button"
          onClick={() => router.push('/portal')}
          className="flex items-center gap-2.5 min-w-0"
          aria-label={`${spaName} portal home`}
        >
          {logoUrl ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={logoUrl}
              alt={spaName}
              className="h-7 w-auto max-w-[140px] object-contain"
            />
          ) : (
            <span
              className="size-7 rounded-md inline-flex items-center justify-center text-white text-xs font-semibold"
              style={{ background: 'var(--portal-brand)' }}
            >
              {spaName.charAt(0).toUpperCase()}
            </span>
          )}
          <span className="font-serif text-sm font-semibold tracking-tight truncate">
            {spaName}
          </span>
        </button>

        {/* Desktop inline nav — hidden on mobile, which uses the
            bottom tab bar instead. */}
        <nav className="hidden sm:flex items-center gap-1">
          {TOP_LINKS.map((l) => {
            const isActive =
              pathname === l.href ||
              (l.href !== '/portal' && pathname?.startsWith(l.href));
            return (
              <button
                key={l.href}
                type="button"
                onClick={() => router.push(l.href)}
                className={cn(
                  'text-sm px-3 py-1.5 rounded-md transition-colors whitespace-nowrap',
                  isActive
                    ? 'bg-muted text-foreground font-medium'
                    : 'text-muted-foreground hover:text-foreground hover:bg-muted/60',
                )}
              >
                {l.label}
              </button>
            );
          })}
        </nav>
      </div>
    </header>
  );
}

// ── Bottom tab bar (mobile nav) ─────────────────────────────────────


const BOTTOM_TABS = [
  { href: '/portal', label: 'Home', icon: Home, exact: true },
  { href: '/portal/book', label: 'Book', icon: CalendarPlus, exact: false },
  { href: '/portal/appointments', label: 'Appointments', icon: CalendarClock, exact: false },
  { href: '/portal/packages', label: 'Packages', icon: Package, exact: false },
] as const;

const MORE_LINKS = [
  { href: '/portal/memberships', label: 'Memberships', icon: BadgeCheck },
  { href: '/portal/forms', label: 'Forms', icon: FileText },
  { href: '/portal/profile', label: 'Profile', icon: UserRound },
] as const;

function PortalBottomNav() {
  const pathname = usePathname();
  const router = useRouter();
  const [moreOpen, setMoreOpen] = useState(false);
  const logout = useLogout();

  const matches = (href: string, exact: boolean) =>
    exact ? pathname === href : pathname === href || Boolean(pathname?.startsWith(`${href}/`));

  const moreActive = MORE_LINKS.some((l) => matches(l.href, false));

  const go = (href: string) => {
    setMoreOpen(false);
    router.push(href);
  };

  const onSignOut = async () => {
    setMoreOpen(false);
    try {
      await logout.mutateAsync();
    } catch {
      // Even if the logout call fails, drop the customer at login —
      // the cookie is cleared client-side on navigation anyway.
    }
    router.replace('/portal/login');
  };

  return (
    <>
      <nav
        className="sm:hidden fixed bottom-0 inset-x-0 z-30 border-t bg-card/95 backdrop-blur"
        style={{ paddingBottom: 'env(safe-area-inset-bottom)' }}
        aria-label="Portal navigation"
      >
        <div className="grid grid-cols-5">
          {BOTTOM_TABS.map((tab) => (
            <BottomTab
              key={tab.href}
              label={tab.label}
              icon={tab.icon}
              active={matches(tab.href, tab.exact)}
              onClick={() => go(tab.href)}
            />
          ))}
          <BottomTab
            label="More"
            icon={MoreHorizontal}
            active={moreOpen || moreActive}
            onClick={() => setMoreOpen(true)}
          />
        </div>
      </nav>

      {moreOpen ? (
        <div className="sm:hidden fixed inset-0 z-40">
          <button
            type="button"
            aria-label="Close menu"
            className="absolute inset-0 bg-black/40"
            onClick={() => setMoreOpen(false)}
          />
          <div
            className="absolute bottom-0 inset-x-0 rounded-t-2xl border-t bg-card shadow-lg p-2"
            style={{ paddingBottom: 'calc(env(safe-area-inset-bottom) + 0.5rem)' }}
          >
            <div className="flex items-center justify-between px-3 py-2">
              <span className="text-sm font-medium">Menu</span>
              <button
                type="button"
                onClick={() => setMoreOpen(false)}
                aria-label="Close"
                className="text-muted-foreground hover:text-foreground"
              >
                <X className="size-4" />
              </button>
            </div>
            {MORE_LINKS.map((l) => {
              const Icon = l.icon;
              return (
                <button
                  key={l.href}
                  type="button"
                  onClick={() => go(l.href)}
                  className="flex w-full items-center gap-3 rounded-lg px-3 py-3 text-sm hover:bg-muted transition-colors"
                >
                  <Icon className="size-4 text-muted-foreground" />
                  {l.label}
                </button>
              );
            })}
            <div className="my-1 border-t" />
            <button
              type="button"
              onClick={onSignOut}
              className="flex w-full items-center gap-3 rounded-lg px-3 py-3 text-sm text-destructive hover:bg-destructive/5 transition-colors"
            >
              <LogOut className="size-4" />
              Sign out
            </button>
          </div>
        </div>
      ) : null}
    </>
  );
}

function BottomTab({
  label,
  icon: Icon,
  active,
  onClick,
}: {
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-current={active ? 'page' : undefined}
      className={cn(
        'flex flex-col items-center justify-center gap-0.5 py-2 transition-colors',
        active ? 'font-medium' : 'text-muted-foreground',
      )}
      style={active ? { color: 'var(--portal-brand)' } : undefined}
    >
      <Icon className="size-5" />
      <span className="text-[10px] leading-none truncate max-w-full px-0.5">
        {label}
      </span>
    </button>
  );
}
