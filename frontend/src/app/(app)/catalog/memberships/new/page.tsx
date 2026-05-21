/**
 * `/catalog/memberships/new` — create a new membership plan.
 *
 * Wraps the shared `<MembershipPlanForm>` with create-mutation
 * wiring + routing on success.
 */

'use client';

import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { toast } from 'sonner';

import { PageHeader } from '@/components/page-header';
import { ApiError } from '@/lib/api';
import { useCreateMembershipPlan } from '@/lib/subscriptions';

import {
  type PlanFormErrors,
  type PlanFormValues,
  MembershipPlanForm,
  emptyPlanItemRow,
  planFormToPayload,
  validatePlanForm,
} from '../_components/plan-form';

const INITIAL_VALUES: PlanFormValues = {
  name: '',
  sku: '',
  description: '',
  price_dollars: '',
  tax_rate_percent: '0',
  billing_interval: 'monthly',
  member_discount_percent: '0',
  is_active: true,
  items: [emptyPlanItemRow()],
};

export default function NewMembershipPlanPage() {
  const router = useRouter();
  const create = useCreateMembershipPlan();
  const [values, setValues] = useState<PlanFormValues>(INITIAL_VALUES);
  const [errors, setErrors] = useState<PlanFormErrors>({});

  const onSubmit = () => {
    const next = validatePlanForm(values);
    setErrors(next);
    if (Object.keys(next).length > 0) {
      toast.error('Please fix the highlighted fields.');
      return;
    }

    create.mutate(planFormToPayload(values), {
      onSuccess: (created) => {
        toast.success(`${created.name} added to catalog`);
        router.push(`/catalog/memberships/${created.id}`);
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
            } else if (k in INITIAL_VALUES) {
              (merged as Record<string, string>)[k] = msg;
            }
          }
          setErrors(merged);
          toast.error('Please fix the highlighted fields.');
        } else {
          toast.error('Could not save this plan. Please try again.');
        }
      },
    });
  };

  return (
    <div className="px-8 py-8">
      <PageHeader
        title="New membership plan"
        description="Bundle services with member-only pricing into a recurring rate. Customer pays each cycle and draws down credits."
        back={{ href: '/catalog/memberships', label: 'All plans' }}
      />
      <div className="mt-2">
        <MembershipPlanForm
          values={values}
          setValues={setValues}
          errors={errors}
          onSubmit={onSubmit}
          isPending={create.isPending}
          submitLabel="Save plan"
          cancelHref="/catalog/memberships"
        />
      </div>
    </div>
  );
}
