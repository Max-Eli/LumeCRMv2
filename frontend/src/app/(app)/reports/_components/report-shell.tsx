/**
 * Common chrome for a report page: header (title + back to library) +
 * date-range controls + summary-tile row + content slot.
 *
 * The page-specific bits (which summary tiles, which table) live in
 * the report's own page component — this just keeps the rhythm
 * consistent so every report reads the same way.
 */

'use client';

import { ShieldCheck } from 'lucide-react';

import { PageHeader } from '@/components/page-header';
import { type PhiTier } from '@/lib/reports';
import { cn } from '@/lib/utils';

import { DateRangePicker, type DateRange } from './date-range-picker';
import { ExportCsvButton } from './export-csv-button';

export interface ReportShellProps {
  title: string;
  description: string;
  phiTier: PhiTier;
  /** Optional — reports without a date filter (lifetime metrics, snapshots) omit this. */
  dateRange?: DateRange;
  onDateRangeChange?: (next: DateRange) => void;
  /** Custom controls (e.g. a `?days=` slider) rendered alongside the date picker. */
  controls?: React.ReactNode;
  isLoading: boolean;
  error: unknown;
  /** Backend report path (e.g. /api/reports/financial/sales-by-date-range/).
   *  When provided, the shell renders a Download CSV button next to the
   *  date controls. PHI confirmation modal fires automatically based on
   *  `phiTier`. */
  exportPath?: string;
  /** Extra non-date params to forward to the export URL (e.g. `days`,
   *  `limit`, `window_days`). The shell already passes the date range
   *  when present. */
  exportParams?: Record<string, string | undefined>;
  children: React.ReactNode;
}

export function ReportShell({
  title,
  description,
  phiTier,
  dateRange,
  onDateRangeChange,
  controls,
  isLoading,
  error,
  exportPath,
  exportParams,
  children,
}: ReportShellProps) {
  const hasDateControls = !!dateRange && !!onDateRangeChange;
  const showControlRow = hasDateControls || !!controls || !!exportPath;
  return (
    <div className="px-10 py-10 max-w-7xl space-y-6">
      <PageHeader
        title={title}
        description={description}
        back={{ href: '/reports', label: 'All reports' }}
        actions={<PhiBadge tier={phiTier} />}
      />

      {showControlRow ? (
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex flex-wrap items-center gap-4">
            {hasDateControls ? (
              <DateRangePicker value={dateRange!} onChange={onDateRangeChange!} />
            ) : null}
            {controls}
          </div>
          {exportPath ? (
            <ExportCsvButton
              reportPath={exportPath}
              phiTier={phiTier}
              params={{ ...(dateRange ?? {}), ...(exportParams ?? {}) }}
              disabled={isLoading || !!error}
            />
          ) : null}
        </div>
      ) : null}

      {error ? (
        <div className="border border-destructive/40 bg-destructive/5 rounded-lg px-4 py-3 text-sm text-destructive">
          Could not load the report. Try a different parameters or refresh the page.
        </div>
      ) : isLoading ? (
        <p className="text-sm text-muted-foreground">Running report…</p>
      ) : (
        children
      )}
    </div>
  );
}

// ── Building blocks reused by report pages ──────────────────────────

export function SummaryTileRow({ children }: { children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
      {children}
    </div>
  );
}

export function SummaryTile({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <div className="rounded-lg border bg-card px-4 py-3">
      <p className="text-[11px] uppercase tracking-wide text-muted-foreground/80 font-medium">
        {label}
      </p>
      <p className="font-serif text-2xl font-semibold tracking-tight tabular-nums mt-1">
        {value}
      </p>
      {hint ? (
        <p className="text-[11px] text-muted-foreground mt-1 truncate">{hint}</p>
      ) : null}
    </div>
  );
}

export function ReportSection({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="space-y-3">
      <header>
        <h2 className="font-serif text-base font-semibold tracking-tight">
          {title}
        </h2>
        {description ? (
          <p className="text-xs text-muted-foreground mt-0.5">{description}</p>
        ) : null}
      </header>
      {children}
    </section>
  );
}

export function EmptyRow({ children }: { children: React.ReactNode }) {
  return (
    <div className="border border-dashed rounded-lg bg-muted/20 px-6 py-10 text-center">
      <p className="text-sm text-muted-foreground">{children}</p>
    </div>
  );
}

// ── PHI badge ───────────────────────────────────────────────────────

function PhiBadge({ tier }: { tier: PhiTier }) {
  if (tier === 'none') return null;
  const label = tier === 'aggregated' ? 'Names staff' : 'Contains PHI';
  const tone =
    tier === 'per_customer'
      ? 'bg-amber-50 text-amber-900 ring-amber-200 dark:bg-amber-950 dark:text-amber-100 dark:ring-amber-900'
      : 'bg-muted text-muted-foreground ring-border';
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 h-7 px-2 text-[11px] rounded ring-1',
        tone,
      )}
      title={
        tier === 'per_customer'
          ? 'This report includes individual customer names. Treat the screen + any export accordingly.'
          : 'This report names individual staff members.'
      }
    >
      <ShieldCheck className="size-3" aria-hidden />
      {label}
    </span>
  );
}
