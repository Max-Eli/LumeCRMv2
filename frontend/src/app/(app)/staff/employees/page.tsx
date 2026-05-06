/**
 * `/staff/employees` — employee list with inline role / bookable /
 * active edits. The "Employees" tab of the Staff surface (siblings:
 * Schedule, Check-in, Payroll). Promoted out of `/settings` because
 * staff management is its own day-to-day workflow, not a
 * once-in-a-while settings tweak.
 *
 * Naming note: the underlying data model is `TenantMembership` (the
 * join table between User and Tenant). The user-facing label is
 * "Employees" because that matches the spa's mental model better than
 * the model name "Members".
 *
 * Layout:
 *
 *   - Page header with a "Show inactive" toggle in the actions slot.
 *     Inactive employees are filtered out of the default view; the
 *     toggle reveals them so an admin can re-activate (no destructive
 *     "delete" path — `is_active=false` preserves the audit trail).
 *   - Employee list as compact rows: avatar + name + email + role chip
 *     (clickable Select to change) + bookable badge + Active/Inactive
 *     state + actions (Deactivate / Reactivate, both with confirm).
 *
 * Role changes go through `useUpdateMembership()` (PATCH
 * /api/memberships/{id}/), gated by `MANAGE_STAFF` on the backend.
 * The last-active-owner guardrail is also enforced server-side; we
 * mirror it client-side as a disabled control + tooltip so the
 * destructive button never even tempts a click in that state.
 *
 * "Owner" is intentionally absent from the inline role-select choices
 * (`ASSIGNABLE_ROLES`); promoting to owner is sensitive enough that
 * it deserves its own confirmation flow (Phase 1H polish).
 */

'use client';

import { Ban, Check, ChevronRight, Clock, Search, Shield, UserPlus } from 'lucide-react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useMemo, useState } from 'react';
import { toast } from 'sonner';

import { InitialsAvatar } from '@/components/initials-avatar';
import { PageHeader } from '@/components/page-header';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { ApiError } from '@/lib/api';
import { useCurrentMembership } from '@/lib/auth';
import {
  hasMultipleLocations,
  locationDisplayName,
  useActiveLocation,
  useLocations,
} from '@/lib/locations';
import {
  ASSIGNABLE_ROLES,
  ROLE_LABELS,
  type StaffMembership,
  type StaffRole,
  staffDisplayName,
  useAllMemberships,
  useUpdateMembership,
} from '@/lib/tenant';
import { cn } from '@/lib/utils';

import { AddEmployeeSheet } from '../_components/add-employee-sheet';

export default function StaffSettingsPage() {
  const router = useRouter();
  // Roster scoped to the active location: this page lives under the
  // sidebar's "Location · {name}" group, so its content should match
  // the calendar / dashboard's scope. Cross-location management lives
  // at /org/dashboard's Staff & locations section.
  const { data: memberships, isLoading } = useAllMemberships({ scope: 'current' });
  const [showInactive, setShowInactive] = useState(false);
  const [search, setSearch] = useState('');
  const [addOpen, setAddOpen] = useState(false);

  // Active-location info for the page header copy + helper hint to
  // multi-location operators about where to manage cross-location
  // assignments. Single-location tenants don't see either.
  const { data: locations } = useLocations();
  const { location: activeLocation } = useActiveLocation();
  const isMultiLocation = hasMultipleLocations(locations);
  const activeLocationName = activeLocation
    ? locationDisplayName(activeLocation)
    : null;

  // Owner + manager can create employees. The backend re-validates
  // MANAGE_STAFF — this gate is just to avoid showing the affordance
  // to people who would only get a 403.
  const me = useCurrentMembership();
  const canManageStaff = me?.role === 'owner' || me?.role === 'manager';

  const filtered = useMemo(() => {
    const all = memberships ?? [];
    let list = showInactive ? all : all.filter((m) => m.is_active);
    if (search.trim()) {
      const q = search.trim().toLowerCase();
      list = list.filter(
        (m) =>
          staffDisplayName(m).toLowerCase().includes(q) ||
          m.user_email.toLowerCase().includes(q),
      );
    }
    return list;
  }, [memberships, showInactive, search]);

  const inactiveCount = useMemo(
    () => (memberships ?? []).filter((m) => !m.is_active).length,
    [memberships],
  );

  // Owner-count is the basis for the last-active-owner guardrail
  // — used to disable destructive controls on the only remaining owner.
  const activeOwnerCount = useMemo(
    () => (memberships ?? []).filter((m) => m.role === 'owner' && m.is_active).length,
    [memberships],
  );

  return (
    <div className="px-10 py-10 max-w-7xl space-y-6">
      <PageHeader
        title={
          isMultiLocation && activeLocationName
            ? `Employees · ${activeLocationName}`
            : 'Employees'
        }
        description={
          isMultiLocation
            ? `Staff assigned to this location. Adding an employee here also assigns them to ${activeLocationName ?? 'this site'}. To manage who works at multiple sites, use the Org dashboard.`
            : "Manage who works in this spa, what role they hold, and whether they're bookable as a provider."
        }
        actions={
          <>
            <ShowInactiveToggle
              value={showInactive}
              onChange={setShowInactive}
              inactiveCount={inactiveCount}
            />
            {canManageStaff ? (
              <Button type="button" size="sm" onClick={() => setAddOpen(true)}>
                <UserPlus className="size-4" />
                Add employee
              </Button>
            ) : null}
          </>
        }
      />

      <div className="relative max-w-sm">
        <Search className="absolute left-2 top-1/2 -translate-y-1/2 size-3.5 text-muted-foreground pointer-events-none" />
        <Input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search employees by name or email…"
          className="pl-7"
        />
      </div>

      {isLoading ? (
        <p className="text-sm text-muted-foreground">Loading employees…</p>
      ) : filtered.length === 0 ? (
        <EmptyState showInactive={showInactive} hasAny={(memberships ?? []).length > 0} />
      ) : (
        <ul className="border rounded-lg divide-y bg-card">
          {filtered.map((m) => (
            <StaffRow
              key={m.id}
              membership={m}
              activeOwnerCount={activeOwnerCount}
              canManageStaff={canManageStaff}
            />
          ))}
        </ul>
      )}

      <p className="text-[11px] text-muted-foreground/80 leading-relaxed">
        New employees get a one-time temporary password to share with them
        directly. Email-based invitations land with Phase 1F. Deactivation
        preserves the audit trail rather than destructively deleting.
      </p>

      {canManageStaff ? (
        <AddEmployeeSheet
          open={addOpen}
          onOpenChange={setAddOpen}
          onCreated={(emp) => {
            // Pre-warm the detail route so the click after closing the
            // share-credentials panel feels instant.
            router.prefetch(`/staff/employees/${emp.id}`);
          }}
        />
      ) : null}
    </div>
  );
}

// ── Sub-components ──────────────────────────────────────────────────

function ShowInactiveToggle({
  value,
  onChange,
  inactiveCount,
}: {
  value: boolean;
  onChange: (next: boolean) => void;
  inactiveCount: number;
}) {
  return (
    <button
      type="button"
      onClick={() => onChange(!value)}
      aria-pressed={value}
      className={cn(
        'inline-flex items-center gap-1.5 h-8 px-2.5 rounded-md text-xs uppercase tracking-wide transition-colors border',
        value
          ? 'border-foreground/30 bg-foreground text-background'
          : 'border-border bg-card text-muted-foreground hover:bg-muted hover:text-foreground',
      )}
    >
      <Clock className="size-3.5" />
      {value ? 'Hide inactive' : `Show inactive${inactiveCount ? ` (${inactiveCount})` : ''}`}
    </button>
  );
}

function StaffRow({
  membership,
  activeOwnerCount,
  canManageStaff,
}: {
  membership: StaffMembership;
  activeOwnerCount: number;
  canManageStaff: boolean;
}) {
  const update = useUpdateMembership(membership.id);
  const [confirmDeactivate, setConfirmDeactivate] = useState(false);

  const isOwner = membership.role === 'owner';
  // Last-active-owner guardrail — mirror the backend so destructive
  // controls on the only remaining owner are visibly disabled.
  const isOnlyActiveOwner = isOwner && membership.is_active && activeOwnerCount <= 1;

  const handleRoleChange = (next: StaffRole) => {
    update.mutate(
      { role: next },
      {
        onSuccess: () => toast.success('Role updated'),
        onError: (err) => toastErr(err, 'Could not update role.'),
      },
    );
  };

  const handleBookableToggle = () => {
    update.mutate(
      { is_bookable: !membership.is_bookable },
      {
        onSuccess: () => toast.success(membership.is_bookable ? 'Removed from booking' : 'Now bookable'),
        onError: (err) => toastErr(err, 'Could not update bookable.'),
      },
    );
  };

  const handleDeactivate = () => {
    update.mutate(
      { is_active: false },
      {
        onSuccess: () => {
          toast.success(`${staffDisplayName(membership)} deactivated`);
          setConfirmDeactivate(false);
        },
        onError: (err) => {
          setConfirmDeactivate(false);
          toastErr(err, 'Could not deactivate.');
        },
      },
    );
  };

  const handleReactivate = () => {
    update.mutate(
      { is_active: true },
      {
        onSuccess: () => toast.success(`${staffDisplayName(membership)} reactivated`),
        onError: (err) => toastErr(err, 'Could not reactivate.'),
      },
    );
  };

  const detailHref = `/staff/employees/${membership.id}`;

  return (
    <li
      className={cn(
        'group relative flex items-center gap-4 px-4 py-3 transition-colors',
        !membership.is_active && 'bg-muted/30',
        canManageStaff && 'hover:bg-muted/40',
      )}
    >
      {/* Stretched-link overlay — covers the row but sits beneath the
          inline interactive controls (which use `relative z-10`). Only
          rendered for users who can open the detail page. */}
      {canManageStaff ? (
        <Link
          href={detailHref}
          className="absolute inset-0 z-0 rounded-md focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring/40"
          aria-label={`Open ${staffDisplayName(membership)}'s profile`}
        >
          <span className="sr-only">Open profile</span>
        </Link>
      ) : null}

      <InitialsAvatar
        name={staffDisplayName(membership)}
        size="sm"
        className={cn(!membership.is_active && 'opacity-60')}
      />

      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <p
            className={cn(
              'text-sm font-medium truncate',
              !membership.is_active && 'text-muted-foreground line-through',
            )}
          >
            {staffDisplayName(membership)}
          </p>
          {!membership.is_active ? (
            <span className="text-[10px] uppercase tracking-wide px-1.5 py-px rounded bg-muted text-muted-foreground">
              Inactive
            </span>
          ) : null}
          {isOwner ? (
            <span
              title="Owners have full control over the tenant"
              className="inline-flex items-center gap-0.5 text-[10px] uppercase tracking-wide px-1.5 py-px rounded bg-accent/15 text-accent"
            >
              <Shield className="size-3" />
              Owner
            </span>
          ) : null}
        </div>
        <p className="text-xs text-muted-foreground truncate">
          {membership.user_email}
          {membership.job_title_name ? ` · ${membership.job_title_name}` : ''}
        </p>
      </div>

      {/* Right-side inline controls. Wrapped in a `relative z-10`
          container so the stretched-link overlay doesn't intercept
          clicks on the Select/toggle/button. */}
      <div className="relative z-10 flex items-center gap-3">
        {/* Role select. Owners can't be demoted from this dropdown
            (would need a deliberate "demote owner" flow); other roles
            can change to any non-owner assignable role. */}
        {isOwner ? (
          <span
            className="text-xs text-muted-foreground italic w-[140px] text-right"
            title="Promoting/demoting owners isn't supported from this dropdown."
          >
            Owner role
          </span>
        ) : (
          <Select
            value={membership.role}
            onValueChange={(v) => handleRoleChange(v as StaffRole)}
            disabled={update.isPending || !membership.is_active}
          >
            <SelectTrigger size="sm" className="w-[140px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {ASSIGNABLE_ROLES.map((r) => (
                <SelectItem key={r} value={r}>
                  {ROLE_LABELS[r]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}

        <BookableToggle
          bookable={membership.is_bookable}
          disabled={update.isPending || !membership.is_active}
          onToggle={handleBookableToggle}
        />

        {/* Action: Deactivate (active members) or Reactivate (inactive). */}
        {membership.is_active ? (
          confirmDeactivate ? (
            <div className="flex items-center gap-1.5">
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => setConfirmDeactivate(false)}
                disabled={update.isPending}
              >
                Cancel
              </Button>
              <Button
                type="button"
                variant="destructive"
                size="sm"
                onClick={handleDeactivate}
                disabled={update.isPending}
              >
                <Check className="size-3.5" />
                Confirm
              </Button>
            </div>
          ) : (
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={isOnlyActiveOwner || update.isPending}
              title={
                isOnlyActiveOwner
                  ? 'This is the only active owner. Promote another member to Owner first.'
                  : 'Deactivate this staff member'
              }
              onClick={() => setConfirmDeactivate(true)}
              className={cn(
                !isOnlyActiveOwner && 'text-destructive hover:text-destructive',
              )}
            >
              <Ban className="size-3.5" />
              Deactivate
            </Button>
          )
        ) : (
          <Button
            type="button"
            size="sm"
            disabled={update.isPending}
            onClick={handleReactivate}
          >
            <Check className="size-3.5" />
            Reactivate
          </Button>
        )}

        {canManageStaff ? (
          <ChevronRight className="size-4 text-muted-foreground/60 group-hover:text-muted-foreground transition-colors" />
        ) : null}
      </div>
    </li>
  );
}

function BookableToggle({
  bookable,
  disabled,
  onToggle,
}: {
  bookable: boolean;
  disabled: boolean;
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onToggle}
      disabled={disabled}
      aria-pressed={bookable}
      className={cn(
        'inline-flex items-center gap-1.5 h-7 px-2 rounded-md text-[11px] uppercase tracking-wide border transition-colors disabled:opacity-50',
        bookable
          ? 'border-accent/40 bg-accent/10 text-accent'
          : 'border-border bg-card text-muted-foreground hover:bg-muted',
      )}
      title={
        bookable
          ? 'Bookable — appears as a column on the calendar'
          : 'Not bookable — does not appear on the calendar'
      }
    >
      {bookable ? 'Bookable' : 'Not bookable'}
    </button>
  );
}

function EmptyState({
  showInactive,
  hasAny,
}: {
  showInactive: boolean;
  hasAny: boolean;
}) {
  return (
    <div className="border rounded-lg bg-card px-6 py-12 text-center">
      <p className="text-sm text-foreground font-medium">
        {!hasAny
          ? 'No employees yet'
          : showInactive
            ? 'No matching employees'
            : 'No active employees'}
      </p>
      <p className="text-xs text-muted-foreground mt-1">
        {!hasAny
          ? 'Onboarding adds your first employees; the invite flow lands with Phase 1F.'
          : 'Try adjusting the search or toggling Show inactive.'}
      </p>
    </div>
  );
}

function toastErr(err: unknown, fallback: string) {
  if (err instanceof ApiError && err.status === 403) {
    if (typeof err.body === 'object' && err.body) {
      const detail = (err.body as { detail?: string }).detail;
      if (detail) {
        toast.error(detail);
        return;
      }
    }
    toast.error("You don't have permission for this action.");
    return;
  }
  if (err instanceof ApiError && err.status === 400 && typeof err.body === 'object' && err.body) {
    const body = err.body as Record<string, string[] | string>;
    const firstField = Object.keys(body)[0];
    const detail = firstField
      ? Array.isArray(body[firstField])
        ? (body[firstField] as string[])[0]
        : String(body[firstField])
      : fallback;
    toast.error(detail);
    return;
  }
  toast.error(fallback);
}
