/**
 * Retail product catalog hooks.
 *
 * Pairs with the Django `apps.products` API at `/api/products/`.
 * Pricing is in cents on the wire; helpers convert to/from a form-
 * friendly dollar string. Stock adjustments require an operator
 * note — `useAdjustProductStock()` enforces that at the input type
 * level so the API never gets a missing-note 400.
 */

'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from './api';

// ── Categories ──────────────────────────────────────────────────────

export interface ProductCategorySummary {
  id: number;
  name: string;
  color: string;
  sort_order: number;
}

export interface ProductCategory extends ProductCategorySummary {
  product_count: number;
}

export interface CreateProductCategoryInput {
  name: string;
  color?: string;
  sort_order?: number;
}

export type UpdateProductCategoryInput = Partial<CreateProductCategoryInput>;

const PRODUCT_CATEGORIES_KEY = ['product-categories'] as const;
const productCategoryKey = (id: number) =>
  [...PRODUCT_CATEGORIES_KEY, id] as const;

export function useProductCategories() {
  return useQuery<ProductCategory[]>({
    queryKey: PRODUCT_CATEGORIES_KEY,
    queryFn: () => api.get<ProductCategory[]>('/api/product-categories/'),
  });
}

export function useCreateProductCategory() {
  const qc = useQueryClient();
  return useMutation<ProductCategory, Error, CreateProductCategoryInput>({
    mutationFn: (input) =>
      api.post<ProductCategory>('/api/product-categories/', input),
    onSuccess: (created) => {
      qc.invalidateQueries({ queryKey: PRODUCT_CATEGORIES_KEY });
      qc.setQueryData(productCategoryKey(created.id), created);
    },
  });
}

export function useUpdateProductCategory(id: number) {
  const qc = useQueryClient();
  return useMutation<ProductCategory, Error, UpdateProductCategoryInput>({
    mutationFn: (input) =>
      api.patch<ProductCategory>(`/api/product-categories/${id}/`, input),
    onSuccess: (updated) => {
      qc.setQueryData(productCategoryKey(updated.id), updated);
      qc.invalidateQueries({ queryKey: PRODUCT_CATEGORIES_KEY });
    },
  });
}

export function useDeleteProductCategory() {
  const qc = useQueryClient();
  return useMutation<void, Error, number>({
    mutationFn: (id) => api.delete(`/api/product-categories/${id}/`),
    onSuccess: () => qc.invalidateQueries({ queryKey: PRODUCT_CATEGORIES_KEY }),
  });
}

// ── Products ────────────────────────────────────────────────────────

export interface Product {
  id: number;
  name: string;
  sku: string;
  description: string;
  category: ProductCategorySummary | null;
  price_cents: number;
  price_dollars: string;
  cost_cents: number;
  /** DRF DecimalField returns as string for precision. */
  tax_rate_percent: string;
  track_inventory: boolean;
  stock_quantity: number;
  low_stock_threshold: number;
  is_low_stock: boolean;
  is_active: boolean;
  sort_order: number;
  created_at: string;
  updated_at: string;
}

export interface CreateProductInput {
  name: string;
  sku?: string;
  description?: string;
  category_id?: number | null;
  price_cents: number;
  cost_cents?: number;
  tax_rate_percent?: string | number;
  track_inventory?: boolean;
  stock_quantity?: number;
  low_stock_threshold?: number;
  is_active?: boolean;
  sort_order?: number;
}

export type UpdateProductInput = Partial<CreateProductInput>;

export interface AdjustStockInput {
  /** Signed delta — positive for received, negative for write-offs.
   *  Zero is rejected by the API. */
  delta: number;
  /** Required operator note — persists to the audit log. */
  note: string;
}

const PRODUCTS_KEY = ['products'] as const;
const productKey = (id: number) => [...PRODUCTS_KEY, id] as const;

export interface ProductListFilter {
  q?: string;
  categoryId?: number;
  activeOnly?: boolean;
  lowStockOnly?: boolean;
}

export function useProducts(opts: ProductListFilter = {}) {
  const params = new URLSearchParams();
  if (opts.q) params.set('q', opts.q);
  if (opts.categoryId) params.set('category', String(opts.categoryId));
  if (opts.activeOnly !== undefined) {
    params.set('active', opts.activeOnly ? 'true' : 'false');
  }
  if (opts.lowStockOnly) params.set('low_stock', 'true');
  const qs = params.toString();
  const path = qs ? `/api/products/?${qs}` : '/api/products/';

  return useQuery<Product[]>({
    queryKey: [
      ...PRODUCTS_KEY,
      opts.q ?? '',
      opts.categoryId ?? 0,
      opts.activeOnly ?? null,
      opts.lowStockOnly ?? false,
    ],
    queryFn: () => api.get<Product[]>(path),
  });
}

export function useProduct(id: number | undefined) {
  return useQuery<Product>({
    queryKey: id ? productKey(id) : ['products', 'disabled'],
    queryFn: () => api.get<Product>(`/api/products/${id}/`),
    enabled: typeof id === 'number' && id > 0,
  });
}

export function useCreateProduct() {
  const qc = useQueryClient();
  return useMutation<Product, Error, CreateProductInput>({
    mutationFn: (input) => api.post<Product>('/api/products/', input),
    onSuccess: (created) => {
      qc.invalidateQueries({ queryKey: PRODUCTS_KEY });
      qc.setQueryData(productKey(created.id), created);
    },
  });
}

export function useUpdateProduct(id: number) {
  const qc = useQueryClient();
  return useMutation<Product, Error, UpdateProductInput>({
    mutationFn: (input) => api.patch<Product>(`/api/products/${id}/`, input),
    onSuccess: (updated) => {
      qc.setQueryData(productKey(updated.id), updated);
      qc.invalidateQueries({ queryKey: PRODUCTS_KEY });
    },
  });
}

export function useDeleteProduct() {
  const qc = useQueryClient();
  return useMutation<void, Error, number>({
    mutationFn: (id) => api.delete(`/api/products/${id}/`),
    onSuccess: () => qc.invalidateQueries({ queryKey: PRODUCTS_KEY }),
  });
}

/** Apply a signed stock delta with required operator note (audit-logged). */
export function useAdjustProductStock(id: number) {
  const qc = useQueryClient();
  return useMutation<Product, Error, AdjustStockInput>({
    mutationFn: (input) =>
      api.post<Product>(`/api/products/${id}/adjust-stock/`, input),
    onSuccess: (updated) => {
      qc.setQueryData(productKey(updated.id), updated);
      qc.invalidateQueries({ queryKey: PRODUCTS_KEY });
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
