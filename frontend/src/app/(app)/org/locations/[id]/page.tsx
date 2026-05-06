/**
 * `/org/locations/[id]` — edit a single location. Owner-only (the
 * backend re-validates `MANAGE_TENANT_SETTINGS`). Cross-tenant ids
 * 404; deleted / non-existent ids 404.
 *
 * Edit-mode guards mirror the backend invariants so the UI never
 * tempts an action that would 400:
 *   - Can't un-set is_default on the current default
 *   - Can't deactivate the default
 *   - Can't deactivate the only active location
 */

'use client';

import { use } from 'react';
import { useRouter } from 'next/navigation';
import { toast } from 'sonner';

import { PageHeader } from '@/components/page-header';
import { ApiError } from '@/lib/api';
import { useCurrentMembership } from '@/lib/auth';
import {
  useLocation,
  useLocations,
  useUpdateLocation,
} from '@/lib/locations';

import {
  LocationForm,
  type LocationFormValues,
  valuesToUpdatePayload,
} from '../_components/location-form';

export default function EditLocationPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const locationId = Number(id);
  const router = useRouter();

  const me = useCurrentMembership();
  const canEdit = me?.role === 'owner';

  const { data: location, isLoading, error } = useLocation(locationId);
  // Used to determine the only-active-location guardrail. Cheap;
  // already cached if the user came from the list page.
  const { data: allLocations } = useLocations();

  const update = useUpdateLocation(locationId);

  if (isLoading) {
    return (
      <div className="px-10 py-10 text-sm text-muted-foreground">
        Loading location…
      </div>
    );
  }
  if (error || !location) {
    return (
      <div className="px-10 py-10">
        <PageHeader
          title="Location not found"
          back={{ href: '/org/locations', label: 'Back to locations' }}
        />
        <p className="text-sm text-destructive">Could not load this location.</p>
      </div>
    );
  }

  const otherActiveCount =
    (allLocations ?? []).filter((l) => l.is_active && l.id !== location.id).length;
  const isOnlyActiveLocation = location.is_active && otherActiveCount === 0;

  const handleSubmit = (values: LocationFormValues) => {
    if (!canEdit) return;
    update.mutate(valuesToUpdatePayload(values), {
      onSuccess: () => toast.success('Location saved'),
      onError: (err) => surfaceError(err),
    });
  };

  return (
    <div className="max-w-6xl px-10 py-10 space-y-6">
      <PageHeader
        title={location.name}
        description={
          location.is_default
            ? 'This is the default location — the fallback when no specific site is selected.'
            : 'Per-site settings: address, hours, contact, and the active flag.'
        }
        back={{ href: '/org/locations', label: 'Back to locations' }}
      />
      <fieldset disabled={!canEdit} className="contents">
        <LocationForm
          existing={location}
          isOnlyActiveLocation={isOnlyActiveLocation}
          onSubmit={handleSubmit}
          onCancel={() => router.push('/org/locations')}
          isSubmitting={update.isPending}
        />
      </fieldset>
      {!canEdit ? (
        <p className="text-xs text-muted-foreground text-right">
          You can view this location but only owners can edit it.
        </p>
      ) : null}
    </div>
  );
}

function surfaceError(err: unknown) {
  if (err instanceof ApiError && err.status === 403) {
    toast.error("You don't have permission to edit locations.");
    return;
  }
  if (err instanceof ApiError && err.status === 400 && typeof err.body === 'object' && err.body) {
    const body = err.body as Record<string, string[] | string>;
    const firstField = Object.keys(body)[0];
    const detail = firstField
      ? Array.isArray(body[firstField])
        ? (body[firstField] as string[])[0]
        : String(body[firstField])
      : 'Could not save.';
    toast.error(detail);
    return;
  }
  toast.error('Could not save. Please try again.');
}
