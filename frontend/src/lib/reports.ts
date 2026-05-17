/**
 * Report hooks (Phase 1G).
 *
 * Two surfaces:
 *
 *   - **Catalog** (`GET /api/reports/`) — drives the reports library
 *     landing page. Server-side filtered by the membership's
 *     permissions; we never get back a report we can't run, so the
 *     UI doesn't need to duplicate the gating.
 *   - **Per-report run** (`GET /api/reports/<category>/<slug>/`) —
 *     each report returns the same envelope (`report_id`, `params`,
 *     `summary`, `rows`) but the inner shape varies by report. The
 *     hook is generic over the row + summary types so each report
 *     page declares its own shape locally.
 *
 * Every successful run writes an audit log entry server-side
 * (SOC 2 CC 6.1, HIPAA §164.312(b)). The frontend doesn't need to
 * do anything to participate — just calling the endpoint is enough.
 *
 * See ADR 0013 for the architecture.
 */

'use client';

import { useQuery } from '@tanstack/react-query';

import { api } from './api';

export type ReportCategoryId =
  | 'financial'
  | 'staff'
  | 'guests'
  | 'operations'
  | 'marketing';

export type PhiTier = 'none' | 'aggregated' | 'per_customer';

export interface ReportCatalogEntry {
  id: string;          // e.g. 'financial.sales_by_date_range'
  category: ReportCategoryId;
  title: string;
  description: string;
  phi_tier: PhiTier;
  url: string;         // e.g. '/api/reports/financial/sales-by-date-range/'
}

export interface ReportCategory {
  id: ReportCategoryId;
  label: string;
  description: string;
  reports: ReportCatalogEntry[];
}

export interface ReportCatalog {
  categories: ReportCategory[];
}

const CATALOG_KEY = ['reports', 'catalog'] as const;

/** List of reports the current user is allowed to run, grouped by category.
 *  Categories with zero accessible reports are omitted server-side. */
export function useReportCatalog() {
  return useQuery<ReportCatalog>({
    queryKey: CATALOG_KEY,
    queryFn: () => api.get<ReportCatalog>('/api/reports/'),
    // Catalog is small + permission-shaped; cache for the session.
    staleTime: 5 * 60 * 1000,
  });
}

// ── Generic single-report runner ────────────────────────────────────

/** Standard envelope every report returns. `Summary` and `Row` shapes
 *  are report-specific — supply them at the call site. */
export interface ReportEnvelope<Summary, Row> {
  report_id: string;
  params: Record<string, string>;
  summary: Summary;
  rows: Row[];
}

export interface DateRangeParams {
  date_from?: string;  // YYYY-MM-DD; defaults to last 30 days server-side
  date_to?: string;
  // Index signature lets DateRangeParams pass through `useReportRun`'s
  // generic Record<string, string | undefined> without a cast.
  [k: string]: string | undefined;
}

function paramsToQuery(params: Record<string, string | undefined> = {}): string {
  const usp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== '') usp.set(k, v);
  }
  const qs = usp.toString();
  return qs ? `?${qs}` : '';
}

/** Run an arbitrary report by URL, returning the typed envelope.
 *  Designed to be wrapped by per-report hooks below. */
export function useReportRun<Summary, Row>(
  url: string | undefined,
  params: Record<string, string | undefined> = {},
) {
  const qs = paramsToQuery(params);
  return useQuery<ReportEnvelope<Summary, Row>>({
    queryKey: ['reports', 'run', url ?? '', params],
    queryFn: () => api.get<ReportEnvelope<Summary, Row>>(`${url}${qs}`),
    enabled: !!url,
  });
}

// ── Per-report typed shapes + hooks ─────────────────────────────────

// Financial · Sales by date range

export interface SalesByDateRangeRow {
  date: string;             // YYYY-MM-DD
  gross_cents: number;
  tax_cents: number;
  subtotal_cents: number;
  invoice_count: number;
}

export interface SalesByDateRangeSummary {
  total_gross_cents: number;
  total_tax_cents: number;
  total_subtotal_cents: number;
  paid_invoice_count: number;
  avg_invoice_cents: number;
  by_payment_method: Array<{
    method: string;
    method_label: string;
    gross_cents: number;
    invoice_count: number;
  }>;
}

export function useSalesByDateRange(params: DateRangeParams = {}) {
  return useReportRun<SalesByDateRangeSummary, SalesByDateRangeRow>(
    '/api/reports/financial/sales-by-date-range/',
    params,
  );
}

// Staff · Revenue by provider

export interface RevenueByProviderRow {
  provider_id: number;
  provider_name: string;
  gross_cents: number;
  appointment_count: number;
}

export interface RevenueByProviderSummary {
  total_gross_cents: number;
  total_appointments: number;
  provider_count: number;
  avg_revenue_per_provider_cents: number;
}

export function useRevenueByProvider(params: DateRangeParams = {}) {
  return useReportRun<RevenueByProviderSummary, RevenueByProviderRow>(
    '/api/reports/staff/revenue-by-provider/',
    params,
  );
}

// Guests · New vs returning

export type NewVsReturningClassification = 'new' | 'returning';

export interface NewVsReturningRow {
  customer_id: number;
  customer_name: string;
  classification: NewVsReturningClassification;
  first_appointment_date: string;
  appointments_in_range: number;
}

export interface NewVsReturningSummary {
  new_count: number;
  returning_count: number;
  total_unique_customers: number;
}

export function useNewVsReturning(params: DateRangeParams = {}) {
  return useReportRun<NewVsReturningSummary, NewVsReturningRow>(
    '/api/reports/guests/new-vs-returning/',
    params,
  );
}

// ── Session 2 hooks (Financial / Staff / Guests / Operations) ──────

// Financial · Daily close-out

export interface DailyCloseOutRow {
  date: string;
  gross_cents: number;
  tax_cents: number;
  invoice_count: number;
  by_method: Record<string, number>;
}

export interface DailyCloseOutSummary {
  total_gross_cents: number;
  total_tax_cents: number;
  paid_invoice_count: number;
  method_keys: string[];
  method_labels: Record<string, string>;
}

export function useDailyCloseOut(params: DateRangeParams = {}) {
  return useReportRun<DailyCloseOutSummary, DailyCloseOutRow>(
    '/api/reports/financial/daily-close-out/',
    params,
  );
}

// Financial · AR aging

export interface ARAgingRow {
  invoice_id: number;
  customer_id: number;
  customer_name: string;
  customer_email: string;
  age_days: number;
  bucket: string;
  gross_cents: number;
  created_date: string;
}

export interface ARAgingBucket {
  id: string;
  label: string;
  gross_cents: number;
  invoice_count: number;
}

export interface ARAgingSummary {
  total_open_cents: number;
  open_invoice_count: number;
  buckets: ARAgingBucket[];
}

export function useARAging() {
  return useReportRun<ARAgingSummary, ARAgingRow>('/api/reports/financial/ar-aging/');
}

// Financial · Revenue by service

export interface RevenueByServiceRow {
  service_id: number;
  service_name: string;
  gross_cents: number;
  tax_cents: number;
  unit_count: number;
}

export interface RevenueByServiceSummary {
  total_gross_cents: number;
  total_units: number;
  service_count: number;
  avg_revenue_per_service_cents: number;
}

export function useRevenueByService(params: DateRangeParams = {}) {
  return useReportRun<RevenueByServiceSummary, RevenueByServiceRow>(
    '/api/reports/financial/revenue-by-service/',
    params,
  );
}

// Financial · Revenue by location

export interface RevenueByLocationRow {
  location_id: number;
  location_name: string;
  gross_cents: number;
  appointment_count: number;
}

export interface RevenueByLocationSummary {
  total_gross_cents: number;
  total_appointments: number;
  location_count: number;
}

export function useRevenueByLocation(params: DateRangeParams = {}) {
  return useReportRun<RevenueByLocationSummary, RevenueByLocationRow>(
    '/api/reports/financial/revenue-by-location/',
    params,
  );
}

// Financial · Tax collected

export interface TaxCollectedRow {
  tax_rate_percent: string;
  taxable_subtotal_cents: number;
  tax_cents: number;
  line_count: number;
}

export interface TaxCollectedSummary {
  total_tax_cents: number;
  total_taxable_subtotal_cents: number;
  rate_count: number;
  effective_rate_percent: number;
}

export function useTaxCollected(params: DateRangeParams = {}) {
  return useReportRun<TaxCollectedSummary, TaxCollectedRow>(
    '/api/reports/financial/tax-collected/',
    params,
  );
}

// Staff · Schedule utilization

export interface ScheduleUtilizationRow {
  provider_id: number;
  provider_name: string;
  scheduled_minutes: number;
  delivered_minutes: number;
  utilization_pct: number;
}

export interface ScheduleUtilizationSummary {
  total_scheduled_minutes: number;
  total_delivered_minutes: number;
  overall_utilization_pct: number;
  provider_count: number;
}

export function useScheduleUtilization(params: DateRangeParams = {}) {
  return useReportRun<ScheduleUtilizationSummary, ScheduleUtilizationRow>(
    '/api/reports/staff/schedule-utilization/',
    params,
  );
}

// Staff · No-show rate by provider

export interface NoShowByProviderRow {
  provider_id: number;
  provider_name: string;
  total_appointments: number;
  no_show_count: number;
  no_show_rate_pct: number;
}

export interface NoShowByProviderSummary {
  total_appointments: number;
  total_no_shows: number;
  overall_no_show_rate_pct: number;
  provider_count: number;
}

export function useNoShowByProvider(params: DateRangeParams = {}) {
  return useReportRun<NoShowByProviderSummary, NoShowByProviderRow>(
    '/api/reports/staff/no-show-rate-by-provider/',
    params,
  );
}

// Staff · New clients by provider

export interface NewClientsByProviderRow {
  provider_id: number;
  provider_name: string;
  new_client_count: number;
}

export interface NewClientsByProviderSummary {
  total_new_clients: number;
  provider_count: number;
}

export function useNewClientsByProvider(params: DateRangeParams = {}) {
  return useReportRun<NewClientsByProviderSummary, NewClientsByProviderRow>(
    '/api/reports/staff/new-clients-by-provider/',
    params,
  );
}

// Staff · Repeat rate by provider

export interface RepeatRateByProviderRow {
  provider_id: number;
  provider_name: string;
  unique_client_count: number;
  repeat_client_count: number;
  repeat_rate_pct: number;
}

export interface RepeatRateByProviderSummary {
  total_unique_clients: number;
  total_repeat_clients: number;
  overall_repeat_rate_pct: number;
  provider_count: number;
}

export function useRepeatRateByProvider() {
  return useReportRun<RepeatRateByProviderSummary, RepeatRateByProviderRow>(
    '/api/reports/staff/repeat-rate-by-provider/',
  );
}

// Guests · Top spenders

export interface TopSpendersRow {
  customer_id: number;
  customer_name: string;
  customer_email: string;
  lifetime_cents: number;
  paid_invoice_count: number;
  last_paid_date: string | null;
}

export interface TopSpendersSummary {
  returned_count: number;
  total_lifetime_cents: number;
  avg_lifetime_cents: number;
  limit: number;
}

export function useTopSpenders(params: { limit?: string } = {}) {
  return useReportRun<TopSpendersSummary, TopSpendersRow>(
    '/api/reports/guests/top-spenders/',
    params,
  );
}

// Guests · Inactive clients

export interface InactiveClientsRow {
  customer_id: number;
  customer_name: string;
  customer_email: string;
  customer_phone: string;
  last_appointment_date: string | null;
  days_since_last_visit: number;
  never_visited: boolean;
}

export interface InactiveClientsSummary {
  inactive_client_count: number;
  never_visited_count: number;
  days_threshold: number;
}

export function useInactiveClients(params: { days?: string } = {}) {
  return useReportRun<InactiveClientsSummary, InactiveClientsRow>(
    '/api/reports/guests/inactive-clients/',
    params,
  );
}

// Guests · Birthday list

export interface BirthdayListRow {
  customer_id: number;
  customer_name: string;
  customer_email: string;
  customer_phone: string;
  birthday: string;
  next_birthday_date: string;
  days_until_birthday: number;
  age_turning: number;
  email_opt_in: boolean;
}

export interface BirthdayListSummary {
  upcoming_birthday_count: number;
  window_days: number;
  opted_in_count: number;
}

export function useBirthdayList(params: { window_days?: string } = {}) {
  return useReportRun<BirthdayListSummary, BirthdayListRow>(
    '/api/reports/guests/birthday-list/',
    params,
  );
}

// Guests · Visit frequency

export interface VisitFrequencyRow {
  bucket_id: string;
  label: string;
  min_visits: number;
  max_visits: number | null;
  customer_count: number;
  share_pct: number;
}

export interface VisitFrequencySummary {
  total_unique_clients_with_visits: number;
  bucket_count: number;
}

export function useVisitFrequency() {
  return useReportRun<VisitFrequencySummary, VisitFrequencyRow>(
    '/api/reports/guests/visit-frequency/',
  );
}

// Guests · Forms outstanding

export interface FormsOutstandingRow {
  customer_id: number;
  customer_name: string;
  customer_email: string;
  customer_phone: string;
  pending_form_count: number;
}

export interface FormsOutstandingSummary {
  customer_count: number;
  total_pending_forms: number;
}

export function useFormsOutstanding() {
  return useReportRun<FormsOutstandingSummary, FormsOutstandingRow>(
    '/api/reports/guests/forms-outstanding/',
  );
}

// Operations · Appointments by status

export interface AppointmentsByStatusRow {
  status: string;
  status_label: string;
  appointment_count: number;
}

export interface AppointmentsByStatusSummary {
  total_appointments: number;
  status_count: number;
}

export function useAppointmentsByStatus(params: DateRangeParams = {}) {
  return useReportRun<AppointmentsByStatusSummary, AppointmentsByStatusRow>(
    '/api/reports/operations/appointments-by-status/',
    params,
  );
}

// Operations · No-show rate (overall, daily breakdown)

export interface NoShowRateRow {
  date: string;
  total_appointments: number;
  no_show_count: number;
  no_show_rate_pct: number;
}

export interface NoShowRateSummary {
  total_appointments: number;
  total_no_shows: number;
  overall_no_show_rate_pct: number;
}

export function useNoShowRate(params: DateRangeParams = {}) {
  return useReportRun<NoShowRateSummary, NoShowRateRow>(
    '/api/reports/operations/no-show-rate/',
    params,
  );
}

// Operations · Cancellation rate

export interface CancellationRateRow {
  date: string;
  total_appointments: number;
  cancelled_count: number;
  cancellation_rate_pct: number;
}

export interface CancellationRateSummary {
  total_appointments: number;
  total_cancellations: number;
  overall_cancellation_rate_pct: number;
}

export function useCancellationRate(params: DateRangeParams = {}) {
  return useReportRun<CancellationRateSummary, CancellationRateRow>(
    '/api/reports/operations/cancellation-rate/',
    params,
  );
}

// Operations · Booking lead time

export interface BookingLeadTimeRow {
  bucket_id: string;
  label: string;
  min_days: number;
  max_days: number | null;
  appointment_count: number;
  share_pct: number;
}

export interface BookingLeadTimeSummary {
  total_appointments: number;
  avg_lead_days: number;
}

export function useBookingLeadTime(params: DateRangeParams = {}) {
  return useReportRun<BookingLeadTimeSummary, BookingLeadTimeRow>(
    '/api/reports/operations/booking-lead-time/',
    params,
  );
}

// Operations · Service mix

export interface ServiceMixRow {
  service_id: number;
  service_name: string;
  appointment_count: number;
  share_pct: number;
}

export interface ServiceMixSummary {
  total_appointments: number;
  service_count: number;
}

export function useServiceMix(params: DateRangeParams = {}) {
  return useReportRun<ServiceMixSummary, ServiceMixRow>(
    '/api/reports/operations/service-mix/',
    params,
  );
}

// Operations · Busiest hours

export interface BusiestHoursRow {
  weekday: number;
  weekday_label: string;
  hour: number;
  appointment_count: number;
}

export interface BusiestHoursSummary {
  total_appointments: number;
  peak_hour: number | null;
  peak_hour_label: string | null;
  peak_weekday: number | null;
  peak_weekday_label: string | null;
  grid: number[][];        // [weekday][hour] → count
  per_hour: number[];      // [hour] → count
  per_weekday: number[];   // [weekday] → count
}

export function useBusiestHours(params: DateRangeParams = {}) {
  return useReportRun<BusiestHoursSummary, BusiestHoursRow>(
    '/api/reports/operations/busiest-hours/',
    params,
  );
}

// ── Display helpers (extra) ────────────────────────────────────────

export function formatPct(value: number, decimals = 1): string {
  return `${value.toFixed(decimals)}%`;
}

export function formatMinutesAsHours(minutes: number): string {
  if (minutes < 60) return `${minutes}m`;
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return m === 0 ? `${h}h` : `${h}h ${m}m`;
}

// ── Display helpers ────────────────────────────────────────────────

export function formatCents(cents: number): string {
  const dollars = cents / 100;
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(dollars);
}

export function formatNumber(n: number): string {
  return new Intl.NumberFormat('en-US').format(n);
}

/** Build a YYYY-MM-DD string in the local timezone (avoids UTC drift
 *  on inputs the user just picked). */
export function toIsoDate(d: Date): string {
  const year = d.getFullYear();
  const month = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

export interface DatePreset {
  id: string;
  label: string;
  range: () => { date_from: string; date_to: string };
}

export const DATE_PRESETS: DatePreset[] = [
  {
    id: 'last_7',
    label: 'Last 7 days',
    range: () => {
      const today = new Date();
      const start = new Date(today);
      start.setDate(today.getDate() - 6);
      return { date_from: toIsoDate(start), date_to: toIsoDate(today) };
    },
  },
  {
    id: 'last_30',
    label: 'Last 30 days',
    range: () => {
      const today = new Date();
      const start = new Date(today);
      start.setDate(today.getDate() - 29);
      return { date_from: toIsoDate(start), date_to: toIsoDate(today) };
    },
  },
  {
    id: 'last_90',
    label: 'Last 90 days',
    range: () => {
      const today = new Date();
      const start = new Date(today);
      start.setDate(today.getDate() - 89);
      return { date_from: toIsoDate(start), date_to: toIsoDate(today) };
    },
  },
  {
    id: 'this_month',
    label: 'This month',
    range: () => {
      const today = new Date();
      const start = new Date(today.getFullYear(), today.getMonth(), 1);
      return { date_from: toIsoDate(start), date_to: toIsoDate(today) };
    },
  },
  {
    id: 'last_month',
    label: 'Last month',
    range: () => {
      const today = new Date();
      const start = new Date(today.getFullYear(), today.getMonth() - 1, 1);
      const end = new Date(today.getFullYear(), today.getMonth(), 0);
      return { date_from: toIsoDate(start), date_to: toIsoDate(end) };
    },
  },
  {
    id: 'ytd',
    label: 'Year to date',
    range: () => {
      const today = new Date();
      const start = new Date(today.getFullYear(), 0, 1);
      return { date_from: toIsoDate(start), date_to: toIsoDate(today) };
    },
  },
];

// Financial · Revenue by acquisition source (ADR 0027 §8c)

export interface RevenueByAcquisitionSourceRow {
  acquisition_source: string;
  acquisition_source_label: string;
  gross_cents: number;
  invoice_count: number;
  customer_count: number;
  avg_ticket_cents: number;
}

export interface RevenueByAcquisitionSourceSummary {
  total_gross_cents: number;
  total_invoices: number;
  distinct_sources: number;
}

export function useRevenueByAcquisitionSource(params: DateRangeParams = {}) {
  return useReportRun<RevenueByAcquisitionSourceSummary, RevenueByAcquisitionSourceRow>(
    '/api/reports/financial/revenue-by-acquisition-source/',
    params,
  );
}

// Operations · Bookings by acquisition source (ADR 0027 §8c)

export interface BookingsByAcquisitionSourceRow {
  acquisition_source: string;
  acquisition_source_label: string;
  appointment_count: number;
  completed_count: number;
  cancelled_count: number;
  no_show_count: number;
  cancellation_rate_pct: number;
  no_show_rate_pct: number;
}

export interface BookingsByAcquisitionSourceSummary {
  total_appointments: number;
  distinct_sources: number;
}

export function useBookingsByAcquisitionSource(params: DateRangeParams = {}) {
  return useReportRun<BookingsByAcquisitionSourceSummary, BookingsByAcquisitionSourceRow>(
    '/api/reports/operations/bookings-by-acquisition-source/',
    params,
  );
}
