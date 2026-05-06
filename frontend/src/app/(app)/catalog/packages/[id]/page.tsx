/**
 * `/catalog/packages/[id]` — edit a catalog package.
 *
 * Reuses the shared `<PackageForm>`. Replaces items wholesale on
 * save (matches backend semantics). Delete option is available on
 * packages with no PurchasedPackage references; backend returns
 * 400 with a clear message otherwise.
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
  type Package,
  dollarsFromCents,
  useDeletePackage,
  usePackage,
  useUpdatePackage,
} from '@/lib/packages';

import {
  type PackageFormErrors,
  type PackageFormValues,
  PackageForm,
  packageFormToPayload,
  validatePackageForm,
} from '../_components/package-form';

function packageToFormValues(p: Package): PackageFormValues {
  return {
    name: p.name,
    sku: p.sku,
    description: p.description,
    price_dollars: dollarsFromCents(p.price_cents),
    tax_rate_percent: p.tax_rate_percent || '0',
    validity_days: p.validity_days != null ? String(p.validity_days) : '',
    is_active: p.is_active,
    items: p.items.length
      ? p.items.map((it) => ({
          service_id: String(it.service_id),
          quantity: String(it.quantity),
        }))
      : [{ service_id: '', quantity: '1' }],
  };
}

export default function PackageDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const packageId = Number(id);
  const me = useCurrentMembership();
  const canEdit = me?.role === 'owner' || me?.role === 'manager';
  const router = useRouter();

  const { data: pkg, isLoading, error } = usePackage(packageId);
  const update = useUpdatePackage(packageId);
  const remove = useDeletePackage();

  // Track which package id we've initialized for; lets us re-seed
  // form values when the user navigates between detail pages without
  // calling setState in an effect (which trips react-hooks rules).
  const [seededFor, setSeededFor] = useState<number | null>(null);
  const [values, setValues] = useState<PackageFormValues | null>(null);
  const [errors, setErrors] = useState<PackageFormErrors>({});

  if (pkg && seededFor !== pkg.id) {
    setSeededFor(pkg.id);
    setValues(packageToFormValues(pkg));
  }

  if (isLoading) {
    return (
      <div className="px-8 py-8">
        <PageHeader
          title=""
          back={{ href: '/catalog/packages', label: 'All packages' }}
        />
        <div className="rounded-lg border bg-card p-12 text-center text-sm text-muted-foreground">
          Loading package…
        </div>
      </div>
    );
  }
  if (error || !pkg || !values) {
    return (
      <div className="px-8 py-8">
        <PageHeader
          title="Package not found"
          back={{ href: '/catalog/packages', label: 'All packages' }}
        />
        <p className="text-sm text-destructive">Failed to load this package.</p>
      </div>
    );
  }

  const onSubmit = () => {
    if (!values) return;
    const next = validatePackageForm(values);
    setErrors(next);
    if (Object.keys(next).length > 0) {
      toast.error('Please fix the highlighted fields.');
      return;
    }
    update.mutate(packageFormToPayload(values), {
      onSuccess: (saved) => {
        toast.success('Package saved');
        setValues(packageToFormValues(saved));
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
        `Delete "${pkg.name}"? Customers who already bought it keep their balances.`,
      )
    )
      return;
    remove.mutate(packageId, {
      onSuccess: () => {
        toast.success('Package deleted');
        router.push('/catalog/packages');
      },
      onError: (err) => {
        if (err instanceof ApiError && err.body && typeof err.body === 'object') {
          const body = err.body as { detail?: string };
          if (body.detail) {
            toast.error(body.detail);
            return;
          }
        }
        toast.error('Could not delete this package.');
      },
    });
  };

  return (
    <div className="px-8 py-8">
      <PageHeader
        title={pkg.name}
        description={`SKU ${pkg.sku || '—'}`}
        back={{ href: '/catalog/packages', label: 'All packages' }}
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
        <PackageForm
          values={values}
          setValues={setValues}
          errors={errors}
          onSubmit={onSubmit}
          isPending={update.isPending}
          submitLabel="Save changes"
          cancelHref="/catalog/packages"
        />
      </div>
    </div>
  );
}
