/**
 * `/dashboard` — the daily entry point for every authenticated user.
 *
 * Layout (top → bottom):
 *
 *   1. PageHeader   — greeting + active-location chip + New client CTA
 *   2. KPI row      — 4 tiles, owner/manager view (revenue today, today's
 *                     appointments, new clients month-to-date, no-show
 *                     rate month-to-date with trend arrows)
 *   3. Hero chart   — 30-day revenue line + total + delta vs. previous
 *                     30 days
 *   4. Three panels — today's schedule · AR overdue · forms pending
 *
 * Role-aware composition (per the security gates each report enforces
 * server-side; dashboard mirrors the gates so the operator never sees
 * a tile fail with 403):
 *
 *   - Owner / Manager → every tile + chart + panel
 *   - Bookkeeper      → revenue tile + revenue chart + AR overdue panel
 *                       (no operational / guest sections — matches
 *                       their VIEW_FINANCIAL_REPORTS-only access)
 *   - Front desk      → today's appointments tile + schedule + forms
 *                       pending (operational view; no financial
 *                       surfaces because their role gates them out
 *                       at the API too)
 *   - Provider        → today's appointments tile + schedule (their
 *                       day-of-business surface; everything else
 *                       belongs in /staff or the chart, not here)
 *
 * Empty states everywhere — a brand-new tenant on day one sees the
 * shell with "no data yet" rather than skeleton bars that never
 * resolve.
 */

'use client';

import { MapPin } from 'lucide-react';
import { useEffect, useState } from 'react';

import { PageHeader } from '@/components/page-header';
import { useUser } from '@/lib/auth';
import {
  hasMultipleLocations,
  locationDisplayName,
  useActiveLocation,
  useLocations,
} from '@/lib/locations';

import { AROverduePanel } from './_components/ar-overdue-panel';
import { FormsPendingPanel } from './_components/forms-pending-panel';
import {
  AppointmentsTodayTile,
  NewClientsThisMonthTile,
  NoShowRateThisMonthTile,
  RevenueTodayTile,
} from './_components/kpi-tiles';
import { KpiRow } from './_components/kpi-tile';
import { MyDayPanel } from './_components/my-day-panel';
import { MyEarningsTile } from './_components/my-earnings-tile';
import { OnTheClockTile } from './_components/on-the-clock-tile';
import { RevenueChartPanel } from './_components/revenue-chart-panel';
import { TodaySchedulePanel } from './_components/today-schedule-panel';

type Role = 'owner' | 'manager' | 'front_desk' | 'provider' | 'bookkeeper' | 'marketing';

interface RoleConfig {
  showRevenueTile: boolean;
  showAppointmentsTile: boolean;
  showNewClientsTile: boolean;
  showNoShowTile: boolean;
  /** "On the clock right now" — operational awareness for owner/
   *  manager/front-desk. */
  showOnTheClockTile: boolean;
  /** "Your commissions MTD" — provider/manager/owner only. */
  showMyEarningsTile: boolean;
  showRevenueChart: boolean;
  /** Tenant-wide schedule panel. Provider role gets `showMyDayPanel`
   *  instead — their own schedule + clock-in in one mobile-first card. */
  showSchedulePanel: boolean;
  /** Provider-only mobile-first day card; replaces the schedule panel. */
  showMyDayPanel: boolean;
  showAROverduePanel: boolean;
  showFormsPendingPanel: boolean;
}

const ROLE_CONFIGS: Record<Role, RoleConfig> = {
  owner: {
    showRevenueTile: true,
    showAppointmentsTile: true,
    showNewClientsTile: true,
    showNoShowTile: true,
    showOnTheClockTile: true,
    showMyEarningsTile: false,
    showRevenueChart: true,
    showSchedulePanel: true,
    showMyDayPanel: false,
    showAROverduePanel: true,
    showFormsPendingPanel: true,
  },
  manager: {
    showRevenueTile: true,
    showAppointmentsTile: true,
    showNewClientsTile: true,
    showNoShowTile: true,
    showOnTheClockTile: true,
    showMyEarningsTile: false,
    showRevenueChart: true,
    showSchedulePanel: true,
    showMyDayPanel: false,
    showAROverduePanel: true,
    showFormsPendingPanel: true,
  },
  bookkeeper: {
    showRevenueTile: true,
    showAppointmentsTile: false,
    showNewClientsTile: false,
    showNoShowTile: false,
    showOnTheClockTile: false,
    showMyEarningsTile: false,
    showRevenueChart: true,
    showSchedulePanel: false,
    showMyDayPanel: false,
    showAROverduePanel: true,
    showFormsPendingPanel: false,
  },
  front_desk: {
    showRevenueTile: false,
    showAppointmentsTile: true,
    showNewClientsTile: false,
    showNoShowTile: false,
    showOnTheClockTile: true,
    showMyEarningsTile: false,
    showRevenueChart: false,
    showSchedulePanel: true,
    showMyDayPanel: false,
    showAROverduePanel: false,
    showFormsPendingPanel: true,
  },
  provider: {
    showRevenueTile: false,
    showAppointmentsTile: false,
    showNewClientsTile: false,
    showNoShowTile: false,
    showOnTheClockTile: false,
    showMyEarningsTile: true,
    showRevenueChart: false,
    showSchedulePanel: false,
    showMyDayPanel: true,
    showAROverduePanel: false,
    showFormsPendingPanel: false,
  },
  marketing: {
    showRevenueTile: false,
    showAppointmentsTile: false,
    showNewClientsTile: true,
    showNoShowTile: false,
    showOnTheClockTile: false,
    showMyEarningsTile: false,
    showRevenueChart: false,
    showSchedulePanel: false,
    showMyDayPanel: false,
    showAROverduePanel: false,
    showFormsPendingPanel: false,
  },
};

const FALLBACK_CONFIG = ROLE_CONFIGS.owner;

export default function DashboardPage() {
  const { data: user } = useUser();
  const primaryMembership = user?.memberships[0];
  const greeting = user?.first_name || user?.email?.split('@')[0] || 'there';

  // Time-of-day greeting only resolves after mount to avoid an SSR
  // mismatch (server "morning" → client "afternoon" hydration warning).
  // Initial render is "morning"; client effect swaps in the real one.
  const [tod, setTod] = useState<'morning' | 'afternoon' | 'evening'>('morning');
  useEffect(() => {
    const h = new Date().getHours();
    setTod(h < 12 ? 'morning' : h < 18 ? 'afternoon' : 'evening');
  }, []);

  const role = (primaryMembership?.role ?? 'owner') as Role;
  const config = ROLE_CONFIGS[role] ?? FALLBACK_CONFIG;

  const { data: locations } = useLocations();
  const { location: activeLocation } = useActiveLocation();
  const showLocationChip = hasMultipleLocations(locations);

  const visibleTiles = [
    config.showRevenueTile && <RevenueTodayTile key="revenue" />,
    config.showAppointmentsTile && <AppointmentsTodayTile key="appts" />,
    config.showOnTheClockTile && <OnTheClockTile key="onclock" />,
    config.showMyEarningsTile && <MyEarningsTile key="earnings" />,
    config.showNewClientsTile && <NewClientsThisMonthTile key="new" />,
    config.showNoShowTile && <NoShowRateThisMonthTile key="noshow" />,
  ].filter(Boolean);

  const visiblePanels = [
    config.showMyDayPanel && <MyDayPanel key="myday" />,
    config.showSchedulePanel && <TodaySchedulePanel key="schedule" />,
    config.showAROverduePanel && <AROverduePanel key="ar" />,
    config.showFormsPendingPanel && <FormsPendingPanel key="forms" />,
  ].filter(Boolean);

  return (
    <div className="px-4 py-6 sm:px-8 sm:py-10 space-y-6 sm:space-y-8">
      <PageHeader
        title={`Good ${tod}, ${greeting}`}
        actions={
          showLocationChip && activeLocation ? (
            <span
              className="inline-flex items-center gap-1.5 h-8 px-2.5 rounded-md border bg-card text-xs text-muted-foreground"
              title="Active location — switch in the sidebar"
            >
              <MapPin className="size-3.5 text-accent" aria-hidden />
              <span className="text-foreground font-medium">
                {locationDisplayName(activeLocation)}
              </span>
            </span>
          ) : null
        }
      />

      {visibleTiles.length > 0 ? <KpiRow>{visibleTiles}</KpiRow> : null}

      {config.showRevenueChart ? <RevenueChartPanel /> : null}

      {visiblePanels.length > 0 ? (
        <div
          className={
            visiblePanels.length === 1
              ? 'grid grid-cols-1'
              : visiblePanels.length === 2
                ? 'grid grid-cols-1 gap-5 lg:grid-cols-2'
                : 'grid grid-cols-1 gap-5 lg:grid-cols-3'
          }
        >
          {visiblePanels}
        </div>
      ) : null}
    </div>
  );
}

