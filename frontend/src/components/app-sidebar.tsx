/**
 * Sidebar shell for authenticated app routes.
 *
 * Pinned to the viewport — the page's scroll container is `<main>`, not the
 * document. Holds the brand wordmark, primary nav, and the current user's
 * profile chip + sign-out button.
 *
 * Collapsible: a toggle button shrinks the sidebar to an icon-only rail. State
 * persists in localStorage so the user's choice survives reloads.
 *
 * Nav routes are declared in the local `NAV_LINKS` array; routes flagged
 * `comingSoon` render as disabled placeholders so we can ship the shell ahead
 * of the destinations.
 */

'use client';

import {
  BarChart3,
  Building2,
  Calendar,
  CalendarClock,
  FileText,
  Inbox,
  LayoutDashboard,
  LogOut,
  Megaphone,
  PanelLeftClose,
  PanelLeftOpen,
  Sparkles,
  Users,
  UsersRound,
} from 'lucide-react';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';

import { BrandMark } from '@/components/brand-mark';
import { InitialsAvatar } from '@/components/initials-avatar';
import { LocationSwitcher } from '@/components/location-switcher';
import { Button } from '@/components/ui/button';
import type { User } from '@/lib/auth';
import { useLogout } from '@/lib/auth';
import {
  hasMultipleLocations,
  locationDisplayName,
  useActiveLocation,
  useLocations,
} from '@/lib/locations';
import { cn } from '@/lib/utils';

const COLLAPSED_KEY = 'lume_sidebar_collapsed';

export interface NavLink {
  href: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  comingSoon?: boolean;
  /** Which IA group this link belongs to. Drives the visible section
   *  headers in the sidebar nav for **multi-location tenants only** —
   *  single-location tenants see the flat list (no headers), so the
   *  IA tax of "Organization vs Location" only kicks in when it
   *  actually means something. Defaults to `'location'` (the day-to-
   *  day, current-site surfaces). */
  group?: 'location' | 'organization';
  /** When set, hide the link entirely from members whose role is
   *  NOT in this list. Mirrors the backend permission gate so the
   *  user doesn't click through to a 403. */
  roles?: ReadonlyArray<'owner' | 'manager' | 'front_desk' | 'provider' | 'bookkeeper' | 'marketing'>;
  /** Optional sub-links shown when the parent is active (i.e. the
   *  current path starts with `href`). Each sub-link can be role-
   *  gated; if `roles` is set, only members whose role is in the
   *  list see the link. */
  children?: SubNavLink[];
}

export interface SubNavLink {
  href: string;
  label: string;
  /** When set, only members with one of these roles see the link.
   *  Mirrors the backend permission gate so the user doesn't click
   *  through to a 403. */
  roles?: ReadonlyArray<'owner' | 'manager' | 'front_desk' | 'provider' | 'bookkeeper' | 'marketing'>;
}

export const NAV_LINKS: NavLink[] = [
  { href: '/dashboard', label: 'Dashboard', icon: LayoutDashboard, group: 'location' },
  { href: '/calendar', label: 'Calendar', icon: Calendar, group: 'location' },
  { href: '/clients', label: 'Clients', icon: Users, group: 'location' },
  // Contractor self-scheduling. Visible to providers (contractors are
  // providers); the page itself is read-only for non-contractors.
  {
    href: '/my-schedule',
    label: 'My schedule',
    icon: CalendarClock,
    group: 'location',
    roles: ['provider'],
  },
  // Messaging lives behind the calendar right-rail Messages tile,
  // which opens a popout window at /inbox. Intentional: front-desk
  // staff work the inbox alongside the calendar, not on a separate
  // sidebar route.
  //
  // `/clock-in` (staff shift clock-in/out) is intentionally NOT in
  // the nav — operators access it from the staff schedule page +
  // the calendar's right-rail when they need it. The route is still
  // live, just hidden from the rail to avoid sidebar bloat.
  // Catalog — services + categories live here today; products,
  // memberships, and packages are placeholder pages until the
  // retail / packages / memberships features land. Sub-pages
  // visible to all roles (read-only listings); create/edit gated
  // server-side by the existing service permissions.
  {
    href: '/catalog',
    label: 'Catalog',
    icon: Sparkles,
    group: 'location',
    children: [
      { href: '/catalog/categories', label: 'Categories' },
      { href: '/catalog/services', label: 'Services' },
      { href: '/catalog/products', label: 'Products' },
      { href: '/catalog/memberships', label: 'Memberships' },
      { href: '/catalog/packages', label: 'Packages' },
      { href: '/catalog/gift-cards', label: 'Gift cards' },
    ],
  },
  // Staff is its own surface — promoted out of Settings because role
  // changes / scheduling / time-tracking / payroll are day-to-day
  // workflows, not once-in-a-while settings tweaks. Sub-pages are
  // role-gated to owner + manager (mirrors `MANAGE_STAFF`).
  {
    href: '/staff',
    label: 'Staff',
    icon: UsersRound,
    group: 'location',
    children: [
      { href: '/staff/employees', label: 'Employees', roles: ['owner', 'manager'] },
      { href: '/staff/schedule', label: 'Schedule', roles: ['owner', 'manager'] },
      { href: '/staff/check-in', label: 'Check-in', roles: ['owner', 'manager'] },
      { href: '/staff/commissions', label: 'Commissions' },
      { href: '/staff/payroll', label: 'Payroll', roles: ['owner', 'manager'] },
    ],
  },
  // Forms surface — customer-facing client forms (intake + consent)
  // AND provider-facing EMR templates (treatment records). Both are
  // schema-driven forms; pairing them under one nav reduces the
  // "where do I go to author a form?" guesswork operators hit when
  // the two were in different menus.
  {
    href: '/forms',
    label: 'Forms',
    icon: FileText,
    group: 'location',
    children: [
      { href: '/forms', label: 'Client forms' },
      { href: '/forms/emr-templates', label: 'EMR templates' },
    ],
  },
  { href: '/reports', label: 'Reports', icon: BarChart3, group: 'location' },
  // Marketing — audiences, templates, campaigns. Owner + manager +
  // marketing roles by default (front-desk gets read-only audience
  // segment access via VIEW_AUDIENCE_SEGMENTS).
  {
    href: '/marketing',
    label: 'Marketing',
    icon: Megaphone,
    group: 'location',
    children: [
      { href: '/marketing', label: 'Overview', roles: ['owner', 'manager', 'marketing', 'front_desk'] },
      { href: '/marketing/audiences', label: 'Audiences', roles: ['owner', 'manager', 'marketing', 'front_desk'] },
      { href: '/marketing/templates', label: 'Templates', roles: ['owner', 'manager', 'marketing'] },
      { href: '/marketing/campaigns', label: 'Campaigns', roles: ['owner', 'manager', 'marketing'] },
    ],
  },
  // Social inbox — Instagram Business DMs (FB + WhatsApp later).
  // Distinct from /inbox (SMS popout) because social DMs are batched
  // triage, not real-time front-desk work alongside the calendar.
  // Owner + manager only (mirrors backend MANAGE_INTEGRATIONS gate).
  {
    href: '/social',
    label: 'Social inbox',
    icon: Inbox,
    group: 'location',
    roles: ['owner', 'manager'],
  },
  // Organization-level surface — the business as a whole, not any one
  // location. Houses business profile + locations management +
  // org-rollup dashboard today; online-booking config and integrations
  // land in later sessions of Phase 4E.
  {
    href: '/org',
    label: 'Organization',
    icon: Building2,
    group: 'organization',
    children: [
      { href: '/org/dashboard', label: 'Dashboard', roles: ['owner', 'manager'] },
      { href: '/org/business', label: 'Business profile', roles: ['owner'] },
      { href: '/org/locations', label: 'Locations', roles: ['owner'] },
      { href: '/org/online-booking', label: 'Online booking', roles: ['owner'] },
      { href: '/org/integrations', label: 'Integrations', roles: ['owner', 'manager'] },
    ],
  },
];

export interface AppSidebarProps {
  user: User;
}

export function AppSidebar({ user }: AppSidebarProps) {
  const router = useRouter();
  const logout = useLogout();
  const [collapsed, setCollapsed] = useState(false);

  // Restore collapse state from localStorage after mount (SSR-safe).
  useEffect(() => {
    if (typeof window === 'undefined') return;
    if (window.localStorage.getItem(COLLAPSED_KEY) === '1') {
      setCollapsed(true);
    }
  }, []);

  const toggle = () => {
    setCollapsed((prev) => {
      const next = !prev;
      if (typeof window !== 'undefined') {
        window.localStorage.setItem(COLLAPSED_KEY, next ? '1' : '0');
      }
      return next;
    });
  };

  const primaryMembership = user.memberships[0];
  const userDisplayName =
    user.first_name || user.last_name
      ? `${user.first_name} ${user.last_name}`.trim()
      : user.email;

  // Multi-location detection drives the visible IA split:
  //   - Location switcher in the header (only when 2+ locations)
  //   - "Location · {name}" + "Organization" group headers above the
  //     respective nav items
  // Single-location tenants keep today's flat sidebar — no surprise
  // headers, no switcher.
  const { data: locations } = useLocations();
  const { location: activeLocation } = useActiveLocation();
  const showIASplit = hasMultipleLocations(locations);
  const activeLocationName = activeLocation
    ? locationDisplayName(activeLocation)
    : null;

  return (
    <aside
      data-collapsed={collapsed || undefined}
      className={cn(
        'shrink-0 border-r bg-sidebar text-sidebar-foreground flex flex-col transition-[width] duration-200 ease-out',
        collapsed ? 'w-16' : 'w-64',
      )}
    >
      <div
        className={cn(
          'border-b border-sidebar-border shrink-0 transition-[padding] duration-200',
          collapsed ? 'p-2 space-y-2' : 'px-6 pt-6 pb-5 space-y-3',
        )}
      >
        {collapsed ? (
          <>
            <Link
              href="/dashboard"
              className="inline-flex w-full items-center justify-center"
              aria-label="Lumè dashboard"
            >
              <BrandMark variant="icon" size={32} />
            </Link>
            <button
              type="button"
              onClick={toggle}
              aria-label="Expand sidebar"
              title="Expand sidebar"
              className="inline-flex w-full h-9 items-center justify-center rounded-md text-muted-foreground hover:bg-sidebar-accent hover:text-sidebar-accent-foreground transition-colors"
            >
              <PanelLeftOpen className="size-4" />
            </button>
            {/* Switcher only renders when 2+ locations — otherwise a no-op. */}
            <LocationSwitcher collapsed />
          </>
        ) : (
          <>
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0 flex-1">
                <Link href="/dashboard" className="inline-block" aria-label="Lumè dashboard">
                  <BrandMark variant="lockup" size={44} />
                </Link>
                {primaryMembership ? (
                  <p className="text-xs text-muted-foreground mt-1 truncate">
                    {primaryMembership.tenant.name}
                  </p>
                ) : null}
              </div>
              <button
                type="button"
                onClick={toggle}
                aria-label="Collapse sidebar"
                title="Collapse sidebar"
                className="inline-flex size-7 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:bg-sidebar-accent hover:text-sidebar-accent-foreground transition-colors"
              >
                <PanelLeftClose className="size-4" />
              </button>
            </div>
            {/* Context strip: which location are you currently scoped to.
                Only renders when 2+ locations exist; otherwise a no-op. */}
            <LocationSwitcher />
          </>
        )}
      </div>

      <nav
        className={cn(
          'flex-1 overflow-y-auto space-y-0.5 transition-[padding] duration-200',
          collapsed ? 'p-2' : 'p-3',
        )}
      >
        <NavGroups
          links={NAV_LINKS}
          collapsed={collapsed}
          userRole={primaryMembership?.role}
          showIASplit={showIASplit}
          activeLocationName={activeLocationName}
        />
      </nav>

      <div
        className={cn(
          'border-t border-sidebar-border shrink-0 transition-[padding] duration-200',
          collapsed ? 'p-2' : 'p-3',
        )}
      >
        {collapsed ? (
          <div className="flex flex-col items-center gap-2">
            <InitialsAvatar name={userDisplayName} size="sm" />
            <button
              type="button"
              aria-label="Sign out"
              title={`Sign out (${userDisplayName})`}
              disabled={logout.isPending}
              onClick={() => {
                logout.mutate(undefined, {
                  onSuccess: () => router.replace('/login'),
                });
              }}
              className="inline-flex size-8 items-center justify-center rounded-md text-muted-foreground hover:bg-sidebar-accent hover:text-sidebar-accent-foreground transition-colors disabled:opacity-50"
            >
              <LogOut className="size-4" />
            </button>
          </div>
        ) : (
          <>
            <Link
              href="/account"
              className="flex items-center gap-3 px-2 py-2 rounded-md hover:bg-sidebar-accent hover:text-sidebar-accent-foreground transition-colors"
              title="Account settings"
            >
              <InitialsAvatar name={userDisplayName} size="sm" />
              <div className="min-w-0 flex-1">
                <p className="text-xs font-medium truncate" title={userDisplayName}>
                  {userDisplayName}
                </p>
                {primaryMembership ? (
                  <p className="text-[11px] text-muted-foreground truncate">
                    {primaryMembership.role_display}
                  </p>
                ) : null}
              </div>
            </Link>
            <Button
              variant="outline"
              size="sm"
              className="w-full mt-2"
              disabled={logout.isPending}
              onClick={() => {
                logout.mutate(undefined, {
                  onSuccess: () => router.replace('/login'),
                });
              }}
            >
              {logout.isPending ? 'Signing out…' : 'Sign out'}
            </Button>
          </>
        )}
      </div>
    </aside>
  );
}

// ── Nav groups ──────────────────────────────────────────────────────
//
// When the tenant is single-location, this collapses to a flat list of
// SidebarLink — same shape as before the multi-location work landed.
// When 2+ locations exist, it splits the list into two visual groups
// with thin uppercase headers: "Location · {name}" above the day-to-
// day items (Dashboard / Calendar / Clients / Services / Staff / etc.)
// and "Organization" above the cross-cutting items (Org Dashboard /
// Business profile / Locations management). Coming-soon links keep
// their group; null group treats as "location" by default.
//
// Headers render only in the expanded sidebar — collapsed icon-rail
// stays clean (the LocationSwitcher icon already serves as the
// "you're scoped to a location" affordance).

function NavGroups({
  links,
  collapsed,
  userRole,
  showIASplit,
  activeLocationName,
}: {
  links: NavLink[];
  collapsed: boolean;
  userRole?: string;
  showIASplit: boolean;
  activeLocationName: string | null;
}) {
  // Filter out role-gated top-level links the user can't see (mirrors
  // backend permission gates — prevents the link from rendering at
  // all rather than a 403 on click).
  const visibleLinks = links.filter(
    (l) => !l.roles || (userRole && l.roles.includes(userRole as never)),
  );

  if (!showIASplit) {
    return (
      <>
        {visibleLinks.map((link) => (
          <SidebarLink
            key={link.href}
            link={link}
            collapsed={collapsed}
            userRole={userRole}
          />
        ))}
      </>
    );
  }

  const locationLinks = visibleLinks.filter((l) => (l.group ?? 'location') === 'location');
  const orgLinks = visibleLinks.filter((l) => l.group === 'organization');

  return (
    <>
      {!collapsed && locationLinks.length > 0 ? (
        <NavGroupHeader>
          Location
          {activeLocationName ? (
            <span className="text-foreground/80"> · {activeLocationName}</span>
          ) : null}
        </NavGroupHeader>
      ) : null}
      {locationLinks.map((link) => (
        <SidebarLink key={link.href} link={link} collapsed={collapsed} userRole={userRole} />
      ))}

      {orgLinks.length > 0 ? (
        <>
          {!collapsed ? (
            <NavGroupHeader className="mt-3">Organization</NavGroupHeader>
          ) : (
            // Subtle divider in the icon rail so the org section doesn't
            // visually merge with the location section above.
            <div className="my-2 mx-2 border-t border-sidebar-border" aria-hidden />
          )}
          {orgLinks.map((link) => (
            <SidebarLink key={link.href} link={link} collapsed={collapsed} userRole={userRole} />
          ))}
        </>
      ) : null}
    </>
  );
}

function NavGroupHeader({
  className,
  children,
}: {
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <p
      className={cn(
        'px-3 pt-1 pb-1.5 text-[10px] uppercase tracking-wide text-muted-foreground/70 font-medium truncate',
        className,
      )}
    >
      {children}
    </p>
  );
}

function SidebarLink({
  link,
  collapsed,
  userRole,
}: {
  link: NavLink;
  collapsed: boolean;
  /** The user's role in their primary membership — used to filter
   *  role-gated sub-links. Undefined for users with no membership. */
  userRole?: string;
}) {
  const pathname = usePathname();
  const isActive = pathname === link.href || pathname.startsWith(`${link.href}/`);
  const Icon = link.icon;

  // When collapsed, the native title attribute provides the label on hover
  // until we layer Tooltip primitives in (deferred until we have multiple
  // tooltip needs and can bring them in once).
  const title = collapsed ? link.label + (link.comingSoon ? ' (coming soon)' : '') : undefined;

  if (link.comingSoon) {
    return (
      <span
        title={title}
        className={cn(
          'flex items-center gap-3 rounded-md text-sm text-muted-foreground/60 cursor-not-allowed',
          collapsed ? 'justify-center p-2' : 'px-3 py-2',
        )}
      >
        <Icon className="size-4 shrink-0" />
        {!collapsed ? (
          <>
            <span className="flex-1">{link.label}</span>
            <span className="text-[10px] uppercase tracking-wide opacity-70">Soon</span>
          </>
        ) : null}
      </span>
    );
  }

  // Sub-links visible to this user — filter by role gates. If nothing
  // is visible we treat the parent as if it had no children (common
  // case for non-owner / non-manager roles on /settings).
  const visibleChildren =
    link.children?.filter(
      (child) => !child.roles || (userRole && child.roles.includes(userRole as never)),
    ) ?? [];

  return (
    <>
      <Link
        href={link.href}
        title={title}
        className={cn(
          'flex items-center gap-3 rounded-md text-sm transition-colors',
          collapsed ? 'justify-center p-2' : 'px-3 py-2',
          isActive
            ? 'bg-sidebar-accent text-sidebar-accent-foreground font-medium'
            : 'text-sidebar-foreground/80 hover:bg-sidebar-accent/60 hover:text-sidebar-foreground',
        )}
      >
        <Icon className="size-4 shrink-0" />
        {!collapsed ? <span>{link.label}</span> : null}
      </Link>

      {/* Sub-nav: only renders when the parent route is active AND the
          sidebar isn't collapsed. Indented + smaller text to read as
          children of the parent. Inactive children get a quieter tone;
          the active child gets the accent. */}
      {!collapsed && isActive && visibleChildren.length > 0 ? (
        <ul className="mt-0.5 mb-1 ml-7 border-l border-sidebar-border/60 space-y-px">
          {visibleChildren.map((child) => {
            const childActive = pathname === child.href || pathname.startsWith(`${child.href}/`);
            return (
              <li key={child.href}>
                <Link
                  href={child.href}
                  className={cn(
                    'block pl-3 pr-2 py-1.5 text-xs rounded-r transition-colors -ml-px border-l',
                    childActive
                      ? 'border-accent text-foreground font-medium'
                      : 'border-transparent text-muted-foreground hover:text-foreground hover:bg-sidebar-accent/40',
                  )}
                >
                  {child.label}
                </Link>
              </li>
            );
          })}
        </ul>
      ) : null}
    </>
  );
}
