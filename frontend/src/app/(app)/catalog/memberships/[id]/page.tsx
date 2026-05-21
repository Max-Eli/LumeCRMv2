/**
 * `/catalog/memberships/[id]` — edit a membership plan.
 *
 * Reuses the shared `<MembershipPlanForm>`. Items list replaces
 * wholesale on save (matches backend semantics). Delete option
 * available on plans with no Subscription references; backend
 * returns 400 with a clear message otherwise.
 */

'use client';

import { Trash2 } from 'lucide-react';
import { useRouter } from 'next/navigation';
import { use, useState } from 'react';
import { toast } from 'sonner';

import { PageHeader } from '@/components/page-header';
import { Button } from '@/components/ui/button';
import { ApiError } from '@/lib/api';
import { useCurrentMembership } from '@/lib/auth';
import {
  type MembershipPlan,
  dollarsFromCents,
  useDeleteMembershipPlan,
  useMembershipPlan,
  useUpdateMembershipPlan,
} from '@/lib/subscriptions';

import {
  type PlanFormErrors,
  type PlanFormValues,
  MembershipPlanForm,
  emptyPlanItemRow,
  planFormToPayload,
  validatePlanForm,
} from '../_components/plan-form';

function planToFormValues(p: MembershipPlan): PlanFormValues {
  return {
    name: p.name,
    sku: p.sku,
    description: p.description,
    price_dollars: dollarsFromCents(p.price_cents),
    tax_rate_percent: p.tax_rate_percent || '0',
    billing_interval: p.billing_interval,
    member_discount_percent: p.member_discount_percent || '0',
    is_active: p.is_active,
    items: p.items.length
      ? p.items.map((it) => ({
          item_type: it.item_type,
          service_id: it.service_id != null ? String(it.service_id) : '',
          category_id: it.category_id != null ? String(it.category_id) : '',
          quantity_per_cycle: String(it.quantity_per_cycle),
        }))
      : [emptyPlanItemRow()],
  };
}

export default function MembershipPlanDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const planId = Number(id);
  const me = useCurrentMembership();
  const canEdit = me?.role === 'owner' || me?.role === 'manager';
  const router = useRouter();

  const { data: plan, isLoading, error } = useMembershipPlan(planId);
  const update = useUpdateMembershipPlan(planId);
  const remove = useDeleteMembershipPlan();

  const [seededFor, setSeededFor] = useState<number | null>(null);
  const [values, setValues] = useState<PlanFormValues | null>(null);
  const [errors, setErrors] = useState<PlanFormErrors>({});

  if (plan && seededFor !== plan.id) {
    setSeededFor(plan.id);
    setValues(planToFormValues(plan));
  }

  if (isLoading) {
    return (
      <div className="px-8 py-8">
        <PageHeader
          title=""
          back={{ href: '/catalog/memberships', label: 'All plans' }}
        />
        <div className="rounded-lg border bg-card p-12 text-center text-sm text-muted-foreground">
          Loading plan…
        </div>
      </div>
    );
  }
  if (error || !plan || !values) {
    return (
      <div className="px-8 py-8">
        <PageHeader
          title="Plan not found"
          back={{ href: '/catalog/memberships', label: 'All plans' }}
        />
        <p className="text-sm text-destructive">Failed to load this plan.</p>
      </div>
    );
  }

  const onSubmit = () => {
    if (!values) return;
    const next = validatePlanForm(values);
    setErrors(next);
    if (Object.keys(next).length > 0) {
      toast.error('Please fix the highlighted fields.');
      return;
    }
    update.mutate(planFormToPayload(values), {
      onSuccess: (saved) => {
        toast.success('Plan saved');
        setValues(planToFormValues(saved));
      },
      onError: (err) => {
        if (
          err instanceof ApiError
          && err.status === 400
          && err.body
          && typeof err.body === 'object'
        ) {
          const body = err.body as Record<string, unknown>;
          const merged: PlanFormErrors = {};
          for (const [k, v] of Object.entries(body)) {
            const msg = Array.isArray(v) ? String(v[0]) : String(v);
            if (k === 'items_input' || k === 'items') {
              merged.items = msg;
            } else {
              (merged as Record<string, string>)[k] = msg;
            }
          }
          setErrors(merged);
          toast.error('Please fix the highlighted fields.');
        } else {
          toast.error('Save failed. Please try again.');
        }
      },
    });
  };

  const onDelete = () => {
    if (
      !confirm(
        `Delete "${plan.name}"? Existing subscribers keep their current cycle.`,
      )
    )
      return;
    remove.mutate(planId, {
      onSuccess: () => {
        toast.success('Plan deleted');
        router.push('/catalog/memberships');
      },
      onError: (err) => {
        if (err instanceof ApiError && err.body && typeof err.body === 'object') {
          const body = err.body as { detail?: string };
          if (body.detail) {
            toast.error(body.detail);
            return;
          }
        }
        toast.error('Could not delete this plan.');
      },
    });
  };

  return (
    <div className="px-8 py-8">
      <PageHeader
        title={plan.name}
        description={`SKU ${plan.sku || '—'}`}
        back={{ href: '/catalog/memberships', label: 'All plans' }}
        actions={
          canEdit ? (
            <Button
              type="button"
              variant="outline"
              onClick={onDelete}
              disabled={remove.isPending}
            >
              <Trash2 className="size-4" />
              Delete
            </Button>
          ) : null
        }
      />
      <div className="mt-2">
        <MembershipPlanForm
          values={values}
          setValues={setValues}
          errors={errors}
          onSubmit={onSubmit}
          isPending={update.isPending}
          submitLabel="Save changes"
          cancelHref="/catalog/memberships"
        />
      </div>
    </div>
  );
}
