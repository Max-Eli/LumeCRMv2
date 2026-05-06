/**
 * `/catalog/packages/new` — create a new catalog package.
 *
 * Wraps the shared `<PackageForm>` with create-mutation wiring +
 * routing on success. Validation lives in the form module.
 */

'use client';

import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { toast } from 'sonner';

import { PageHeader } from '@/components/page-header';
import { ApiError } from '@/lib/api';
import { useCreatePackage } from '@/lib/packages';

import {
  type PackageFormErrors,
  type PackageFormValues,
  PackageForm,
  packageFormToPayload,
  validatePackageForm,
} from '../_components/package-form';

const INITIAL_VALUES: PackageFormValues = {
  name: '',
  sku: '',
  description: '',
  price_dollars: '',
  tax_rate_percent: '0',
  validity_days: '365',
  is_active: true,
  items: [{ service_id: '', quantity: '1' }],
};

export default function NewPackagePage() {
  const router = useRouter();
  const create = useCreatePackage();
  const [values, setValues] = useState<PackageFormValues>(INITIAL_VALUES);
  const [errors, setErrors] = useState<PackageFormErrors>({});

  const onSubmit = () => {
    const next = validatePackageForm(values);
    setErrors(next);
    if (Object.keys(next).length > 0) {
      toast.error('Please fix the highlighted fields.');
      return;
    }

    create.mutate(packageFormToPayload(values), {
      onSuccess: (created) => {
        toast.success(`${created.name} added to catalog`);
        router.push(`/catalog/packages/${created.id}`);
      },
      onError: (err) => {
        if (
          err instanceof ApiError
          && err.status === 400
          && err.body
          && typeof err.body === 'object'
        ) {
          const body = err.body as Record<string, unknown>;
          const merged: PackageFormErrors = {};
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
          toast.error('Could not save this package. Please try again.');
        }
      },
    });
  };

  return (
    <div className="px-8 py-8">
      <PageHeader
        title="New package"
        description="Bundle services at a discount. Customer pays once and draws down credits at future visits."
        back={{ href: '/catalog/packages', label: 'All packages' }}
      />
      <div className="mt-2">
        <PackageForm
          values={values}
          setValues={setValues}
          errors={errors}
          onSubmit={onSubmit}
          isPending={create.isPending}
          submitLabel="Save package"
          cancelHref="/catalog/packages"
        />
      </div>
    </div>
  );
}
