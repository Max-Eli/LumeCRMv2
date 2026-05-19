/**
 * Mobile navigation shell.
 *
 * Renders ONLY at viewport widths below `lg` (1024px). The desktop
 * `<AppSidebar>` is hidden at that breakpoint and this takes over.
 *
 * Three-part pattern (Stripe / Shopify / Linear iOS):
 *   - **Top app bar** (sticky, top) — hamburger + Lumè brand + page
 *     actions slot. Hamburger opens the full nav drawer.
 *   - **Bottom tab bar** (sticky, bottom, safe-area-aware) — 4 primary
 *     destinations + a "More" tile that opens the drawer.
 *   - **Drawer** — side sheet that holds the rest of the nav (catalog,
 *     staff, marketing, forms, reports, social, organization) plus
 *     the user profile + sign-out.
 *
 * The drawer reuses the same `NAV_LINKS` declared on the desktop
 * sidebar so nav additions only need to be made in one place.
 *
 * Role + comingSoon gating mirrors the sidebar: links the current
 * member can't visit (or that aren't shipped yet) render disabled,
 * not clickable through to a 403.
 */

'use client';

import {
  Calendar,
  ChevronRight,
  LogOut,
  type LucideIcon,
  Menu,
  MoreHorizontal,
  Users,
} from 'lucide-react';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';

import { type NavLink, NAV_LINKS } from '@/components/app-sidebar';
import { BrandMark } from '@/components/brand-mark';
import { InitialsAvatar } from '@/components/initials-avatar';
import { LocationSwitcher } from '@/components/location-switcher';
import {
  Sheet,
  SheetBody,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet';
import type { User } from '@/lib/auth';
import { useLogout } from '@/lib/auth';
import {
  hasMultipleLocations,
  useActiveLocation,
  useLocations,
} from '@/lib/locations';
import { cn } from '@/lib/utils';

export interface MobileNavProps {
  user: User;
}

/** Primary tabs surfaced on the bottom bar. Order chosen for how
 *  often operators reach for each: calendar (every minute), clients
 *  (every booking), catalog (price/service edits), then "More" for
 *  everything else. Dashboard intentionally not pinned — it's a
 *  landing page, not a destination during real work. */
const BOTTOM_TABS: ReadonlyArray<{
  href: string;
  label: string;
  icon: LucideIcon;
  /** Used by the active-state matcher — a route is active when the
   *  current path starts with this prefix. */
  match: string;
}> = [
  { href: '/calendar', label: 'Calendar', icon: Calendar, match: '/calendar' },
  { href: '/clients', label: 'Clients', icon: Users, match: '/clients' },
  {
    href: '/catalog/services',
    label: 'Catalog',
    icon: getCatalogIcon(),
    match: '/catalog',
  },
];

function getCatalogIcon(): LucideIcon {
  // Pulled from NAV_LINKS so the icon stays in lockstep with the
  // sidebar entry. Fallback to nothing — TS keeps everyone honest.
  const link = NAV_LINKS.find((l) => l.href === '/catalog');
  return (link?.icon ?? Calendar) as LucideIcon;
}

export function MobileNav({ user }: MobileNavProps) {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const pathname = usePathname();

  // Close the drawer whenever the route changes. Without this the
  // drawer stays open behind the new page until the user manually
  // closes it.
  useEffect(() => {
    setDrawerOpen(false);
  }, [pathname]);

  return (
    <>
      {/* ── Top app bar ───────────────────────────────────────── */}
      <header className="lg:hidden sticky top-0 z-30 h-14 border-b bg-background/90 backdrop-blur supports-[backdrop-filter]:bg-background/70">
        <div className="flex h-full items-center px-3 gap-2">
          <button
            type="button"
            onClick={() => setDrawerOpen(true)}
            aria-label="Open navigation"
            className="inline-flex size-9 items-center justify-center rounded-md text-foreground/80 hover:bg-muted hover:text-foreground transition-colors"
          >
            <Menu className="size-5" aria-hidden />
          </button>
          <Link
            href="/dashboard"
            className="inline-flex items-center"
            aria-label="Dashboard"
          >
            <BrandMark variant="lockup" size={32} />
          </Link>
        </div>
      </header>

      {/* ── Bottom tab bar ────────────────────────────────────── */}
      <nav
        className="lg:hidden fixed inset-x-0 bottom-0 z-30 border-t bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/80 pb-[env(safe-area-inset-bottom)]"
        aria-label="Primary"
      >
        <ul className="flex items-stretch">
          {BOTTOM_TABS.map((tab) => {
            const active = pathname?.startsWith(tab.match) ?? false;
            const Icon = tab.icon;
            return (
              <li key={tab.href} className="flex-1">
                <Link
                  href={tab.href}
                  className={cn(
                    'flex h-14 flex-col items-center justify-center gap-0.5 transition-colors',
                    active
                      ? 'text-foreground'
                      : 'text-muted-foreground hover:text-foreground',
                  )}
                  aria-current={active ? 'page' : undefined}
                >
                  <Icon className={cn('size-5', active && 'text-foreground')} aria-hidden />
                  <span className={cn('text-[10.5px] font-medium', active && 'text-foreground')}>
                    {tab.label}
                  </span>
                </Link>
              </li>
            );
          })}
          <li className="flex-1">
            <button
              type="button"
              onClick={() => setDrawerOpen(true)}
              className="flex h-14 w-full flex-col items-center justify-center gap-0.5 text-muted-foreground hover:text-foreground transition-colors"
              aria-label="More navigation"
            >
              <MoreHorizontal className="size-5" aria-hidden />
              <span className="text-[10.5px] font-medium">More</span>
            </button>
          </li>
        </ul>
      </nav>

      {/* ── Drawer ────────────────────────────────────────────── */}
      <Sheet open={drawerOpen} onOpenChange={setDrawerOpen}>
        <SheetContent side="left" className="w-80 max-w-[88vw] p-0 flex flex-col">
          <SheetHeader className="border-b">
            <SheetTitle className="sr-only">Navigation</SheetTitle>
            <div className="flex items-center gap-3 px-5 py-4">
              <BrandMark variant="lockup" size={36} />
            </div>
          </SheetHeader>
          <SheetBody className="flex-1 overflow-y-auto p-0">
            <MobileDrawerContents user={user} />
          </SheetBody>
        </SheetContent>
      </Sheet>
    </>
  );
}

// ── Drawer contents ─────────────────────────────────────────────────

function MobileDrawerContents({ user }: { user: User }) {
  const router = useRouter();
  const logout = useLogout();
  const pathname = usePathname();
  const { data: locations } = useLocations();
  const { location: activeLocation } = useActiveLocation();
  const showLocationSwitcher = hasMultipleLocations(locations) && activeLocation !== null;

  const primaryMembership = user.memberships[0];
  const role = primaryMembership?.role ?? '';
  const userDisplayName =
    user.first_name || user.last_name
      ? `${user.first_name} ${user.last_name}`.trim()
      : user.email;

  const visibleLinks = NAV_LINKS.filter((link) => isLinkVisible(link, role));

  const handleSignOut = () => {
    logout.mutate(undefined, {
      onSettled: () => router.replace('/login'),
    });
  };

  return (
    <div className="flex flex-col h-full">
      {showLocationSwitcher ? (
        <div className="px-4 pt-4">
          <LocationSwitcher />
        </div>
      ) : null}

      <nav className="flex-1 px-2 py-4 space-y-0.5">
        {visibleLinks.map((link) => (
          <MobileDrawerLink
            key={link.href}
            link={link}
            currentPath={pathname ?? ''}
            role={role}
          />
        ))}
      </nav>

      <div className="border-t px-4 py-4 space-y-3">
        <div className="flex items-center gap-3">
          <InitialsAvatar name={userDisplayName || user.email} size="default" />
          <div className="min-w-0 flex-1">
            <p className="text-sm font-medium truncate">{userDisplayName}</p>
            <p className="text-xs text-muted-foreground truncate">{user.email}</p>
          </div>
        </div>
        <button
          type="button"
          onClick={handleSignOut}
          className="w-full inline-flex items-center justify-center gap-1.5 h-9 rounded-md border bg-card text-sm font-medium hover:bg-muted transition-colors"
        >
          <LogOut className="size-3.5" />
          Sign out
        </button>
      </div>
    </div>
  );
}

function MobileDrawerLink({
  link,
  currentPath,
  role,
}: {
  link: NavLink;
  currentPath: string;
  role: string;
}) {
  const [expanded, setExpanded] = useState(() =>
    currentPath.startsWith(link.href),
  );
  const isActive = currentPath === link.href || currentPath.startsWith(`${link.href}/`);
  const hasChildren = !!link.children && link.children.length > 0;
  const Icon = link.icon;

  const visibleChildren = hasChildren
    ? link.children!.filter(
        (c) => !c.roles || (c.roles as readonly string[]).includes(role),
      )
    : [];

  if (link.comingSoon) {
    return (
      <div className="flex items-center gap-3 px-3 py-2.5 rounded-md text-sm text-muted-foreground/70 cursor-not-allowed">
        <Icon className="size-4 shrink-0" aria-hidden />
        <span className="flex-1">{link.label}</span>
        <span className="text-[10px] uppercase tracking-wide text-muted-foreground/60">Soon</span>
      </div>
    );
  }

  if (visibleChildren.length === 0) {
    return (
      <Link
        href={link.href}
        className={cn(
          'flex items-center gap-3 px-3 py-2.5 rounded-md text-sm transition-colors',
          isActive
            ? 'bg-sidebar-accent text-sidebar-accent-foreground font-medium'
            : 'text-foreground/80 hover:bg-muted hover:text-foreground',
        )}
      >
        <Icon className="size-4 shrink-0" aria-hidden />
        <span>{link.label}</span>
      </Link>
    );
  }

  return (
    <div>
      <button
        type="button"
        onClick={() => setExpanded((prev) => !prev)}
        className={cn(
          'flex w-full items-center gap-3 px-3 py-2.5 rounded-md text-sm transition-colors',
          isActive
            ? 'text-foreground font-medium'
            : 'text-foreground/80 hover:bg-muted hover:text-foreground',
        )}
        aria-expanded={expanded}
      >
        <Icon className="size-4 shrink-0" aria-hidden />
        <span className="flex-1 text-left">{link.label}</span>
        <ChevronRight
          className={cn(
            'size-3.5 text-muted-foreground transition-transform',
            expanded && 'rotate-90',
          )}
          aria-hidden
        />
      </button>
      {expanded ? (
        <ul className="ml-6 mt-0.5 mb-1 space-y-0.5 border-l pl-2">
          {visibleChildren.map((child) => {
            const childActive = currentPath === child.href;
            return (
              <li key={child.href}>
                <Link
                  href={child.href}
                  className={cn(
                    'block px-3 py-2 rounded-md text-sm transition-colors',
                    childActive
                      ? 'bg-sidebar-accent text-sidebar-accent-foreground font-medium'
                      : 'text-muted-foreground hover:bg-muted hover:text-foreground',
                  )}
                >
                  {child.label}
                </Link>
              </li>
            );
          })}
        </ul>
      ) : null}
    </div>
  );
}

function isLinkVisible(link: NavLink, role: string): boolean {
  if (!link.roles || link.roles.length === 0) return true;
  return (link.roles as readonly string[]).includes(role);
}
