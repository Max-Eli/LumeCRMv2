/**
 * Service catalog data hooks for the Lumè frontend.
 *
 * Pairs with the Django `apps.services` API at `/api/services/`. Pricing is
 * stored in cents on the backend; helpers below expose a `price_dollars`
 * preformatted string for display, plus `centsFromDollars` for converting
 * form input.
 */

'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from './api';
import type { JobTitle } from './job-titles';

/** Slim category shape returned nested inside Service responses. */
export interface ServiceCategorySummary {
  id: number;
  name: string;
  color: string;
  sort_order: number;
}

/** Full category shape with eligibility rules + service count. */
export interface ServiceCategory extends ServiceCategorySummary {
  eligible_job_titles: JobTitle[];
  service_count: number;
}

export interface CreateCategoryInput {
  name: string;
  color?: string;
  sort_order?: number;
  eligible_job_title_ids?: number[];
}

export type UpdateCategoryInput = Partial<CreateCategoryInput>;

export type ServiceType = 'regular' | 'addon';

/** A bookable, billable service offered by the tenant. */
export interface Service {
  id: number;
  name: string;
  code: string;
  description: string;
  service_type: ServiceType;
  category: ServiceCategorySummary | null;
  duration_minutes: number;
  buffer_minutes: number;
  price_cents: number;
  price_dollars: string;
  tax_rate_percent: string; // DRF returns DecimalField as string for precision
  is_bookable_online: boolean;
  is_active: boolean;
  sort_order: number;
  created_at: string;
  updated_at: string;
}

export interface CreateServiceInput {
  name: string;
  code?: string;
  description?: string;
  service_type?: ServiceType;
  category_id?: number | null;
  duration_minutes: number;
  buffer_minutes?: number;
  price_cents: number;
  tax_rate_percent?: string | number;
  is_bookable_online?: boolean;
  is_active?: boolean;
  sort_order?: number;
}

export type UpdateServiceInput = Partial<CreateServiceInput>;

const SERVICES_KEY = ['services'] as const;
const serviceKey = (id: number) => [...SERVICES_KEY, id] as const;

/** Convert a dollar amount typed in a form to integer cents for the API. */
export function centsFromDollars(input: string | number): number {
  if (input === '' || input == null) return 0;
  const n = typeof input === 'string' ? Number(input) : input;
  if (Number.isNaN(n)) return 0;
  return Math.round(n * 100);
}

/** Convert integer cents (e.g. 24000) to a form-friendly dollar string ("240.00"). */
export function dollarsFromCents(cents: number): string {
  return (cents / 100).toFixed(2);
}

const CATEGORIES_KEY = ['service-categories'] as const;
const categoryKey = (id: number) => [...CATEGORIES_KEY, id] as const;

/** List all service categories for the current tenant. */
export function useServiceCategories() {
  return useQuery<ServiceCategory[]>({
    queryKey: CATEGORIES_KEY,
    queryFn: () => api.get<ServiceCategory[]>('/api/service-categories/'),
  });
}

/** Fetch a single category by ID — used by the edit page. */
export function useServiceCategory(id: number | undefined) {
  return useQuery<ServiceCategory>({
    queryKey: id ? categoryKey(id) : ['service-categories', 'disabled'],
    queryFn: () => api.get<ServiceCategory>(`/api/service-categories/${id}/`),
    enabled: typeof id === 'number' && id > 0,
  });
}

export function useCreateServiceCategory() {
  const qc = useQueryClient();
  return useMutation<ServiceCategory, Error, CreateCategoryInput>({
    mutationFn: (input) => api.post<ServiceCategory>('/api/service-categories/', input),
    onSuccess: (created) => {
      qc.invalidateQueries({ queryKey: CATEGORIES_KEY });
      qc.setQueryData(categoryKey(created.id), created);
    },
  });
}

export function useUpdateServiceCategory(id: number) {
  const qc = useQueryClient();
  return useMutation<ServiceCategory, Error, UpdateCategoryInput>({
    mutationFn: (input) => api.patch<ServiceCategory>(`/api/service-categories/${id}/`, input),
    onSuccess: (updated) => {
      qc.setQueryData(categoryKey(updated.id), updated);
      qc.invalidateQueries({ queryKey: CATEGORIES_KEY });
    },
  });
}

export function useDeleteServiceCategory() {
  const qc = useQueryClient();
  return useMutation<void, Error, number>({
    mutationFn: (id) => api.delete(`/api/service-categories/${id}/`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: CATEGORIES_KEY });
    },
  });
}

/**
 * List services. Optional search + category filter + active-only toggle.
 * Server applies tenant scoping.
 */
export function useServices(opts?: { q?: string; categoryId?: number; activeOnly?: boolean }) {
  const params = new URLSearchParams();
  if (opts?.q) params.set('q', opts.q);
  if (opts?.categoryId) params.set('category', String(opts.categoryId));
  if (opts?.activeOnly !== undefined) params.set('active', opts.activeOnly ? 'true' : 'false');
  const qs = params.toString();
  const path = qs ? `/api/services/?${qs}` : '/api/services/';

  return useQuery<Service[]>({
    queryKey: [...SERVICES_KEY, opts?.q ?? '', opts?.categoryId ?? 0, opts?.activeOnly ?? null],
    queryFn: () => api.get<Service[]>(path),
  });
}

/** Fetch a single service by ID. */
export function useService(id: number | undefined) {
  return useQuery<Service>({
    queryKey: id ? serviceKey(id) : ['services', 'disabled'],
    queryFn: () => api.get<Service>(`/api/services/${id}/`),
    enabled: typeof id === 'number' && id > 0,
  });
}

export function useCreateService() {
  const qc = useQueryClient();
  return useMutation<Service, Error, CreateServiceInput>({
    mutationFn: (input) => api.post<Service>('/api/services/', input),
    onSuccess: (created) => {
      qc.invalidateQueries({ queryKey: SERVICES_KEY });
      qc.setQueryData(serviceKey(created.id), created);
    },
  });
}

export function useUpdateService(id: number) {
  const qc = useQueryClient();
  return useMutation<Service, Error, UpdateServiceInput>({
    mutationFn: (input) => api.patch<Service>(`/api/services/${id}/`, input),
    onSuccess: (updated) => {
      qc.setQueryData(serviceKey(updated.id), updated);
      qc.invalidateQueries({ queryKey: SERVICES_KEY });
    },
  });
}
