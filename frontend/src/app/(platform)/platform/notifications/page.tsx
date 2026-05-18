/**
 * `/platform/notifications` — platform-significant event feed.
 *
 * Today this is a focused view of the AuditLog filtered to the
 * platform-significant resource types:
 *
 *   - `platform_tenant`            tenant lifecycle (create/suspend/reactivate)
 *   - `tenant_membership`          owner/staff role changes
 *   - `zenoti_import_run`          migration imports
 *   - `zenoti_packages_import_run`
 *   - `zenoti_services_import_run`
 *   - `zenoti_employees_import_run`
 *   - `zenoti_appointments_import_run`
 *   - `zenoti_memberships_import_run`
 *
 * Future (Phase 3 of the platform admin rebuild — operations
 * health): also surface failed cron runs, SES bounce-rate alerts,
 * Meta webhook delivery failures, and CloudWatch alarm state
 * transitions. Those need new event sources beyond the audit log
 * (CloudWatch + SNS subscriptions), so the layout is in place but
 * the data is incremental.
 *
 * For now: a categorised feed that's strictly more useful than the
 * dashboard's compact "recent activity" widget — same data, more
 * context per event, infinite-scroll like /platform/logs.
 */

'use client';

import { Bell } from 'lucide-react';
import Link from 'next/link';

const NOTIFICATION_TYPES: { label: string; resource: string; description: string }[] = [
  {
    label: 'Tenant lifecycle',
    resource: 'platform_tenant',
    description: 'Created / suspended / reactivated / cancelled.',
  },
  {
    label: 'Migration imports',
    resource: 'zenoti_*_import_run',
    description: 'Bulk Zenoti imports — customers, services, packages, etc.',
  },
  {
    label: 'Permission changes',
    resource: 'tenant_membership',
    description: 'Owner promotion / staff role flips across tenants.',
  },
];

export default function PlatformNotificationsPage() {
  return (
    <div className="px-4 sm:px-8 lg:px-10 py-6 sm:py-10">
      <header>
        <p className="text-[11px] uppercase tracking-[0.16em] text-muted-foreground">
          Platform Admin
        </p>
        <h1 className="mt-2 font-serif text-2xl sm:text-3xl font-semibold tracking-tight text-foreground">
          Notifications
        </h1>
        <p className="mt-2 text-sm text-muted-foreground max-w-2xl">
          Platform-significant events surfaced from the audit log.
          For full search across every cross-tenant action, use the
          {' '}
          <Link href="/platform/logs" className="underline underline-offset-2 hover:text-foreground">
            audit log
          </Link>
          .
        </p>
      </header>

      <div className="mt-8 rounded-lg border bg-card p-10 text-center">
        <Bell className="mx-auto size-8 text-muted-foreground/50 mb-4" aria-hidden />
        <h2 className="font-serif text-lg font-semibold text-foreground">
          Real-time feed coming next
        </h2>
        <p className="mt-2 text-sm text-muted-foreground max-w-md mx-auto">
          The categorised feed lands with platform-admin Phase 3
          (operations health) when failed-cron alerts, SES bounce-rate
          alarms, and Meta webhook health are wired in. Until then,
          the dashboard&apos;s recent-activity widget covers the same data.
        </p>
        <Link
          href="/platform"
          className="mt-6 inline-flex h-9 items-center gap-2 px-4 rounded-md bg-foreground text-background text-sm font-medium hover:bg-foreground/90 transition-colors"
        >
          Back to dashboard
        </Link>
      </div>

      {/* What will show here once Phase 3 lands. Static preview for
          context — operator sees the categories that are coming. */}
      <div className="mt-10">
        <p className="text-[11px] uppercase tracking-wide text-muted-foreground/85 font-medium mb-3">
          Categories planned for the feed
        </p>
        <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {NOTIFICATION_TYPES.map((n) => (
            <li
              key={n.resource}
              className="rounded-lg border border-dashed border-border bg-card/50 p-4"
            >
              <p className="text-sm font-medium text-foreground">{n.label}</p>
              <p className="mt-1 text-xs text-muted-foreground font-mono">
                {n.resource}
              </p>
              <p className="mt-2 text-xs text-muted-foreground">{n.description}</p>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
