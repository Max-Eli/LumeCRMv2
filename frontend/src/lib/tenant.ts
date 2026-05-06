/**
 * Tenant-settings + membership-mutation hooks.
 *
 * Wraps `GET/PATCH /api/tenant/` (account-level: identity + branding)
 * and `PATCH /api/memberships/{id}/` (staff role / activation /
 * job-title / bookable). Read-only listing of memberships continues
 * to use `useBookableMemberships()` (calendar) and the new
 * `useAllMemberships()` (settings/staff) here.
 *
 * Per-site fields (timezone, address, hours, phone, email) used to
 * live on Tenant but moved to `Location` during the Phase 4E rollout.
 * They're now read + edited via `lib/locations.ts` (the calendar uses
 * `useActiveLocation()` for its day-window bounds; the
 * `/org/locations/[id]` page is the editor).
 *
 * Branding (`primary_color`, `logo_url`) lives on the tenant but the
 * staff CRM does NOT consume it — these are rendered only on the
 * tenant's login page and public booking page. The staff tools stay
 * on the consistent Lumè design system.
 */

'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from './api';
import type { Membership as AuthMembership } from './auth';
import { useActiveLocationSlug } from './locations';

export type TenantStatus = 'trial' | 'active' | 'suspended' | 'cancelled';

export interface TenantSettings {
  id: number;
  name: string;
  /** Subdomain — read-only. The user's portal URL is derived from this. */
  slug: string;
  status: TenantStatus;
  primary_color: string;
  logo_url: string;

  // Online booking settings — exposed on the same Tenant endpoint
  // because they're account-level config (not per-location). Edited
  // from `/org/online-booking`. See backend Tenant model for field
  // semantics.
  online_booking_enabled: boolean;
  online_booking_lead_minutes: number;
  online_booking_window_days: number;
  online_booking_welcome_message: string;
  online_booking_cancellation_policy: string;

  created_at: string;
  updated_at: string;
}

/** Parse a TimeField string (`HH:MM:SS` or `HH:MM`) to its hour
 *  component as an integer 0-23. Used by the calendar to derive the
 *  day-window bounds from a Location's business hours. Lives in this
 *  file for legacy reasons (it was originally for tenant hours); a
 *  future cleanup could move it to `lib/locations.ts`. */
export function tenantHourFromTime(time: string | null | undefined): number | null {
  if (!time) return null;
  const m = /^(\d{1,2}):(\d{2})/.exec(time);
  if (!m) return null;
  const h = Number(m[1]);
  if (!Number.isFinite(h) || h < 0 || h > 24) return null;
  return h;
}

export type UpdateTenantInput = Partial<
  Omit<TenantSettings, 'id' | 'slug' | 'status' | 'created_at' | 'updated_at'>
>;

const TENANT_KEY = ['tenant', 'settings'] as const;

/** Fetch the current tenant's settings (resolved by subdomain / cookie). */
export function useTenantSettings() {
  return useQuery<TenantSettings>({
    queryKey: TENANT_KEY,
    queryFn: () => api.get<TenantSettings>('/api/tenant/'),
    staleTime: 5 * 60 * 1000,
  });
}

/** Update the current tenant's business profile / branding. Owner-only
 *  on the backend (`MANAGE_TENANT_SETTINGS`).
 *
 *  Cache notes: we update the tenant detail cache directly AND
 *  invalidate the auth `me` query, because tenant fields (notably
 *  `name`) are also embedded inside `User.memberships[].tenant` for
 *  the sidebar / dashboard greeting. Without the second invalidation,
 *  the user sees the new name on /settings/business but stale
 *  everywhere else until a hard reload. */
export function useUpdateTenantSettings() {
  const qc = useQueryClient();
  return useMutation<TenantSettings, Error, UpdateTenantInput>({
    mutationFn: (input) => api.patch<TenantSettings>('/api/tenant/', input),
    onSuccess: (updated) => {
      qc.setQueryData(TENANT_KEY, updated);
      qc.invalidateQueries({ queryKey: ['auth', 'me'] });
    },
  });
}

// ── Memberships (writable) ────────────────────────────────────────────

export type StaffRole =
  | 'owner'
  | 'manager'
  | 'front_desk'
  | 'provider'
  | 'bookkeeper'
  | 'marketing';

export const ROLE_LABELS: Record<StaffRole, string> = {
  owner: 'Owner',
  manager: 'Manager',
  front_desk: 'Front desk',
  provider: 'Provider',
  bookkeeper: 'Bookkeeper',
  marketing: 'Marketing',
};

/** Roles surfaced as "promotable to" choices in the staff editor.
 *  Owner is intentionally omitted from this list — promoting to owner
 *  is a sensitive action that should go through a dedicated flow
 *  (e.g. an "Add owner" confirmation), not the casual role dropdown. */
export const ASSIGNABLE_ROLES: StaffRole[] = [
  'manager',
  'front_desk',
  'provider',
  'bookkeeper',
  'marketing',
];

export interface StaffMembership {
  id: number;
  user_email: string;
  user_first_name: string;
  user_last_name: string;
  role: StaffRole;
  job_title_id: number | null;
  job_title_name: string | null;
  job_title_is_clinical: boolean;
  is_bookable: boolean;
  is_active: boolean;
  /** Populated only when the request used `?location=current|<slug>`
   *  (the calendar + the per-location scheduler always do; the org
   *  staff list does not). The id of this person's
   *  `MembershipLocation` row at the active location — needed to
   *  PUT a per-location schedule against `/api/schedules/{id}/`. */
  membership_location_id?: number | null;
  /** Schedule for the active location (also only populated under
   *  location-scoped requests). Object keyed by lowercase weekday
   *  with `{start, end}` HH:MM blocks per day. `null` means "no
   *  schedule set" — provider bookable any time within business
   *  hours. Empty arrays per day mean "explicitly off." */
  schedule_for_location?: Record<string, Array<{ start: string; end: string }>> | null;
}

export interface UpdateMembershipInput {
  role?: StaffRole;
  is_active?: boolean;
  is_bookable?: boolean;
  job_title_id?: number | null;
}

// ── Employee detail (per-employee profile page) ───────────────────────

export type EmploymentType = 'full_time' | 'part_time' | 'contractor';
export type PayType = 'hourly' | 'salary' | 'commission_only';

export const EMPLOYMENT_TYPE_LABELS: Record<EmploymentType, string> = {
  full_time: 'Full-time',
  part_time: 'Part-time',
  contractor: 'Contractor',
};

export const PAY_TYPE_LABELS: Record<PayType, string> = {
  hourly: 'Hourly',
  salary: 'Salary',
  commission_only: 'Commission only',
};

/** Read-only summary of another tenant the same person belongs to —
 *  the "multi-center assignment" data on the employee profile. The
 *  backend strips payroll / contact info from this view. */
export interface OtherMembershipSummary {
  id: number;
  tenant_id: number;
  tenant_name: string;
  role: StaffRole;
  job_title_name: string | null;
  is_active: boolean;
}

/** Full employee detail returned by `GET /api/memberships/{id}/`.
 *  Includes nested user contact + per-tenant employment + payroll +
 *  multi-center summary + per-location assignments. PATCH accepts the
 *  same shape (minus the read-only fields), plus `set_location_ids`
 *  for replacing the assignment set. */
export interface EmployeeDetail extends StaffMembership {
  // Personal contact (lives on User; same regardless of which tenant)
  user_phone: string;
  user_address_line1: string;
  user_address_line2: string;
  user_city: string;
  user_state: string;
  user_zip_code: string;

  // Per-tenant employment + payroll
  employment_type: EmploymentType | '';
  pay_type: PayType | '';
  pay_rate_cents: number;
  hire_date: string | null; // YYYY-MM-DD
  employment_notes: string;

  // Per-location assignments — active locations the employee is
  // assigned to within this tenant. Read-only on the response;
  // mutate via `set_location_ids` on PATCH. The location-toggle UI
  // on the employee profile + the org-dashboard chip matrix both
  // read this list to decide which checkboxes are on.
  location_ids: number[];

  // Cross-tenant memberships (read-only) — kept for backward compat.
  // Will be removed entirely when the cross-tenant concept gets
  // retired in favor of per-location assignments alone.
  other_memberships: OtherMembershipSummary[];

  created_at: string;
  updated_at: string;
}

export interface UpdateEmployeeInput {
  // User-side
  user_first_name?: string;
  user_last_name?: string;
  user_phone?: string;
  user_address_line1?: string;
  user_address_line2?: string;
  user_city?: string;
  user_state?: string;
  user_zip_code?: string;
  // Membership-side
  role?: StaffRole;
  job_title_id?: number | null;
  is_bookable?: boolean;
  is_active?: boolean;
  employment_type?: EmploymentType | '';
  pay_type?: PayType | '';
  pay_rate_cents?: number;
  hire_date?: string | null;
  employment_notes?: string;
  // Location assignments (full-replace semantics — passed locations
  // are the active set after the PATCH; everything else gets soft-
  // deleted on the backend, preserving the audit trail).
  set_location_ids?: number[];
}

export interface CreateEmployeeInput {
  email: string;
  first_name: string;
  last_name: string;
  role: StaffRole;
  job_title_id?: number | null;
  is_bookable?: boolean;
  /** Optional explicit list of locations to assign this employee to.
   *  When omitted, the backend auto-assigns to the active location —
   *  matches the common Add-from-/staff/employees flow where the
   *  operator is at a specific site. Pass `[]` to opt out of auto-
   *  assignment (the employee won't show on any calendar until
   *  assigned later). */
  location_ids?: number[];
}

/** Response from `POST /api/memberships/` — full detail PLUS an
 *  optional one-time `temp_password` field. Present only when a brand-
 *  new User was created (not when an existing User was attached). The
 *  caller MUST display + clear it immediately; the password is not
 *  recoverable from the server after this point. */
export interface CreateEmployeeResponse extends EmployeeDetail {
  temp_password?: string;
}

const MEMBERSHIPS_KEY = ['memberships'] as const;

export interface UseAllMembershipsOptions {
  /** Scope the result by location:
   *    'current'  — active location (cookie / tenant default)
   *    'all'      — every membership in the tenant (org-wide view)
   *    undefined  — defaults to 'all' for backward compat
   *
   *  The `/staff/employees` page uses 'current' (location-scoped
   *  roster); the `/org/dashboard` Staff & locations matrix uses
   *  'all' (the editor that lets you assign anyone to any site). */
  scope?: 'current' | 'all';
}

/** List memberships for the current tenant — optionally scoped to the
 *  active location. Different from `useBookableMemberships()` which
 *  also filters by `bookable=true&active=true`. */
export function useAllMemberships(options: UseAllMembershipsOptions = {}) {
  const scope = options.scope ?? 'all';
  // Embed the active-location slug in the key so switching sites
  // flips the location-scoped cache cleanly. For scope='all' the
  // slug doesn't affect the data so it isn't part of the key.
  const slug = useActiveLocationSlug();
  const url =
    scope === 'current'
      ? '/api/memberships/?location=current'
      : '/api/memberships/';
  return useQuery<StaffMembership[]>({
    queryKey:
      scope === 'current'
        ? [...MEMBERSHIPS_KEY, { all: true, location: slug ?? 'default' }]
        : [...MEMBERSHIPS_KEY, { all: true }],
    queryFn: () => api.get<StaffMembership[]>(url),
    staleTime: 60 * 1000,
  });
}

export function useUpdateMembership(membershipId: number) {
  const qc = useQueryClient();
  return useMutation<StaffMembership, Error, UpdateMembershipInput>({
    mutationFn: (input) =>
      api.patch<StaffMembership>(`/api/memberships/${membershipId}/`, input),
    onSuccess: () => {
      // Both the staff list and the bookable-providers list (calendar)
      // can be affected by a single PATCH (changing is_bookable or
      // is_active flips both).
      qc.invalidateQueries({ queryKey: MEMBERSHIPS_KEY });
    },
  });
}

const employeeDetailKey = (id: number) => [...MEMBERSHIPS_KEY, 'detail', id] as const;

/** Fetch a single employee's full profile (personal contact + employment +
 *  payroll + multi-center summary). Backend returns this only to users
 *  with access to the membership's tenant; cross-tenant retrieves 404. */
export function useEmployee(id: number | undefined) {
  return useQuery<EmployeeDetail>({
    queryKey: employeeDetailKey(id ?? 0),
    queryFn: () => api.get<EmployeeDetail>(`/api/memberships/${id}/`),
    enabled: typeof id === 'number' && id > 0,
  });
}

/** PATCH the employee's profile. Single mutation handles both user-side
 *  fields (phone, address) and membership-side fields (role, payroll)
 *  in one transaction on the backend. Invalidates the detail cache +
 *  the roster list since either side might appear in the list. */
export function useUpdateEmployee(membershipId: number) {
  const qc = useQueryClient();
  return useMutation<EmployeeDetail, Error, UpdateEmployeeInput>({
    mutationFn: (input) =>
      api.patch<EmployeeDetail>(`/api/memberships/${membershipId}/`, input),
    onSuccess: (updated) => {
      qc.setQueryData(employeeDetailKey(membershipId), updated);
      qc.invalidateQueries({ queryKey: MEMBERSHIPS_KEY });
    },
  });
}

/** Create a new employee. Returns the detail PLUS a one-time
 *  `temp_password` if a brand-new user was created. Caller MUST surface
 *  the password to the operator immediately — it's not stored anywhere
 *  recoverable on the server. */
export function useCreateEmployee() {
  const qc = useQueryClient();
  return useMutation<CreateEmployeeResponse, Error, CreateEmployeeInput>({
    mutationFn: (input) =>
      api.post<CreateEmployeeResponse>('/api/memberships/', input),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: MEMBERSHIPS_KEY });
    },
  });
}

// ── Helpers ──────────────────────────────────────────────────────────

/** Display name from a staff membership — first + last, falling back to email. */
export function staffDisplayName(m: StaffMembership): string {
  const full = `${m.user_first_name} ${m.user_last_name}`.trim();
  return full || m.user_email;
}

/** Map an auth-context membership role to its display label. Used by
 *  the sidebar / settings sub-nav role gating. */
export function roleLabel(role: AuthMembership['role']): string {
  return ROLE_LABELS[role as StaffRole] ?? role;
}
