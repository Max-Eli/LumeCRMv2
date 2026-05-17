/**
 * `/reports` — categorized library of every report the current user
 * is allowed to run.
 *
 * The category list comes from `GET /api/reports/`, which is already
 * permission-filtered server-side: a category the user can't access
 * never appears in the response. Empty categories (placeholders for
 * future sessions — Operations, Marketing) are also omitted, so the
 * page only renders sections that actually have something to click.
 */

'use client';

import {
  ArrowRight,
  BarChart3,
  Briefcase,
  DollarSign,
  Megaphone,
  ShieldCheck,
  Users,
} from 'lucide-react';
import Link from 'next/link';

import { PageHeader } from '@/components/page-header';
import {
  type PhiTier,
  type ReportCatalogEntry,
  type ReportCategoryId,
  useReportCatalog,
} from '@/lib/reports';
import { cn } from '@/lib/utils';

const CATEGORY_ICON: Record<ReportCategoryId, typeof BarChart3> = {
  financial: DollarSign,
  staff: Briefcase,
  guests: Users,
  operations: BarChart3,
  marketing: Megaphone,
};

const REPORT_HREF: Record<string, string> = {
  // Financial
  'financial.sales_by_date_range':  '/reports/financial/sales-by-date-range',
  'financial.daily_close_out':      '/reports/financial/daily-close-out',
  'financial.ar_aging':             '/reports/financial/ar-aging',
  'financial.revenue_by_service':   '/reports/financial/revenue-by-service',
  'financial.revenue_by_location':  '/reports/financial/revenue-by-location',
  'financial.tax_collected':        '/reports/financial/tax-collected',
  'financial.revenue_by_acquisition_source': '/reports/financial/revenue-by-acquisition-source',
  // Staff
  'staff.revenue_by_provider':         '/reports/staff/revenue-by-provider',
  'staff.schedule_utilization':        '/reports/staff/schedule-utilization',
  'staff.no_show_rate_by_provider':    '/reports/staff/no-show-rate-by-provider',
  'staff.new_clients_by_provider':     '/reports/staff/new-clients-by-provider',
  'staff.repeat_rate_by_provider':     '/reports/staff/repeat-rate-by-provider',
  // Guests
  'guests.new_vs_returning':  '/reports/guests/new-vs-returning',
  'guests.top_spenders':      '/reports/guests/top-spenders',
  'guests.inactive_clients':  '/reports/guests/inactive-clients',
  'guests.birthday_list':     '/reports/guests/birthday-list',
  'guests.visit_frequency':   '/reports/guests/visit-frequency',
  'guests.forms_outstanding': '/reports/guests/forms-outstanding',
  // Operations
  'operations.appointments_by_status': '/reports/operations/appointments-by-status',
  'operations.no_show_rate':           '/reports/operations/no-show-rate',
  'operations.cancellation_rate':      '/reports/operations/cancellation-rate',
  'operations.booking_lead_time':      '/reports/operations/booking-lead-time',
  'operations.service_mix':            '/reports/operations/service-mix',
  'operations.busiest_hours':          '/reports/operations/busiest-hours',
  'operations.bookings_by_acquisition_source': '/reports/operations/bookings-by-acquisition-source',
};

export default function ReportsLibraryPage() {
  const { data: catalog, isLoading, error } = useReportCatalog();

  return (
    <div className="px-10 py-10 max-w-7xl space-y-8">
      <PageHeader
        title="Reports"
        description="Pull a snapshot of how the spa is doing — sales, providers, clients, operations. Every report runs against the live data and you can pick any date range."
      />

      {isLoading ? (
        <p className="text-sm text-muted-foreground">Loading reports…</p>
      ) : error ? (
        <p className="text-sm text-destructive">Could not load the reports library.</p>
      ) : !catalog || catalog.categories.length === 0 ? (
        <EmptyState />
      ) : (
        <div className="space-y-10">
          {catalog.categories.map((category) => (
            <CategorySection
              key={category.id}
              id={category.id}
              label={category.label}
              description={category.description}
              reports={category.reports}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// ── Sub-components ──────────────────────────────────────────────────

function CategorySection({
  id,
  label,
  description,
  reports,
}: {
  id: ReportCategoryId;
  label: string;
  description: string;
  reports: ReportCatalogEntry[];
}) {
  const Icon = CATEGORY_ICON[id] ?? BarChart3;
  return (
    <section>
      <header className="mb-3">
        <div className="flex items-center gap-2">
          <Icon className="size-4 text-muted-foreground" />
          <h2 className="font-serif text-base font-semibold tracking-tight">
            {label}
          </h2>
          <span className="text-[11px] text-muted-foreground/80">
            ({reports.length} report{reports.length === 1 ? '' : 's'})
          </span>
        </div>
        <p className="text-xs text-muted-foreground mt-1.5 max-w-2xl leading-relaxed">
          {description}
        </p>
      </header>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
        {reports.map((r) => (
          <ReportCard key={r.id} report={r} />
        ))}
      </div>
    </section>
  );
}

function ReportCard({ report }: { report: ReportCatalogEntry }) {
  const href = REPORT_HREF[report.id];
  const isWired = !!href;

  if (!isWired) {
    return (
      <div className="rounded-lg border bg-muted/30 px-4 py-4 opacity-60">
        <p className="text-sm font-medium">{report.title}</p>
        <p className="text-xs text-muted-foreground mt-1 leading-relaxed">
          {report.description}
        </p>
        <p className="text-[11px] text-muted-foreground/80 mt-2">Coming soon</p>
      </div>
    );
  }

  return (
    <Link
      href={href}
      className={cn(
        'group rounded-lg border bg-card px-4 py-4 transition-colors hover:bg-muted/40 hover:border-ring/40',
        'focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring/50',
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <p className="text-sm font-medium text-foreground">{report.title}</p>
        <ArrowRight className="size-3.5 text-muted-foreground/60 group-hover:text-foreground transition-colors mt-0.5" />
      </div>
      <p className="text-xs text-muted-foreground mt-1 leading-relaxed line-clamp-3">
        {report.description}
      </p>
      <div className="flex items-center gap-1.5 mt-3">
        <PhiPill tier={report.phi_tier} />
      </div>
    </Link>
  );
}

function PhiPill({ tier }: { tier: PhiTier }) {
  if (tier === 'none') {
    return (
      <span className="inline-flex items-center text-[10px] uppercase tracking-wide text-muted-foreground/70">
        Aggregate only
      </span>
    );
  }
  if (tier === 'aggregated') {
    return (
      <span className="inline-flex items-center gap-1 text-[10px] uppercase tracking-wide text-muted-foreground">
        <ShieldCheck className="size-3" aria-hidden />
        Names staff
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 text-[10px] uppercase tracking-wide text-amber-700 dark:text-amber-400">
      <ShieldCheck className="size-3" aria-hidden />
      Contains PHI
    </span>
  );
}

function EmptyState() {
  return (
    <div className="border rounded-lg bg-card px-6 py-12 text-center">
      <BarChart3 className="size-6 mx-auto mb-3 text-muted-foreground/60" />
      <p className="text-sm text-foreground font-medium">
        No reports available for your role
      </p>
      <p className="text-xs text-muted-foreground mt-1 max-w-md mx-auto leading-relaxed">
        Reports are gated by role — financials for owners, managers, and
        bookkeepers; client lists for owners, managers, and marketing; and so
        on. Ask your owner if you need access to a specific report.
      </p>
    </div>
  );
}
