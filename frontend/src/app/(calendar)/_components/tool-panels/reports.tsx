/**
 * `ReportsPanel` — daily stats for the focus date.
 *
 * Derives everything from the appointments already loaded for the
 * calendar grid (`useAppointmentsForDate(date)`), so the panel
 * doesn't fire a second backend round-trip — the data is already
 * in the operator's tab. Updates whenever the calendar date changes
 * because the parent passes the same array down.
 *
 * What's shown (v1):
 *   - **Today total** — appointment count + total quoted revenue
 *     (the day's earnings *if* every appointment is paid; actual
 *     paid revenue lives in the financial reports library when
 *     POS lands in 2A).
 *   - **By status** — booked / confirmed / checked-in / completed /
 *     no-show / cancelled, each as a count + percent bar.
 *   - **By source** — online / staff / other (a quick at-a-glance
 *     of how the day was filled).
 *   - **Top providers** — three highest-load providers with their
 *     appointment count.
 *
 * Operators who want deeper analysis click "Open reports library"
 * and land in `/reports`. This panel is for the at-a-glance read.
 */

'use client';

import {
  ArrowRight,
  BarChart3,
  Clock,
  DollarSign,
  Globe,
  Lock,
  Store,
  Users,
} from 'lucide-react';
import Link from 'next/link';
import { useMemo } from 'react';

import { ApiError } from '@/lib/api';
import {
  type Appointment,
  type AppointmentStatus,
  STATUS_LABELS,
} from '@/lib/appointments';
import { useDailyCloseOut, type DailyCloseOutRow, type DailyCloseOutSummary } from '@/lib/reports';
import { cn } from '@/lib/utils';

export interface ReportsPanelProps {
  focusDate: string;
  appointments: Appointment[];
  timezone: string;
}

export function ReportsPanel({ focusDate, appointments, timezone }: ReportsPanelProps) {
  const stats = useMemo(() => deriveStats(appointments), [appointments]);
  const dateLabel = useMemo(() => formatFocusDate(focusDate, timezone), [focusDate, timezone]);

  // Money-collected: hits the existing daily-close-out report scoped
  // to the focus date. Permission-gated to VIEW_FINANCIAL_REPORTS
  // (owner + manager + bookkeeper by default), so front desk gets a
  // graceful "no access" state instead of a broken card.
  const closeOutQ = useDailyCloseOut({ date_from: focusDate, date_to: focusDate });

  if (appointments.length === 0) {
    return (
      <div className="px-3 py-3 space-y-3">
        <Header dateLabel={dateLabel} />
        <MoneyCollectedCard
          isLoading={closeOutQ.isLoading}
          error={closeOutQ.error}
          summary={closeOutQ.data?.summary}
          row={closeOutQ.data?.rows?.[0]}
        />
        <EmptyState />
      </div>
    );
  }

  return (
    <div className="px-3 py-3 space-y-4">
      <Header dateLabel={dateLabel} />

      <MoneyCollectedCard
        isLoading={closeOutQ.isLoading}
        error={closeOutQ.error}
        summary={closeOutQ.data?.summary}
        row={closeOutQ.data?.rows?.[0]}
      />

      <TotalsCard
        appointmentCount={stats.total}
        revenueCents={stats.revenueCents}
        completedCount={stats.byStatus.completed}
      />

      <StatusBreakdown total={stats.total} byStatus={stats.byStatus} />

      <SourceBreakdown total={stats.total} bySource={stats.bySource} />

      {stats.topProviders.length > 0 ? (
        <ProvidersBreakdown providers={stats.topProviders} />
      ) : null}

      <Link
        href="/reports"
        className="flex items-center justify-between gap-2 rounded-md border border-border bg-card px-3 py-2.5 text-sm font-medium text-foreground hover:bg-muted/60 transition-colors"
      >
        <span className="inline-flex items-center gap-2">
          <BarChart3 className="size-4 text-muted-foreground" />
          Open reports library
        </span>
        <ArrowRight className="size-3.5 text-muted-foreground" />
      </Link>
    </div>
  );
}

// ── Money collected card ─────────────────────────────────────────────

function MoneyCollectedCard({
  isLoading,
  error,
  summary,
  row,
}: {
  isLoading: boolean;
  error: Error | null;
  summary: DailyCloseOutSummary | undefined;
  row: DailyCloseOutRow | undefined;
}) {
  // Permission gate (403): the operator's role doesn't include
  // VIEW_FINANCIAL_REPORTS. Render a small "no access" stub so they
  // know the card exists for owners/bookkeepers but isn't theirs to
  // see. Less alarming than a generic error and respects the
  // minimum-necessary disclosure principle.
  if (error instanceof ApiError && (error.status === 403 || error.status === 401)) {
    return (
      <div className="rounded-lg border border-border bg-card px-4 py-3 flex items-start gap-2.5">
        <Lock className="size-4 text-muted-foreground mt-0.5 shrink-0" />
        <div>
          <p className="text-xs font-medium text-foreground">
            Money collected
          </p>
          <p className="text-[11px] text-muted-foreground mt-0.5 leading-relaxed">
            Owner, manager, and bookkeeper roles can see today&rsquo;s
            collected revenue here.
          </p>
        </div>
      </div>
    );
  }

  if (isLoading || !row || !summary) {
    return (
      <div className="rounded-lg border border-border bg-card p-4">
        <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-medium">
          Money collected
        </p>
        <div className="h-7 w-32 rounded bg-muted/60 animate-pulse mt-2" />
        <div className="h-3 w-24 rounded bg-muted/40 animate-pulse mt-2" />
      </div>
    );
  }

  const grossCents = row.gross_cents ?? 0;
  const invoiceCount = row.invoice_count ?? 0;
  const taxCents = row.tax_cents ?? 0;
  const netCents = grossCents - taxCents;

  // Method breakdown — ordered by gross descending, hide zero rows so
  // the card stays scannable. Show all when the day has nothing.
  const methodEntries = (summary.method_keys ?? [])
    .map((key) => ({
      key,
      label: summary.method_labels[key] ?? key,
      cents: row.by_method?.[key] ?? 0,
    }))
    .filter((m) => m.cents > 0)
    .sort((a, b) => b.cents - a.cents);

  return (
    <div className="rounded-lg border border-border bg-card overflow-hidden">
      {/* Headline */}
      <div className="px-4 py-3 border-b border-border bg-gradient-to-br from-emerald-50/40 to-card">
        <div className="flex items-center justify-between gap-2 mb-1">
          <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-medium inline-flex items-center gap-1">
            <DollarSign className="size-3" aria-hidden />
            Money collected
          </p>
          <span className="text-[10px] tabular-nums text-muted-foreground">
            {invoiceCount} {invoiceCount === 1 ? 'invoice' : 'invoices'}
          </span>
        </div>
        <p className="text-2xl font-semibold tracking-tight text-foreground tabular-nums">
          {formatDollarsExact(grossCents)}
        </p>
        <p className="text-[11px] text-muted-foreground mt-0.5">
          Net {formatDollarsExact(netCents)} · Tax {formatDollarsExact(taxCents)}
        </p>
      </div>

      {/* Method breakdown */}
      {grossCents === 0 ? (
        <div className="px-4 py-3 text-[11px] text-muted-foreground italic">
          No payments collected today yet.
        </div>
      ) : (
        <ul className="divide-y divide-border">
          {methodEntries.map((m) => {
            const pct =
              grossCents > 0 ? Math.round((m.cents / grossCents) * 100) : 0;
            return (
              <li
                key={m.key}
                className="px-4 py-2 flex items-center gap-2"
              >
                <span className="text-xs font-medium text-foreground/80 w-20 shrink-0 capitalize">
                  {m.label}
                </span>
                <div className="flex-1 h-1.5 rounded-full bg-muted/60 overflow-hidden">
                  <div
                    className="h-full rounded-full bg-emerald-500"
                    style={{ width: `${pct}%` }}
                  />
                </div>
                <span className="text-xs tabular-nums text-foreground w-16 text-right">
                  {formatDollarsExact(m.cents)}
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

// ── Sub-components ───────────────────────────────────────────────────

function Header({ dateLabel }: { dateLabel: string }) {
  return (
    <div className="px-1">
      <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-medium">
        Reports for
      </p>
      <p className="text-sm font-semibold text-foreground">{dateLabel}</p>
    </div>
  );
}

function EmptyState() {
  return (
    <div className="rounded-lg border border-dashed bg-muted/30 p-5 text-center">
      <div className="inline-flex size-10 items-center justify-center rounded-full bg-card text-muted-foreground border mb-3">
        <BarChart3 className="size-4" />
      </div>
      <h3 className="font-serif text-base font-semibold tracking-tight">
        No appointments today
      </h3>
      <p className="text-xs text-muted-foreground mt-1.5 leading-relaxed">
        Stats appear here once the day has bookings. For multi-day analysis,
        open the full reports library.
      </p>
      <Link
        href="/reports"
        className="inline-flex items-center gap-1 mt-4 text-xs font-medium text-foreground hover:underline"
      >
        Open reports library
        <ArrowRight className="size-3" />
      </Link>
    </div>
  );
}

function TotalsCard({
  appointmentCount,
  revenueCents,
  completedCount,
}: {
  appointmentCount: number;
  revenueCents: number;
  completedCount: number;
}) {
  return (
    <div className="grid grid-cols-2 gap-2">
      <Stat
        label="Appointments"
        value={String(appointmentCount)}
        sublabel={completedCount > 0 ? `${completedCount} completed` : undefined}
      />
      <Stat
        label="Quoted revenue"
        value={formatDollars(revenueCents)}
        sublabel="If all paid"
      />
    </div>
  );
}

function Stat({
  label,
  value,
  sublabel,
}: {
  label: string;
  value: string;
  sublabel?: string;
}) {
  return (
    <div className="rounded-md border border-border bg-card px-3 py-2.5">
      <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-medium">
        {label}
      </p>
      <p className="text-lg font-semibold tracking-tight text-foreground tabular-nums">
        {value}
      </p>
      {sublabel ? (
        <p className="text-[10px] text-muted-foreground mt-0.5">{sublabel}</p>
      ) : null}
    </div>
  );
}

function StatusBreakdown({
  total,
  byStatus,
}: {
  total: number;
  byStatus: Record<AppointmentStatus, number>;
}) {
  const ORDER: AppointmentStatus[] = [
    'booked',
    'confirmed',
    'checked_in',
    'completed',
    'no_show',
    'cancelled',
  ];
  return (
    <Section title="By status" icon={<Clock className="size-3.5 text-muted-foreground" />}>
      <ul className="space-y-1.5">
        {ORDER.map((status) => {
          const count = byStatus[status] ?? 0;
          if (count === 0) return null;
          const pct = total > 0 ? Math.round((count / total) * 100) : 0;
          return (
            <li key={status} className="flex items-center gap-2">
              <span className="text-xs text-foreground/80 w-24 shrink-0 truncate">
                {STATUS_LABELS[status]}
              </span>
              <div className="flex-1 h-1.5 rounded-full bg-muted/60 overflow-hidden">
                <div
                  className={cn('h-full rounded-full', STATUS_BAR_COLOR[status])}
                  style={{ width: `${pct}%` }}
                />
              </div>
              <span className="text-xs tabular-nums text-foreground w-6 text-right">
                {count}
              </span>
            </li>
          );
        })}
      </ul>
    </Section>
  );
}

function SourceBreakdown({
  total,
  bySource,
}: {
  total: number;
  bySource: Record<'online' | 'staff' | 'other', number>;
}) {
  const items: {
    key: 'online' | 'staff' | 'other';
    label: string;
    icon: React.ComponentType<{ className?: string }>;
  }[] = [
    { key: 'online', label: 'Online', icon: Globe },
    { key: 'staff', label: 'Staff', icon: Store },
    { key: 'other', label: 'Other', icon: Clock },
  ];
  return (
    <Section title="Booking source" icon={<Globe className="size-3.5 text-muted-foreground" />}>
      <ul className="grid grid-cols-3 gap-2">
        {items.map(({ key, label, icon: Icon }) => {
          const count = bySource[key] ?? 0;
          const pct = total > 0 ? Math.round((count / total) * 100) : 0;
          return (
            <li
              key={key}
              className="rounded-md border border-border bg-card px-2 py-2 text-center"
            >
              <Icon className="size-3 text-muted-foreground mx-auto mb-1" />
              <p className="text-sm font-semibold text-foreground tabular-nums">{count}</p>
              <p className="text-[10px] text-muted-foreground">{label}</p>
              <p className="text-[10px] text-muted-foreground tabular-nums">{pct}%</p>
            </li>
          );
        })}
      </ul>
    </Section>
  );
}

function ProvidersBreakdown({
  providers,
}: {
  providers: { id: number; name: string; count: number }[];
}) {
  return (
    <Section title="Top providers" icon={<Users className="size-3.5 text-muted-foreground" />}>
      <ul className="space-y-1.5">
        {providers.map((p) => (
          <li
            key={p.id}
            className="flex items-center justify-between gap-2 px-2 py-1 rounded-md hover:bg-muted/40"
          >
            <span className="text-xs text-foreground truncate">{p.name}</span>
            <span className="text-xs tabular-nums text-muted-foreground">
              {p.count}
            </span>
          </li>
        ))}
      </ul>
    </Section>
  );
}

function Section({
  title,
  icon,
  children,
}: {
  title: string;
  icon?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section>
      <div className="flex items-center gap-1.5 px-1 mb-2">
        {icon}
        <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-medium">
          {title}
        </p>
      </div>
      {children}
    </section>
  );
}

// ── Stat derivation ─────────────────────────────────────────────────

interface DerivedStats {
  total: number;
  revenueCents: number;
  byStatus: Record<AppointmentStatus, number>;
  bySource: Record<'online' | 'staff' | 'other', number>;
  topProviders: { id: number; name: string; count: number }[];
}

function deriveStats(appts: Appointment[]): DerivedStats {
  const byStatus: Record<AppointmentStatus, number> = {
    booked: 0,
    confirmed: 0,
    checked_in: 0,
    completed: 0,
    cancelled: 0,
    no_show: 0,
  };
  const bySource: Record<'online' | 'staff' | 'other', number> = {
    online: 0,
    staff: 0,
    other: 0,
  };
  const providerLoad = new Map<number, { name: string; count: number }>();

  let revenueCents = 0;

  for (const a of appts) {
    byStatus[a.status] = (byStatus[a.status] ?? 0) + 1;

    const sourceKey: 'online' | 'staff' | 'other' =
      a.source === 'online' ? 'online' : a.source === 'staff' ? 'staff' : 'other';
    bySource[sourceKey] += 1;

    // Cancelled / no-show appointments aren't part of "today's
    // revenue" expectation — quoted price for those was never going
    // to land, so we exclude them from the revenue total. The display
    // copy ("If all paid") makes this an estimate, not a financial
    // truth.
    if (a.status !== 'cancelled' && a.status !== 'no_show') {
      revenueCents += a.quoted_price_cents ?? 0;
    }

    const pid = a.provider.id;
    const pname = `${a.provider.user_first_name} ${a.provider.user_last_name}`.trim()
      || a.provider.user_email;
    const cur = providerLoad.get(pid) ?? { name: pname, count: 0 };
    cur.count += 1;
    providerLoad.set(pid, cur);
  }

  const topProviders = Array.from(providerLoad.entries())
    .map(([id, v]) => ({ id, name: v.name, count: v.count }))
    .sort((a, b) => b.count - a.count)
    .slice(0, 3);

  return {
    total: appts.length,
    revenueCents,
    byStatus,
    bySource,
    topProviders,
  };
}

// ── Helpers ────────────────────────────────────────────────────────

const STATUS_BAR_COLOR: Record<AppointmentStatus, string> = {
  booked: 'bg-stone-400',
  confirmed: 'bg-blue-500',
  checked_in: 'bg-amber-500',
  completed: 'bg-emerald-500',
  cancelled: 'bg-stone-300',
  no_show: 'bg-red-400',
};

function formatDollars(cents: number): string {
  // No-cents formatting for the at-a-glance "quoted revenue" stat.
  // Used when a rough order-of-magnitude is the right read.
  return `$${(cents / 100).toLocaleString('en-US', {
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  })}`;
}

function formatDollarsExact(cents: number): string {
  // Cents-precise formatting for the money-collected card. The
  // owner reconciles this against the cash drawer + card terminal,
  // so $1,234.56 is the right resolution; rounding to whole dollars
  // would make reconciliation harder.
  return `$${(cents / 100).toLocaleString('en-US', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

function formatFocusDate(iso: string, timezone: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  if (!m) return iso;
  // Build the date in the location's tz so "today" reads correctly
  // when the server is somewhere else.
  const todayIso = new Intl.DateTimeFormat('en-CA', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    timeZone: timezone,
  })
    .format(new Date())
    .replaceAll('/', '-');
  if (iso === todayIso) return 'Today';
  const tmrw = new Date();
  tmrw.setDate(tmrw.getDate() + 1);
  const tmrwIso = new Intl.DateTimeFormat('en-CA', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    timeZone: timezone,
  })
    .format(tmrw)
    .replaceAll('/', '-');
  if (iso === tmrwIso) return 'Tomorrow';

  const d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  return d.toLocaleDateString('en-US', {
    weekday: 'long',
    month: 'long',
    day: 'numeric',
  });
}
