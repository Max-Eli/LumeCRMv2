/**
 * Sidebar for the platform admin surface.
 *
 * Visually distinct from the customer-facing CRM sidebar:
 *   - Dark theme (inherited from `data-theme="platform"`)
 *   - "PLATFORM ADMIN" eyebrow at the top instead of the brand mark
 *     (the brand mark goes back to the cream theme; in the dark
 *     surface it would feel out of place)
 *   - Smaller link set: Dashboard, Tenants, Notifications (S2),
 *     Logs (S2)
 *   - "Back to CRM" affordance at the bottom — explicit way to
 *     leave the platform surface
 */

'use client';

import {
  Bell,
  Building2,
  LayoutDashboard,
  LogOut,
  ScrollText,
} from 'lucide-react';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';

import { InitialsAvatar } from '@/components/initials-avatar';
import type { User } from '@/lib/auth';
import { useLogout } from '@/lib/auth';
import { cn } from '@/lib/utils';

interface NavLink {
  href: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  comingSoon?: boolean;
}

const PLATFORM_NAV: NavLink[] = [
  { href: '/platform', label: 'Dashboard', icon: LayoutDashboard },
  { href: '/platform/tenants', label: 'Tenants', icon: Building2 },
  // "Error logs" was the placeholder name; we renamed to "Audit log"
  // because the page surfaces application audit entries (PHI CRUD,
  // logins, exports), not stack-trace error logs. Error logs proper
  // live in CloudWatch + Sentry — surfacing those is Phase 3.
  { href: '/platform/logs', label: 'Audit log', icon: ScrollText },
  { href: '/platform/notifications', label: 'Notifications', icon: Bell },
];

export function PlatformSidebar({ user }: { user: User }) {
  const pathname = usePathname();
  const router = useRouter();
  const logout = useLogout();

  const userDisplayName =
    user.first_name || user.last_name
      ? `${user.first_name} ${user.last_name}`.trim()
      : user.email;

  return (
    <aside className="w-64 shrink-0 border-r border-sidebar-border bg-sidebar text-sidebar-foreground flex flex-col">
      {/* Header — "PLATFORM ADMIN" eyebrow. Visually distinct from the
          brand wordmark used in the cream-themed CRM sidebar. */}
      <div className="px-6 pt-6 pb-5 border-b border-sidebar-border space-y-3">
        <Link href="/platform" className="block group">
          <p className="text-[10px] uppercase tracking-[0.18em] font-semibold text-accent">
            Platform Admin
          </p>
          <p className="mt-1 font-serif text-lg font-semibold tracking-tight text-foreground">
            Lumè Console
          </p>
        </Link>
        <p className="text-[11px] text-muted-foreground">
          Internal — superuser access only.
        </p>
      </div>

      {/* Navigation */}
      <nav className="flex-1 overflow-y-auto px-3 py-4 space-y-1">
        {PLATFORM_NAV.map((link) => {
          const Icon = link.icon;
          const isActive =
            link.href === '/platform'
              ? pathname === '/platform'
              : pathname?.startsWith(link.href);
          const disabled = link.comingSoon;
          return (
            <Link
              key={link.href}
              href={disabled ? '#' : link.href}
              aria-disabled={disabled}
              onClick={disabled ? (e) => e.preventDefault() : undefined}
              className={cn(
                'flex items-center gap-3 px-3 py-2 rounded-md text-sm transition-colors',
                isActive
                  ? 'bg-sidebar-accent text-sidebar-accent-foreground font-medium'
                  : 'text-foreground/75 hover:bg-sidebar-accent/60 hover:text-foreground',
                disabled && 'opacity-50 cursor-not-allowed pointer-events-none',
              )}
            >
              <Icon className="size-4 shrink-0" />
              <span className="flex-1">{link.label}</span>
              {disabled ? (
                <span className="text-[9px] uppercase tracking-wide text-muted-foreground/70">
                  soon
                </span>
              ) : null}
            </Link>
          );
        })}
      </nav>

      {/* Footer — signed-in identity + sign out. The "Back to CRM"
          link was removed: platform admins land here intentionally
          and don't need a one-click route into a tenant they aren't
          a member of. Real cross-tenant access goes through the
          Impersonate feature on a tenant detail page (Phase 2). */}
      <div className="p-3 border-t border-sidebar-border">
        <div className="px-3 py-2 flex items-center gap-2.5">
          <InitialsAvatar name={userDisplayName} size="sm" />
          <div className="min-w-0 flex-1">
            <p className="text-xs text-foreground truncate font-medium">{userDisplayName}</p>
            <p className="text-[10px] text-muted-foreground truncate">Superuser</p>
          </div>
          <button
            type="button"
            onClick={() => logout.mutate(undefined, { onSuccess: () => router.replace('/login') })}
            className="inline-flex size-7 items-center justify-center rounded-md text-muted-foreground hover:bg-sidebar-accent hover:text-foreground transition-colors"
            title="Sign out"
            aria-label="Sign out"
          >
            <LogOut className="size-3.5" />
          </button>
        </div>
      </div>
    </aside>
  );
}
