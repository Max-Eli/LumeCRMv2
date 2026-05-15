/**
 * Packages catalog + per-customer purchased-package hooks.
 *
 * Pairs with `apps.packages` at `/api/packages/` (catalog) and the
 * invoice action endpoints for sale + redemption.
 *
 * Money in cents on the wire; helpers convert at the display edge.
 */

'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from './api';

// ── Catalog types ───────────────────────────────────────────────────

export interface PackageItemOutput {
  id: number;
  service_id: number;
  service_name: string;
  service_price_cents: number;
  quantity: number;
  sort_order: number;
}

export interface PackageItemInput {
  service_id: number;
  quantity: number;
  sort_order?: number;
}

export interface Package {
  id: number;
  name: string;
  sku: string;
  description: string;
  price_cents: number;
  price_dollars: string;
  /** DRF DecimalField returns as string for precision. */
  tax_rate_percent: string;
  validity_days: number | null;
  is_active: boolean;
  sort_order: number;
  items: PackageItemOutput[];
  a_la_carte_total_cents: number;
  implicit_discount_cents: number;
  created_at: string;
  updated_at: string;
}

export interface CreatePackageInput {
  name: string;
  sku?: string;
  description?: string;
  price_cents: number;
  tax_rate_percent?: string | number;
  validity_days?: number | null;
  is_active?: boolean;
  sort_order?: number;
  items_input: PackageItemInput[];
}

export type UpdatePackageInput = Partial<CreatePackageInput>;

// ── Catalog query keys ──────────────────────────────────────────────

const PACKAGES_KEY = ['packages'] as const;
const packageKey = (id: number) => [...PACKAGES_KEY, id] as const;

export interface PackageListFilter {
  q?: string;
  activeOnly?: boolean;
}

export function usePackages(opts: PackageListFilter = {}) {
  const params = new URLSearchParams();
  if (opts.q) params.set('q', opts.q);
  if (opts.activeOnly !== undefined) {
    params.set('active', opts.activeOnly ? 'true' : 'false');
  }
  const qs = params.toString();
  const path = qs ? `/api/packages/?${qs}` : '/api/packages/';

  return useQuery<Package[]>({
    queryKey: [...PACKAGES_KEY, opts.q ?? '', opts.activeOnly ?? null],
    queryFn: () => api.get<Package[]>(path),
  });
}

export function usePackage(id: number | undefined) {
  return useQuery<Package>({
    queryKey: id ? packageKey(id) : ['packages', 'disabled'],
    queryFn: () => api.get<Package>(`/api/packages/${id}/`),
    enabled: typeof id === 'number' && id > 0,
  });
}

export function useCreatePackage() {
  const qc = useQueryClient();
  return useMutation<Package, Error, CreatePackageInput>({
    mutationFn: (input) => api.post<Package>('/api/packages/', input),
    onSuccess: (created) => {
      qc.invalidateQueries({ queryKey: PACKAGES_KEY });
      qc.setQueryData(packageKey(created.id), created);
    },
  });
}

export function useUpdatePackage(id: number) {
  const qc = useQueryClient();
  return useMutation<Package, Error, UpdatePackageInput>({
    mutationFn: (input) => api.patch<Package>(`/api/packages/${id}/`, input),
    onSuccess: (updated) => {
      qc.setQueryData(packageKey(updated.id), updated);
      qc.invalidateQueries({ queryKey: PACKAGES_KEY });
    },
  });
}

export function useDeletePackage() {
  const qc = useQueryClient();
  return useMutation<void, Error, number>({
    mutationFn: (id) => api.delete(`/api/packages/${id}/`),
    onSuccess: () => qc.invalidateQueries({ queryKey: PACKAGES_KEY }),
  });
}

// ── PurchasedPackage (per-customer instance) ────────────────────────

export type PurchasedPackageStatus = 'pending' | 'active' | 'voided';

export interface PurchasedPackageItem {
  id: number;
  service: number;
  service_name: string;
  quantity_purchased: number;
  quantity_remaining: number;
  unit_value_cents: number;
  sort_order: number;
}

export interface PackageRedemptionLedgerRow {
  id: number;
  purchased_package: number;
  item: number;
  service_name: string;
  quantity: number;
  invoice_line: number | null;
  appointment: number | null;
  by_user_email: string | null;
  note: string;
  redeemed_at: string;
}

export interface PurchasedPackage {
  id: number;
  customer: number;
  customer_first_name: string;
  customer_last_name: string;
  source_template: number | null;
  source_invoice_line: number;
  name: string;
  description: string;
  price_cents: number;
  validity_days: number | null;
  purchased_at: string | null;
  expires_at: string | null;
  status: PurchasedPackageStatus;
  voided_at: string | null;
  voided_by_email: string | null;
  void_reason: string;
  is_expired: boolean;
  is_redeemable: boolean;
  total_credits_remaining: number;
  items: PurchasedPackageItem[];
  redemptions: PackageRedemptionLedgerRow[];
  created_at: string;
  updated_at: string;
}

const PURCHASED_PACKAGES_KEY = ['purchased-packages'] as const;

export function useCustomerPurchasedPackages(
  customerId: number | undefined,
  opts: { status?: PurchasedPackageStatus } = {},
) {
  const params = new URLSearchParams();
  if (customerId) params.set('customer', String(customerId));
  if (opts.status) params.set('status', opts.status);
  const qs = params.toString();

  return useQuery<PurchasedPackage[]>({
    queryKey: [...PURCHASED_PACKAGES_KEY, customerId ?? 0, opts.status ?? ''],
    queryFn: () =>
      api.get<PurchasedPackage[]>(`/api/purchased-packages/?${qs}`),
    enabled: typeof customerId === 'number' && customerId > 0,
  });
}

// ── Build custom package (calendar tile workflow) ──────────────────


export interface BuildCustomPackageItemInput {
  service_id: number;
  quantity: number;
}

export interface BuildCustomPackageInput {
  customer_id: number;
  name: string;
  description?: string;
  price_cents: number;
  tax_rate_percent?: number;
  validity_days?: number | null;
  items: BuildCustomPackageItemInput[];
}

export interface BuildCustomPackageResult {
  purchased_package: PurchasedPackage;
  invoice_id: number;
  invoice_number: string;
  customer_id: number;
}

/** Build a one-off `PurchasedPackage` for a specific customer +
 *  an accompanying draft invoice in one atomic call. The returned
 *  `invoice_id` is the POS-handoff target — the UI links the
 *  operator to `/appointments/.../invoice/` or the
 *  `/invoices/<id>` page (whichever exists) so they can take
 *  payment on the spot. */
export function useBuildCustomPackage() {
  const qc = useQueryClient();
  return useMutation<BuildCustomPackageResult, Error, BuildCustomPackageInput>({
    mutationFn: (input) =>
      api.post<BuildCustomPackageResult>(
        '/api/purchased-packages/build-custom/',
        input,
      ),
    onSuccess: (_data, variables) => {
      // Refresh this customer's packages list so the new package
      // appears immediately in the calendar panel.
      qc.invalidateQueries({
        queryKey: [...PURCHASED_PACKAGES_KEY, variables.customer_id],
      });
    },
  });
}

// ── Money formatters ────────────────────────────────────────────────

export function centsFromDollars(input: string | number): number {
  if (input === '' || input == null) return 0;
  const n = typeof input === 'string' ? Number(input) : input;
  if (Number.isNaN(n)) return 0;
  return Math.round(n * 100);
}

export function dollarsFromCents(cents: number): string {
  return (cents / 100).toFixed(2);
}
