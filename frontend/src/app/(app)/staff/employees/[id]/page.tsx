/**
 * `/staff/employees/[id]` — single-employee profile page.
 *
 * Shows + edits the full employee record:
 *
 *   - Identity (role, job title, bookable, active status)
 *   - Personal contact (phone + address; lives on User, shared
 *     across every tenant the same person belongs to)
 *   - Employment (full-time / part-time / contractor, hire date)
 *   - Payroll (pay type, pay rate; rate is entered in dollars and
 *     stored as cents on the wire)
 *   - Multi-center (read-only summary of every other tenant this
 *     person is a member of — flags when payroll terms must stay in
 *     sync across spas)
 *   - Notes (internal free-text employment notes)
 *
 * Edit gating: owner + manager only. Non-managing roles see a
 * read-only view (the backend re-validates `MANAGE_STAFF` on PATCH).
 *
 * Email is intentionally read-only: it's the User's identity. The
 * "change email" path would require a re-verification flow (Phase
 * 1F). For typo fixes during onboarding, do it through Django admin.
 *
 * The page reuses the same `Section` two-column layout pattern as
 * `/settings/business` so all admin/settings pages feel like one
 * surface.
 */

'use client';

import { zodResolver } from '@hookform/resolvers/zod';
import {
  Banknote,
  Briefcase,
  Building2,
  Check,
  Lock,
  Mail,
  MapPin,
  NotebookText,
  Phone,
  Shield,
  UserCircle,
} from 'lucide-react';
import Link from 'next/link';
import { use, useEffect } from 'react';
import { useForm } from 'react-hook-form';
import { toast } from 'sonner';
import { z } from 'zod';

import { InitialsAvatar } from '@/components/initials-avatar';
import { PageHeader } from '@/components/page-header';
import { Button } from '@/components/ui/button';
import { Field, FieldError, FieldLabel } from '@/components/ui/field';
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
import { locationDisplayName, useLocations } from '@/lib/locations';
import {
  ASSIGNABLE_ROLES,
  EMPLOYMENT_TYPE_LABELS,
  type EmployeeDetail,
  type EmploymentType,
  type OtherMembershipSummary,
  PAY_TYPE_LABELS,
  type PayType,
  ROLE_LABELS,
  type StaffRole,
  staffDisplayName,
  useEmployee,
  useUpdateEmployee,
} from '@/lib/tenant';
import { cn } from '@/lib/utils';

// ── Form schema ─────────────────────────────────────────────────────

const EMPTY_OR_NUMERIC = /^\d*\.?\d{0,2}$/;

const schema = z.object({
  // Identity (membership-side)
  role: z.enum([
    'owner',
    'manager',
    'front_desk',
    'provider',
    'bookkeeper',
    'marketing',
  ]),
  job_title_id: z.string(), // 'none' or numeric string — coerced on submit
  is_bookable: z.boolean(),
  is_active: z.boolean(),

  // Personal contact (user-side). Empty strings are allowed — the
  // backend accepts blank for optional fields. We avoid `.optional()`
  // here because that creates an input/output type mismatch the RHF
  // resolver typings can't reconcile.
  user_first_name: z.string().min(1, 'First name is required').max(150),
  user_last_name: z.string().min(1, 'Last name is required').max(150),
  user_phone: z.string().max(20),
  user_address_line1: z.string().max(200),
  user_address_line2: z.string().max(200),
  user_city: z.string().max(100),
  user_state: z.string().max(2),
  user_zip_code: z.string().max(10),

  // Employment + payroll
  employment_type: z.enum(['', 'full_time', 'part_time', 'contractor']),
  pay_type: z.enum(['', 'hourly', 'salary', 'commission_only']),
  pay_rate_dollars: z
    .string()
    .regex(EMPTY_OR_NUMERIC, 'Use a number like 25 or 25.50'),
  hire_date: z.string(), // YYYY-MM-DD or '' (input type=date)
  employment_notes: z.string().max(5000),

  // Per-location assignments — toggling a location off removes the
  // employee from that site's calendar / staff page (soft-delete on
  // the backend; audit trail preserved).
  location_ids: z.array(z.number().int().positive()),
});

type FormValues = z.infer<typeof schema>;

// ── Page ────────────────────────────────────────────────────────────

export default function EmployeeDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const employeeId = Number(id);
  const { data: employee, isLoading, error } = useEmployee(employeeId);

  const me = useCurrentMembership();
  const canEdit = me?.role === 'owner' || me?.role === 'manager';

  if (isLoading) {
    return (
      <div className="px-10 py-10 text-sm text-muted-foreground">
        Loading employee…
      </div>
    );
  }
  if (error || !employee) {
    return (
      <div className="px-10 py-10">
        <PageHeader
          title="Employee not found"
          back={{ href: '/staff/employees', label: 'Back to employees' }}
        />
        <p className="text-sm text-destructive">Failed to load this employee.</p>
      </div>
    );
  }

  return <EmployeeDetailForm employee={employee} canEdit={canEdit} />;
}

// ── Form ────────────────────────────────────────────────────────────

function EmployeeDetailForm({
  employee,
  canEdit,
}: {
  employee: EmployeeDetail;
  canEdit: boolean;
}) {
  const update = useUpdateEmployee(employee.id);

  const defaultValues = toFormValues(employee);
  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues,
  });

  // Re-seed when the underlying record refetches (e.g. mutation onSuccess
  // replaces the cached record with the server's canonical version).
  useEffect(() => {
    form.reset(toFormValues(employee));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [employee.updated_at, employee.id]);

  const onSubmit = form.handleSubmit((values) => {
    if (!canEdit) return;
    update.mutate(toApiInput(values, employee), {
      onSuccess: () => toast.success('Profile saved'),
      onError: (err) => {
        if (err instanceof ApiError && err.status === 403) {
          toast.error("You don't have permission to edit this employee.");
        } else if (
          err instanceof ApiError &&
          err.status === 400 &&
          typeof err.body === 'object' &&
          err.body
        ) {
          const body = err.body as Record<string, string[] | string>;
          const firstField = Object.keys(body)[0];
          const detail = firstField
            ? Array.isArray(body[firstField])
              ? (body[firstField] as string[])[0]
              : String(body[firstField])
            : 'Could not save.';
          toast.error(detail);
        } else {
          toast.error('Could not save. Please try again.');
        }
      },
    });
  });

  // For the role Select, owners can be promoted *to* assignable roles
  // (demoted) but a non-owner can't become "owner" through this dropdown
  // — that's a deliberate sensitive flow. So the choice list depends on
  // the employee's current role.
  const roleChoices: StaffRole[] =
    employee.role === 'owner' ? ['owner', ...ASSIGNABLE_ROLES] : ASSIGNABLE_ROLES;

  return (
    <div className="max-w-6xl px-10 py-10 space-y-6">
      <PageHeader
        title=""
        back={{ href: '/staff/employees', label: 'Back to employees' }}
        className="mb-0"
      />

      <Hero employee={employee} />

      <form onSubmit={onSubmit}>
        <fieldset disabled={!canEdit} className="contents">
          <div className="divide-y border-t border-b">
            <Section
              title="Role & access"
              description="What this person does at this spa, and whether they appear on the booking calendar."
              icon={<Shield className="size-4 text-muted-foreground" />}
            >
              <div className="grid grid-cols-2 gap-3">
                <Field>
                  <FieldLabel htmlFor="role">Role</FieldLabel>
                  <Select
                    value={form.watch('role')}
                    onValueChange={(v) =>
                      form.setValue('role', v as StaffRole, { shouldDirty: true })
                    }
                    disabled={!canEdit}
                  >
                    <SelectTrigger id="role">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {roleChoices.map((r) => (
                        <SelectItem key={r} value={r}>
                          {ROLE_LABELS[r]}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  {employee.role === 'owner' ? (
                    <p className="text-[11px] text-muted-foreground mt-1">
                      Owners have full control of the tenant. Demoting an owner
                      requires another active owner to remain.
                    </p>
                  ) : null}
                </Field>

                <Field>
                  <FieldLabel htmlFor="job_title">Job title</FieldLabel>
                  <Input
                    id="job_title"
                    value={employee.job_title_name ?? '—'}
                    readOnly
                    disabled
                    title="Job title is managed in the legacy staff list (will be inline-editable in a follow-up)."
                  />
                  <p className="text-[11px] text-muted-foreground mt-1">
                    Set during onboarding. Editing inline lands with the next
                    job-titles polish pass.
                  </p>
                </Field>
              </div>

              <ToggleRow
                label="Bookable on the calendar"
                description="Appears as a column on the booking calendar so customers can book appointments with this person."
                value={form.watch('is_bookable')}
                onChange={(next) =>
                  form.setValue('is_bookable', next, { shouldDirty: true })
                }
                disabled={!canEdit}
              />

              <ToggleRow
                label="Active"
                description="Inactive employees can't sign in and don't appear in default lists. Their history is preserved for the audit trail."
                value={form.watch('is_active')}
                onChange={(next) =>
                  form.setValue('is_active', next, { shouldDirty: true })
                }
                disabled={!canEdit}
              />
            </Section>

            <Section
              title="Personal contact"
              description="The employee's personal details. Shared across every spa they belong to on Lumè — changes here update their record at every center."
              icon={<UserCircle className="size-4 text-muted-foreground" />}
            >
              <div className="grid grid-cols-2 gap-3">
                <Field>
                  <FieldLabel htmlFor="user_first_name">First name</FieldLabel>
                  <Input id="user_first_name" {...form.register('user_first_name')} />
                  <FieldError>
                    {form.formState.errors.user_first_name?.message}
                  </FieldError>
                </Field>
                <Field>
                  <FieldLabel htmlFor="user_last_name">Last name</FieldLabel>
                  <Input id="user_last_name" {...form.register('user_last_name')} />
                  <FieldError>
                    {form.formState.errors.user_last_name?.message}
                  </FieldError>
                </Field>
              </div>

              <ReadOnlyField icon={<Lock className="size-3.5" />} label="Email">
                <span className="font-mono text-sm">{employee.user_email}</span>
              </ReadOnlyField>

              <Field>
                <FieldLabel htmlFor="user_phone">Phone</FieldLabel>
                <div className="relative">
                  <Phone className="absolute left-2.5 top-1/2 -translate-y-1/2 size-3.5 text-muted-foreground pointer-events-none" />
                  <Input
                    id="user_phone"
                    type="tel"
                    {...form.register('user_phone')}
                    className="pl-8"
                    placeholder="(555) 123-4567"
                  />
                </div>
              </Field>

              <div className="space-y-3 pt-1">
                <p className="text-[11px] uppercase tracking-wide text-muted-foreground font-medium flex items-center gap-1">
                  <MapPin className="size-3.5" />
                  Address
                </p>
                <Field>
                  <FieldLabel htmlFor="user_address_line1">Street address</FieldLabel>
                  <Input
                    id="user_address_line1"
                    {...form.register('user_address_line1')}
                  />
                </Field>
                <Field>
                  <FieldLabel htmlFor="user_address_line2">
                    Suite / unit (optional)
                  </FieldLabel>
                  <Input
                    id="user_address_line2"
                    {...form.register('user_address_line2')}
                  />
                </Field>
                <div className="grid grid-cols-[1fr_80px_120px] gap-3">
                  <Field>
                    <FieldLabel htmlFor="user_city">City</FieldLabel>
                    <Input id="user_city" {...form.register('user_city')} />
                  </Field>
                  <Field>
                    <FieldLabel htmlFor="user_state">State</FieldLabel>
                    <Input
                      id="user_state"
                      {...form.register('user_state')}
                      maxLength={2}
                      placeholder="NY"
                      className="uppercase"
                    />
                  </Field>
                  <Field>
                    <FieldLabel htmlFor="user_zip_code">ZIP</FieldLabel>
                    <Input id="user_zip_code" {...form.register('user_zip_code')} />
                  </Field>
                </div>
              </div>
            </Section>

            <Section
              title="Employment"
              description="Their employment classification at this spa. Per-center because the same person can be full-time at one location and a contractor at another."
              icon={<Briefcase className="size-4 text-muted-foreground" />}
            >
              <div className="grid grid-cols-2 gap-3">
                <Field>
                  <FieldLabel htmlFor="employment_type">Employment type</FieldLabel>
                  <Select
                    value={form.watch('employment_type') || '__unset__'}
                    onValueChange={(v) =>
                      form.setValue(
                        'employment_type',
                        v === '__unset__' ? '' : (v as EmploymentType),
                        { shouldDirty: true },
                      )
                    }
                    disabled={!canEdit}
                  >
                    <SelectTrigger id="employment_type">
                      <SelectValue placeholder="Not set" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="__unset__">Not set</SelectItem>
                      {(Object.keys(EMPLOYMENT_TYPE_LABELS) as EmploymentType[]).map(
                        (et) => (
                          <SelectItem key={et} value={et}>
                            {EMPLOYMENT_TYPE_LABELS[et]}
                          </SelectItem>
                        ),
                      )}
                    </SelectContent>
                  </Select>
                </Field>

                <Field>
                  <FieldLabel htmlFor="hire_date">Hire date</FieldLabel>
                  <Input
                    id="hire_date"
                    type="date"
                    {...form.register('hire_date')}
                  />
                </Field>
              </div>
            </Section>

            <Section
              title="Payroll"
              description="How this person is paid at this spa. Visible to owners and managers only."
              icon={<Banknote className="size-4 text-muted-foreground" />}
            >
              <div className="grid grid-cols-2 gap-3">
                <Field>
                  <FieldLabel htmlFor="pay_type">Pay type</FieldLabel>
                  <Select
                    value={form.watch('pay_type') || '__unset__'}
                    onValueChange={(v) =>
                      form.setValue(
                        'pay_type',
                        v === '__unset__' ? '' : (v as PayType),
                        { shouldDirty: true },
                      )
                    }
                    disabled={!canEdit}
                  >
                    <SelectTrigger id="pay_type">
                      <SelectValue placeholder="Not set" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="__unset__">Not set</SelectItem>
                      {(Object.keys(PAY_TYPE_LABELS) as PayType[]).map((pt) => (
                        <SelectItem key={pt} value={pt}>
                          {PAY_TYPE_LABELS[pt]}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </Field>

                <Field>
                  <FieldLabel htmlFor="pay_rate_dollars">
                    {payRateLabel(form.watch('pay_type') as PayType | '')}
                  </FieldLabel>
                  <div className="relative">
                    <span className="absolute left-2.5 top-1/2 -translate-y-1/2 text-sm text-muted-foreground pointer-events-none">
                      $
                    </span>
                    <Input
                      id="pay_rate_dollars"
                      inputMode="decimal"
                      {...form.register('pay_rate_dollars')}
                      className="pl-6"
                      placeholder="0.00"
                      disabled={
                        !canEdit ||
                        form.watch('pay_type') === '' ||
                        form.watch('pay_type') === 'commission_only'
                      }
                    />
                  </div>
                  <FieldError>
                    {form.formState.errors.pay_rate_dollars?.message}
                  </FieldError>
                  {form.watch('pay_type') === 'commission_only' ? (
                    <p className="text-[11px] text-muted-foreground mt-1">
                      Commission-only — no base pay rate. Commission rates live
                      with the services + payroll module (Phase 1G).
                    </p>
                  ) : null}
                </Field>
              </div>
            </Section>

            <Section
              title="Locations"
              description="Which sites this person works at. The calendar at each site only shows providers assigned here. Toggling a location off soft-deactivates the assignment (audit trail preserved); toggling back on reactivates it."
              icon={<Building2 className="size-4 text-muted-foreground" />}
            >
              <LocationAssignmentEditor
                assignedLocationIds={form.watch('location_ids')}
                onChange={(next) =>
                  form.setValue('location_ids', next, { shouldDirty: true })
                }
                disabled={!canEdit}
              />
              {employee.other_memberships.length > 0 ? (
                <details className="mt-4 text-xs text-muted-foreground">
                  <summary className="cursor-pointer hover:text-foreground transition-colors">
                    Also works at other businesses on Lumè ({employee.other_memberships.length})
                  </summary>
                  <div className="mt-2">
                    <OtherMembershipsList memberships={employee.other_memberships} />
                  </div>
                </details>
              ) : null}
            </Section>

            <Section
              title="Notes"
              description="Internal notes about this employment relationship — visible to owners and managers only. Not surfaced to the employee."
              icon={<NotebookText className="size-4 text-muted-foreground" />}
            >
              <Field>
                <FieldLabel htmlFor="employment_notes" className="sr-only">
                  Employment notes
                </FieldLabel>
                <textarea
                  id="employment_notes"
                  {...form.register('employment_notes')}
                  rows={5}
                  placeholder="e.g. 90-day commission ramp, conference attendance approved through Q2…"
                  className="w-full rounded-md border bg-background px-3 py-2 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 resize-y"
                />
              </Field>
            </Section>
          </div>

          {canEdit ? (
            <div className="flex items-center justify-end gap-2 pt-4">
              <Button
                type="button"
                variant="outline"
                disabled={!form.formState.isDirty || update.isPending}
                onClick={() => form.reset(defaultValues)}
              >
                Reset
              </Button>
              <Button
                type="submit"
                disabled={!form.formState.isDirty || update.isPending}
              >
                {update.isPending ? (
                  'Saving…'
                ) : (
                  <>
                    <Check className="size-4" />
                    Save changes
                  </>
                )}
              </Button>
            </div>
          ) : (
            <p className="text-xs text-muted-foreground pt-4 text-right">
              You can view this profile but only owners and managers can edit it.
            </p>
          )}
        </fieldset>
      </form>
    </div>
  );
}

// ── Sub-components ──────────────────────────────────────────────────

function Hero({ employee }: { employee: EmployeeDetail }) {
  const name = staffDisplayName(employee);
  return (
    <div className="flex items-center gap-4 pb-2">
      <InitialsAvatar name={name} size="lg" />
      <div className="min-w-0 flex-1">
        <h1 className="font-serif text-2xl font-semibold tracking-tight truncate">
          {name}
        </h1>
        <p className="text-sm text-muted-foreground flex items-center gap-1.5 mt-0.5">
          <Mail className="size-3.5" />
          {employee.user_email}
          {employee.job_title_name ? (
            <span className="text-muted-foreground/60"> · {employee.job_title_name}</span>
          ) : null}
        </p>
      </div>
      <div className="flex items-center gap-2">
        <span
          className={cn(
            'text-[11px] uppercase tracking-wide px-2 py-0.5 rounded',
            employee.role === 'owner'
              ? 'bg-accent/15 text-accent'
              : 'bg-muted text-muted-foreground',
          )}
        >
          {ROLE_LABELS[employee.role]}
        </span>
        {!employee.is_active ? (
          <span className="text-[11px] uppercase tracking-wide px-2 py-0.5 rounded bg-muted text-muted-foreground">
            Inactive
          </span>
        ) : null}
        {employee.is_bookable ? (
          <span className="text-[11px] uppercase tracking-wide px-2 py-0.5 rounded bg-accent/10 text-accent border border-accent/30">
            Bookable
          </span>
        ) : null}
      </div>
    </div>
  );
}

/** Per-employee location assignment editor.
 *
 *  Shows every active location in the tenant as a checkbox row;
 *  toggling a row mutates the form's `location_ids` array. The PATCH
 *  call (in the page's `onSubmit`) sends `set_location_ids` with the
 *  full new set — backend reconciles via soft-delete (deactivates
 *  removed assignments, reactivates re-added ones) so the audit log
 *  captures every change.
 *
 *  Guards: prevents the operator from saving zero locations (employee
 *  would disappear from every site's calendar / staff page), with an
 *  inline warning. Default location chips have a star indicator —
 *  not because they're special to assign, but to give context for
 *  multi-location operators about which site is the fallback.
 */
function LocationAssignmentEditor({
  assignedLocationIds,
  onChange,
  disabled,
}: {
  assignedLocationIds: number[];
  onChange: (next: number[]) => void;
  disabled?: boolean;
}) {
  const { data: locations, isLoading } = useLocations();

  if (isLoading) {
    return (
      <p className="text-sm text-muted-foreground">Loading locations…</p>
    );
  }
  const activeLocations = (locations ?? []).filter((l) => l.is_active);
  if (activeLocations.length === 0) {
    return (
      <p className="text-sm text-muted-foreground italic">
        No active locations configured.
      </p>
    );
  }

  const assigned = new Set(assignedLocationIds);

  const toggle = (locationId: number) => {
    if (disabled) return;
    const next = new Set(assigned);
    if (next.has(locationId)) {
      next.delete(locationId);
    } else {
      next.add(locationId);
    }
    onChange([...next]);
  };

  return (
    <div className="space-y-2">
      <ul className="space-y-1.5">
        {activeLocations.map((loc) => {
          const isAssigned = assigned.has(loc.id);
          return (
            <li key={loc.id}>
              <label
                className={cn(
                  'flex items-start gap-3 rounded-md border bg-card px-3 py-2 transition-colors',
                  disabled
                    ? 'cursor-not-allowed opacity-70'
                    : 'cursor-pointer hover:bg-muted/40',
                  isAssigned && 'border-accent/40 bg-accent/[0.04]',
                )}
              >
                <input
                  type="checkbox"
                  checked={isAssigned}
                  disabled={disabled}
                  onChange={() => toggle(loc.id)}
                  className="mt-0.5 size-4 rounded border-border text-foreground focus-visible:ring-2 focus-visible:ring-ring/50"
                />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-1.5">
                    <span className="text-sm font-medium">
                      {locationDisplayName(loc)}
                    </span>
                    {loc.is_default ? (
                      <span
                        title="Default location — fallback when no specific site is selected"
                        className="inline-flex items-center gap-0.5 text-[10px] uppercase tracking-wide px-1.5 py-px rounded bg-accent/15 text-accent"
                      >
                        Default
                      </span>
                    ) : null}
                  </div>
                  <p className="text-[11px] text-muted-foreground truncate">
                    {[loc.city, loc.state].filter(Boolean).join(', ') ||
                      'No address set'}
                  </p>
                </div>
              </label>
            </li>
          );
        })}
      </ul>
      {assignedLocationIds.length === 0 ? (
        <p className="text-[11px] text-destructive leading-relaxed">
          This employee won&apos;t appear on any calendar or staff list
          until you assign them to at least one location.
        </p>
      ) : null}
    </div>
  );
}

function OtherMembershipsList({
  memberships,
}: {
  memberships: OtherMembershipSummary[];
}) {
  if (memberships.length === 0) {
    return (
      <p className="text-sm text-muted-foreground italic">
        Not a member of any other spas on Lumè.
      </p>
    );
  }
  return (
    <ul className="space-y-2">
      {memberships.map((m) => (
        <li
          key={m.id}
          className="flex items-center justify-between gap-3 rounded-md border bg-card px-3 py-2"
        >
          <div className="min-w-0">
            <p className="text-sm font-medium truncate">{m.tenant_name}</p>
            <p className="text-xs text-muted-foreground truncate">
              {ROLE_LABELS[m.role]}
              {m.job_title_name ? ` · ${m.job_title_name}` : ''}
            </p>
          </div>
          {!m.is_active ? (
            <span className="text-[10px] uppercase tracking-wide px-1.5 py-px rounded bg-muted text-muted-foreground shrink-0">
              Inactive
            </span>
          ) : null}
        </li>
      ))}
    </ul>
  );
}

function ToggleRow({
  label,
  description,
  value,
  onChange,
  disabled,
}: {
  label: string;
  description: string;
  value: boolean;
  onChange: (next: boolean) => void;
  disabled?: boolean;
}) {
  return (
    <label className="flex items-start gap-3 py-2 cursor-pointer">
      <input
        type="checkbox"
        checked={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
        className="mt-0.5 size-4 rounded border-border text-foreground focus-visible:ring-2 focus-visible:ring-ring/50 disabled:opacity-50"
      />
      <div className="min-w-0 flex-1">
        <span className="text-sm font-medium">{label}</span>
        <p className="text-[11px] text-muted-foreground leading-relaxed">
          {description}
        </p>
      </div>
    </label>
  );
}

// ── Layout primitives (mirror /settings/business) ───────────────────

function Section({
  title,
  description,
  icon,
  children,
}: {
  title: string;
  description?: string;
  icon?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className="grid grid-cols-1 lg:grid-cols-[300px_1fr] gap-6 lg:gap-12 py-6 first:pt-8 last:pb-8">
      <header>
        <div className="flex items-center gap-2">
          {icon}
          <h2 className="font-serif text-base font-semibold tracking-tight">
            {title}
          </h2>
        </div>
        {description ? (
          <p className="text-xs text-muted-foreground mt-1.5 leading-relaxed">
            {description}
          </p>
        ) : null}
      </header>
      <div className="space-y-3 max-w-2xl">{children}</div>
    </section>
  );
}

function ReadOnlyField({
  icon,
  label,
  children,
}: {
  icon?: React.ReactNode;
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <p className="text-[11px] uppercase tracking-wide text-muted-foreground font-medium flex items-center gap-1">
        {icon}
        {label}
      </p>
      <p className="text-sm mt-1">{children}</p>
    </div>
  );
}

// ── Helpers ─────────────────────────────────────────────────────────

function payRateLabel(payType: PayType | ''): string {
  switch (payType) {
    case 'hourly':
      return 'Hourly rate';
    case 'salary':
      return 'Annual salary';
    case 'commission_only':
      return 'Pay rate';
    default:
      return 'Pay rate';
  }
}

function centsToDollars(cents: number): string {
  if (!cents) return '';
  // Whole dollars stay as integers; cents preserved with 2 decimals.
  return cents % 100 === 0 ? String(cents / 100) : (cents / 100).toFixed(2);
}

function dollarsToCents(dollars: string): number {
  const n = Number(dollars);
  if (!Number.isFinite(n) || n < 0) return 0;
  return Math.round(n * 100);
}

function toFormValues(employee: EmployeeDetail): FormValues {
  return {
    role: employee.role,
    job_title_id:
      employee.job_title_id == null ? 'none' : String(employee.job_title_id),
    is_bookable: employee.is_bookable,
    is_active: employee.is_active,

    user_first_name: employee.user_first_name,
    user_last_name: employee.user_last_name,
    user_phone: employee.user_phone,
    user_address_line1: employee.user_address_line1,
    user_address_line2: employee.user_address_line2,
    user_city: employee.user_city,
    user_state: employee.user_state,
    user_zip_code: employee.user_zip_code,

    employment_type: employee.employment_type,
    pay_type: employee.pay_type,
    pay_rate_dollars: centsToDollars(employee.pay_rate_cents),
    hire_date: employee.hire_date ?? '',
    employment_notes: employee.employment_notes,

    location_ids: [...employee.location_ids],
  };
}

function toApiInput(values: FormValues, original: EmployeeDetail) {
  // Commission-only zeros out the rate — no base pay applies.
  const payRateCents =
    values.pay_type === 'commission_only' || values.pay_type === ''
      ? 0
      : dollarsToCents(values.pay_rate_dollars);

  // Only send `set_location_ids` when assignments actually changed.
  // Sending it always would overwrite to the same set on every PATCH,
  // adding noise to the audit log even when nothing about locations
  // changed.
  const originalLocationIds = [...original.location_ids].sort((a, b) => a - b);
  const nextLocationIds = [...values.location_ids].sort((a, b) => a - b);
  const locationIdsChanged =
    originalLocationIds.length !== nextLocationIds.length ||
    originalLocationIds.some((id, i) => id !== nextLocationIds[i]);

  return {
    role: values.role,
    is_bookable: values.is_bookable,
    is_active: values.is_active,
    user_first_name: values.user_first_name,
    user_last_name: values.user_last_name,
    user_phone: values.user_phone,
    user_address_line1: values.user_address_line1,
    user_address_line2: values.user_address_line2,
    user_city: values.user_city,
    user_state: values.user_state.toUpperCase(),
    user_zip_code: values.user_zip_code,
    employment_type: values.employment_type,
    pay_type: values.pay_type,
    pay_rate_cents: payRateCents,
    hire_date: values.hire_date || null,
    employment_notes: values.employment_notes,
    // Job title isn't editable from this page yet; preserve current value.
    job_title_id: original.job_title_id,
    ...(locationIdsChanged ? { set_location_ids: values.location_ids } : {}),
  };
}
