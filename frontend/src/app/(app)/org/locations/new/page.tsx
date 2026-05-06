/**
 * `/org/locations/new` — create a new physical site for the current
 * tenant. Owner-only. After successful create the user lands on the
 * new location's edit page so they can fine-tune anything they didn't
 * fill in during creation.
 */

'use client';

import { useRouter } from 'next/navigation';
import { toast } from 'sonner';

import { PageHeader } from '@/components/page-header';
import { ApiError } from '@/lib/api';
import { useCurrentMembership } from '@/lib/auth';
import { useCreateLocation } from '@/lib/locations';

import {
  LocationForm,
  type LocationFormValues,
  valuesToCreatePayload,
} from '../_components/location-form';

export default function NewLocationPage() {
  const router = useRouter();
  const me = useCurrentMembership();
  const create = useCreateLocation();

  if (me && me.role !== 'owner') {
    return (
      <div className="px-10 py-10 max-w-3xl">
        <PageHeader
          title="Add location"
          back={{ href: '/org/locations', label: 'Back to locations' }}
        />
        <p className="text-sm text-destructive">
          Only owners can add locations.
        </p>
      </div>
    );
  }

  const handleSubmit = (values: LocationFormValues) => {
    create.mutate(valuesToCreatePayload(values), {
      onSuccess: (location) => {
        toast.success(`${location.name} added`);
        router.push(`/org/locations/${location.id}`);
      },
      onError: (err) => surfaceError(err),
    });
  };

  return (
    <div className="max-w-6xl px-10 py-10 space-y-6">
      <PageHeader
        title="Add a location"
        description="Set up a new physical site for your business. You can fine-tune address, hours, and contact details after creating."
        back={{ href: '/org/locations', label: 'Back to locations' }}
      />
      <LocationForm
        onSubmit={handleSubmit}
        onCancel={() => router.push('/org/locations')}
        isSubmitting={create.isPending}
      />
    </div>
  );
}

function surfaceError(err: unknown) {
  if (err instanceof ApiError && err.status === 403) {
    toast.error("You don't have permission to add locations.");
    return;
  }
  if (err instanceof ApiError && err.status === 400 && typeof err.body === 'object' && err.body) {
    const body = err.body as Record<string, string[] | string>;
    const firstField = Object.keys(body)[0];
    const detail = firstField
      ? Array.isArray(body[firstField])
        ? (body[firstField] as string[])[0]
        : String(body[firstField])
      : 'Could not add location.';
    toast.error(detail);
    return;
  }
  toast.error('Could not add location. Please try again.');
}
