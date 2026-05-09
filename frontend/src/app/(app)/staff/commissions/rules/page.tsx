/**
 * `/staff/commissions/rules` — manager admin for commission rules.
 *
 * One row per staff member. Each row shows the base rate and any
 * per-category overrides. Inline edit lets the manager set/change
 * rates without navigating; saving fires the standard PATCH (or
 * POST when no rule exists yet).
 *
 * Mobile-OK but desktop-first: rate-table editing is a config flow
 * Owners do at a desk, not on a phone.
 */

'use client';

import { Loader2, Pencil, Plus, Trash2, X } from 'lucide-react';
import { useMemo, useState } from 'react';
import { toast } from 'sonner';

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
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { ApiError } from '@/lib/api';
import { useCurrentMembership } from '@/lib/auth';
import {
  type CommissionOverrideInput,
  type CommissionRule,
  useCommissionRules,
  useCreateCommissionRule,
  useDeleteCommissionRule,
  useUpdateCommissionRule,
} from '@/lib/commissions';
import { useServiceCategories } from '@/lib/services';
import { useAllMemberships } from '@/lib/tenant';
import { cn } from '@/lib/utils';

export default function CommissionRulesPage() {
  const me = useCurrentMembership();
  const isManager = me?.role === 'owner' || me?.role === 'manager';

  const rules = useCommissionRules();
  const memberships = useAllMemberships();
  const categories = useServiceCategories();

  const [editingMembershipId, setEditingMembershipId] = useState<number | null>(
    null,
  );

  // Map staff → rule (or null if no rule yet). Only show staff who
  // are eligible for commission (providers — bookable). Front-desk /
  // bookkeeper / marketing roles aren't on commission in v1.
  const rows = useMemo(() => {
    const ruleByMembership = new Map<number, CommissionRule>(
      (rules.data ?? []).map((r) => [r.membership, r]),
    );
    return (memberships.data ?? [])
      .filter((m) => m.role === 'provider' || m.role === 'manager')
      .map((m) => ({
        membership: m,
        rule: ruleByMembership.get(m.id) ?? null,
      }))
      .sort((a, b) => {
        const al = `${a.membership.user_last_name ?? ''} ${a.membership.user_first_name ?? ''}`;
        const bl = `${b.membership.user_last_name ?? ''} ${b.membership.user_first_name ?? ''}`;
        return al.localeCompare(bl);
      });
  }, [rules.data, memberships.data]);

  if (!isManager) {
    return (
      <div className="px-8 py-8">
        <PageHeader
          title="Commission rules"
          back={{ href: '/staff/commissions', label: 'Commissions' }}
        />
        <div className="rounded-lg border bg-muted/20 p-8 text-center text-sm text-muted-foreground">
          Owners and managers only.
        </div>
      </div>
    );
  }

  return (
    <div className="px-8 py-8 space-y-6">
      <PageHeader
        title="Commission rules"
        description="Per-staff base rate plus optional per-category overrides. Existing accruals are unaffected when rates change — the rate is snapshotted on each ledger entry."
        back={{ href: '/staff/commissions', label: 'Commissions' }}
      />

      {rules.isLoading || memberships.isLoading ? (
        <div className="rounded-lg border bg-card p-12 text-center text-sm text-muted-foreground">
          <Loader2 className="size-5 animate-spin mx-auto mb-2" />
          Loading…
        </div>
      ) : rows.length === 0 ? (
        <div className="rounded-lg border border-dashed bg-muted/20 p-10 text-center text-sm text-muted-foreground">
          No providers on staff. Add a provider in{' '}
          <a href="/staff/employees" className="text-foreground underline">
            Employees
          </a>{' '}
          first.
        </div>
      ) : (
        <div className="rounded-lg border bg-card overflow-hidden">
          <Table>
            <TableHeader>
              <TableRow className="bg-muted/30 hover:bg-muted/30">
                <TableHead className="w-[28%]">Staff</TableHead>
                <TableHead className="w-[140px] text-right">Base rate</TableHead>
                <TableHead>Per-category overrides</TableHead>
                <TableHead className="w-[120px]">Active</TableHead>
                <TableHead className="w-[110px]" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map(({ membership, rule }) =>
                editingMembershipId === membership.id ? (
                  <EditRow
                    key={membership.id}
                    membershipId={membership.id}
                    fullName={fullName(membership)}
                    role={membership.role}
                    existingRule={rule}
                    categories={categories.data ?? []}
                    onClose={() => setEditingMembershipId(null)}
                  />
                ) : (
                  <ViewRow
                    key={membership.id}
                    membershipId={membership.id}
                    fullName={fullName(membership)}
                    role={membership.role}
                    rule={rule}
                    onEdit={() => setEditingMembershipId(membership.id)}
                  />
                ),
              )}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}

function fullName(m: { user_first_name: string; user_last_name: string; user_email: string }): string {
  const full = `${m.user_first_name ?? ''} ${m.user_last_name ?? ''}`.trim();
  return full || m.user_email;
}

// ── Read-only row ───────────────────────────────────────────────────

function ViewRow({
  membershipId,
  fullName,
  role,
  rule,
  onEdit,
}: {
  membershipId: number;
  fullName: string;
  role: string;
  rule: CommissionRule | null;
  onEdit: () => void;
}) {
  return (
    <TableRow>
      <TableCell className="py-3.5">
        <p className="font-medium">{fullName}</p>
        <p className="text-xs text-muted-foreground capitalize">
          {role.replace('_', ' ')}
        </p>
      </TableCell>
      <TableCell className="text-right">
        {rule ? (
          <span className="font-mono text-base font-medium tabular-nums">
            {Number(rule.base_rate_percent).toFixed(2)}%
          </span>
        ) : (
          <span className="text-xs text-muted-foreground/70">No rule</span>
        )}
      </TableCell>
      <TableCell>
        {rule && rule.overrides.length > 0 ? (
          <div className="flex flex-wrap gap-1.5">
            {rule.overrides.map((o) => (
              <span
                key={o.id}
                className="inline-flex items-center gap-1.5 rounded-full bg-muted px-2 py-0.5 text-xs"
              >
                <span
                  className="size-2 rounded-full shrink-0"
                  style={{ background: o.category_color || '#999' }}
                />
                <span className="text-muted-foreground truncate max-w-[120px]">
                  {o.category_name}
                </span>
                <span className="font-mono font-medium">
                  {Number(o.rate_percent).toFixed(2)}%
                </span>
              </span>
            ))}
          </div>
        ) : (
          <span className="text-xs text-muted-foreground/70">—</span>
        )}
      </TableCell>
      <TableCell>
        {rule ? (
          rule.is_active ? (
            <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 text-emerald-700 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider">
              <span className="size-1.5 rounded-full bg-emerald-500" />
              Active
            </span>
          ) : (
            <span className="inline-flex items-center gap-1 rounded-full bg-stone-100 text-stone-600 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider">
              Paused
            </span>
          )
        ) : (
          <span className="text-xs text-muted-foreground/70">—</span>
        )}
      </TableCell>
      <TableCell>
        <button
          type="button"
          onClick={onEdit}
          className="inline-flex items-center gap-1 px-2.5 h-7 rounded-md text-xs font-medium border bg-card hover:bg-muted transition-colors"
        >
          {rule ? (
            <>
              <Pencil className="size-3" /> Edit
            </>
          ) : (
            <>
              <Plus className="size-3" /> Set rule
            </>
          )}
        </button>
      </TableCell>
    </TableRow>
  );
}

// ── Inline edit row ─────────────────────────────────────────────────

function EditRow({
  membershipId,
  fullName,
  role,
  existingRule,
  categories,
  onClose,
}: {
  membershipId: number;
  fullName: string;
  role: string;
  existingRule: CommissionRule | null;
  categories: { id: number; name: string; color: string }[];
  onClose: () => void;
}) {
  const create = useCreateCommissionRule();
  const update = useUpdateCommissionRule(existingRule?.id ?? 0);
  const remove = useDeleteCommissionRule();

  const [baseRate, setBaseRate] = useState(
    existingRule?.base_rate_percent ?? '0',
  );
  const [isActive, setIsActive] = useState(existingRule?.is_active ?? true);
  const [overrides, setOverrides] = useState<
    Array<{ category_id: string; rate_percent: string }>
  >(() =>
    (existingRule?.overrides ?? []).map((o) => ({
      category_id: String(o.category),
      rate_percent: o.rate_percent,
    })),
  );

  const isPending = create.isPending || update.isPending || remove.isPending;

  const onSave = () => {
    if (Number.isNaN(Number(baseRate)) || Number(baseRate) < 0 || Number(baseRate) > 100) {
      toast.error('Base rate must be 0–100.');
      return;
    }
    // Validate override rows.
    for (const o of overrides) {
      if (!o.category_id) {
        toast.error('Pick a category for every override row.');
        return;
      }
      const r = Number(o.rate_percent);
      if (Number.isNaN(r) || r < 0 || r > 100) {
        toast.error('Override rates must be 0–100.');
        return;
      }
    }
    const dupes = new Set<string>();
    for (const o of overrides) {
      if (dupes.has(o.category_id)) {
        toast.error('Each category may only appear once.');
        return;
      }
      dupes.add(o.category_id);
    }

    const overrides_input: CommissionOverrideInput[] = overrides.map((o) => ({
      category_id: Number(o.category_id),
      rate_percent: o.rate_percent,
    }));

    const onError = (err: Error) => {
      if (err instanceof ApiError && err.body && typeof err.body === 'object') {
        const body = err.body as Record<string, unknown>;
        const detail = Object.values(body).find(
          (v) => typeof v === 'string' || (Array.isArray(v) && typeof v[0] === 'string'),
        );
        const msg =
          typeof detail === 'string'
            ? detail
            : Array.isArray(detail)
              ? String(detail[0])
              : "Couldn't save.";
        toast.error(msg);
        return;
      }
      toast.error("Couldn't save.");
    };

    if (existingRule) {
      update.mutate(
        {
          base_rate_percent: baseRate,
          is_active: isActive,
          overrides_input,
        },
        {
          onSuccess: () => {
            toast.success('Rule saved');
            onClose();
          },
          onError,
        },
      );
    } else {
      create.mutate(
        {
          membership: membershipId,
          base_rate_percent: baseRate,
          is_active: isActive,
          overrides_input,
        },
        {
          onSuccess: () => {
            toast.success('Rule created');
            onClose();
          },
          onError,
        },
      );
    }
  };

  const onDelete = () => {
    if (!existingRule) return;
    if (
      !confirm(
        `Delete commission rule for ${fullName}? Existing accruals stay; future invoices won't accrue commission.`,
      )
    ) {
      return;
    }
    remove.mutate(existingRule.id, {
      onSuccess: () => {
        toast.success('Rule deleted');
        onClose();
      },
      onError: () => toast.error("Couldn't delete."),
    });
  };

  return (
    <TableRow className="bg-amber-50/40">
      <TableCell colSpan={5} className="py-4">
        <div className="space-y-4">
          <div className="flex items-baseline justify-between gap-3">
            <div>
              <p className="font-medium">{fullName}</p>
              <p className="text-xs text-muted-foreground capitalize">
                {role.replace('_', ' ')}
              </p>
            </div>
            <button
              type="button"
              onClick={onClose}
              className="inline-flex size-7 items-center justify-center rounded-md text-muted-foreground hover:bg-muted"
              aria-label="Cancel"
            >
              <X className="size-3.5" />
            </button>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            <div>
              <label className="text-[11px] uppercase tracking-wide text-muted-foreground font-medium">
                Base rate
              </label>
              <div className="relative mt-1">
                <Input
                  type="text"
                  inputMode="decimal"
                  value={baseRate}
                  onChange={(e) => setBaseRate(e.target.value)}
                  className="pr-7"
                />
                <span className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground text-sm">
                  %
                </span>
              </div>
              <p className="text-xs text-muted-foreground mt-1">
                Default percent on services with no per-category override.
              </p>
            </div>
            <div className="flex items-end gap-3">
              <label className="inline-flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={isActive}
                  onChange={(e) => setIsActive(e.target.checked)}
                  className="size-4 rounded border-input"
                />
                <span className="text-sm">Active</span>
              </label>
            </div>
          </div>

          <div className="space-y-2">
            <p className="text-[11px] uppercase tracking-wide text-muted-foreground font-medium">
              Per-category overrides
            </p>
            {overrides.length === 0 ? (
              <p className="text-sm text-muted-foreground italic">
                No overrides — every category uses the base rate.
              </p>
            ) : (
              overrides.map((row, index) => {
                const usedIds = new Set(
                  overrides
                    .filter((_, i) => i !== index)
                    .map((o) => o.category_id),
                );
                const availableCategories = categories.filter(
                  (c) =>
                    !usedIds.has(String(c.id))
                    || String(c.id) === row.category_id,
                );
                return (
                  <div key={index} className="grid grid-cols-12 gap-2 items-center">
                    <div className="col-span-7">
                      <Select
                        value={row.category_id}
                        onValueChange={(v) => {
                          const next = [...overrides];
                          next[index] = { ...row, category_id: v ?? '' };
                          setOverrides(next);
                        }}
                      >
                        <SelectTrigger>
                          <SelectValue placeholder="Pick a category…" />
                        </SelectTrigger>
                        <SelectContent>
                          {availableCategories.map((c) => (
                            <SelectItem key={c.id} value={String(c.id)}>
                              {c.name}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="col-span-4">
                      <div className="relative">
                        <Input
                          type="text"
                          inputMode="decimal"
                          placeholder="0"
                          value={row.rate_percent}
                          onChange={(e) => {
                            const next = [...overrides];
                            next[index] = {
                              ...row,
                              rate_percent: e.target.value,
                            };
                            setOverrides(next);
                          }}
                          className="pr-7"
                        />
                        <span className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground text-sm">
                          %
                        </span>
                      </div>
                    </div>
                    <div className="col-span-1 flex justify-end">
                      <button
                        type="button"
                        onClick={() =>
                          setOverrides(overrides.filter((_, i) => i !== index))
                        }
                        className="inline-flex size-9 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-destructive transition-colors"
                        aria-label="Remove this override"
                      >
                        <Trash2 className="size-3.5" />
                      </button>
                    </div>
                  </div>
                );
              })
            )}
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() =>
                setOverrides([
                  ...overrides,
                  { category_id: '', rate_percent: '' },
                ])
              }
            >
              <Plus className="size-3.5" />
              Add an override
            </Button>
          </div>

          <div className="flex items-center justify-between gap-2 pt-2 border-t border-amber-200/60">
            {existingRule ? (
              <Button
                variant="outline"
                onClick={onDelete}
                disabled={isPending}
                className="text-destructive hover:text-destructive"
              >
                <Trash2 className="size-4" />
                Delete rule
              </Button>
            ) : (
              <span />
            )}
            <div className="flex items-center gap-2">
              <Button variant="outline" onClick={onClose} disabled={isPending}>
                Cancel
              </Button>
              <Button onClick={onSave} disabled={isPending}>
                {isPending ? <Loader2 className="size-4 animate-spin" /> : null}
                Save
              </Button>
            </div>
          </div>
        </div>
      </TableCell>
    </TableRow>
  );
}
